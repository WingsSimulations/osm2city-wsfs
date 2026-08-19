# SPDX-FileCopyrightText: (C) 2017 - 2026, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later

import argparse
from enum import IntEnum, unique
import datetime
import logging
import logging.config
import multiprocessing as mp
import multiprocessing.synchronize as mps
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import unittest

import shapely.geometry as shg

from osm2city import details, pylons, buildings, parameters, linear_transportation
import osm2city.proto.proto_reader as pr
import osm2city.proto.proto_writer as pw
import osm2city.utils.aptdat_io as aio
from osm2city.utils import calc_tile
from osm2city.utils import coordinates
import osm2city.utils.elev_probe as ep
import osm2city.utils.environment as env
from osm2city.utils import stg_io2
from osm2city.utils import utilities as u


FILE_NAME_EXCEPTIONS_LOG = 'osm2city-exceptions.log'
FILE_NAME_PROGRESS_LOG = 'osm2city-progress.log'


class SceneryTile(object):
    __slots__ = ('boundary_west', 'boundary_south', 'boundary_north', 'boundary_east', 'tile_index', 'prefix')

    def __init__(self, my_boundary_west: float, my_boundary_south: float,
                 my_boundary_east: float, my_boundary_north: float,
                 my_tile_index: int, prefix: str) -> None:
        self.boundary_west = my_boundary_west
        self.boundary_south = my_boundary_south
        self.boundary_east = my_boundary_east
        self.boundary_north = my_boundary_north
        self.tile_index = my_tile_index
        self.prefix = prefix

    def __str__(self) -> str:
        my_string = "Tile index: " + str(self.tile_index)
        my_string += ", prefix: " + self.prefix
        my_string += "; boundary west: " + str(self.boundary_west)
        my_string += " - south: " + str(self.boundary_south)
        my_string += " - east: " + str(self.boundary_east)
        my_string += " - north: " + str(self.boundary_north)
        return my_string


@unique
class Procedures(IntEnum):
    all = 0
    buildings = 2
    non_buildings = 3


def _parse_exec_for_procedure(exec_argument: str) -> Procedures:
    """Parses a command line argument to determine which osm2city procedure to run.
    Returns KeyError if mapping cannot be done"""
    return Procedures.__members__[exec_argument.lower()]


class RuntimeFormatter(logging.Formatter):
    """A logging formatter which includes the delta time since start.

    Cf. https://stackoverflow.com/questions/25194864/python-logging-time-since-start-of-program
    """
    def __init__(self, *the_args, **kwargs) -> None:
        super().__init__(*the_args, **kwargs)
        self.start_time = time.time()

    def formatTime(self, record, datefmt=None):
        duration = datetime.datetime.fromtimestamp(record.created - self.start_time, datetime.UTC)
        elapsed = duration.strftime('%H:%M:%S')
        return "{}".format(elapsed)


def configure_time_logging(log_level: str, log_to_file: bool) -> None:
    """Set the logging level and maybe write to file.

    See also accepted answer to https://stackoverflow.com/questions/29015958/how-can-i-prevent-the-inheritance-
    of-python-loggers-and-handlers-during-multipro?noredirect=1&lq=1.
    And: https://docs.python.org/3.5/howto/logging-cookbook.html#logging-to-a-single-file-from-multiple-processes
    """
    log_format = '%(processName)-10s %(name)s -- %(asctime)s - %(levelname)-9s: %(message)s'
    console_handler = logging.StreamHandler()
    fmt = RuntimeFormatter(log_format)
    console_handler.setFormatter(fmt)
    logging.getLogger().addHandler(console_handler)
    logging.getLogger().setLevel(log_level)
    if log_to_file:
        process_name = mp.current_process().name
        if process_name == 'MainProcess':
            file_name = 'osm2city_main_{}.log'.format(u.date_time_now())
        else:
            file_name = 'osm2city_process_{}_{}.log'.format(process_name, u.date_time_now())
        file_handler = logging.FileHandler(filename=file_name)
        file_handler.setFormatter(fmt)
        logging.getLogger().addHandler(file_handler)


