# SPDX-FileCopyrightText: (C) 2013 - 2026, rick@vanosten.net, radi, portree_kid
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Call hierarchy (as of summer 2017) - building_lib is called from building.py:

* building_lib.overlap_check_blocked_areas(...)
* building_lib.overlap_check_convex_hull(...)
* building_lib.analyse(...)
    for building in ...
        b.analyse_elev_and_water(..)
        b.analyse.edge_lengths(...)
        b.analyse_roof_shape(...)
        b.analyse_height_and_levels()
        b.analyse_large_enough()
        b.analyse_roof_check(...)
        b.analyse_textures()
* building_lib.decide_lod(...)
* building_lib.write(...)
    for building in ...
        b.write_to_ac(...)

"""
from enum import IntEnum, unique
import logging
import random
from math import fabs, tan, floor

import numpy as np
from shapely import affinity
import shapely.geometry as shg

from osm2city import parameters, roofs
import osm2city.static_types.enumerations as enu
import osm2city.static_types.shared_models as sm
import osm2city.textures.coverings as cov
from osm2city.utils import coordinates as co
import osm2city.utils.elev_probe as ep
import osm2city.utils.gltf_io as gio
from osm2city.utils import osmparser as op
from osm2city.utils import utilities
from osm2city.static_types import osmstrings as s
from osm2city.static_types import types as t
from osm2city.utils import stg_io2


def _random_roof_shape() -> enu.RoofShape:
    random_shape = utilities.random_value_from_ratio_dict_parameter(parameters.BUILDING_ROOF_SHAPE_RATIO)
    return enu.map_osm_roof_shape(random_shape)


# Based on lines 534 ff in simgear/scene/tgdb/SGBuildingBin.cxx -> "if (buildingtype == SGBuildingBin::SMALL)"
BUILDING_LIST_SMALL_MIN_SIDE = 3.
BUILDING_LIST_MEDIUM_MIN_SIDE = 10.
BUILDING_LIST_LARGE_MIN_SIDE = 20.
BUILDING_LIST_SMALL_MAX_LEVELS = 3
BUILDING_LIST_MEDIUM_MAX_LEVELS = 8
BUILDING_LIST_LARGE_MAX_LEVELS = 22


@unique
class BuildingListType(IntEnum):
    """Available Random Building BUILDING_LIST types."""
    small = 0  # typically a family house
    medium = 1  # large house or smaller flat
    large = 2  # larger apartment or industrial/commercial/retail ...


def _calc_levels_for_settlement_type(settlement_type: enu.SettlementType, building_class: enu.BuildingClass) -> int:
    if settlement_type is enu.SettlementType.centre:
        ratio_parameter = parameters.BUILDING_NUMBER_LEVELS_CENTRE
    elif settlement_type is enu.SettlementType.block:
        ratio_parameter = parameters.BUILDING_NUMBER_LEVELS_BLOCK
    else:
        # now check residential vs. others
        if building_class in [building_class.residential, building_class.residential_small]:
            if settlement_type is enu.SettlementType.dense:
                ratio_parameter = parameters.BUILDING_NUMBER_LEVELS_DENSE
            elif settlement_type is enu.SettlementType.periphery:
                ratio_parameter = parameters.BUILDING_NUMBER_LEVELS_PERIPHERY
            else:
                ratio_parameter = parameters.BUILDING_NUMBER_LEVELS_RURAL
        elif building_class is enu.BuildingClass.apartments:
            ratio_parameter = parameters.BUILDING_NUMBER_LEVELS_APARTMENTS
        elif building_class in [enu.BuildingClass.industrial, enu.BuildingClass.warehouse]:
            ratio_parameter = parameters.BUILDING_NUMBER_LEVELS_INDUSTRIAL
        else:
            ratio_parameter = parameters.BUILDING_NUMBER_LEVELS_OTHER
    return utilities.random_value_from_ratio_dict_parameter(ratio_parameter)


def _calc_level_height_for_settlement_type(settlement_type: enu.SettlementType) -> float:
    if settlement_type in [enu.SettlementType.periphery, enu.SettlementType.rural]:
        return enu.BUILDING_LEVEL_HEIGHT_RURAL
    return enu.BUILDING_LEVEL_HEIGHT_URBAN


class Zone:
    """The zone returned by osm2gear and referenced in buildings."""
    __slots__ = ('osm_id', 'geometry', 'building_zone_type', 'settlement_type', '_number_of_buildings')

    def __init__(self, osm_id: t.OSMId, geometry: shg.Polygon,
                 building_zone_type: enu.BuildingZoneType, settlement_type: enu.SettlementType) -> None:
        self.osm_id = osm_id
        self.geometry = geometry
        self.building_zone_type = building_zone_type
        self.settlement_type = settlement_type
        self._number_of_buildings: int = 0

    def increase_building_count(self) -> None:
        self._number_of_buildings += 1

    def get_building_count(self) -> int:
        return self._number_of_buildings


class Building(object):
    """Central object class.
    Holds all data relevant for a building. Coordinates, type, area, ...
    Read-only access to node coordinates via self.pts[node][0|1]

    Trying to keep naming consistent:
        * Node: from OSM and OSM way
        * Vertex: in ac-file
        * Point (abbreviated to pt and pts): local coordinates for points on building (inner and outer)
    """
    __slots__ = ('osm_id', 'tags', 'is_owbb_model', 'stg_typ',
                 'street_angle', 'anchor', 'width', 'depth', 'zone',
                 'building_class',
                 'levels', 'level_height', 'min_level', 'roof_shape', 'roof_height', 'roof_hint',
                 'refs', 'refs_inner', 'has_neighbours',
                 'inner_rings_list', 'outer_nodes_closest', 'polygon', 'geometry',
                 'parent', 'pts_all', 'roof_height_pts', 'edge_length_pts', 'facade_covering',
                 'roof_covering', 'roof_requirements',
                 'ground_elev', 'diff_elev'
                 )

    def __init__(self, osm_id: t.OSMId, tags: t.OSMTags, outer_ring: shg.LinearRing,
                 anchor: co.Vec2d | None,
                 stg_typ: stg_io2.STGVerbType = None, street_angle: float=0, inner_rings_list=None,
                 refs: list[t.OSMId] = None, refs_inner: list[list[t.OSMId]] = None,
                 is_owbb_model: bool = False, width: float = 0., depth: float = 0.) -> None:
        # assert empty lists if default None
        if inner_rings_list is None:
            inner_rings_list = list()
        if refs is None:
            refs = list()

        # set during init and methods called by init
        self.osm_id: t.OSMId = osm_id
        self.tags: t.OSMTags = tags
        self.is_owbb_model: bool = is_owbb_model
        self.stg_typ: stg_io2.STGVerbType | None = stg_typ

        # For buildings drawn by shader in BUILDING_LIST
        self.street_angle: float = street_angle  # the angle from the front-door looking at the street
        self.anchor: co.Vec2d | None = anchor
        self.width: float = width
        self.depth: float = depth

        # set from osm2gear
        self.zone: Zone | None = None

        # set in method analyse_building_class()
        self.building_class = enu.BuildingClass.undefined

        # For the definition of '*level' and '*height' see method analyse_height_and_levels(..)
        # level is the total number of levels to the top - no matter whether there is min_level
        # i.e. if there are 7 levels and min_levels is 3, then the facade of the building part would have
        # 7-3=4 levels - but self.levels is still=7
        self.levels: int = 0
        self.level_height: float = 0.
        self.min_level: int = 0
        self.roof_shape = enu.RoofShape.flat
        self.roof_height: float = 0.0  # the height of the roof (0 if flat), not the elevation over ground of the roof
        self.roof_hint: roofs.RoofHint | None = None

        # set during method called by init(...) through self.update_geometry and related sub-calls
        self.refs = None  # contains only the refs of the outer_ring
        self.refs_inner = None
        self.has_neighbours = False  # transferred from osm2gear
        self.inner_rings_list = None
        self.outer_nodes_closest = None
        self.polygon = None  # can have inner and outer rings, i.e. the real polygon
        self.geometry = None  # only the outer ring - for convenience and faster processing in some analysis
        self._update_geometry(outer_ring, inner_rings_list, refs, refs_inner)

        # set in buildings.py for building relations prior to building_lib.analyse(...)
        # - from building._process_building_parts(...)
        self.parent = None  # BuildingParent if available

        # set after init(...)
        self.pts_all = None
        self.roof_height_pts: list[float] = list()  # roof height at pt - only set and used for type=skillion
        self.edge_length_pts = None  # numpy array of side length between pt and pt+1
        self.facade_covering: cov.CCovering | None = None
        self.roof_covering: cov.CCovering | None = None
        self.roof_requirements = cov.RoofRequirements(None, None)

        self.ground_elev = 0.0  # the lowest elevation over sea of any point in the outer ring of the building
        self.diff_elev = 0.0  # the difference between the lowest elevation and the highest ground elevation of building

    def make_building_from_part(self) -> None:
        """Make sure a former building_part gets tagged correctly"""
        if s.K_BUILDING_PART in self.tags:
            part_value = self.tags[s.K_BUILDING_PART]
            del self.tags[s.K_BUILDING_PART]
            if s.K_BUILDING not in self.tags:
                self.tags[s.K_BUILDING] = part_value

    def _update_geometry(self, outer_ring: shg.LinearRing, inner_rings_list: list[shg.LinearRing] = None,
                         refs: list[t.OSMId] = None, refs_inner: list[list[t.OSMId]] = None) -> None:
        """Updates the geometry of the building. This can also happen after the building has been initialised.
        Makes also sure that inner and outer rings have correct orientation.
        """
        if inner_rings_list is None:
            inner_rings_list = list()
        if refs is None:
            refs = list()

        # make sure that the outer ring is ccw
        # OpenStreetMap:
        # - The outer ring (exterior boundary) of polygons should be in a clockwise (CW) direction [[1]](https://www.openstreetmap.org/user/bdon/diary/391736)
        # - Inner rings (holes) should be in a counter-clockwise (CCW) direction [[5]](https://docs.mapbox.com/data/tilesets/guides/vector-tiles-standards/)
        #
        # This follows the OGC Simple Features specification and is a common convention in GIS systems [[9]](https://gis.stackexchange.com/questions/48747/polygon-creation-clockwise-rotation-or-not).
        # Therefore, it should be common that the direction of the outer ring needs to be changed
        self.refs = refs
        if not outer_ring.is_ccw:
            outer_ring = shg.LinearRing(list(outer_ring.coords)[::-1])
            self.refs = self.refs[::-1]

        # handle inner rings
        self.inner_rings_list = inner_rings_list
        if self.inner_rings_list:
            # make sure that inner rings are not ccw
            index_pos = 0
            append_new = list()
            for inner_ring in reversed(self.inner_rings_list):
                if inner_ring.is_ccw:
                    new_inner_ring = shg.LinearRing(list(inner_ring.coords)[::-1])
                    append_new.append(new_inner_ring)
                    self.inner_rings_list.remove(inner_ring)
                    refs_inner[index_pos] = refs_inner[index_pos][::-1]
                index_pos += 1
            self.inner_rings_list.extend(append_new)
        self.outer_nodes_closest = []
        if len(outer_ring.coords) > 2:
            self._set_polygon(outer_ring, self.inner_rings_list)
        else:
            self.polygon = None
        if self.inner_rings_list:
            self.roll_inner_nodes()
        self.update_anchor(False)

    def update_anchor(self, recalculate: bool) -> None:
        """Determines the anchor point of a building.
        The anchor point is used in 2 situations:
        * For buildings in meshes it just determines in which cluster a building is. Therefore, it does basically not
          matter.
        * For shader buildings in lists, it matters a lot, because it determines the orientation. Here 0,0,0 is
          defined as the bottom center of the front face of the building. The "front face" is the facade of the
          building facing the street. "Bottom center" is on ground level vertically and centre means that it is
          horizontally between the left and right edge of the front face. Still: the rotation is relative to this
          point and not the geometric or centre of gravity.
        """
        if not recalculate:
            if self.anchor is not None:  # keep what we have. Even after a simplification for a mesh it is good enough
                return

            if self.zone is None:  # zone is first set after building has been created
                # just use the first point of the outside of the building
                self.anchor = co.Vec2d(self.pts_outer[0])
                self.street_angle = 0.
                return

        # Apparently we deal with an OSM building that is not to be drawn in a mesh, but in building list.
        # As anchor candidates we choose the middle points of the sides of the convex hull of the building.
        # Then we search for the candidate which has the shortest distance to the zone/block border.
        # The candidate with the shortest distance is chosen and the
        # street angle is based on the side of the convex hull, where the chosen candidate is situated.
        try:
            hull = self.polygon.convex_hull
            hull_points = list(hull.exterior.coords)
            shortest_distance = 99999.
            shortest_node = 0
            for j in range(len(hull_points) - 1):
                x, y = co.calc_point_on_line_local(hull_points[j][0], hull_points[j][1],
                                                   hull_points[j + 1][0], hull_points[j + 1][1], 0.5)
                distance = shg.Point(x, y).distance(self.zone.geometry.exterior)
                if distance < shortest_distance:
                    shortest_node = j
                    shortest_distance = distance

            i = shortest_node
            x, y = co.calc_point_on_line_local(hull_points[i][0], hull_points[i][1],
                                               hull_points[i + 1][0], hull_points[i + 1][1], 0.5)
            angle = co.calc_angle_of_line_local(hull_points[i][0], hull_points[i][1],
                                                hull_points[i + 1][0], hull_points[i + 1][1])
            self.anchor = co.Vec2d(x, y)
            self.street_angle = co.normal_degrees(angle + 90)

            # to get the width depth we must rotate the hull and then calculate the distance of the most distant points.
            # we could calculate the width based on the following, but that is not accurate if e.g. the building in OSM
            # is modelled with a small front door entrance just 1 meter wide (happens e.g. in the Netherlands)
            # self.width = co.calc_distance_local(hull_points[i][0], hull_points[i][1],
            #                                    hull_points[i + 1][0], hull_points[i + 1][1])
            rotated_hull = affinity.rotate(hull, angle, hull_points[i])
            rotated_hull_points = list(rotated_hull.exterior.coords)
            longest_1 = 0.
            longest_2 = 0.
            widest_1 = 0.
            widest_2 = 0.
            for k in range(len(rotated_hull_points) - 1):
                distance = fabs(rotated_hull_points[i][0] - rotated_hull_points[k][0])
                if distance > longest_1:
                    longest_2 = longest_1
                    longest_1 = distance
                elif distance > longest_2:
                    longest_2 = distance
                distance = fabs(rotated_hull_points[i][1] - rotated_hull_points[k][1])
                if distance > widest_1:
                    widest_2 = widest_1
                    widest_1 = distance
                elif distance > widest_2:
                    widest_2 = distance

            if longest_1 * parameters.BUILDING_LIST_DIST_DEVIATION > longest_2:
                self.depth = longest_1
            else:
                self.depth = (longest_1 + longest_2) / 2
            if widest_1 * parameters.BUILDING_LIST_DIST_DEVIATION > widest_2:
                self.width = widest_1
            else:
                self.width = (widest_1 + widest_2) / 2

        except AttributeError:
            logging.exception('Problem to calc anchor for building osm_id=%i in building zone type=%s and settlement type=%s',
                              self.osm_id, self.zone.building_zone_type, self.zone.settlement_type)

    def roll_inner_nodes(self) -> None:
        """Roll inner rings such that for each inner ring the node closest to an outer node goes first.

        Also, create a list of outer corresponding outer nodes.
        """
        new_inner_rings_list = []
        self.outer_nodes_closest = []
        outer_nodes_avail = list(range(self.pts_outer_count))
        for inner in self.polygon.interiors:
            min_r = 1e99  # minimum distance between inner node i and outer node o
            min_i = 0  # index position of the inner node
            min_o = 0  # index position of the outer node
            for i, node_i in enumerate(list(inner.coords)[:-1]):
                node_i = co.Vec2d(node_i)
                for o in outer_nodes_avail:
                    r = node_i.distance_to(co.Vec2d(self.pts_outer[o]))
                    if r <= min_r:
                        min_r = r
                        min_i = i
                        min_o = o
            new_inner = shg.polygon.LinearRing(np.roll(np.array(inner.coords)[:-1], -min_i, axis=0))
            new_inner_rings_list.append(new_inner)
            self.outer_nodes_closest.append(min_o)
            outer_nodes_avail.remove(min_o)
            if len(outer_nodes_avail) == 0:
                break  # cannot have more inner rings than outer points. So just discard the other inner rings
        # -- sort inner rings by index of closest outer node
        yx = sorted(zip(self.outer_nodes_closest, new_inner_rings_list))
        self.inner_rings_list = [x for (y, x) in yx]
        self.outer_nodes_closest = [y for (y, x) in yx]
        self._set_polygon(self.polygon.exterior, self.inner_rings_list)

    def _set_polygon(self, outer: shg.LinearRing, inner: list[shg.LinearRing] = None) -> None:
        if inner is None:
            inner = list()
        self.polygon = shg.Polygon(outer, inner)
        self.geometry = shg.Polygon(outer)

    def set_ground_elev(self) -> None:
        """Sets the ground elevations taking into consideration that the world is round."""
        self.pts_all = np.array(self.pts_outer + self.pts_inner)
        self.ground_elev -= co.calc_horizon_elev_local(self.pts_all[0, 0], self.pts_all[0, 1])

    def calc_building_list_type(self) -> BuildingListType | None:
        """Determines the building list type. A return of None means it should be handled in a mesh."""
        # first make the obvious choices
        if s.K_AEROWAY in self.tags:
            return None
        if s.K_MIN_HEIGHT in self.tags or s.K_BUILDING_MIN_LEVEL in self.tags:
            return None
        if s.K_MAN_MADE in self.tags and self.tags[s.K_MAN_MADE] == s.V_TOWER:
            return None
        if s.K_BUILDING in self.tags and self.tags[s.K_BUILDING] == s.V_WATER_TOWER:
            return None
        if self.has_parent:  # mostly detailed buildings in OSM, which might be landmarks
            return None
        if self.has_neighbours and not parameters.BUILDING_LIST_ALLOW_NEIGHBOURS:
            return None
        if self.has_inner:
            return None
        if self.pts_outer_count == 3:  # triangles
            return None
        if self.pts_outer_count >= 7 and self.area > parameters.BUILDING_COMPLEX_ROOFS_MIN_RATIO_AREA:
            return None  # keep larger buildings with many edges
        if self.area < parameters.BUILDING_LIST_AREA_DEVIATION * self.width * self.depth:  # L-buildings or trapeze
            return None

        # then exclude buildings which do not look residential
        if self.building_class not in [enu.BuildingClass.residential, enu.BuildingClass.residential_small,
                                       enu.BuildingClass.shed, enu.BuildingClass.terrace,
                                       enu.BuildingClass.apartments, enu.BuildingClass.commercial]:
            return None

        # now determine in details
        min_side = min(self.width, self.depth)
        if min_side < BUILDING_LIST_SMALL_MIN_SIDE:
            return None

        # first double-check height vs. side: it is more important to get high buildings rights than to
        # have many building list buildings.
        if self.levels > BUILDING_LIST_LARGE_MAX_LEVELS:
            return None
        if BUILDING_LIST_MEDIUM_MAX_LEVELS < self.levels <= BUILDING_LIST_LARGE_MAX_LEVELS:
            if min_side < BUILDING_LIST_LARGE_MIN_SIDE:
                return None
            else:
                list_type = BuildingListType.large
        elif BUILDING_LIST_SMALL_MAX_LEVELS < self.levels <= BUILDING_LIST_MEDIUM_MAX_LEVELS:
            if min_side < BUILDING_LIST_MEDIUM_MIN_SIDE:
                return None
            else:
                list_type = BuildingListType.medium
        else:
            list_type = BuildingListType.small

        return list_type

    @property
    def roof_complex(self) -> bool:
        """Proxy to see whether the roof is flat or not.
        Skillion is also kind of flat, but is not horizontal and therefore would also return false."""
        if self.roof_shape is enu.RoofShape.flat:
            return False
        return True

    @property
    def pts_outer(self) -> list[tuple[float, float]]:
        return list(self.polygon.exterior.coords)[:-1]

    @property
    def has_parent(self) -> bool:
        if self.parent is None:
            return False
        return True

    @property
    def has_inner(self) -> bool:
        return len(self.polygon.interiors) > 0

    @property
    def pts_inner(self) -> list[tuple[float, float]]:
        """All points related to inner rings/holes no matter which inner ring they belong to."""
        return [coord for interior in self.polygon.interiors for coord in list(interior.coords)[:-1]]

    @property
    def pts_inner_list(self) -> list[list[tuple[float, float]]]:
        inner_list = list()
        for interior in self.polygon.interiors:
            inner_list.append(list(interior.coords)[:-1])
        return inner_list

    @property
    def pts_outer_count(self) -> int:
        return len(self.polygon.exterior.coords) - 1

    @property
    def pts_all_count(self) -> int:
        n = self.pts_outer_count
        for item in self.polygon.interiors:
            n += len(item.coords) - 1
        return n

    @property
    def area(self):
        """The area of the building only taking into account the outer ring, not inside holes."""
        return self.geometry.area

    @property
    def circumference(self):
        return self.polygon.length

    @property
    def longest_edge_length(self) -> float:
        return max(self.edge_length_pts)

    @property
    def facade_height(self) -> float:
        """The height of the facade of this building(-part)."""
        return (self.levels - self.min_level) * self.level_height

    @property
    def min_height(self) -> float:
        """The height over ground where the facade starts for this building(-part)."""
        return self.min_level * self.level_height

    @property
    def facade_top_height(self) -> float:
        """The height over ground of the facade top of this building(-part)."""
        return self.facade_height + self.min_height

    @property
    def building_height(self) -> float:
        """ The total height of the building corresponding to the OSM definition of 'height' resp. 'building:height'"""
        return self.facade_top_height + self.roof_height

    @property
    def top_of_roof_above_sea_level(self) -> float:
        """Top of the building's roof above the main sea level"""
        return self.ground_elev + self.building_height

    @property
    def beginning_of_roof_above_sea_level(self) -> float:
        """The point above the main sea level, where the roof starts"""
        return self.ground_elev + self.min_height + self.facade_height

    def _analyse_facade_roof_requirements(self) -> list[str]:
        """Determines the requirements for facade (textures) and depending on requirements found updates roof reqs."""
        facade_requires = []

        if self.roof_shape in [enu.RoofShape.flat]:
            facade_requires.append(cov.COMPAT_ROOF_FLAT)
        else:
            facade_requires.append('age:old')
            facade_requires.append(cov.COMPAT_ROOF_PITCHED)

        try:
            if s.V_TERMINAL in self.tags[s.K_AEROWAY].lower():
                facade_requires.append('facade:shape:terminal')
        except KeyError:
            pass
        try:
            if s.K_BUILDING_MATERIAL not in self.tags:
                if self.tags[s.K_BUILDING_PART] == "column":
                    facade_requires.append(str('facade:building:material:stone'))
        except KeyError:
            pass
        try:
            facade_requires.append('facade:building:colour:' + self.tags[s.K_BUILDING_COLOUR].lower())
        except KeyError:
            pass
        try:
            material_type = self.tags[s.K_BUILDING_MATERIAL].lower()
            if str(material_type) in [s.V_STONE, s.V_BRICK, s.V_TIMBER_FRAMING, s.V_CONCRETE, s.V_GLASS]:
                facade_requires.append(str('facade:building:material:' + str(material_type)))

            # stone white default
            if str(material_type) == s.V_STONE and s.K_BUILDING_COLOUR not in self.tags:
                self.tags[s.K_BUILDING_COLOUR] = s.V_WHITE
                facade_requires.append(str('facade:building:colour:white'))
        except KeyError:
            pass

        return facade_requires

    def analyse_facade_textures(self, facade_mgr: cov.FacadeManager, facade_height: float) -> bool:
        """Determine the facade textures. Return False if an anomaly is found.

        Facade height is a parameter such that it can be set from outside instead of from the building object directly.
        """
        facade_requires = self._analyse_facade_roof_requirements()
        longest_edge_length = self.longest_edge_length  # keep for performance
        self.facade_covering = facade_mgr.find_matching_facade(facade_requires, self.tags, facade_height,
                                                               longest_edge_length)
        if self.facade_covering:
            logging.debug('Facade texture for osm_id {}: {} - {}'.format(self.osm_id, str(self.facade_covering),
                                                                         str(self.facade_covering.provides)))
        else:
            logging.debug("Skipping building with osm_id %d: (no matching facade texture)" % self.osm_id)
            return False
        if not self.facade_covering.h_can_repeat and longest_edge_length > self.facade_covering.width:
            logging.debug(
                "Skipping building with osm_id %d: longest_edge_len > b.facade_covering.width" % self.osm_id)
            return False

        return True

    def analyse_roof_requirements(self):
        # Try to match materials and colours defined in OSM with available roof textures
        if s.K_ROOF_MATERIAL in self.tags:
            self.roof_requirements.roof_material = self.tags[s.K_ROOF_MATERIAL]
        if s.K_ROOF_COLOUR in self.tags:
            self.roof_requirements.roof_colour = self.tags[s.K_ROOF_COLOUR]

    def analyse_elev_and_water(self, fg_elev: ep.FGElev) -> bool:
        """Get the elevation of the lowest node on the outer ring.
        If a node is in the water or at FG_ELEV_NO_ELEV (-9999), then return False."""
        min_ground_elev, diff_elev = fg_elev.probe_list_of_points(self.pts_outer)
        if min_ground_elev != ep.FG_ELEV_NO_ELEV:
            self.ground_elev = min_ground_elev
            self.diff_elev = diff_elev
            return True
        return False

    def analyse_edge_lengths(self) -> None:
        # -- compute edge length
        pts_outer = np.array(self.pts_outer)
        self.edge_length_pts = np.zeros(self.pts_all_count)
        for i in range(self.pts_outer_count - 1):
            self.edge_length_pts[i] = ((pts_outer[i + 1, 0] - pts_outer[i, 0]) ** 2 +
                                       (pts_outer[i + 1, 1] - pts_outer[i, 1]) ** 2) ** 0.5
        n = self.pts_outer_count
        self.edge_length_pts[n - 1] = ((pts_outer[0, 0] - pts_outer[n - 1, 0]) ** 2 +
                                       (pts_outer[0, 1] - pts_outer[n - 1, 1]) ** 2) ** 0.5

        if self.inner_rings_list:
            index = self.pts_outer_count
            for interior in self.polygon.interiors:
                pts_inner = np.array(interior.coords)[:-1]
                n = len(pts_inner)
                for i in range(n - 1):
                    self.edge_length_pts[index + i] = ((pts_inner[i + 1, 0] - pts_inner[i, 0]) ** 2 +
                                                       (pts_inner[i + 1, 1] - pts_inner[i, 1]) ** 2) ** 0.5
                self.edge_length_pts[index + n - 1] = ((pts_inner[0, 0] - pts_inner[n - 1, 0]) ** 2 +
                                                       (pts_inner[0, 1] - pts_inner[n - 1, 1]) ** 2) ** 0.5
                index += n

    def analyse_street_angle(self) -> None:
        if self.is_owbb_model:
            # the model already gives the angle
            return
        self.street_angle = co.calc_angle_of_longest_edge(self.pts_outer)

    def analyse_roof_shape(self, building_parent: 'BuildingParent | None') -> None:
        """See also description in manual for European Style parameters.

        Be aware that these tags could be overwritten later in the processing again. It just increases probability.
        """
        if self.has_inner:
            self.roof_shape = enu.RoofShape.flat
            return
        if self.pts_all_count < 4:
            self.roof_shape = enu.RoofShape.flat
            return

        # special case based on roof hints
        if  (4 <= self.pts_all_count <= 6) and (
                    self.roof_hint is not None and self.roof_hint.inner_node is not None):
            if s.K_ROOF_SHAPE in self.tags:
                my_roof_shape = enu.map_osm_roof_shape(self.tags[s.K_ROOF_SHAPE])
                if my_roof_shape is enu.RoofShape.flat:
                    self.roof_shape = my_roof_shape
                else:
                    self.roof_shape = enu.RoofShape.separate_gable_with_corner
            else:
                self.roof_shape = enu.RoofShape.separate_gable_with_corner
        elif s.K_ROOF_SHAPE in self.tags:
            self.roof_shape = enu.map_osm_roof_shape(self.tags[s.K_ROOF_SHAPE])
            if self.pts_all_count > 4 and self.roof_shape in [enu.RoofShape.skillion, enu.RoofShape.gabled,
                                                              enu.RoofShape.half_hipped, enu.RoofShape.hipped,
                                                              enu.RoofShape.gambrel, enu.RoofShape.mansard,
                                                              enu.RoofShape.round, enu.RoofShape.saltbox]:
                self.roof_shape = enu.RoofShape.skeleton
        elif self.building_class in [enu.BuildingClass.shed,
                                     enu.BuildingClass.parking_house, enu.BuildingClass.data_centre,
                                     enu.BuildingClass.airport]:
            self.roof_shape = enu.RoofShape.flat
        else:
            # use some parameters and randomise to assign a roof shape
            # in analyse_roof_shape_check it is double-checked whether e.g. building height or area exceed limits
            # and then it will be corrected (back) to a flat roof.
            if parameters.BUILDING_COMPLEX_ROOFS and building_parent is None:
                if len(self.pts_outer) == 4:
                    self.roof_shape = _random_roof_shape()
                else:
                    self.roof_shape = enu.RoofShape.skeleton
            else:
                self.roof_shape = enu.RoofShape.flat

        # make some sanitization for dome, pyramid and onion - we want the ground shape to be concave
        if self.roof_shape in [enu.RoofShape.pyramidal, enu.RoofShape.onion, enu.RoofShape.dome]:
            hull = self.geometry.convex_hull
            if abs(hull.area - self.geometry.area)/self.geometry.area > 0.01:
                self.roof_shape = enu.RoofShape.skeleton

    def analyse_building_class(self, building_parent: 'BuildingParent | None') -> None:
        self.building_class = enu.get_building_class(self.tags, self.area)
        if self.building_class is enu.BuildingClass.undefined:
            # small stuff could be just a shed
            if self.area < parameters.BUILDING_MAX_AREA_ASSUME_SHED and s.parse_building_levels(self.tags) < 1.5:
                self.building_class = enu.BuildingClass.shed

            # try to improve the tagging in retail, industrial and commercial zones
            # we do not need to bother about the number of levels as parse_building_tags_for_type()
            # will do that afterwards
            elif not building_parent:
                my_rand = random.random()
                if self.zone.building_zone_type is enu.BuildingZoneType.retail:
                    if self.area > enu.BUILDING_MIN_AREA_ONE_LEVEL_LARGE_BUILDING_CLASS:
                        if my_rand > 0.7:
                            s.replace_building_value(self.tags, s.V_SUPERMARKET)
                        elif my_rand > 0.2:
                            s.replace_building_value(self.tags, s.V_RETAIL)
                        else:
                            s.replace_building_value(self.tags, s.V_OFFICE)
                    else:
                        if my_rand > 0.5:
                            s.replace_building_value(self.tags, s.V_RETAIL)
                        else:
                            s.replace_building_value(self.tags, s.V_COMMERCIAL)
                elif self.zone.building_zone_type is enu.BuildingZoneType.commercial:
                    if self.area > 2 * enu.BUILDING_MIN_AREA_ONE_LEVEL_LARGE_BUILDING_CLASS and my_rand > 0.7:
                        s.replace_building_value(self.tags, s.V_WAREHOUSE)
                    elif my_rand > 0.8:
                        s.replace_building_value(self.tags, s.V_RETAIL)
                    elif my_rand > 0.6:
                        s.replace_building_value(self.tags, s.V_INDUSTRIAL)
                    elif my_rand > 0.3:
                        s.replace_building_value(self.tags, s.V_OFFICE)
                    else:
                        s.replace_building_value(self.tags, s.V_COMMERCIAL)
                elif self.zone.building_zone_type is enu.BuildingZoneType.industrial:
                    if my_rand > 0.5:
                        s.replace_building_value(self.tags, s.V_INDUSTRIAL)
                    elif my_rand > 0.3:
                        s.replace_building_value(self.tags, s.V_WAREHOUSE)
                    else:
                        s.replace_building_value(self.tags, s.V_OFFICE)

                # because we have updated the tags, we need to get the building_class again
                self.building_class = enu.get_building_class(self.tags, self.area)

    def analyse_height_and_levels(self, building_parent: 'BuildingParent | None') -> None:
        """Determines the level height, the number of levels and the min level of a building
        based on OSM values and other logic.
        Raises ValueError ian OSM attribute cannot be interpreted if needed.
        
        The OSM key 'height' is defined as: Distance between the lowest possible position with ground contact and 
        the top of the roof of the building, excluding antennas, spires and other equipment mounted on the roof.
        
        The OSM key 'min_height' is for raising a facade. Even if this 'min_height' is > 0, then the height
        of the building remains the same - the facade just gets shorter.
        See https://wiki.openstreetmap.org/wiki/Key:min_height and https://wiki.openstreetmap.org/wiki/Simple_3D_buildings

        To make stuff more obvious in processing, the code will use the following properties:
        * min_height - as described above and therefore mostly 0.0
        * body_height - the height of the main building body (corpus) without the roof-height and maybe
                        min_height above ground
        * roof_height - only the height between where the roof starts on top of the 'body' and where the roof ends.
                        For flat roofs it is 0.0

        Therefore, what is called 'height' is min_height + body_height + roof_height.

        However, at the core the level height, number of levels and min level are calculated and fixed -
        everything else will be calculated on the fly based on these.

        Simple (silly?) heuristics to 'respect' layers (https://wiki.openstreetmap.org/wiki/Key:layer) are NOT used,
        as it would be wrong and only a last resort method like: proxy_levels = layer + 2
        """
        proxy_total_height = 0.  # something that mimics the OSM 'height'
        proxy_body_height = 0.
        proxy_roof_height = 0.
        proxy_min_height = 0.

        if s.K_HEIGHT in self.tags:
            proxy_total_height = op.parse_length(self.tags[s.K_HEIGHT])
        if s.K_BUILDING_HEIGHT in self.tags:
            proxy_body_height = op.parse_length(self.tags[s.K_BUILDING_HEIGHT])
        if s.K_ROOF_HEIGHT in self.tags:
            proxy_roof_height = op.parse_length(self.tags[s.K_ROOF_HEIGHT])

        if s.K_MIN_HEIGHT_COLON in self.tags and (s.K_MIN_HEIGHT not in self.tags):  # very few values, wrong tagging
            self.tags[s.K_MIN_HEIGHT] = self.tags[s.K_MIN_HEIGHT_COLON]
            del self.tags[s.K_MIN_HEIGHT_COLON]
        if s.K_MIN_HEIGHT in self.tags:
            proxy_min_height = op.parse_length(self.tags[s.K_MIN_HEIGHT])

        # a bit of sanity
        if proxy_roof_height == 0. and self.roof_complex:
            proxy_roof_height = _calc_level_height_for_settlement_type(self.zone.settlement_type)
            if proxy_total_height > 0.:  # a bit of sanity
                proxy_roof_height = min(proxy_roof_height, proxy_total_height / 2)
        if proxy_body_height > 0. and proxy_total_height == 0.:
            pass  # proxy_total_height = proxy_roof_height + proxy_body_height + self.min_height
        elif proxy_body_height == 0. and proxy_total_height > 0.:
            proxy_body_height = proxy_total_height - proxy_roof_height - proxy_min_height
        # level stuff from OSM
        try:
            self.levels = floor(s.parse_building_levels(self.tags))
        except ValueError:
            self.levels = 0
        self.min_level = s.parse_min_building_level(self.tags)

        # Now that we have everything that OSM provides, use some heuristics if we are missing height/levels.
        # The most important distinction is whether the building is in a relationship, because if it is, then the
        # height given needs to be respected to make sure that e.g. a building:part=dome actually sits at the right
        # position on the top
        self.level_height = self._calculate_level_height()
        if s.K_BUILDING_MIN_LEVEL not in self.tags and proxy_min_height > 0.:
            self.min_level = floor(proxy_min_height / self.level_height)

        if self.levels == 0:
            if proxy_body_height > 0.:
                self.levels = round(proxy_body_height / self.level_height)
            else:
                self.levels = self._calculate_levels(self.level_height)

    def _calculate_levels(self, level_height: float) -> int:
        # certain BuildingClasses have a defined number of levels
        if self.building_class in [enu.BuildingClass.retail, enu.BuildingClass.supermarket,
                                   enu.BuildingClass.industrial,
                                   enu.BuildingClass.warehouse,
                                   enu.BuildingClass.data_centre]:
            my_levels = 1

        elif self.zone.building_zone_type is enu.BuildingZoneType.aerodrome:
            my_levels = parameters.BUILDING_NUMBER_LEVELS_AEROWAY
        else:
            my_levels = _calc_levels_for_settlement_type(self.zone.settlement_type, self.building_class)
        # make corrections for steep slopes
        if (my_levels == 1 and self.diff_elev/level_height > 0.3) or self.diff_elev/level_height > 0.7:
            my_levels += 1
        return my_levels

    def _calculate_level_height(self) -> float:
        if self.zone.building_zone_type is enu.BuildingZoneType.aerodrome:
            return parameters.BUILDING_LEVEL_HEIGHT_AEROWAY

        if self.building_class is enu.BuildingClass.retail:
            return enu.BUILDING_LEVEL_HEIGHT_RETAIL

        if self.building_class is enu.BuildingClass.retail_mall:
            return enu.BUILDING_LEVEL_HEIGHT_RETAIL_MALL

        if self.building_class is enu.BuildingClass.supermarket:
            return enu.BUILDING_LEVEL_HEIGHT_SUPERMARKET

        if self.building_class is enu.BuildingClass.industrial:
            return enu.BUILDING_LEVEL_HEIGHT_INDUSTRIAL

        if self.building_class is enu.BuildingClass.industrial_old:
            return enu.BUILDING_LEVEL_HEIGHT_INDUSTRIAL_OLD

        if self.building_class is enu.BuildingClass.industrial_other:
            return enu.BUILDING_LEVEL_HEIGHT_INDUSTRIAL_OTHER

        if self.building_class is enu.BuildingClass.warehouse:
            return enu.BUILDING_LEVEL_HEIGHT_WAREHOUSE

        if self.building_class is enu.BuildingClass.warehouse_old:
            return enu.BUILDING_LEVEL_HEIGHT_WAREHOUSE_OLD

        if self.building_class is enu.BuildingClass.data_centre:
            return enu.BUILDING_LEVEL_HEIGHT_DATA_CENTRE

        if self.building_class in [enu.BuildingClass.commercial, enu.BuildingClass.public,
                                   enu.BuildingClass.parking_house]:
            return enu.BUILDING_LEVEL_HEIGHT_URBAN
        return _calc_level_height_for_settlement_type(self.zone.settlement_type)

    def analyse_roof_shape_check(self) -> None:
        """Check whether we actually may use something else than a flat roof."""
        # roof_shape from OSM is already set in analyse_height_and_levels(...)
        if self.roof_complex:
            allow_complex_roofs = False
            if parameters.BUILDING_COMPLEX_ROOFS:  # Attention: due to elif's the sequence is important!
                allow_complex_roofs = True
                # no complex roof on tall buildings
                if self.levels > parameters.BUILDING_COMPLEX_ROOFS_MAX_LEVELS and s.K_ROOF_SHAPE not in self.tags:
                    allow_complex_roofs = False
                # no complex roof on tiny buildings.
                elif self.levels < parameters.BUILDING_COMPLEX_ROOFS_MIN_LEVELS and s.K_ROOF_SHAPE not in self.tags:
                    allow_complex_roofs = False
                # no complex roof on large buildings
                elif self.area > parameters.BUILDING_COMPLEX_ROOFS_MAX_AREA:
                    allow_complex_roofs = False
                # if the area is between thresholds, then have a look at the ratio between area and circumference:
                # the smaller the ratio, the less deep the building is compared to its length.
                # It is more common to have long houses with complex roofs than a square once it is a big building.
                elif parameters.BUILDING_COMPLEX_ROOFS_MIN_RATIO_AREA < self.area < \
                        parameters.BUILDING_COMPLEX_ROOFS_MAX_AREA:
                    if roofs.roof_looks_square(self.circumference, self.area):
                        allow_complex_roofs = False
                # no complex roof on buildings with inner rings
                elif self.polygon.interiors:
                    if len(self.polygon.interiors) == 1:
                        self.roof_shape = enu.RoofShape.skeleton
                    else:
                        allow_complex_roofs = False
                elif self.roof_shape not in [enu.RoofShape.pyramidal, enu.RoofShape.dome, enu.RoofShape.onion,
                                             enu.RoofShape.skillion] \
                        and self.pts_all_count > parameters.BUILDING_SKEL_MAX_NODES:
                    allow_complex_roofs = False

            # make sure the roof shape is flat if we are not allowed to use it
            if not allow_complex_roofs:
                self.roof_shape = enu.RoofShape.flat

    def calc_roof_list_orientation(self) -> int:
        """Roof orientation for buildings in lists: 0 = parallel to front, 1 = orthogonal to front.

        See README.scenery in FGDATA/docs.

        For buildings in meshes the orientation was calculated in analyse_roof_neighbour_orientation.
        """
        front_is_longest = self.width >= self.depth
        if s.K_ROOF_ORIENTATION in self.tags:  # if OSM data has hints, use them
            osm_roof_orientation = str(self.tags[s.K_ROOF_ORIENTATION])
            if osm_roof_orientation == s.V_ALONG:
                if front_is_longest:
                    return 0
                else:
                    return 1
            elif osm_roof_orientation == s.V_ACROSS:
                if front_is_longest:
                    return 1
                else:
                    return 0
            # else follow through next checks
        if self.has_neighbours:  # assume like in European inner cities and most row houses
            return 0
        # just look at the width/depth
        if front_is_longest:
            return 0
        return 1

    def compute_roof_height(self, in_building_list: bool = False) -> None:
        """Compute roof_height for each node"""

        self.roof_height = 0.
        temp_roof_height = 0.  # temp variable before assigning to self

        if self.roof_shape is enu.RoofShape.skillion and (in_building_list is False):
            assert not self.has_inner, 'Skillion roof may not have inner nodes'
            # get global roof_height and height for each vertex
            if s.K_ROOF_HEIGHT in self.tags:
                # force clean of tag if the unit is given
                temp_roof_height = op.parse_length(self.tags[s.K_ROOF_HEIGHT])
            else:
                if s.K_ROOF_ANGLE in self.tags and s.is_parsable_float(self.tags[s.K_ROOF_ANGLE]):
                    angle = float(self.tags[s.K_ROOF_ANGLE])
                    while angle > 0:
                        temp_roof_height = tan(np.deg2rad(angle)) * (self.edge_length_pts[1] / 2)
                        if temp_roof_height < parameters.BUILDING_SKILLION_ROOF_MAX_HEIGHT:
                            break
                        angle -= 1
                else:
                    temp_roof_height = _calc_level_height_for_settlement_type(self.zone.settlement_type)

            # There is a parameter s.K_ROOF_SLOPE_DIRECTION, but it is very cumbersome to
            # calculate a direction, which also corresponds to a side. Given that skillion in
            # osm2city is constrained to 4 nodes, we just use the first and second node as
            # the low points of the roof.
            # If there are several attached houses, then there is a high chance that the mapping
            # has used the same first and second node in each house.
            self.roof_height = temp_roof_height
            for i, pt in enumerate(self.pts_outer):
                if i < 2:
                    self.roof_height_pts.append(0.)
                else:
                    self.roof_height_pts.append(self.roof_height)

        else:  # roof types other than skillion
            if s.K_ROOF_HEIGHT in self.tags:
                # get roof:height given by osm
                self.roof_height = op.parse_length(self.tags[s.K_ROOF_HEIGHT])

            else:  # roof:height based on heuristics
                if self.roof_shape is enu.RoofShape.flat:
                    self.roof_height = 0.
                else:
                    if s.K_ROOF_ANGLE in self.tags and s.is_parsable_float(self.tags[s.K_ROOF_ANGLE]):
                        angle = float(self.tags[s.K_ROOF_ANGLE])
                        while angle > 0:
                            temp_roof_height = tan(np.deg2rad(angle)) * (self.edge_length_pts[1] / 2)
                            if temp_roof_height < parameters.BUILDING_SKEL_ROOF_MAX_HEIGHT:
                                break
                            angle -= 5
                        if temp_roof_height > parameters.BUILDING_SKEL_ROOF_MAX_HEIGHT:
                            temp_roof_height = parameters.BUILDING_SKEL_ROOF_MAX_HEIGHT
                    else:  # use the same as level height
                        temp_roof_height = _calc_level_height_for_settlement_type(self.zone.settlement_type)
                    self.roof_height = temp_roof_height

    def write_facades(self, geom_collector: gio.GeometryCollector3D) -> None:
        """

        From side:
        skillion
                   __ -+
             __-+--    |
          +--          |
          |            |
          +-----+------+

         others roofs

          +-----+------+
          |            |
          +-----+------+
        """
        top_vertices: dict[int, gio.CVertexDTO] = dict()
        bot_vertices: dict[int, gio.CVertexDTO] = dict()
        z: float = self.ground_elev + self.min_height
        z_roof: float = self.beginning_of_roof_above_sea_level
        extra: int = len(self.pts_outer)  # add to index for the bot to get unique ids
        # outer facades
        for i, pt in enumerate(self.pts_outer):
            if self.roof_shape is enu.RoofShape.skillion:
                z_roof = self.beginning_of_roof_above_sea_level + self.roof_height_pts[i]
            top_vertices[i] = gio.CVertexDTO(gio.VertexId(i), pt[0], pt[1], z_roof)
            bot_vertices[i] = gio.CVertexDTO(gio.VertexId(i + extra), pt[0], pt[1], z)
        geom_collector.add_sides(bot_vertices, top_vertices, self.facade_covering)
        # inner faces
        for inner in self.pts_inner_list:
            top_vertices = dict()
            bot_vertices = dict()
            z = self.ground_elev + self.min_height
            extra = len(inner)
            # outer facades
            for i, pt in enumerate(inner):
                z_roof = self.beginning_of_roof_above_sea_level
                top_vertices[i] = gio.CVertexDTO(gio.VertexId(i), pt[0], pt[1], z_roof)
                bot_vertices[i] = gio.CVertexDTO(gio.VertexId(i + extra), pt[0], pt[1], z)
            geom_collector.add_sides(bot_vertices, top_vertices, self.facade_covering)

    def _write_flat_roof(self, roof_mgr: cov.RoofManager, geom_collector: gio.GeometryCollector3D,
                         override: bool = False) -> None:
        if override:  # meaning we do a flat roof despite a non-flat was requested
            self.roof_shape = enu.RoofShape.flat
            if self.parent:
                self.roof_covering = self.parent.get_roof_covering(self.roof_requirements, self.roof_shape)
                if not self.roof_covering:
                    self.roof_covering = roof_mgr.find_matching_roof(self.roof_requirements, self.roof_shape)
            else:
                self.roof_covering = roof_mgr.find_matching_roof(self.roof_requirements, self.roof_shape)
        roofs.write_flat(geom_collector, self)

    def write_roof(self, roof_mgr: cov.RoofManager, geom_collector: gio.GeometryCollector3D) -> None:
        if self.parent:
            self.roof_covering = self.parent.get_roof_covering(self.roof_requirements, self.roof_shape)
            if not self.roof_covering:
                self.roof_covering = roof_mgr.find_matching_roof(self.roof_requirements, self.roof_shape)
        else:
            self.roof_covering = roof_mgr.find_matching_roof(self.roof_requirements, self.roof_shape)

        if self.roof_shape is enu.RoofShape.flat:
            self._write_flat_roof(roof_mgr, geom_collector)
        elif self.roof_shape is enu.RoofShape.skillion:
            roofs.write_skillion(geom_collector, self)
        elif self.roof_shape is enu.RoofShape.separate_gable_with_corner:
            roofs.write_gable_with_corner(geom_collector, self, 0, 0)
        elif self.roof_shape in [enu.RoofShape.gabled, enu.RoofShape.gambrel, enu.RoofShape.hipped]:
            roofs.write_gabled_variants(geom_collector, self)
        elif self.roof_shape in [enu.RoofShape.pyramidal, enu.RoofShape.dome, enu.RoofShape.onion]:
            roofs.write_pyramidal(geom_collector, self)
        else:
            skeleton_possible: bool = roofs.write_skeleton(geom_collector, self)
            if not skeleton_possible:
                logging.debug('Tried skeleton, but does not work: replaced by flat roof')
                self._write_flat_roof(roof_mgr, geom_collector, True)

    def __str__(self):
        return "<OSM_ID %d at %s>" % (self.osm_id, hex(id(self)))


