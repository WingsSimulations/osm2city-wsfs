# SPDX-FileCopyrightText: (C) 2020 - 2025, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later

from enum import IntEnum, unique
import logging
import multiprocessing.synchronize as mps
import os

import shapely.geometry as shg
from shapely.geometry.base import JOIN_STYLE

from osm2city import parameters, maritime
import osm2city.pylons as po
import osm2city.static_types.osmstrings as s
import osm2city.static_types.types as t
import osm2city.textures.coverings as cov
from osm2city.utils import coordinates as co
import osm2city.utils.elev_probe as ep
import osm2city.utils.gltf_io as gio
from osm2city.utils import osmparser as op
from osm2city.utils import stg_io2


OUR_MAGIC = "details"

PLATFORM_HEIGHT = 1.0
PLATFORM_RAILWAY_NON_AREA_WIDTH = 2.0
PLATFORM_PIER_NON_AREA_WIDTH = 2.0


@unique
class PlatformType(IntEnum):
    railway_platform = 0
    pier = 10


class Platform(object):
    """A railway platform, pier or something similar. Basically a somewhat raised and
    distinguishable walkway or place to wait."""
    __slots__ = ('way', 'line_ring', 'platform_type')

    def __init__(self, way: op.Way, nodes_dict: dict[t.OSMId, op.Node], transformer: co.Transformation,
                 platform_type: PlatformType):
        self.way = way
        self.platform_type = platform_type
        line_string = way.line_string_from_osm_way(nodes_dict, transformer)
        is_area = way.is_closed()
        if s.K_AREA in way.tags and way.tags[s.K_AREA] == s.V_NO:
            is_area = False
        if not is_area:
            dist = PLATFORM_PIER_NON_AREA_WIDTH if platform_type is PlatformType.pier else PLATFORM_RAILWAY_NON_AREA_WIDTH
            left = line_string.offset_curve(0.5*dist, join_style=JOIN_STYLE.mitre)
            right = line_string.offset_curve(-0.5*dist, join_style=JOIN_STYLE.mitre)
            if not isinstance(left, shg.LineString) or not isinstance(right, shg.LineString):
                error_str = 'Platform with osm_id={} cannot be created due to geometry'.format(self.way.osm_id)
                raise ValueError(error_str)
            all_coordinates: list[tuple[float, float]] = list()
            for p in left.coords:
                all_coordinates.append(p)
            for index in range(len(right.coords) - 1, -1, -1):
                all_coordinates.append(right.coords[index])
            all_coordinates.append(left.coords[0])  # close the ring
            line_string = shg.LineString(all_coordinates)
        self.line_ring = shg.LinearRing(line_string)
        if not self.line_ring.is_ccw:
            self.line_ring = shg.LinearRing(self.line_ring.coords[::-1])

    def add_to_geom_collector(self, geom_collector: gio.GeometryCollector3D, covering: cov.CCovering,
                              fg_elev: ep.FGElev) -> None:
        top_vertices: dict[int, gio.CVertexDTO] = dict()
        bot_vertices: dict[int, gio.CVertexDTO] = dict()
        extra = len(self.line_ring.coords)  # add to index for the bot to get unique ids
        for i, p in enumerate(self.line_ring.coords):
            osm_id: t.OSMId = op.get_next_pseudo_osm_id(op.OSMFeatureType.generic_node)
            asl = fg_elev.probe_elev((p[0], p[1]))
            horizon_elev = co.calc_horizon_elev_local(p[0], p[1])
            top_vertices[i] = gio.CVertexDTO(gio.VertexId(i), p[0], p[1],
                                             asl - horizon_elev + PLATFORM_HEIGHT, osm_id)
            bot_vertices[i] = gio.CVertexDTO(gio.VertexId(i + extra), p[0], p[1],
                                             asl - horizon_elev - 2*PLATFORM_HEIGHT, osm_id)

        # the sides
        geom_collector.add_sides(bot_vertices, top_vertices, covering)

        # We want the top texture coordinates to be aligned with the longest edge
        outer_tuples: list[tuple[float, float]] = list()
        for v in top_vertices.values():
            outer_tuples.append((v.x, v.y))
        angle_rotate: float = co.calc_angle_of_longest_edge(outer_tuples)  # relative to North
        angle_rotate = co.calc_delta_bearing(90, angle_rotate)
        rotation_point: shg.Point = shg.Point(outer_tuples[0][0], outer_tuples[0][1])

        geom_collector.add_polygon_face_no_holes(list(top_vertices.values()), covering,
                                                 angle_rotate, rotation_point, self.way.osm_id)


