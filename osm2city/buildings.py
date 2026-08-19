# SPDX-FileCopyrightText: (C) 2013 - 2026, rick@vanosten.net, radi, portree_kid
# SPDX-License-Identifier: GPL-2.0-or-later
"""
buildings.py aims at generating 3D city models for FG, using OSM data.
Currently, it generates 3D textured buildings.
However, it has a somewhat more advanced texture manager and comes with a
number of facade/roof textures.

- cluster a number of buildings into a single .ac file
- LOD animation based on building height and area
- terrain elevation probing: places buildings at the correct elevation
"""

import gzip
import logging
import multiprocessing.synchronize as mps
import os
import random
import time

import numpy as np
from osm2city import building_lib, parameters
from osm2city.textures import materials as mat
import osm2city.textures.coverings as cov
import osm2city.utils.coordinates as co
import osm2city.utils.elev_probe as ep
import osm2city.utils.gltf_io as gio
import osm2city.utils.osmparser as op
from osm2city.utils import utilities, stg_io2
from osm2city.static_types import osmstrings as s
from osm2city.static_types import types as t

OUR_MAGIC = "osm2city"  # Used in e.g. stg files to mark edits by osm2city


def make_building_from_way(nodes_dict: dict[t.OSMId, op.Node], all_tags: t.OSMTags, way: op.Way,
                           coords_transform: co.Transformation,
                           inner_ways: list[op.Way] = None) -> building_lib.Building | None:
    if way.refs[0] == way.refs[-1]:
        way.refs = way.refs[0:-1]  # -- kick the last ref if it coincides with the first

    try:
        outer_ring = op.refs_to_ring(coords_transform, way.refs, nodes_dict)
        inner_rings_list = list()
        inner_refs_list = list()
        if inner_ways:
            for _way in inner_ways:
                if _way.refs[0] == _way.refs[-1]:
                    _way.refs = _way.refs[0:-1]  # -- kick the last ref if it coincides with the first
                inner_rings_list.append(op.refs_to_ring(coords_transform, _way.refs, nodes_dict))
                inner_refs_list.append(_way.refs)
    except KeyError as reason:
        logging.debug("ERROR: Failed to parse building referenced node missing clipped?(%s) WayID %d %s Refs %s" % (
            reason, way.osm_id, all_tags, way.refs))
        return None
    except Exception as reason:
        logging.debug("ERROR: Failed to parse building (%s)  WayID %d %s Refs %s" % (reason, way.osm_id, all_tags,
                                                                                     way.refs))
        return None

    return building_lib.Building(way.osm_id, all_tags, outer_ring, None, inner_rings_list=inner_rings_list,
                                 refs=way.refs, refs_inner=inner_refs_list)


def _write_obstruction_lights(coords_transform: co.Transformation, stg_manager: stg_io2.STGManager,
                              the_buildings: list[building_lib.Building]) -> None:
    """Add obstruction lights on top of high buildings."""
    light_list = list()  # list of strings
    for b in the_buildings:
        if b.building_height >= parameters.OBSTRUCTION_LIGHT_MIN_HEIGHT:
            nodes_outer = np.array(b.pts_outer)
            for i in np.arange(0, b.pts_outer_count, b.pts_outer_count):
                xo = nodes_outer[int(i + 0.5), 0]
                yo = nodes_outer[int(i + 0.5), 1]
                zo = b.top_of_roof_above_sea_level + 1.5
                line = '{:.1f} {:.1f} {:.1f} 20 2000 3 1.0 0.0 0.0 1.0'.format(-yo, xo, zo)  # red light
                light_list.append(line)
    if len(light_list) > 0:
        file_shader = stg_manager.prefix + '_light_list.txt.gz'
        path_to_stg = stg_manager.add_light_list(file_shader, coords_transform.anchor, 0.)
        try:
            with gzip.open(os.path.join(path_to_stg, file_shader), 'wt') as shader:
                for light in light_list:
                    shader.write(light)
                    shader.write('\n')
        except IOError as exc:
            logging.warning('Could not write lights in list to file %s', exc)
        logging.info("Total number of lights written to a light_list: %d", len(light_list))