class BuildingParent(object):
    """The parent of buildings that are part of a Simple3D building with an outline building.
    Alternatively, virtual parent for combinations of OSM building and OSM building:part.
    Mostly used to coordinate textures for facades and roofs.
    The parts determine the common textures by a simple rule: the first to set the values wins the race.
    """
    __slots__ = ('osm_id', 'parent_type', 'children', 'tags',
                 '_flat_roof_requirements', '_flat_roof_covering', '_pitched_roof_requirements',
                 '_pitched_roof_covering')

    def __init__(self, osm_id: t.OSMId, parent_type: enu.BuildingParentType) -> None:
        self.osm_id = osm_id  # By convention the osm_id of the outline building, not the relation id from OSM!
        self.parent_type: enu.BuildingParentType = parent_type
        self.children: list[Building] = list()  # pointers to Building objects. Those building objects point back in self.parent
        self.tags = dict()
        self._flat_roof_requirements = cov.RoofRequirements(None, None)
        self._flat_roof_covering: cov.RCovering | None = None
        self._pitched_roof_requirements = cov.RoofRequirements(None, None)
        self._pitched_roof_covering: cov.RCovering | None = None

    def add_child(self, child: Building) -> None:
        """Adds the building to the children and adds a pointer back from the child"""
        self.children.append(child)
        child.parent = self

    def remove_child(self, child: Building) -> None:
        self.children.remove(child)
        child.parent = None

    def add_tags(self, tags: t.OSMTags) -> None:
        """The added tags are either from the outline if Simple3d or otherwise from the original building
        used as a parent for building_parts, if no relation was given."""
        self.tags = tags

    def align_facade_textures_children(self, facade_mgr: cov.FacadeManager) -> bool:
        """Aligns the facade textures for all the children belonging to this parent.
        Per default, the building colour and building material of the child with the largest longest_edge_len is chosen.
        Then the rest of the children are searched for colour/material and the first one wins.
        Finally, the default is used to analyse for textures again with whatever colour/material was there, and this
        time the height of the highest child is used.
        If the analysis does return a result, then the texture is used for all children. Otherwise, False is
        returned and the whole BuildingParent with all its buildings is removed.
        """
        if len(self.children) == 0:  # might be sanitize_children() has removed them all
            return True

        # first find the child with the longest edge
        default_child: Building = self.children[0]
        for child in self.children:
            if child is default_child:
                continue
            if child.longest_edge_length > default_child.longest_edge_length:
                default_child = child

        # find out if we can find hints for real material
        largest_facade_height = default_child.facade_height
        building_colour = None
        building_material = None
        if s.K_BUILDING_COLOUR in default_child.tags:
            building_colour = default_child.tags[s.K_BUILDING_COLOUR]
        if s.K_BUILDING_MATERIAL in default_child.tags:
            building_material = default_child.tags[s.K_BUILDING_MATERIAL]

        for child in self.children:
            if child is default_child:
                continue
            if building_colour is None and s.K_BUILDING_COLOUR in child.tags:
                building_colour = child.tags[s.K_BUILDING_COLOUR]
            if building_material is None and s.K_BUILDING_MATERIAL in child.tags:
                building_material = child.tags[s.K_BUILDING_MATERIAL]
            largest_facade_height = max(largest_facade_height, child.facade_height)

        if s.K_BUILDING_COLOUR not in default_child.tags and building_colour:
            default_child.tags[s.K_BUILDING_COLOUR] = building_colour
        if s.K_BUILDING_MATERIAL not in default_child.tags and building_material:
            default_child.tags[s.K_BUILDING_MATERIAL] = building_material

        # now that everything is in place, analyse for facade texture again
        try:
            default_child.analyse_facade_textures(facade_mgr, largest_facade_height)
            if default_child.facade_covering is None:
                return False
        except Exception:
            pass

        # apply same facade textures to all children
        for child in self.children:
            if child is default_child:
                continue
            child.facade_covering = default_child.facade_covering
        return True

    def align_roof_requirements(self, roof_mgr: cov.RoofManager) -> None:
        """The basic assumption is that the roof requirements for flat roofs are the same for all children;
        and that the same is true for children with pitched roofs."""
        flat_requirements: list[cov.RoofRequirements] = list()
        pitched_requirements: list[cov.RoofRequirements] = list()
        pitched_shapes: set[enu.RoofShape] = set()
        for child in self.children:
            if child.roof_shape is enu.RoofShape.flat:
                if not child.roof_requirements.empty and child.roof_requirements not in flat_requirements:
                    flat_requirements.append(child.roof_requirements)
            else:
                pitched_shapes.add(child.roof_shape)
                if not child.roof_requirements.empty and child.roof_requirements not in pitched_requirements:
                    pitched_requirements.append(child.roof_requirements)

        if len(flat_requirements) == 0:
            self._flat_roof_requirements = cov.RoofRequirements(None, None)
        elif len(flat_requirements) == 1:
            self._flat_roof_requirements = flat_requirements[0]
        else:
            self._flat_roof_requirements = random.choice(flat_requirements)
        self._flat_roof_covering = roof_mgr.find_matching_roof(self._flat_roof_requirements, enu.RoofShape.flat)

        if len(pitched_requirements) == 0:
            self._pitched_roof_requirements = cov.RoofRequirements(None, None)
        elif len(pitched_requirements) == 1:
            if pitched_requirements[0].roof_material == s.V_GLASS:
                self._pitched_roof_requirements = cov.RoofRequirements(None, None)
            else:
                self._pitched_roof_requirements = pitched_requirements[0]
        else:
            valid_random_choices: list[cov.RoofRequirements] = list()
            for req in pitched_requirements:
                if req.roof_material != s.V_GLASS:  # we do not want to default to glass
                    valid_random_choices.append(req)
            self._pitched_roof_requirements = random.choice(valid_random_choices)
        if not pitched_shapes:
            pitched_shapes.add(enu.RoofShape.hipped)
        self._pitched_roof_covering = roof_mgr.find_matching_roof(self._pitched_roof_requirements, random.choice(list(pitched_shapes)))

    def get_roof_covering(self, roof_requirements: cov.RoofRequirements, roof_shape: enu.RoofShape) -> cov.RCovering | None:
        """Return a RCovering but respect that the incoming roof requirement might be more specific.

        It will be quite rare that the roof requirements are more specific, because then the children
        had more than 1 roof requirement defined for pitched respectively flat roofs."""
        if roof_shape is enu.RoofShape.flat:
            if not roof_requirements.empty:
                if roof_requirements == self._flat_roof_requirements:
                    return self._flat_roof_covering
                else:
                    return None
            return self._flat_roof_covering
        else:
            if not roof_requirements.empty:
                if roof_requirements == self._pitched_roof_requirements:
                    return self._pitched_roof_covering
                else:
                    return None
            return self._pitched_roof_covering

    @staticmethod
    def get_building_parents(my_buildings: list[Building]) -> set['BuildingParent']:
        building_parents = set()
        for building in my_buildings:
            if building.parent:
                building_parents.add(building.parent)
        return building_parents

    @staticmethod
    def clean_building_parents_dangling_children(my_buildings: list[Building]) -> None:
        """Make sure that buildings with a parent, which only has this child, get no parent.
        There is no point in a BuildingParent, if there is only one child."""
        building_parents = BuildingParent.get_building_parents(my_buildings)

        for parent in building_parents:
            # remove no longer valid children
            for child in reversed(parent.children):
                if child not in my_buildings:
                    parent.remove_child(child)

            parent.make_sure_lone_building_in_parent_stands_alone()

    def make_sure_lone_building_in_parent_stands_alone(self) -> None:
        """If only one child left, then inherit tags from the parent and make it stand alone"""
        if len(self.children) == 1:
            building = self.children[0]
            building.make_building_from_part()
            for key, value in building.parent.tags.items():
                if key not in building.tags:
                    building.tags[key] = value
            building.parent = None