def _process_osm_platform(my_coord_transformator: co.Transformation) -> list[Platform]:
    osm_way_result = op.fetch_osm_data_ways_key_values([s.KV_RAILWAY_PLATFORM])
    osm_nodes_dict = osm_way_result.nodes_dict
    osm_ways_dict = osm_way_result.ways_dict

    my_platforms = list()
    clipping_border = shg.Polygon(parameters.get_clipping_border())

    for key, way in osm_ways_dict.items():
        if not (s.K_RAILWAY in way.tags and way.tags[s.K_RAILWAY] == s.V_PLATFORM):
            continue

        if s.K_LAYER in way.tags and int(way.tags[s.K_LAYER]) < 0:
            logging.debug("layer %s %d", way.tags[s.K_LAYER], key)
            continue  # no underground platforms allowed

        first_node = osm_nodes_dict[way.refs[0]]
        if not clipping_border.contains(shg.Point(first_node.lon, first_node.lat)):
            continue
        try:
            platform = Platform(way, osm_nodes_dict, my_coord_transformator,
                                PlatformType.railway_platform)
            my_platforms.append(platform)
        except ValueError as e:
            logging.debug(e)
    logging.info("number of platforms: %i", len(my_platforms))
    return my_platforms


def _process_osm_piers(my_coord_transformator: co.Transformation) -> list[Platform]:
    osm_way_result = op.fetch_osm_data_ways_key_values([s.KV_MAN_MADE_PIER])
    osm_nodes_dict = osm_way_result.nodes_dict
    osm_ways_dict = osm_way_result.ways_dict

    my_platforms = list()
    clipping_border = shg.Polygon(parameters.get_clipping_border())

    for key, way in osm_ways_dict.items():
        if not (s.K_MAN_MADE in way.tags and way.tags[s.K_MAN_MADE] == s.V_PIER):
            continue

        first_node = osm_nodes_dict[way.refs[0]]
        if not clipping_border.contains(shg.Point(first_node.lon, first_node.lat)):
            continue
        try:
            platform = Platform(way, osm_nodes_dict, my_coord_transformator,
                                PlatformType.pier)
            my_platforms.append(platform)
        except ValueError as e:
            logging.debug(e)
    logging.info("number of piers: %i", len(my_platforms))
    return my_platforms


def _create_platforms(coords_transform: co.Transformation) -> list[Platform]:
    platforms: list[Platform] = list()
    if parameters.DETAILS_PROCESS_PIERS:
        platforms.extend(_process_osm_piers(coords_transform))
    if parameters.DETAILS_PROCESS_PLATFORMS:
        platforms.extend(_process_osm_platform(coords_transform))
    return platforms


def create_platform_polygons(my_coord_transformator: co.Transformation) -> list[shg.Polygon]:
    """Creates a list of polygons representing platforms.
    The polygons are in local coordinates, so they are not yet transformed to real coordinates."""
    platforms = _create_platforms(my_coord_transformator)
    polygons: list[shg.Polygon] = list()
    for platform in platforms:
        polygons.append(shg.Polygon(platform.line_ring))
    return polygons


def process_details(coords_transform: co.Transformation, lit_areas: list[shg.Polygon],
                    rail_lines: list[po.RailLine],
                    fg_elev: ep.FGElev, file_lock: mps.Lock | None = None) -> None:
    # initialize STGManager
    path_to_output = parameters.get_output_path()
    stg_manager = stg_io2.STGManager(path_to_output, stg_io2.SceneryType.details, OUR_MAGIC, parameters.PREFIX)
    instanced_collector = stg_io2.ObjectInstancedListCollector()

    # platforms
    the_platforms: list[Platform] = _create_platforms(coords_transform)

    # seamarks
    if parameters.DETAILS_PROCESS_SEAMARKS:
        the_seamarks = maritime.process_seamarks(coords_transform, fg_elev)
        if len(the_seamarks) > 0:
            light_list_file_name = stg_manager.prefix + '_light_list.txt'
            path_to_stg = stg_manager.add_light_list(light_list_file_name, coords_transform.anchor, 0.)
            try:
                with open(os.path.join(path_to_stg, light_list_file_name), 'w') as light_list_file:
                    for seamark in the_seamarks:
                        value = seamark.light_list_value()
                        if value:
                            light_list_file.write(value)
                            light_list_file.write('\n')
                        seamark.make_instanced_entry(instanced_collector)
            except IOError as exc:
                logging.warning('Could not write lights in list to file %s', exc)
            logging.info("Total number of seamarks in light list or shared object: %d", len(the_seamarks))

    if the_platforms:
        file_name: str = parameters.PREFIX + '_details' + gio.FILE_ENDING
        path_to_stg = stg_manager.add_object_static(file_name, coords_transform.anchor,
                                                    parameters.get_tile_radius())
        geom_collector = gio.GeometryCollector3D(False, False)
        for platform in the_platforms:
            platform.add_to_geom_collector(geom_collector, cov.COV_ASPHALT, fg_elev)

        geom_collector.process()
        gltf_writer = gio.GLTFWriter(geom_collector.get_shallow_c_vertices_clone(),
                                     geom_collector.get_shallow_c_faces_clone(),
                                     geom_collector.smooth_edges)
        gltf_writer.write_to_file(os.path.join(path_to_stg, file_name), True)

    if parameters.DETAILS_PROCESS_PIERS:
        for platform in the_platforms:
            if platform.platform_type is PlatformType.pier:
                maritime.write_boats(platform.line_ring, instanced_collector, fg_elev)

    # trigger processing of pylon related details
    _process_pylon_details(coords_transform, lit_areas, fg_elev, stg_manager, instanced_collector,
                           rail_lines)

    # -- write stg
    instanced_collector.register_and_write_lists(stg_manager, coords_transform.anchor)
    stg_manager.write(file_lock)