def _write_buildings_in_lists(coords_transform: co.Transformation,
                              list_buildings: dict[building_lib.Building, building_lib.BuildingListType],
                              stg_manager: stg_io2.STGManager) -> None:
    material_name_shader = 'OSMBuildings'
    file_shader = stg_manager.prefix + "_buildings_shader.txt.gz"
    wall_tex_idx = 0
    roof_tex_idx = 0
    loc_x = 0
    loc_y = 0

    path_to_stg = stg_manager.add_building_list(file_shader, material_name_shader, coords_transform.anchor, 0)

    try:
        with gzip.open(os.path.join(path_to_stg, file_shader), 'wt') as shader:
            for b, list_type in list_buildings.items():
                elev = b.ground_elev - co.calc_horizon_elev_local(b.anchor.x, b.anchor.y)
                line = '{:.1f} {:.1f} {:.1f} {:.0f} {}'.format(-b.anchor.y, b.anchor.x, elev, b.street_angle,
                                                               list_type.value)
                b.compute_roof_height(True)
                if parameters.BUILDING_TEXTURE_GROUP_RADIUS_M > 0:
                    # Use the same texture indexes for small buildings close together. We take advantage of the building
                    # list being approximately sorted spatially.  This provides some variability.
                    delta_x = b.anchor.x - loc_x
                    delta_y = b.anchor.y - loc_y
                    dist2 = delta_x * delta_x + delta_y * delta_y

                    if list_type.value == building_lib.BuildingListType.small:
                        if dist2 > (parameters.BUILDING_TEXTURE_GROUP_RADIUS_M *
                                    parameters.BUILDING_TEXTURE_GROUP_RADIUS_M):
                            # Generate a new texture index if a sufficient distance to the centre of the last location.
                            wall_tex_idx = int(abs(b.anchor.x / 7.0))
                            roof_tex_idx = int(abs(b.anchor.y / 5.0))
                            loc_x = b.anchor.x
                            loc_y = b.anchor.y
                    else:
                        # Medium and large buildings have semi-random texture
                        wall_tex_idx = int(abs(b.anchor.x / 7.0))
                        roof_tex_idx = int(abs(b.anchor.y / 5.0))
                else:
                    tex_variability = 6
                    if list_type is building_lib.BuildingListType.large:
                        tex_variability = 4
                    wall_tex_idx = random.randint(0, tex_variability - 1)  # FIXME: should calc on street level or owbb
                    roof_tex_idx = wall_tex_idx

                roof_orientation = b.calc_roof_list_orientation()
                line += ' {:.1f} {:.1f} {:.1f} {:.1f} {} {} {} {} {}'.format(b.width, b.depth, b.facade_height,
                                                                             b.roof_height, b.roof_shape.value,
                                                                             roof_orientation, round(b.levels),
                                                                             wall_tex_idx, roof_tex_idx)
                shader.write(line)
                shader.write('\n')
    except IOError as e:
        logging.warning('Could not write buildings in list to file %s', e)
    logging.info("Total number of shader buildings written to a building_list: %d", len(list_buildings))