def analyse(buildings: list[Building], fg_elev: ep.FGElev, instanced_collector: stg_io2.ObjectInstancedListCollector,
            facade_mgr: cov.FacadeManager, roof_mgr: cov.RoofManager) -> list[Building]:
    """Analyse all buildings and either link directly to static models or specify Building objects.
    The static models are directly added to stg_manager. The Building objects get properties set and will later
    get transformed to dynamically created AC3D files containing a cluster of buildings.
    Some OSM buildings are excluded from analysis, as they get processed in pylons.py.
    """
    new_buildings: list[Building] = list()
    for b in buildings:
        building_parent: BuildingParent | None = None
        if b.parent is not None:
            building_parent = b.parent
            building_parent.remove_child(b)

        # handle places of worship
        if s.K_BUILDING in b.tags and parameters.BUILDING_USE_SHARED_WORSHIP:
            if _analyse_worship_building(b, building_parent, instanced_collector, fg_elev):
                continue

        try:
            b.roll_inner_nodes()
        except Exception as reason:
            logging.warning("Roll_inner_nodes failed (OSM ID %i, %s)", b.osm_id, reason)
            continue

        if not b.analyse_elev_and_water(fg_elev):
            continue

        b.analyse_edge_lengths()

        b.analyse_street_angle()

        b.analyse_building_class(building_parent)

        b.analyse_roof_shape(building_parent)

        try:
            b.analyse_height_and_levels(building_parent)
        except ValueError as e:
            logging.debug('Skipping building osm_id = {}: {}'.format(b.osm_id, e))
            continue

        b.analyse_roof_shape_check()

        if not b.analyse_facade_textures(facade_mgr, b.facade_height):
            continue

        b.analyse_roof_requirements()

        # -- finally: append building to the new list
        new_buildings.append(b)
        if building_parent is not None:
            building_parent.add_child(b)

    # work with parents to align textures and stuff
    BuildingParent.clean_building_parents_dangling_children(new_buildings)

    building_parents = BuildingParent.get_building_parents(new_buildings)
    for parent in building_parents:
        found = parent.align_facade_textures_children(facade_mgr)
        if not found:
            for building in parent.children:
                building.parent = None
                try:
                    new_buildings.remove(building)
                except ValueError:
                    pass  # building might not have been added to new_buildings, but have been referenced to parent
                logging.warning('Removing building osm_id=%i due to no matching texture in parent', building.osm_id)

        parent.align_roof_requirements(roof_mgr)

        if parent.parent_type is enu.BuildingParentType.pseudo_row:
            # align the number of levels and the level height but allow different elevations
            max_levels: int = 0
            max_level_height: float = 0
            for building in parent.children:
                max_levels = max(max_levels, building.levels)
                max_level_height = max(max_level_height, building.level_height)
            for building in parent.children:
                if s.K_BUILDING_LEVELS not in building.tags:
                    building.levels = max_levels
                building.level_height = max_level_height
        else:
            # align the elevation
            min_elev: float = 9999.
            for building in parent.children:
                min_elev = min(min_elev, building.ground_elev)
            for building in parent.children:
                building.ground_elev = min_elev

    # make sure that min_height is only used if there is a real parent (not pseudo_parents)
    # i.e. for all others we just set it to 0.0
    for building in new_buildings:
        if building.parent is None:
            building.min_level = 0

    return new_buildings