def pool_initializer(log_level: str, log_to_file: bool):
    configure_time_logging(log_level, log_to_file)


def _run_osm2gear_subprocess(the_tile_index: int, process_trees: bool, cache_requests: bool) -> None:
    try:
        o2g_args = [env.get_env_parameter('O2C_PATH_TO_O2G'),
                    '-i', str(the_tile_index),
                    '-s', parameters.PATH_TO_SCENERY,
                    '-o', parameters.PATH_TO_OUTPUT]
        if parameters.PATH_TO_AIRPORTS:
            o2g_args.append('-a')
            o2g_args.append(parameters.PATH_TO_AIRPORTS)
        if parameters.CREATE_TREES and process_trees:
            o2g_args.append('-t')
        if parameters.OWBB_GENERATE_BUILDINGS:
            o2g_args.append('-g')
        if parameters.DEBUG_PLOT_LANDUSE:
            o2g_args.append('-p')
        if cache_requests:
            o2g_args.append('-r')
        logging.info('Spawning sub-process for osm2gear.')
        logging.info('Using arguments: %s', str(o2g_args))
        subprocess.run(args=o2g_args, check=True)
        logging.info('osm2gear has successfully done land-use analysis etc.')
    except subprocess.CalledProcessError as e:
        logging.exception('Call to osm2gear returned with code %i', e.returncode)
        raise e  # we just want to log what we can and then raise again for generic handler


