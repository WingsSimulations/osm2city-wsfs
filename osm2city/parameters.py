# SPDX-FileCopyrightText: (C) 2013 - 2026, rick@vanosten.net, radi, portree_kid
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Central place to store parameters / settings / variables in osm2city.
All parameters for length, height, etc. are in meters, square meters (m2) etc.

The assigned values are default values. The Config files will overwrite them
"""

import argparse
import logging
import math
import sys
import traceback
import types
import unittest

import osm2city.textures.road
import osm2city.utils.calc_tile as ct
import osm2city.utils.coordinates as co
import osm2city.utils.log_helper as ulog
import osm2city.static_types.osmstrings as s

# default_args_start # DO NOT MODIFY THIS LINE
# -*- coding: utf-8 -*-
# The preceding line sets encoding of this file to utf-8. Needed for non-ascii
# object names. It must stay on the first or second line.

# =============================================================================
# PARAMETERS FOR ALL osm2city MODULES
# =============================================================================
# -- Scenery folder, typically a geographic name or the ICAO code of the airport
PREFIX = "LSZR"

# -- Boundary of the scenery in degrees (use "." not ","). The example below is from LSZR.
# The values are set dynamically during program execution - no need to set them manually.
BOUNDARY_WEST = 9.54
BOUNDARY_SOUTH = 47.48
BOUNDARY_EAST = 9.58
BOUNDARY_NORTH = 47.50

AREA = ''  # Not used in the code - use it in your parameters.py for conditional parameters

# -- Full path to the scenery folder without trailing slash. This is where we
#    will probe elevation and check for overlap with static objects. Most
#    likely you'll want to use your TerraSync path here.
PATH_TO_SCENERY = "/home/user/fgfs/scenery/TerraSync"
# Full path to WS3 airports folder - will be added for elevation probing if not None
PATH_TO_AIRPORTS: str | None = None
USE_LINE_FEATURE_LIST_FOR_ROADS = False  # only to be used with WS30

CACHE_DIR_O2C = 'cache_files_o2c'  # cache directory for o2c & o2g files

# For shared models which not part of the default path to scenery.
# This requires that they have been processed - e.g. from WS2 with clean_shared_models.py
SHARED_MODELS_PATH: str | None = None
CREATE_TREES = True

# Optional additional list of paths to scenery folders (e.g. project3000).
# Only used for overlap checking for buildings against static and shared objects
PATH_TO_SCENERY_OPT = None  # if not none, then needs to be a list of strings

# -- The generated scenery (.stg, .ac, .xml) will be written to this path.
#    If empty, we'll use the correct location in PATH_TO_SCENERY. Note that
#    if you use TerraSync for PATH_TO_SCENERY, you MUST choose a different
#    path here. Otherwise, TerraSync will overwrite the generated scenery.
#    Also, make sure PATH_TO_OUTPUT is included in your $FG_SCENERY.
PATH_TO_OUTPUT = "/home/user/fgfs/scenery/osm2city"

NO_ELEV = False             # -- skip elevation probing

# length/width in meters for clustering of meshes; has to be at least 3000. 4000 leads to max 5x5 meshes
CLUSTER_DIMENSION = 4000

FLAG_STG_BUILDING_LIST = True  # use BUILDING_LIST in stg-files in 2019.2+ format
FLAG_BUILDINGS_LIST_SKIP = False
FLAG_BUILDINGS_MESH_SKIP = False

BUILDING_LIST_ALLOW_NEIGHBOURS = True
BUILDING_LIST_AREA_DEVIATION = 0.9
BUILDING_LIST_DIST_DEVIATION = 0.8

# Debugging by plotting with Matplotlib to pdfs. See description about its use in the appendix of the manual
DEBUG_PLOT_LANDUSE = False
DEBUG_PLOT_ROADS = False
DEBUG_PLOT_OFFSETS = False

# =============================================================================
# PARAMETERS RELATED TO BUILDINGS IN osm2city
# =============================================================================

# -- Check for objects in the PATH_TO_SCENERY folder based on convex hull around all points
OVERLAP_CHECK_CONVEX_HULL_STG_MAX_AREA = 300*300  # all kinds of fun stuff happen and it can get very large
OVERLAP_CHECK_CH_BUFFER_STATIC = 0.0
OVERLAP_CHECK_CH_BUFFER_SHARED = 0.0

OVERLAP_CHECK_CONSIDER_SHARED = True

# Scenery directories in which to look for apt.dat files of the form NavData/apt/*.dat[.gz].
# If None (default), use PATH_TO_SCENERY and PATH_TO_SCENERY_OPT.

# Must be formatted as a list even if only one value, e.g. ["/home/pingu/airports_ws3"]
# This is mostly for WS3.0, where the airports' information is not part of FGDATA
OVERLAP_CHECK_APT_DAT_SCENERY_LIST = None

OVERLAP_CHECK_APT_PAVEMENT_BUILDINGS_INCLUDE = []  # At apts in list include overlap check with pavement for buildings
OVERLAP_CHECK_APT_PAVEMENT_ROADS_INCLUDE = []  # At airports in list include overlap check with pavement for roads
OVERLAP_CHECK_APT_USE_OSM_APRON_ROADS = True  # Add OSM APRON polygons for overlap checking with roads
OVERLAP_CHECK_APT_BOUNDARY_ROADS = True
OVERLAP_CHECK_APT_BOUNDARY_BUILDINGS = True

# Only add buildings within an airport boundary if the existing number of static objects
# is at or below a certain number. We assume that if there are just a few static objects, then a human
# has taken care of this airport, and adding buildings from OSM might make it worse instead of better
# use a large number (e.g. 9999) to make sure OSM buildings are added always (unless they overlap with an existing)
APT_MAX_NUMBER_STATIC_OBJECTS_CREATE_BUILDINGS_IN_BOUNDARY = 2

OVERLAP_CHECK_EXCLUDE_AREAS_BUILDINGS = None  # Exclude placing buildings in this area: list of list of lon/lat tuples
OVERLAP_CHECK_EXCLUDE_AREAS_ROADS = None  # ditto

# -- Skip buildings based on their OSM name tag or OSM ID, e.g. in case there's already
#    a static model for these, and the overlap check fails.
#    Use Unicode strings as in the first example if there are non-ASCII characters.
#    E.g. SKIP_LIST = ["Theologische Fakultät", "Rhombergpassage", 55875208]
#    For roads/railways OSM ID is checked.
SKIP_LIST = []
SKIP_LIST_OVERLAP = []  # list of .ac or .xml file names which should not be used for overlap tests


BUILDING_MAX_AREA_ASSUME_SHED = 70  # if we do not know anything else (should be > BUILDING_MIN_AREA)

BUILDING_COMPLEX_ROOFS = True       # -- generate complex roofs on buildings? I.e. other shapes than horizontal and flat
BUILDING_COMPLEX_ROOFS_MIN_LEVELS = 1  # don't put complex roof on buildings smaller than the specified value unless there is an explicit roof:shape flag
BUILDING_COMPLEX_ROOFS_MAX_LEVELS = 5   # don't put complex roofs on buildings taller than the specified value unless there is an explicit roof:shape flag
BUILDING_COMPLEX_ROOFS_MAX_AREA = 1600  # -- don't put complex roofs on buildings larger than this
BUILDING_COMPLEX_ROOFS_MIN_RATIO_AREA = 600  # if larger than this, then the ratio of length vs. area must be fulfilled
BUILDING_SKEL_ROOFS_MIN_ANGLE = 20  # -- pySkeleton based complex roofs will
BUILDING_SKEL_ROOFS_MAX_ANGLE = 60  #    have a random angle between MIN and MAX
BUILDING_SKEL_ROOFS_ANGLE_STEP = 10  # by how much the angle is iteratively reduced
BUILDING_SKEL_MAX_NODES = 10        # -- max number of nodes for which we generate pySkeleton roofs
BUILDING_SKEL_ROOF_MAX_HEIGHT = 6.  # -- skip skeleton roofs (gabled, pyramidal, ...) if the roof height is larger than this
BUILDING_SKEL_MAX_DIST_FROM_CENTROID = 400  # Hack to make sure skeleton residuals are not causing FG to crash in rendering
BUILDING_ROOF_SIMPLIFY_TOLERANCE = .5
BUILDING_SKILLION_ROOF_MAX_HEIGHT = 8.

BUILDING_TEXTURE_GROUP_RADIUS_M = 0  # For BUILDING_LIST buildings, distance within which buildings will tend to have the same texture

# If the roof_type is missing, what shall the distribution of roof_types (must sum up to 1.0) be?
# The keys are the shapes and must correspond to valid RoofShape values in roofs.py
BUILDING_ROOF_SHAPE_RATIO: dict[str, float] = {s.V_FLAT: 0.1, s.V_GABLED: 0.8, s.V_HIPPED: 0.1}

# If the roof_material and/or the roof_colour are missing for a pitched roof, then use the distribution below.
# Flat roofs are more "universal" and might not need a regionalization.
# The distribution must sum up to 1.0.
# The first value in the tuple is the colour, the second the material.
# Make sure to use combinations, for which there is a registered RCovering in coverings.py.
BUILDING_ROOF_COLOUR_MATERIAL_PITCHED_RATIO: dict[tuple[str, str], float] = {
    (s.V_RED, s.V_ROOF_TILES): 0.6,
    (s.V_BLACK, s.V_ROOF_TILES): 0.3,
    (s.V_GREY, s.V_METAL): 0.05,
    (s.V_DARKGREY, s.V_METAL): 0.03,
    (s.V_BLACK, s.V_SLATE): 0.02,
}

# ==================== RECTIFY BUILDINGS ============
RECTIFY_ENABLED = True
RECTIFY_MAX_DRAW_SAMPLE = 20
RECTIFY_SEED_SAMPLE = True
RECTIFY_MAX_90_DEVIATION = 7
RECTIFY_90_TOLERANCE = 0.1

BUILDING_FAKE_AMBIENT_OCCLUSION = True      # -- fake AO by darkening facade textures towards the ground, using
BUILDING_FAKE_AMBIENT_OCCLUSION_HEIGHT = 6.  # 1 - VALUE * exp(- AGL / HEIGHT )
BUILDING_FAKE_AMBIENT_OCCLUSION_VALUE = 0.6

# Parameters which influence the height of buildings if no info from OSM is available.
BUILDING_NUMBER_LEVELS_CENTRE = {4: 0.2, 5: 0.7, 6: 0.1}
BUILDING_NUMBER_LEVELS_BLOCK = {4: 0.4, 5: 0.6}
BUILDING_NUMBER_LEVELS_DENSE = {3: 0.25, 4: 0.75}
BUILDING_NUMBER_LEVELS_PERIPHERY = {1: 0.3, 2: 0.65, 3: 0.05}
BUILDING_NUMBER_LEVELS_RURAL = {1: 0.3, 2: 0.7}
# the following are used if settlement type is not centre or block and building class is not residential
BUILDING_NUMBER_LEVELS_APARTMENTS = {2: 0.05, 3: 0.45, 4: 0.4, 5: 0.08, 6: 0.02}
BUILDING_NUMBER_LEVELS_INDUSTRIAL = {1: 0.3, 2: 0.6, 3: 0.1}  # for both industrial and warehouse
BUILDING_NUMBER_LEVELS_OTHER = {1: 0.2, 2: 0.4, 3: 0.3, 4: 0.1}  # e.g. commercial, public, retail

BUILDING_USE_SHARED_WORSHIP = False  # try to use shared models for worship buildings

BUILDING_NUMBER_LEVELS_AEROWAY = 2
BUILDING_LEVEL_HEIGHT_AEROWAY = 3.5

OBSTRUCTION_LIGHT_MIN_HEIGHT = 45   # -- put obstruction lights on buildings with >= height. 0 for no lights.

# discard cluster if too few objects. Do not go below 1, otherwise lots of empty ac-objects and useless STG entries.
CLUSTER_MIN_OBJECTS = 5

# When searching for an existing OSM node based on distance: what is the allowed tolerance.
# Also used in roads.py to make sure blocked areas do not generate tiny differences.
TOLERANCE_MATCH_NODE = 0.5

DETAILS_PROCESS_PIERS = True
DETAILS_PROCESS_PLATFORMS = True
DETAILS_PROCESS_SEAMARKS = True

# =============================================================================
# PARAMETERS RELATED TO PYLONS, POWERLINES, AERIALWAYS IN pylons.py
# =============================================================================

C2P_PROCESS_POWERLINES = True
C2P_PROCESS_POWERLINES_MINOR = True  # only considered if C2P_PROCESS_POWERLINES is True
C2P_PROCESS_AERIALWAYS = True
C2P_PROCESS_RAIL_OVERHEAD_LINES = True
C2P_PROCESS_WIND_TURBINES = True
C2P_PROCESS_STREETLAMPS = False  # experimental and unsupported
C2P_PROCESS_STORAGE_TANKS = True
C2P_PROCESS_CHIMNEYS = True
C2P_PROCESS_COMMUNICATION_MASTS = True

# The radius for the cable. The cable will be a triangle with side length 2*radius.
# To be better visible, the radius might be chosen larger than in real life
C2P_RADIUS_POWER_LINE = 0.1
C2P_RADIUS_POWER_MINOR_LINE = 0.05
C2P_RADIUS_AERIALWAY_CABLE_CAR = 0.05
C2P_RADIUS_AERIALWAY_CHAIR_LIFT = 0.05
C2P_RADIUS_AERIALWAY_DRAG_LIFT = 0.03
C2P_RADIUS_AERIALWAY_GONDOLA = 0.05
C2P_RADIUS_AERIALWAY_GOODS = 0.03
C2P_RADIUS_TOP_LINE = 0.02
C2P_RADIUS_OVERHEAD_LINE = 0.02

# The number of extra points between 2 pylons to simulate sagging of the cable.
# If 0 is chosen or if CATENARY_A is 0, then no sagging is calculated, which is better for performances (less realistic)
# 3 is normally a good compromise - for cable cars or major power lines with very long distances a value of 5
# or higher might be suitable
C2P_EXTRA_VERTICES_POWER_LINE = 3
C2P_EXTRA_VERTICES_POWER_MINOR_LINE = 3
C2P_EXTRA_VERTICES_AERIALWAY_CABLE_CAR = 5
C2P_EXTRA_VERTICES_AERIALWAY_CHAIR_LIFT = 3
C2P_EXTRA_VERTICES_AERIALWAY_DRAG_LIFT = 0
C2P_EXTRA_VERTICES_AERIALWAY_GONDOLA = 3
C2P_EXTRA_VERTICES_AERIALWAY_GOODS = 5
C2P_EXTRA_VERTICES_OVERHEAD_LINE = 2

# The value for catenary_a can be experimentally determined by using osm2pylon.test_catenary
C2P_CATENARY_A_POWER_LINE = 1500
C2P_CATENARY_A_POWER_MINOR_LINE = 1200
C2P_CATENARY_A_AERIALWAY_CABLE_CAR = 1500
C2P_CATENARY_A_AERIALWAY_CHAIR_LIFT = 1500
C2P_CATENARY_A_AERIALWAY_DRAG_LIFT = 1500
C2P_CATENARY_A_AERIALWAY_GONDOLA = 1500
C2P_CATENARY_A_AERIALWAY_GOODS = 1500
C2P_CATENARY_A_OVERHEAD_LINE = 600
C2P_CATENARY_A_MAX_SAGGING = 0.3  # the maximum sagging allowed no matter the catenary a relative to lowest cable height

C2P_CATENARY_MIN_DISTANCE = 30

C2P_POWER_LINE_ALLOW_100M = False

C2P_STREETLAMPS_MAX_DISTANCE_LANDUSE = 100
C2P_STREETLAMPS_RESIDENTIAL_DISTANCE = 40
C2P_STREETLAMPS_OTHER_DISTANCE = 70
C2P_STREETLAMPS_MIN_STREET_LENGTH = 40

C2P_WIND_TURBINE_MAX_DISTANCE_WITHIN_WIND_FARM = 700
C2P_WIND_TURBINE_MIN_DISTANCE_SHARED_OBJECT = 10

C2P_CHIMNEY_BRICK_RATION = 0.2  # the ratio of chimneys being made of bricks (rest is cement etc.)
C2P_CHIMNEY_MIN_HEIGHT = 20  # the minimum height a Chimney needs to have to be taken into account
C2P_CHIMNEY_DEFAULT_HEIGHT = 30  # the default height of chimneys, where the height is not specified in OSM
C2P_CHIMNEY_DEFAULT_HEIGHT_VARIATION = 10  # a random variation on top of the default height between 0 and value

C2P_COMMUNICATION_MAST_MIN_HEIGHT = 20
C2P_COMMUNICATION_MAST_DEFAULT_HEIGHT = 30  # the default height if height is not specified in OSM

# =============================================================================
# PARAMETERS RELATED TO linear_transportation.py
# =============================================================================

MAX_SLOPE_RAILWAY = 0.04
MAX_SLOPE_TRAM = 0.14
MAX_SLOPE_RACK = 0.49
MAX_SLOPE_MOTORWAY = 0.07       # max slope for motorways
MAX_SLOPE_ROAD = 0.15
MAX_TRANSVERSE_GRADIENT = 0.1   #
BRIDGE_MIN_LENGTH = 15.         # discard short bridges, draw road instead
CREATE_BRIDGES_ONLY = False         # create only bridges and embankments
BRIDGE_LAYER_HEIGHT = 5.         # bridge height per layer - if there are layers
BRIDGE_MIN_HEIGHT = 1.5  # bridge height if no layers - should be more than BRIDGE_BODY_HEIGHT
BRIDGE_BODY_HEIGHT = 0.9         # height of bridge body
EMBANKMENT_TEXTURE = osm2city.textures.road.EMBANKMENT_1  # Texture for the embankment

DELTA_V_ADD_IS_ZERO = 0.1  # when we look at v_add and can think of it as just a bit of jitter, that can be ignored at rendering
MIN_EMBANKMENT_HEIGHT = 0.1     # the min height of an embankment before it actually is written
MIN_ABOVE_GROUND_LEVEL = 0.1    # how much a highway / railway is at least hovering above ground
DISTANCE_BETWEEN_LAYERS = 0.2  # how much different layers of roads/railways at the same node are separated
HIGHWAY_TYPE_MIN = 4  # The lower the number, the more ways are added. See roads.HighwayType
POINTS_ON_LINE_DISTANCE_MAX = 1000  # the max dist between two points on a line. If longer, then new points are added
MIN_ROAD_SEGMENT_LENGTH = 1.0         # if segment length is smaller than this, then remove point

USE_TRAM_LINES = False  # whether to build tram lines (OSM railway=tram). Often they do not merge well with roads

# when a static bridge model or another blocked area (e.g. on airport) intersect with a way,
# how much must at least be left so the way is kept after intersection
OVERLAP_CHECK_ROAD_MIN_REMAINING = 10

# the buffer around built-up land-use areas to be used for lighting of streets
# also used for buffering around water areas in cities
OWBB_BUILT_UP_BUFFER = 50

OWBB_GENERATE_BUILDINGS = False


# ==================== BUILDINGS LIBRARY ============
ALLOW_EMPTY_REGIONS = True
ACCEPTED_REGIONS = ['DE', 'DK']


# ==================== DYNAMICALLY SET ============
CACHE_REQUESTS = False  # Do not set this here - it is set dynamically during program execution based on CLI arguments
TILE_INDEX = 11111  # Do not set this here - it is set dynamically during program execution


# default_args_end # DO NOT MODIFY THIS LINE

def get_output_path():
    if PATH_TO_OUTPUT:
        return PATH_TO_OUTPUT
    return PATH_TO_SCENERY


def get_center_global():
    cmin = co.Vec2d(BOUNDARY_WEST, BOUNDARY_SOUTH)
    cmax = co.Vec2d(BOUNDARY_EAST, BOUNDARY_NORTH)
    return (cmin + cmax) * 0.5


def get_extent_local(transformer: co.Transformation) -> tuple[co.Vec2d, co.Vec2d]:
    cmin = co.Vec2d(BOUNDARY_WEST, BOUNDARY_SOUTH)
    cmax = co.Vec2d(BOUNDARY_EAST, BOUNDARY_NORTH)
    logging.info("min/max " + str(cmin) + " " + str(cmax))
    lmin = co.Vec2d(transformer.to_local((cmin.x, cmin.y)))
    lmax = co.Vec2d(transformer.to_local((cmax.x, cmax.y)))
    return lmin, lmax


def get_tile_radius() -> float:
    return co.calc_distance_global(BOUNDARY_WEST, BOUNDARY_SOUTH, BOUNDARY_EAST, BOUNDARY_NORTH) * 0.5


def get_cluster_dimension_radius() -> float:
    return math.sqrt(2) * CLUSTER_DIMENSION * 0.5


def get_tile_index() -> int:
    lon_lat = get_center_global()
    return ct.calc_tile_index((lon_lat.lon, lon_lat.lat))


def get_clipping_border():
    rect = [(BOUNDARY_WEST, BOUNDARY_SOUTH),
            (BOUNDARY_EAST, BOUNDARY_SOUTH),
            (BOUNDARY_EAST, BOUNDARY_NORTH),
            (BOUNDARY_WEST, BOUNDARY_NORTH)]
    return rect


def _check_ratio_dict_parameter(ratio_dict: dict | None, name: str, is_int: bool = True) -> None:
    if ratio_dict is None:
        raise ValueError('Parameter {} must not be None'.format(name))
    if not isinstance(ratio_dict, dict):
        raise ValueError('Parameter {} must be a dict'.format(name))
    if len(ratio_dict) == 0:
        raise ValueError('Parameter %s must not be an empty dict'.format(name))
    total = 0.
    prev_key = -9999
    for key, ratio in ratio_dict.items():
        if is_int:
            if not isinstance(key, int):
                raise ValueError('key {} in parameter {} must be an int'.format(str(key), name))
            if prev_key > key:
                raise ValueError('key {} in parameter {} must be larger than previous key'.format(str(key), name))
            prev_key = key
        else:
            if not isinstance(key, str) and not isinstance(key, tuple):
                raise ValueError('key {} in parameter {} must be a string or a tuple'.format(str(key), name))
        if not isinstance(ratio, float):
            raise ValueError('ratio {} for key {} in param {} must be a float'.format(str(ratio), str(key), name))
        total += ratio
    if abs(total - 1) > 0.001:
        raise ValueError('The total of all ratios in param {} must be 1'.format(name))


def show():
    """
    Prints all parameters as key = value if the log level is INFO or lower
    """
    if ulog.log_level_info_or_lower():
        print('--- Using the following parameters: ---')
        my_globals = globals()
        for k in sorted(my_globals.keys()):
            if k.startswith('__'):
                continue
            elif k == "args":
                continue
            elif k == "parser":
                continue
            elif isinstance(my_globals[k], type) or \
                    isinstance(my_globals[k], types.FunctionType) or \
                    isinstance(my_globals[k], types.ModuleType):
                continue
            else:
                print('%s = %s' % (k, my_globals[k]))
        print('------')


def read_from_file(filename):
    logging.info('Reading parameters from file: %s' % filename)
    default_globals = globals()
    file_globals = dict()
    try:
        exec(compile(open(filename).read(), filename, 'exec'), file_globals)
    except IOError as reason:
        logging.error("Error processing file with parameters: %s", reason)
        sys.exit(1)
    except NameError:
        logging.error(traceback.format_exc())
        logging.error("Error while reading " + filename + ". Perhaps an unquoted string in your parameters file?")
        sys.exit(1)

    has_unknown_parameters = False
    for k, v in file_globals.items():
        if k.startswith('_'):
            continue
        k = k.upper()
        if k in default_globals:
            default_globals[k] = v
        else:
            logging.error('Unknown parameter: %s=%s' % (k, v))
            has_unknown_parameters = True
    if has_unknown_parameters:
        sys.exit(1)

    # correct use of parameter PATH_TO_SCENERY_OPT: earlier only string, now list of strings (or None)
    global PATH_TO_SCENERY_OPT
    if PATH_TO_SCENERY_OPT:
        if isinstance(PATH_TO_SCENERY_OPT, str):
            if PATH_TO_SCENERY_OPT == "":
                PATH_TO_SCENERY_OPT = None
            else:
                PATH_TO_SCENERY_OPT = [PATH_TO_SCENERY_OPT]

    # check the ratios in specific parameters
    global BUILDING_NUMBER_LEVELS_CENTRE
    global BUILDING_NUMBER_LEVELS_BLOCK
    global BUILDING_NUMBER_LEVELS_DENSE
    global BUILDING_NUMBER_LEVELS_PERIPHERY
    global BUILDING_NUMBER_LEVELS_RURAL
    global BUILDING_NUMBER_LEVELS_APARTMENTS
    global BUILDING_NUMBER_LEVELS_INDUSTRIAL
    global BUILDING_NUMBER_LEVELS_OTHER

    global BUILDING_ROOF_SHAPE_RATIO
    global BUILDING_ROOF_COLOUR_MATERIAL_PITCHED_RATIO

    _check_ratio_dict_parameter(BUILDING_NUMBER_LEVELS_CENTRE, 'BUILDING_NUMBER_LEVELS_CENTRE')
    _check_ratio_dict_parameter(BUILDING_NUMBER_LEVELS_BLOCK, 'BUILDING_NUMBER_LEVELS_BLOCK')
    _check_ratio_dict_parameter(BUILDING_NUMBER_LEVELS_DENSE, 'BUILDING_NUMBER_LEVELS_DENSE')
    _check_ratio_dict_parameter(BUILDING_NUMBER_LEVELS_PERIPHERY, 'BUILDING_NUMBER_LEVELS_PERIPHERY')
    _check_ratio_dict_parameter(BUILDING_NUMBER_LEVELS_RURAL, 'BUILDING_NUMBER_LEVELS_RURAL')
    _check_ratio_dict_parameter(BUILDING_NUMBER_LEVELS_APARTMENTS, 'BUILDING_NUMBER_LEVELS_APARTMENTS')
    _check_ratio_dict_parameter(BUILDING_NUMBER_LEVELS_INDUSTRIAL, 'BUILDING_NUMBER_LEVELS_INDUSTRIAL')
    _check_ratio_dict_parameter(BUILDING_NUMBER_LEVELS_OTHER, 'BUILDING_NUMBER_LEVELS_OTHER')
    _check_ratio_dict_parameter(BUILDING_ROOF_SHAPE_RATIO, 'BUILDING_ROOF_SHAPE_RATIO', False)
    _check_ratio_dict_parameter(BUILDING_ROOF_COLOUR_MATERIAL_PITCHED_RATIO, 'BUILDING_ROOF_COLOUR_MATERIAL_PITCHED_RATIO', False)

    # check minimal tile size - otherwise there might be problems with naming of files within the same tile
    # in clustering. Each tile has maximum ca. 20 km length/width. There may only be one digit for x/y naming
    global CLUSTER_DIMENSION
    if CLUSTER_DIMENSION is None or CLUSTER_DIMENSION < 3000:
        raise ValueError('Parameter CLUSTER_DIMENSION needs to be at least 3000')


def show_default():
    """show default parameters by printing all params defined above between
        # default_args_start and # default_args_end to screen.
    """
    f = open(sys.argv[0], 'r')
    do_print = False
    for line in f.readlines():
        if line.startswith('# default_args_start'):
            do_print = True
            continue
        elif line.startswith('# default_args_end'):
            return
        if do_print:
            print(line, end='')


def set_boundary(boundary_west: float, boundary_south: float,
                 boundary_east: float, boundary_north: float) -> None:
    """Overrides the geographical boundary values (either default values or read from a file).
    In most situations should be called after the method read_from_file().
    """
    import osm2city.utils.utilities as uu
    try:
        uu.check_boundary(boundary_west, boundary_south, boundary_east, boundary_north)
    except uu.BoundaryError as be:
        logging.error(be.message)
        sys.exit(1)

    global BOUNDARY_WEST
    BOUNDARY_WEST = boundary_west
    global BOUNDARY_SOUTH
    BOUNDARY_SOUTH = boundary_south
    global BOUNDARY_EAST
    BOUNDARY_EAST = boundary_east
    global BOUNDARY_NORTH
    BOUNDARY_NORTH = boundary_north


if __name__ == "__main__":
    # Handling arguments and parameters
    parser = argparse.ArgumentParser(
        description="The parameters module provides parameters to osm2city - run as main it shows the parameters used.")
    parser.add_argument("-f", "--file", dest="filename",
                        help="read parameters from FILE (e.g. params.ini)", metavar="FILE")
    parser.add_argument("-d", "--show-default", action="store_true", help="show default parameters")
    args = parser.parse_args()
    if args.filename is not None:
        read_from_file(args.filename)
        show()
    if args.show_default:
        show_default()


# ================ UNITTESTS =======================


class TestParameters(unittest.TestCase):
    def test_check_ratio_dict_parameter(self):
        my_ratio_dict = None
        with self.assertRaises(ValueError):
            _check_ratio_dict_parameter(my_ratio_dict, 'my_ratio_dict')
        my_ratio_dict = list()
        with self.assertRaises(ValueError):
            _check_ratio_dict_parameter(my_ratio_dict, 'my_ratio_dict')
        my_ratio_dict = dict()
        with self.assertRaises(ValueError):
            _check_ratio_dict_parameter(my_ratio_dict, 'my_ratio_dict')
        my_ratio_dict = {'A': 'B'}
        with self.assertRaises(ValueError):
            _check_ratio_dict_parameter(my_ratio_dict, 'my_ratio_dict')
        my_ratio_dict = {1: 'b'}
        with self.assertRaises(ValueError):
            _check_ratio_dict_parameter(my_ratio_dict, 'my_ratio_dict')
        my_ratio_dict = {1: 0.01, 2: 1.}
        with self.assertRaises(ValueError):
            _check_ratio_dict_parameter(my_ratio_dict, 'my_ratio_dict')
        my_ratio_dict = {2: 0.01, 1: .99}
        with self.assertRaises(ValueError):
            _check_ratio_dict_parameter(my_ratio_dict, 'my_ratio_dict')
        my_ratio_dict = {1: 0.01, 2: 0.99}
        self.assertEqual(2, len(my_ratio_dict), 'Length correct and no exception')