def check_buildings_and_tags_in_aerodromes(my_buildings: list[Building]) -> None:
    """Make sure that buildings in aerodromes are tagged such that they look kind of modern.
    And check whether there should be buildings from OSM at all based on the number of static objects placed.
    """
    # first run the parents to make sure that all buildings below a building parent get same aeroway tag
    my_parents = set()
    for building in my_buildings:
        if building.parent is not None and building.zone.building_zone_type is enu.BuildingZoneType.aerodrome:
            my_parents.add(building.parent)

    for building_parent in my_parents:
        aeroway_values = list()
        for child in building_parent.children:
            if s.K_AEROWAY in child.tags:
                aeroway_values.append(child.tags[s.K_AEROWAY])

        settled_value = s.V_AERO_OTHER
        if len(aeroway_values) == 1:
            settled_value = aeroway_values[0]  # in all other situations (0 or > 1) we do not know what to apply
        for child in building_parent.children:
            if s.K_AEROWAY not in child.tags:
                child.tags[s.K_AEROWAY] = settled_value

    # now do all buildings including the roof to make stuff easy in processing
    airport_zones: dict[t.OSMId, Zone] = dict()
    for building in my_buildings:
        if building.zone.building_zone_type is enu.BuildingZoneType.aerodrome:
            if building.zone.osm_id not in airport_zones:
                airport_zones[building.zone.osm_id] = building.zone
            building.zone.increase_building_count()
            if s.K_ROOF_SHAPE not in building.tags:
                building.tags[s.K_ROOF_SHAPE] = s.V_FLAT
            if s.K_AEROWAY not in building.tags:
                building.tags[s.K_AEROWAY] = s.V_AERO_OTHER

    number_removed_buildings = 0
    for building in reversed(my_buildings):
        if building.zone.get_building_count() > parameters.APT_MAX_NUMBER_STATIC_OBJECTS_CREATE_BUILDINGS_IN_BOUNDARY:
            # because BuildingParents above are aligned with children as per above, then the parent will
            # automatically go away, and we do not have to deal with it
            my_buildings.remove(building)
            number_removed_buildings += 1

    logging.info('Removed %i buildings from airports due to too many static objects', number_removed_buildings)


