# SPDX-FileCopyrightText: (C) 2014 - 2026, rick@vanosten.net, radi, portree_kid
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Piers, quays and other harbour stuff.

See also:
    https://wiki.openstreetmap.org/wiki/Marine_navigation
    https://wiki.openstreetmap.org/wiki/Key:mooring
    https://wiki.openstreetmap.org/wiki/Tag:man_made%3Dpier
    https://wiki.openstreetmap.org/wiki/Tag:man_made%3Dquay
    https://wiki.openstreetmap.org/wiki/Harbour
    https://wiki.openstreetmap.org/wiki/Tag:leisure%3Dmarina
"""
import logging
import math
from random import randint

import shapely.geometry as shg

import osm2city.static_types.osmstrings as s
import osm2city.static_types.shared_models as sm
import osm2city.static_types.types as t
import osm2city.textures.materials as mat
from osm2city.utils import coordinates as co
import osm2city.utils.elev_probe as ep
from osm2city.utils import osmparser as op
from osm2city.utils import utilities as u
from osm2city.utils import stg_io2


def write_boats(pier_outer: shg.LinearRing, instanced_collector: stg_io2.ObjectInstancedListCollector,
                fg_elev: ep.FGElev):
    # if the geometry gets too complicated, then just give up - e.g. https://www.openstreetmap.org/way/977518925
    if len(pier_outer.coords) > 10:
        return
    centroid = pier_outer.centroid
    elev = fg_elev.probe_elev((centroid.x, centroid.y))  # round earth will be applied while actually writing the model

    for p in pier_outer.coords:
        line_coords = [[centroid.x, centroid.y], p]
        target_vector = shg.LineString(line_coords)
        coords = pier_outer.coords
        for i in range(len(coords) - 1):
            segment = shg.LineString(coords[i:i + 2])
            if segment.length > 20 and segment.intersects(target_vector):
                direction = math.degrees(math.atan2(segment.coords[0][0] - segment.coords[1][0],
                                                    segment.coords[0][1] - segment.coords[1][1]))
                parallel = segment.parallel_offset(10, 'right')
                boat_position = parallel.interpolate(segment.length / 2)
                try:
                    _write_model(segment.length, boat_position.x, boat_position.y, direction, elev,
                                 instanced_collector)
                except AttributeError as reason:
                    logging.error(reason)


def _write_model(length: float, x: float, y: float, hdg: float, elev: float,
                 instanced_collector: stg_io2.ObjectInstancedListCollector) -> None:
    if length < 20:
        models = [(sm.VESSEL_WOODEN_BOAT, 120),
                  (sm.VESSEL_WOODEN_BLUE_BOAT, 120),
                  (sm.VESSEL_WOODEN_GREEN_BOAT, 120)]
        choice = randint(0, len(models) - 1)
        model = models[choice]
    elif length < 70:
        models = [(sm.VESSEL_SMALL_RED_YACHT, 180),
                  (sm.VESSEL_SMALL_BLACK_YACHT, 180),
                  (sm.VESSEL_SMALL_CLEAR_YACHT, 180),
                  (sm.VESSEL_WIDE_BLACK_YACHT, 180),
                  (sm.VESSEL_WIDE_RED_YACHT, 180),
                  (sm.VESSEL_WIDE_CLEAR_YACHT, 180),
                  (sm.VESSEL_BLUE_SAILING_BOAT_20M, 180),
                  # with sails ('Models/Maritime/Civilian/black-sailing-boat.ac', 180),
                  # with sails ('Models/Maritime/Civilian/blue-sailing-boat.ac', 180),
                  # with sails ('Models/Maritime/Civilian/red-sailing-boat.ac', 180),
                  (sm.VESSEL_RED_SAILING_BOAT_11M, 180),
                  (sm.VESSEL_RED_SAILING_BOAT_20M, 180)]
        choice = randint(0, len(models) - 1)
        model = models[choice]
    elif length < 250:
        models = [(sm.VESSEL_MEDIUM_FERRY, 10)]
        choice = randint(0, len(models) - 1)
        model = models[choice]
    elif length < 400:
        models = [(sm.VESSEL_LARGE_TRAWLER, 10),
                  (sm.VESSEL_LARGE_FERRY, 100),
                  (sm.VESSEL_BARGE, 80)]
        choice = randint(0, len(models) - 1)
        model = models[choice]
    else:
        models = [(sm.VESSEL_SIMPLE_FREIGHTER, 20),
                  (sm.VESSEL_FERRY_BOAT_1, 70)]
        choice = randint(0, len(models) - 1)
        model = models[choice]

    entry = stg_io2.ObjectInstancedListEntry()
    entry.add_position_local_coordinates(x, y, elev)
    entry.add_orientation_local_coordinates(hdg + model[1])
    instanced_collector.add_entry(model[0], entry)


class SeaMark:
    """Handles seamarks and especially the related lights. Depending on seamark type and models in FG scenery
    only the light or only the shape might be represented in scenery.

    See https://wiki.openstreetmap.org/wiki/Seamarks/Seamark_Objects

    Visualisation is not good in OSM - use https://map.openseamap.org/

    Example of left and right beacon at Luzern boat pier
     <node id="8418048929" ...>
      <tag k="seamark:beacon_lateral:category" v="starboard"/>
      <tag k="seamark:beacon_lateral:colour" v="green"/>
      <tag k="seamark:beacon_lateral:shape" v="pile"/>
      <tag k="seamark:light:character" v="F"/>
      <tag k="seamark:light:colour" v="green"/>
      <tag k="seamark:type" v="beacon_lateral"/>
     </node>
     <node id="521676553" ...>
      <tag k="seamark:beacon_lateral:category" v="port"/>
      <tag k="seamark:beacon_lateral:shape" v="pile"/>
      <tag k="seamark:buoy_lateral:colour" v="red"/>
      <tag k="seamark:light:character" v="F"/>
      <tag k="seamark:light:colour" v="red"/>
      <tag k="seamark:type" v="beacon_lateral"/>
     </node>

    """
    SUPPORTED_BEACONS = [s.V_BEACON_CARDINAL, s.V_BEACON_ISOLATED_DANGER, s.V_BEACON_LATERAL,
                         s.V_BEACON_SAFE_WATER, s.V_BEACON_SPECIAL_PURPOSE]
    SUPPORTED_BUOYS = [s.V_BUOY_CARDINAL, s.V_BUOY_ISOLATED_DANGER, s.V_BUOY_LATERAL,
                       s.V_BUOY_SAFE_WATER, s.V_BUOY_SPECIAL_PURPOSE]

    def __init__(self, osm_id: t.OSMId, x: float, y: float, elevation: float,
                 tags: t.OSMTags) -> None:
        """Raises a ValueException if something is not supported and therefore not added to scenery."""
        self.osm_id = osm_id
        self.x = x  # local coordinates
        self.y = y
        self.elevation = elevation
        self.tags = tags

        self.is_supported_type()  # check overall support

        self.light_colour = self.parse_light_colour()  # if None, then no light should be placed
        # default values - might get overridden later
        self.height_of_light = 2.5
        self.candelas = 500
        self.light_size_cm = 10

        self.shared_model = None
        self.parse_shape()

        if self.light_colour:
            self.parse_light_range()

    def has_valid_shared_model(self) -> bool:
        return self.shared_model is not None

    def is_supported_type(self):
        if self.tags[s.K_SEAMARK_TYPE] in self.SUPPORTED_BEACONS:
            return
        if self.tags[s.K_SEAMARK_TYPE] in self.SUPPORTED_BUOYS:
            return
        raise ValueError('Not supported seamark type: {}'.format(self.tags[s.K_SEAMARK_TYPE]))

    def parse_light_colour(self) -> str | None:
        if s.K_SEAMARK_LIGHT_COLOUR in self.tags:
            if mat.is_known_colour_name(self.tags[s.K_SEAMARK_LIGHT_COLOUR]):
                return self.tags[s.K_SEAMARK_LIGHT_COLOUR]
            else:  # we default to yellow, so we have some light
                return s.V_YELLOW  # must be mat.is_known_colour_name
        return None

    def parse_light_range(self) -> None:
        """If the light range is specified, then correct previous default values - else keep it based on shape etc.
        """
        if s.K_SEAMARK_LIGHT_RANGE in self.tags:
            try:
                light_range = float(self.tags[s.K_SEAMARK_LIGHT_RANGE])
            except ValueError:
                pass  # not parsable to float -> nothing to do
            else:
                # this is very primitive and should also correct the light_size in a better version
                # cf. https://gitlab.com/osm2city/osm2city/-/issues/184
                if light_range > 10 and self.candelas < 5000:
                    self.candelas = 5000

    def parse_shape(self) -> None:
        if self.tags[s.K_SEAMARK_TYPE] in self.SUPPORTED_BEACONS:
            for beacon in self.SUPPORTED_BEACONS:
                shape_key = 'seamark:' + beacon + ':shape'
                if shape_key in self.tags:
                    if self.tags[shape_key] == s.V_TOWER:
                        self.height_of_light = 10.
                        self.candelas = 5000
                        self.light_size_cm = 100
                    elif self.tags[shape_key] in [s.V_BUOYANT, s.V_PILE]:
                        if self.light_colour:
                            if self.light_colour == s.V_GREEN:
                                self.shared_model = sm.SEAMARK_GREEN_BUOY
                            elif self.light_colour == s.V_RED:
                                self.shared_model = sm.SEAMARK_RED_BUOY
                        self.height_of_light = 2.1  # just a bit above the model
                        self.candelas = 2000
                        self.light_size_cm = 20
                    break  # we go with defaults else
        elif self.tags[s.K_SEAMARK_TYPE] == s.V_BUOY_LATERAL:
            if self.light_colour:
                if self.light_colour == s.V_GREEN:
                    self.shared_model = sm.SEAMARK_BUOY_CONICAL_GREEN
                elif self.light_colour == s.V_RED:
                    self.shared_model = sm.SEAMARK_BUOY_CYLINDRICAL_RED
            self.height_of_light = 6.1  # just a bit above the model
            self.candelas = 3000
            self.light_size_cm = 20
        elif self.tags[s.K_SEAMARK_TYPE] == s.V_BUOY_SPECIAL_PURPOSE:
            colour_key = 'seamark:' + s.V_BUOY_SPECIAL_PURPOSE + ':colour'
            if (self.light_colour and self.light_colour == s.V_YELLOW) or (
                    colour_key in self.tags and self.tags[colour_key] == s.V_YELLOW
            ):
                self.shared_model = sm.SEAMARK_BUOY_CYLINDRICAL_YELLOW
            self.height_of_light = 6.1  # just a bit above the model
            self.candelas = 3000
            self.light_size_cm = 20
        elif self.tags[s.K_SEAMARK_TYPE] == s.V_BUOY_SAFE_WATER:
            self.shared_model = sm.SEAMARK_BUOY_SAFE_WATER
            self.height_of_light = 6.  # just a bit above the assumed light in the model (above the solar panels)
            self.candelas = 3000
            self.light_size_cm = 20
        elif self.tags[s.K_SEAMARK_TYPE] == s.V_BUOY_ISOLATED_DANGER:
            self.shared_model = sm.SEAMARK_BUOY_ISOLATED_DANGER
            self.height_of_light = 6.  # just a bit above the assumed light in the model (above the solar panels)
            self.candelas = 3000
            self.light_size_cm = 20
        elif self.tags[s.K_SEAMARK_TYPE] == s.V_BUOY_CARDINAL:
            self.shared_model = sm.SEAMARK_BUOY_CARDINAL_NORTH  # in case the cardinal point is not found
            category_key = 'seamark:' + s.V_BUOY_CARDINAL + ':category'
            if category_key in self.tags:
                if self.tags[category_key] == s.V_NORTH:
                    self.shared_model = sm.SEAMARK_BUOY_CARDINAL_NORTH
                elif self.tags[category_key] == s.V_EAST:
                    self.shared_model = sm.SEAMARK_BUOY_CARDINAL_EAST
                elif self.tags[category_key] == s.V_SOUTH:
                    self.shared_model = sm.SEAMARK_BUOY_CARDINAL_SOUTH
                elif self.tags[category_key] == s.V_WEST:
                    self.shared_model = sm.SEAMARK_BUOY_CARDINAL_WEST
            self.height_of_light = 6.  # just a bit above the assumed light in the model (above the solar panels)
            self.candelas = 3000
            self.light_size_cm = 20

    def light_list_value(self) -> str | None:
        """Return a string matching the LIGHT_LIST values for one entry"""
        if self.light_colour is None:
            return None
        rgb = mat.map_osm_colour_value_to_int_rgb_values(self.light_colour, s.V_YELLOW)
        x, y, z, h_angle, v_angle = u.calc_lighting_params(0., 360., -60., 10.)
        line = '{:.1f} {:.1f} {:.1f} {} {} 1 {:.3f} {:.3f} {:.3f} 1.0'.format(-self.y, self.x,
                                                                              self.elevation + self.height_of_light,
                                                                              self.light_size_cm,
                                                                              self.candelas,
                                                                              rgb[0]/255, rgb[1]/255, rgb[2]/255)
        line += ' {:.5f} {:.5f} {:.5f} {:.1f} {:.1f}'.format(x, y, z, h_angle, v_angle)
        return line

    def make_instanced_entry(self, collector: stg_io2.ObjectInstancedListCollector) -> None:
        entry = stg_io2.ObjectInstancedListEntry(self.osm_id)
        entry.add_position_local_coordinates(self.x, self.y, self.elevation)
        collector.add_entry(self.shared_model, entry)


def process_seamarks(coords_transform: co.Transformation,
                     fg_elev: ep.FGElev) -> list[SeaMark]:
    my_seamarks = list()
    result = op.fetch_osm_nodes_isolated_keys([s.K_SEAMARK_TYPE])

    # make sure no existing shared objects are duplicated. Do not care what shared object within distance
    # find relevant / valid wind turbines
    for key, node in result.nodes_dict.items():
        if s.K_SEAMARK_TYPE in node.tags:
            try:
                elevation = fg_elev.probe_elev((node.lon, node.lat), True)
                x, y = coords_transform.to_local((node.lon, node.lat))
                seamark = SeaMark(node.osm_id, x, y, elevation, node.tags)
                if seamark.has_valid_shared_model():
                    my_seamarks.append(seamark)
            except ValueError:
                pass  # nothing to do
    logging.info('Number of seamarks processed: %i', len(my_seamarks))
    return my_seamarks