def process_scenery_tile(scenery_tile: SceneryTile, params_file_name: str,
                         exec_argument: Procedures, my_airports: list[aio.Airport],
                         file_lock: mps.Lock, my_progress: str,
                         cache_o2g: bool, cache_requests: bool) -> None:
    my_fg_elev = None
    try:
        parameters.read_from_file(params_file_name)
        # adapt boundary
        parameters.CACHE_REQUESTS = cache_requests
        parameters.TILE_INDEX = scenery_tile.tile_index
        parameters.set_boundary(scenery_tile.boundary_west, scenery_tile.boundary_south,
                                scenery_tile.boundary_east, scenery_tile.boundary_north)
        parameters.PREFIX = scenery_tile.prefix
        logging.info("Processing tile {} in prefix {} with process id = {} - {}".format(scenery_tile.tile_index,
                                                                                        parameters.PREFIX,
                                                                                        os.getpid(), my_progress))

        the_coords_transform = coordinates.Transformation(parameters.BOUNDARY_WEST, parameters.BOUNDARY_SOUTH,
                                                          parameters.BOUNDARY_EAST, parameters.BOUNDARY_NORTH,
                                                          scenery_tile.tile_index)

        my_fg_elev = ep.FGElev(the_coords_transform)
        my_stg_entries = stg_io2.read_stg_entries_in_boundary(the_coords_transform, False)
        blocked_apt_areas: list[shg.Polygon]
        stg_static_polys: list[shg.Polygon]
        stg_shared_polys: list[shg.Polygon]

        # run programs
        proto_buildings_filename = os.path.join(parameters.CACHE_DIR_O2C,
                                                'osm2gear_buildings_' + str(scenery_tile.tile_index) + '.proto')
        my_file = Path(proto_buildings_filename)

        if not my_file.is_file() or cache_o2g is False or exec_argument in [Procedures.buildings, Procedures.all]:
            blocked, boundaries = aio.get_apt_dat_blocked_areas_from_airports(the_coords_transform,
                                                                              parameters.BOUNDARY_WEST,
                                                                              parameters.BOUNDARY_SOUTH,
                                                                              parameters.BOUNDARY_EAST,
                                                                              parameters.BOUNDARY_NORTH,
                                                                              my_airports, True)
            stg_static_polys = stg_io2.convex_hulls_from_stg_entries(my_stg_entries, stg_io2.STGVerbType.object_static)
            stg_shared_polys = stg_io2.convex_hulls_from_stg_entries(my_stg_entries, stg_io2.STGVerbType.object_shared)
            platform_polys = details.create_platform_polygons(the_coords_transform)
            proto_blocked_filename = os.path.join(parameters.CACHE_DIR_O2C,
                                                 'osm2gear_blocked_areas_' + str(scenery_tile.tile_index) + '.proto')
            pw.write_blocked_areas_to_protobuf(proto_blocked_filename, blocked, boundaries,
                                               stg_static_polys, stg_shared_polys, platform_polys)
        if not my_file.is_file() or cache_o2g is False:
            _run_osm2gear_subprocess(scenery_tile.tile_index, parameters.CREATE_TREES, cache_requests)
        # for some reason the parameters are reset in _run_osm2gear_subprocess
        parameters.read_from_file(params_file_name)
        osm_buildings, lit_areas = pr.read_building_stuff_from_protobuf(the_coords_transform, proto_buildings_filename,
                                                                        cache_o2g)
        if exec_argument in [Procedures.buildings, Procedures.all]:
            buildings.process_buildings(the_coords_transform, my_fg_elev,
                                        osm_buildings, file_lock)
        if exec_argument in [Procedures.non_buildings, Procedures.all]:
            blocked_apt_areas, _ = aio.get_apt_dat_blocked_areas_from_airports(the_coords_transform,
                                                                               parameters.BOUNDARY_WEST,
                                                                               parameters.BOUNDARY_SOUTH,
                                                                               parameters.BOUNDARY_EAST,
                                                                               parameters.BOUNDARY_NORTH,
                                                                               my_airports, False)
            the_stg_entries = stg_io2.read_stg_entries_in_boundary(the_coords_transform, True)
            stg_static_polys = stg_io2.convex_hulls_from_stg_entries(the_stg_entries, stg_io2.STGVerbType.object_static)
            stg_shared_polys = stg_io2.convex_hulls_from_stg_entries(the_stg_entries, stg_io2.STGVerbType.object_shared)
            rail_lines: list[pylons.RailLine] = list()
            water_areas = list()  # FIXME
            linear_transportation.process_transportation(the_coords_transform, my_fg_elev,
                                                         blocked_apt_areas, stg_static_polys, stg_shared_polys,
                                                         lit_areas, water_areas, rail_lines,
                                                         file_lock)
            pylons.process_pylons(the_coords_transform, my_fg_elev, the_stg_entries, file_lock)
            details.process_details(the_coords_transform, lit_areas, rail_lines, my_fg_elev, file_lock)

    except:
        logging.exception('Exception occurred while processing tile {}.'.format(scenery_tile.tile_index))
        msg = "******* Exception in tile {} - to reprocess use boundaries: {}_{}_{}_{} *******".format(
            scenery_tile.tile_index, scenery_tile.boundary_west, scenery_tile.boundary_south,
            scenery_tile.boundary_east, scenery_tile.boundary_north)
        logging.exception(msg)

        with open(FILE_NAME_EXCEPTIONS_LOG, "a") as fe:
            # print info
            fe.write(msg + ' at ' + u.date_time_now() + os.linesep)
            # print exception
            exc_type, exc_value, exc_traceback = sys.exc_info()
            fe.write(''.join(traceback.format_exception(exc_type, exc_value, exc_traceback)))

    finally:
        # clean-up
        if my_fg_elev:
            my_fg_elev.close()

    logging.info("******* Finished tile {} - {} *******".format(scenery_tile.tile_index, my_progress))
    with open(FILE_NAME_PROGRESS_LOG, 'a') as fp:
        fp.write('Tile {} ({}) at {}\n'.format(scenery_tile.tile_index, my_progress, u.date_time_now()))