def _process_pylon_details(coords_transform: co.Transformation, lit_areas: list[shg.Polygon],
                           fg_elev: ep.FGElev, stg_manager: stg_io2.STGManager,
                           instanced_collector: stg_io2.ObjectInstancedListCollector,
                           rail_lines: list[po.RailLine]) -> None:
    """Pylon details (mostly cables) go also into details, but cannot be processed together with piers and pylons."""
    # Transform to real objects
    logging.info("Transforming OSM data to Line and Pylon objects -> details")

    # References for buildings
    building_refs = list()
    storage_tanks = list()
    if parameters.C2P_PROCESS_AERIALWAYS or parameters.C2P_PROCESS_STREETLAMPS:
        building_refs = po.process_osm_building_refs(coords_transform, fg_elev, storage_tanks)
        logging.info('Number of reference buildings: %s', len(building_refs))

    # Minor power lines and aerialways
    powerlines: list[po.WayLine] = list()
    aerialways: list[po.WayLine] = list()
    req_keys: list[str] = list()
    if parameters.C2P_PROCESS_POWERLINES and parameters.C2P_PROCESS_POWERLINES_MINOR:
        req_keys.append(s.K_POWER)
    if parameters.C2P_PROCESS_AERIALWAYS:
        req_keys.append(s.K_AERIALWAY)
    if req_keys:
        powerlines, aerialways = po.process_osm_power_aerialway(req_keys, fg_elev,
                                                                coords_transform, building_refs)
        # remove all those power lines, which are not minor - after we have done the mapping in calc_and_map()
        for wayline in reversed(powerlines):
            wayline.calc_and_map()
            if wayline.type_ is po.WayLineType.power_line:
                powerlines.remove(wayline)
        logging.info('Number of minor power lines to process: %s', len(powerlines))
        logging.info('Number of aerialways to process: %s', len(aerialways))
        for wayline in aerialways:
            wayline.calc_and_map()

    # street lamps
    streetlamp_ways: list[po.StreetlampWay] = list()
    if parameters.C2P_PROCESS_STREETLAMPS:
        highways = po.process_osm_highways(coords_transform)
        streetlamp_ways = po.process_highways_for_streetlamps(highways, lit_areas)
        logging.info('Reduced number of streetlamp ways: %s', len(streetlamp_ways))
        for highway in streetlamp_ways:
            highway.calc_and_map(fg_elev)

    # free some memory
    del building_refs

    all_lines: list[po.Line] = list()
    if parameters.C2P_PROCESS_POWERLINES:
        all_lines.extend(powerlines)
        po.write_instance_entries_pylons_for_line(powerlines, instanced_collector)
    if parameters.C2P_PROCESS_AERIALWAYS:
        all_lines.extend(aerialways)
        po.write_instance_entries_pylons_for_line(aerialways, instanced_collector)
    if parameters.C2P_PROCESS_RAIL_OVERHEAD_LINES:
        all_lines.extend(rail_lines)
        po.write_instance_entries_pylons_for_line(rail_lines, instanced_collector)

    if all_lines:
        po.write_cables(all_lines, coords_transform, stg_manager, details=True)

    if parameters.C2P_PROCESS_STREETLAMPS:
        po.write_instance_entries_pylons_for_line(streetlamp_ways, instanced_collector)