def _analyse_worship_building(building: Building, building_parent: BuildingParent,
                              instanced_collector: stg_io2.ObjectInstancedListCollector,
                              fg_elev: ep.FGElev) -> bool:
    """Returns True and adds shared model if the building is a worship place and there is a shared model for it.
    If the building has a parent, then it is not handled as it is assumed, that then there is an OSM 3D
    representation, which might be more accurate than a generic shared model.
    """
    if building_parent:
        return False
    worship_building_type = WorshipBuilding.screen_worship_building_type(building.tags)
    if worship_building_type:
        if s.K_NAME in building.tags:
            name = building.tags[s.K_NAME]
        else:
            name = 'No Name'
        # check dimensions and then whether we have an adequate building
        hull = building.polygon.convex_hull
        angle, length, width = utilities.minimum_circumference_rectangle_for_polygon(hull)
        model = WorshipBuilding.find_matching_worship_building(building.osm_id, worship_building_type, length, width)
        if model:
            if not model.length_largest:
                angle += 90
            angle = co.normal_degrees(angle)
            x, y = utilities.fit_offsets_for_rectangle_with_hull(angle, hull, model.length, model.width,
                                                                 model.length_offset, model.width_offset,
                                                                 model.length_largest,
                                                                 str(model), building.osm_id)
            model.x = x
            model.y = y
            model.angle = angle
            model.elevation, _ = fg_elev.probe_list_of_points(list(hull.exterior.coords)[:-1])
            model.elevation -= model.height_offset
            if model.elevation == ep.FG_ELEV_NO_ELEV:
                logging.debug('Worship building "%s" with osm_id %i is in water or unknown elevation',
                              name, building.osm_id)
                return False

            logging.info('Found static model for worship building "%s" with osm_id %i: %s at angle %d',
                         name, building.osm_id, model.shared_model, angle)
            model.make_instanced_entry(instanced_collector)
            return True
        logging.debug('No static model found for worship building "%s" with osm_id %i', name, building.osm_id)
        return False
    return False