counter = 0


def counter_callback() -> None:
    global counter
    counter += 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="build-tiles generates a whole scenery of osm2city objects \
    based on a lon/lat defined area")
    parser.add_argument("-f", "--file", dest="filename",
                        help="Read parameters from FILE (e.g. params.ini)", metavar="FILE", required=True)
    parser.add_argument("-b", "--boundary", dest="boundary",
                        help="set the boundary as WEST_SOUTH_EAST_NORTH like *9.1_47.0_11_48.8 (. as decimal)",
                        required=True)
    parser.add_argument("-p", "--processes", dest="processes", type=int,
                        help="Number of parallel processes (should not be more than number of cores/CPUs)",
                        required=True)
    parser.add_argument('-m', '--maxtasksperchild', dest='max_tasks', type=int,
                        help='The number of tasks a worker process completes before it will exit (default: unlimited)',
                        required=False)
    parser.add_argument("-e", "--execute", dest="exec",
                        help="""Execute only the given procedure[s] (all, buildings, non_buildings)""",
                        required=False)
    parser.add_argument("-l", "--loglevel", dest="logging_level",
                        help="Set logging level. Valid levels are DEBUG, INFO (default), WARNING, ERROR, CRITICAL",
                        required=False)
    parser.add_argument('-o', '--logtofile', dest='log_to_file', action='store_true',
                        help='Write the logging output to files in addition to stderr')
    parser.add_argument('-g', '--cache_o2g', dest='cache_o2g', action='store_true',
                        help='Use a cached proto file from osm2gear and skip land-use, building generation and trees',
                        default=False)
    parser.add_argument('-r', '--cache_requests', dest='cache_requests', action='store_true',
                        help='Use cached requests from Overpass API',
                        default=False)

    args = parser.parse_args()

    # make sure we have the caching directory
    cache_dir = Path.cwd() / parameters.CACHE_DIR_O2C
    cache_dir.mkdir(exist_ok=True)

    # configure logging
    my_log_level = 'INFO'
    if args.logging_level:
        my_log_level = args.logging_level.upper()
    configure_time_logging(my_log_level, args.log_to_file)

    parameters.read_from_file(args.filename)

    exec_procedure = Procedures.all
    if args.exec:
        try:
            exec_procedure = _parse_exec_for_procedure(args.exec)
        except KeyError:
            logging.error('Cannot parse --execute argument: {}'.format(args.exec))
            sys.exit(1)

    try:
        boundary_floats = u.parse_boundary(args.boundary)
    except u.BoundaryError as be:
        logging.error(be.message)
        sys.exit(1)

    boundary_west = boundary_floats[0]
    boundary_south = boundary_floats[1]
    boundary_east = boundary_floats[2]
    boundary_north = boundary_floats[3]
    logging.info("Overall boundary {}, {}, {}, {}".format(boundary_west, boundary_south, boundary_east, boundary_north))

    # List of scenery tiles (might have smaller boundaries). Each entry has a list with the 4 boundary points
    scenery_tiles_list = list()

    # loop west-east and south-north on full degrees
    epsilon = 0.00000001  # to make sure that top right boundary not x.0
    for full_lon in range(int(boundary_west) - 1, int(boundary_east - epsilon) + 1):  # -1 for west if negative west
        for full_lat in range(int(boundary_south) - 1, int(boundary_north - epsilon) + 1):
            logging.debug("lon: {}, lat:{}".format(full_lon, full_lat))
            if calc_tile.bucket_span(full_lat) > 1:
                num_lon_parts = 1
            else:
                num_lon_parts = int(1 / calc_tile.bucket_span(full_lat))
            num_lat_parts = 8  # always the same no matter the lon
            for lon_index in range(num_lon_parts):
                for lat_index in range(num_lat_parts):
                    tile_boundary_west = full_lon + lon_index / num_lon_parts
                    tile_boundary_east = full_lon + (lon_index + 1) / num_lon_parts
                    tile_boundary_south = full_lat + lat_index / num_lat_parts
                    tile_boundary_north = full_lat + (lat_index + 1) / num_lat_parts
                    if tile_boundary_east <= boundary_west or tile_boundary_west >= boundary_east:
                        continue
                    if tile_boundary_north <= boundary_south or tile_boundary_south >= boundary_north:
                        continue
                    if boundary_west > tile_boundary_west:
                        tile_boundary_west = boundary_west
                    if tile_boundary_east > boundary_east:
                        tile_boundary_east = boundary_east
                    if boundary_south > tile_boundary_south:
                        tile_boundary_south = boundary_south
                    if tile_boundary_north > boundary_north:
                        tile_boundary_north = boundary_north

                    tile_index = calc_tile.calc_tile_index((tile_boundary_west, tile_boundary_south))
                    tile_prefix = ("%s%s%s" % (calc_tile.location_dir_name((full_lon, full_lat), '_'), '_', tile_index))
                    a_scenery_tile = SceneryTile(tile_boundary_west, tile_boundary_south,
                                                 tile_boundary_east, tile_boundary_north,
                                                 tile_index, tile_prefix)
                    scenery_tiles_list.append(a_scenery_tile)
                    logging.info("Added new scenery tile: {}".format(a_scenery_tile))

    # Get airports from apt_dat. Transformation to blocked areas can only be done in subprocess due to the local
    # coordinate system
    airports = aio.read_apt_dat_files(boundary_west, boundary_south,
                                      boundary_east, boundary_north)

    # Reset the progress file in writing mode
    with open(FILE_NAME_PROGRESS_LOG, 'w') as f:
        f.write('Progress for {} tiles (started at {}): \n'.format(len(scenery_tiles_list), u.date_time_now()))

    start_time = time.time()
    progress = 1
    total = len(scenery_tiles_list)
    if args.processes > 1:
        mp.set_start_method('spawn')  # use a safe approach to make sure e.g. parameters module is initialised separately
        # max tasks per child: see https://docs.python.org/3.5/library/multiprocessing.html#module-multiprocessing.pool
        max_tasks_per_child = None  # the default, meaning a worker process will live as long as the pool
        if args.max_tasks:
            max_tasks_per_child = args.max_tasks
        pool = mp.Pool(processes=args.processes, maxtasksperchild=max_tasks_per_child,
                       initializer=pool_initializer, initargs=(my_log_level, args.log_to_file))
        the_file_lock = mp.Manager().Lock()  # must be after "set_start_method"
        with pool:
            for my_scenery_tile in scenery_tiles_list:
                progress_str = '{}/{}'.format(progress, total)
                pool.apply_async(process_scenery_tile, (my_scenery_tile, args.filename,
                                                        exec_procedure, airports,
                                                        the_file_lock, progress_str,
                                                        args.cache_o2g, args.cache_requests),
                                 callback=counter_callback())
                progress += 1
            pool.close()
            pool.join()

    else:  # do it linearly, which is easier to debug and profile
        the_file_lock = mp.Manager().Lock()
        for my_scenery_tile in scenery_tiles_list:
            progress_str = '{}/{}'.format(progress, total)
            process_scenery_tile(my_scenery_tile, args.filename,
                                 exec_procedure, airports,
                                 the_file_lock, progress_str, args.cache_o2g, args.cache_requests)
            counter_callback()
            progress += 1

    u.time_logging("Total time used", start_time)
    logging.info('Processed %i tiles', counter)


# ================ UNITTESTS =======================


class TestProcedures(unittest.TestCase):
    def test_middle_angle(self):
        self.assertTrue(_parse_exec_for_procedure('NoN_BUILdingS') is Procedures.non_buildings)
        self.assertRaises(KeyError, _parse_exec_for_procedure, 'Hello')