def _write_buildings_in_meshes(coords_transform: co.Transformation,
                               mesh_buildings: list[building_lib.Building],
                               stg_manager: stg_io2.STGManager,
                               roof_manager: cov.RoofManager) -> None:
    all_facades = list()

    for b in mesh_buildings:
        all_facades.append(b)

    total_buildings_written = 0

    file_name: str = parameters.PREFIX + '_build' + gio.FILE_ENDING
    path_to_stg = stg_manager.add_object_static(file_name, coords_transform.anchor,
                                                parameters.get_tile_radius())
    geom_collector = gio.GeometryCollector3D(False, False)

    for i, b in enumerate(mesh_buildings):
        if i % 1000 == 0:
            logging.info("Writing building %d of %d", i, len(mesh_buildings))
        b.set_ground_elev()
        b.compute_roof_height()
        b.write_facades(geom_collector)
        b.write_roof(roof_manager, geom_collector)
        total_buildings_written += 1

    geom_collector.process()
    gltf_writer = gio.GLTFWriter(geom_collector.get_shallow_c_vertices_clone(),
                                 geom_collector.get_shallow_c_faces_clone(),
                                 geom_collector.smooth_edges)
    gltf_writer.write_to_file(os.path.join(path_to_stg, file_name), True)

    logging.info("Total number of buildings written to mesh %s: %d", file_name, total_buildings_written)


def process_buildings(coords_transform: co.Transformation, fg_elev: ep.FGElev,
                      the_buildings: list[building_lib.Building],
                      file_lock: mps.Lock | None = None) -> None:
    last_time = time.time()
    random.seed(42)

    if not the_buildings:
        logging.info("No buildings found in OSM data. Stopping further processing.")
        return

    logging.info("Created %i buildings." % len(the_buildings))

    # clean up colour-related stuff in tags
    for b in the_buildings:
        mat.screen_osm_keys_for_colour_material_variants(b.tags)

    building_lib.check_buildings_and_tags_in_aerodromes(the_buildings)

    # final check on building parent hierarchy and zones linked to buildings > remove dangling stuff
    building_lib.BuildingParent.clean_building_parents_dangling_children(the_buildings)

    if not the_buildings:
        logging.info("No buildings after overlap check etc. Stopping further processing.")
        return

    facade_manager = cov.FacadeManager(cov.FACADE_COVERINGS, s.K_BUILDING_MATERIAL)
    roof_manager = cov.RoofManager(cov.ROOF_COVERINGS)

    # -- initialize STGManager
    path_to_output = parameters.get_output_path()
    stg_manager = stg_io2.STGManager(path_to_output, stg_io2.SceneryType.buildings, OUR_MAGIC, parameters.PREFIX)
    instanced_collector = stg_io2.ObjectInstancedListCollector()

    last_time = utilities.time_logging("Time used in seconds until before analyse", last_time)

    # the heavy lifting: analysis
    the_buildings = building_lib.analyse(the_buildings, fg_elev, instanced_collector,
                                         facade_manager, roof_manager)
    logging.info("Number of buildings after analysis: %i", len(the_buildings))
    last_time = utilities.time_logging("Time used in seconds for analyse", last_time)

    # split between buildings in meshes and in buildings lists
    buildings_in_meshes = list()
    buildings_in_lists = dict()  # key = building, value = building list type
    if parameters.FLAG_STG_BUILDING_LIST:
        for building in the_buildings:
            if not building.is_owbb_model:  # owbb models already have it set when init of Building object
                building.update_anchor(True)  # prepare anchor, street_angle, width, depth
            building_list_type = building.calc_building_list_type()
            if building_list_type is not None:
                buildings_in_lists[building] = building_list_type
            else:
                buildings_in_meshes.append(building)
        if not parameters.FLAG_BUILDINGS_LIST_SKIP:
            _write_buildings_in_lists(coords_transform, buildings_in_lists, stg_manager)
            last_time = utilities.time_logging("Time used in seconds to write buildings in lists", last_time)
    else:
        buildings_in_meshes = the_buildings[:]
    if not parameters.FLAG_BUILDINGS_MESH_SKIP:
        _write_buildings_in_meshes(coords_transform, buildings_in_meshes, stg_manager, roof_manager)
        _write_obstruction_lights(coords_transform, stg_manager, buildings_in_meshes)
        last_time = utilities.time_logging("Time used in seconds to write buildings in meshes", last_time)

    instanced_collector.register_and_write_lists(stg_manager, coords_transform.anchor)
    stg_manager.write(file_lock)
    _ = utilities.time_logging("Time used in seconds to write stg file", last_time)