class WorshipBuilding(object):
    """Buildings for worshipping.
    The building=* should be applied in tagging according to the architectural style, often such religious buildings
    are recognizable landmarks.
    Whereas WorshipBuildingType describes the architectural category, Architecture style,
    the actual style can be described with building:architecture=*.

    For example, a catholic church can be tagged on the building outline with amenity=place_of_worship +
    religion=christian + denomination=catholic + building=church.
    """
    def __init__(self, shared_model: str, has_texture: bool, type_: enu.WorshipBuildingType,
                 style: enu.ArchitectureStyle,
                 number_towers: int, length: float, width: float, height: float,
                 length_offset: float = 0., width_offset: float = 0., height_offset: float = 0.) -> None:
        self.osm_id: t.OSMId = t.OSMId(0)
        self.shared_model = shared_model
        self.has_texture = has_texture
        self.type_ = type_
        self.style = style
        self.number_towers = number_towers
        self.length = length
        self.width = width
        self.height = height
        self.length_offset = length_offset
        self.width_offset = width_offset
        self.height_offset = height_offset

        # will be set later
        self.x = 0.
        self.y = 0.
        self.elevation = 0.
        self.angle = 0.

    def __str__(self) -> str:
        return self.shared_model

    @property
    def length_largest(self) -> bool:
        """Return True if the length is larger than the width. Length is along the x-axis.
        Happens to be False (i.e. width along y-axis is longer) if the model in AC3D has been done so.
        """
        if self.length >= self.width:
            return True
        return False

    @staticmethod
    def screen_worship_building_type(tags: t.OSMTags) -> enu.WorshipBuildingType | None:
        """Returns a type if the building is a worship building, for which there might be a shared model.

        This method needs to be in sync with the list available_worship_buildings"""
        worship_building_type = enu.deduct_worship_building_type(tags)
        if worship_building_type is not None:
            # now make sure that we actually have a mapped building
            for building in _available_worship_buildings:
                if building.type_ is worship_building_type:
                    return worship_building_type
        return None

    @staticmethod
    def find_matching_worship_building(osm_id: t.OSMId, requested_type: enu.WorshipBuildingType,
                                       max_length: float, max_width: float) \
            -> 'WorshipBuilding | None':
        """Finds a worship building of a given type which satisfies the length/width constraints.

        Satisfying meaning that the one building is chosen, which has the largest circumference
        measured by a rectangle with the building's length/with.
        """
        best_fit_building = None
        best_fit_circumference = 0
        for model in _available_worship_buildings:
            if model.type_ is requested_type:
                circumference = 2 * (model.length + model.width)
                if (model.length_largest and model.length <= max_length and model.width <= max_width) or (
                        model.length_largest is False and model.width <= max_length and model.length <= max_width):
                    if circumference > best_fit_circumference:
                        best_fit_building = model
                        best_fit_circumference = circumference
        if best_fit_building:
            best_fit_building.osm_id = osm_id
        return best_fit_building

    def make_instanced_entry(self, collector: stg_io2.ObjectInstancedListCollector) -> None:
        entry = stg_io2.ObjectInstancedListEntry(self.osm_id)
        entry.add_position_local_coordinates(self.x, self.y, self.elevation)
        entry.add_orientation_local_coordinates(self.angle)
        collector.add_entry(self.shared_model, entry)


_available_worship_buildings = [WorshipBuilding(sm.BIG_CHURCH, True, enu.WorshipBuildingType.church,
                                                enu.ArchitectureStyle.romanesque, 1, 30., 26., 40., width_offset=5.5),
                                WorshipBuilding(sm.BRETON_CHURCH, False, enu.WorshipBuildingType.church,
                                                enu.ArchitectureStyle.unknown, 1, 50., 28., 43., length_offset=25.),
                                # WorshipBuilding('Church_generic_twintower_oniondome.ac', False,
                                #                enu.WorshipBuildingType.church,
                                #                enu.ArchitectureStyle.unknown, 2, 22., 37., 34., width_offset=12.5),
                                WorshipBuilding(sm.CHURCH_36M_BLUE, False, enu.WorshipBuildingType.church,
                                                enu.ArchitectureStyle.unknown, 1, 10., 36.2, 34.5, width_offset=0.9),
                                WorshipBuilding(sm.CHURCH_36M_BLUE2, False, enu.WorshipBuildingType.church,
                                                enu.ArchitectureStyle.unknown, 1, 10., 36.2, 34.5, width_offset=0.9),
                                WorshipBuilding(sm.CHURCH_36M_GREEN, False, enu.WorshipBuildingType.church,
                                                enu.ArchitectureStyle.unknown, 1, 10., 36.2, 34.5, width_offset=0.9),
                                WorshipBuilding(sm.CHURCH_36M_RED, False, enu.WorshipBuildingType.church,
                                                enu.ArchitectureStyle.unknown, 1, 10., 36.2, 34.5, width_offset=0.9),
                                WorshipBuilding(sm.GEN_CHURCH_RD, False, enu.WorshipBuildingType.church,
                                                enu.ArchitectureStyle.unknown, 1, 46., 110., 120.),
                                WorshipBuilding(sm.GENERIC_CATHEDRAL, True, enu.WorshipBuildingType.church,
                                                enu.ArchitectureStyle.romanesque, 2, 67., 37., 51.),
                                WorshipBuilding(sm.GENERIC_CHURCH_01, True, enu.WorshipBuildingType.church,
                                                enu.ArchitectureStyle.gothic, 1, 68., 124.4, 100., width_offset=11.2),
                                WorshipBuilding(sm.GENERIC_CHURCH_02, False, enu.WorshipBuildingType.church,
                                                enu.ArchitectureStyle.unknown, 1, 32.4, 71.8, 63.5, width_offset=-1.5),
                                WorshipBuilding(sm.GENERIC_CHURCH_03, False, enu.WorshipBuildingType.church,
                                                enu.ArchitectureStyle.unknown, 1, 38., 89.8, 95.),
                                WorshipBuilding(sm.GOTHICAL_CHURCH, True, enu.WorshipBuildingType.church,
                                                enu.ArchitectureStyle.gothic, 1, 44., 24.8, 46., length_offset=22.),
                                WorshipBuilding(sm.ND_BOULOGNE, True, enu.WorshipBuildingType.church,
                                                enu.ArchitectureStyle.romanesque, 3, 42., 82., 81.5),
                                WorshipBuilding(sm.ROMAN_CHURCH, True, enu.WorshipBuildingType.church,
                                                enu.ArchitectureStyle.romanesque, 1, 44., 24.8, 25., length_offset=22.),
                                WorshipBuilding(sm.ST_VAAST, True, enu.WorshipBuildingType.church,
                                                enu.ArchitectureStyle.romanesque, 0, 58., 98., 36.)
                                ]

# WorshipBuilding(eglise.xml, True, church, gothic)  # not aligned to x-axis
# WorshipBuilding(corp-cathedrale.xml, True, cathedral, gothic)  # is not complete: one wall missing
# WorshipBuilding(gen_orthodox_church.ac, True, church_orthodox, unknown)  # not aligned to any axis
