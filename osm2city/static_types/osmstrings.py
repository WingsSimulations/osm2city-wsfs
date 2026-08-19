# SPDX-FileCopyrightText: (C) 2018 - 2026, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later
"""Holds string constants for OSM keys and values."""

import unittest

from osm2city.static_types import types as t


# ========================= NON OSM KEYS AND VALUES ==============================================================
K_OWBB_GENERATED = 'owbb_generated'
K_REPLACED_BRIDGE_KEY = 'replaced_bridge'  # a linear_obj that was originally a bridge, but due to length was changed

# ======================= KEYS ===================================================================================
K_AERIALWAY = 'aerialway'
K_AEROWAY = 'aeroway'
K_AMENITY = 'amenity'
K_AREA = 'area'
K_BRIDGE = 'bridge'
K_BUILDING = 'building'
K_BUILDING_COLOUR = 'building:colour'
K_BUILDING_HEIGHT = 'building:height'
K_BUILDING_LEVELS = 'building:levels'
K_BUILDING_MATERIAL = 'building:material'
K_BUILDING_MIN_LEVEL = 'building:min_level'
K_BUILDING_PART = 'building:part'
K_CABLES = 'cables'
K_COMMUNICATION_MICRO_WAVE = 'communication:microwave'
K_COMMUNICATION_MOBILE_PHONE = 'communication:mobile_phone'
K_COMMUNICATION_RADIO = 'communication:radio'
K_COMMUNICATION_TELEVISION = 'communication:television'
K_CONSTRUCTION_ELECTRIFIED = 'construction:electrified'
K_CONTENT = 'content'
K_CUTTING = 'cutting'
K_DENOMINATION = 'denomination'
K_DENOTATION = 'denotation'
K_DESIGN = 'design'
K_ELECTRIFIED = 'electrified'
K_EMBANKMENT = 'embankment'
K_GAUGE = 'gauge'
K_GENERATOR_OUTPUT_ELECTRICITY = 'generator:output:electricity'
K_GENERATOR_SOURCE = 'generator:source'
K_GENERATOR_TYPE = 'generator:type'
K_HARBOUR = 'harbour'
K_HEIGHT = 'height'
K_HIGHWAY = 'highway'
K_INDOOR = 'indoor'
K_JUNCTION = 'junction'
K_LANDUSE = 'landuse'
K_LANES = 'lanes'
K_LAYER = 'layer'
K_LEISURE = 'leisure'
K_LEVEL = 'level'
K_LEVELS = 'levels'
K_LIT = 'lit'
K_LOCATION = 'location'
K_MAN_MADE = 'man_made'
K_MANUFACTURER = 'manufacturer'
K_MANUFACTURER_TYPE = 'manufacturer_type'
K_MATERIAL = 'material'
K_MILITARY = 'military'
K_MIN_HEIGHT = 'min_height'
K_MIN_HEIGHT_COLON = 'min:height'  # Incorrect value, but sometimes used
K_MOUNTAIN_PASS = 'mountain_pass'
K_NAME = 'name'
K_NATURAL = 'natural'
K_OFFSHORE = 'offshore'
K_ONEWAY = 'oneway'
K_PARKING = 'parking'
K_PLACE = 'place'
K_PLACE_NAME = 'place_name'
K_POPULATION = 'population'
K_POWER = 'power'
K_PUBLIC_TRANSPORT = 'public_transport'
K_RACK = 'rack'
K_RAILWAY = 'railway'
K_RELIGION = 'religion'
K_ROOF_ANGLE = 'roof:angle'
K_ROOF_COLOUR = 'roof:colour'  # shall be this spelling of colour
K_ROOF_HEIGHT = 'roof:height'
K_ROOF_MATERIAL = 'roof:material'
K_ROOF_ORIENTATION = 'roof:orientation'
K_ROOF_SHAPE = 'roof:shape'
K_ROOF_SLOPE_DIRECTION = 'roof:slope:direction'
K_ROTOR_DIAMETER = 'rotor_diameter'
K_ROUTE = 'route'
K_SEAMARK_LANDMARK_HEIGHT = 'seamark:landmark:height'
K_SEAMARK_LANDMARK_STATUS = 'seamark:landmark:status'
K_SEAMARK_LIGHT_COLOUR = 'seamark:light:colour'  # shall be this spelling of colour
K_SEAMARK_LIGHT_RANGE = 'seamark:light:range'
K_SEAMARK_STATUS = 'seamark:status'
K_SEAMARK_TYPE = 'seamark:type'
K_SERVICE = 'service'
K_SHOP = 'shop'
K_START_DATE = 'start_date'
K_STRUCTURE = 'structure'
K_TELECOM = 'telecom'
K_TOURISM = 'tourism'
K_TOWER_TYPE = 'tower:type'
K_TRACKS = 'tracks'
K_TREE_LINED = 'tree_lined'
K_TUNNEL = 'tunnel'
K_TYPE = 'type'
K_VOLTAGE = 'voltage'
K_WATERWAY = 'waterway'
K_WIKIDATA = 'wikidata'
K_WIRES = 'wires'

# ======================= VALUES =================================================================================
V_24_7 = '24/7'
V_ABANDONED = 'abandoned'
V_ACROSS = 'across'
V_AERODROME = 'aerodrome'
V_AERO_OTHER = 'aero_other'  # does not exist in OSM - used when it is unsure whether terminal, hangar or different
V_ALONG = 'along'
V_APARTMENTS = 'apartments'
V_APRON = 'apron'
V_AQUA = 'aqua'
V_ATTACHED = 'attached'  # does not exist in OSM - used as a proxy for flat buildings attached e.g. in cities
V_BEACH_RESORT = 'beach_resort'
V_BEACON_CARDINAL = 'beacon_cardinal'
V_BEACON_ISOLATED_DANGER = 'beacon_isolated_danger'
V_BEACON_LATERAL = 'beacon_lateral'
V_BEACON_SAFE_WATER = 'beacon_safe_water'
V_BEACON_SPECIAL_PURPOSE = 'beacon_special_purpose'
V_BEIGE = 'beige'
V_BLACK = 'black'
V_BLUE = 'blue'
V_BOROUGH = 'borough'
V_BRICK = 'brick'
V_BRIDGE = 'bridge'
V_BRIDLEWAY = 'bridleway'
V_BROWN = 'brown'
V_BUFFER_STOP = 'buffer_stop'
V_BUILDING = 'building'
V_BUNKER = 'bunker'
V_BUOY_CARDINAL = 'buoy_cardinal'
V_BUOY_ISOLATED_DANGER = 'buoy_isolated_danger'
V_BUOY_LATERAL = 'buoy_lateral'
V_BUOY_SAFE_WATER = 'buoy_safe_water'
V_BUOY_SPECIAL_PURPOSE = 'buoy_special_purpose'
V_BUOYANT = 'buoyant'
V_CANAL = 'canal'
V_CAR_PORT = 'car_port'
V_CARPORT = 'carport'
V_CATHEDRAL = 'cathedral'
V_CIRCULAR = 'circular'
V_CITY = 'city'
V_CHECKPOINT = 'checkpoint'
V_CHIMNEY = 'chimney'
V_CHRISTIAN = 'christian'
V_CHURCH = 'church'
V_COASTLINE = 'coastline'
V_COMMERCIAL = 'commercial'
V_COMMON = 'common'
V_COMMUNICATION = 'communication'
V_COMMUNICATIONS_TOWER = 'communications_tower'
V_CONCRETE = 'concrete'
V_CONSTRUCTION = 'construction'
V_CONTACT_LINE = 'contact_line'
V_COPPER = 'copper'
V_CYCLEWAY = 'cycleway'
V_DAM = 'dam'
V_DANGER_AREA = 'danger_area'
V_DARKGREEN = 'darkgreen'
V_DARKGREY = 'darkgrey'
V_DARKSALMON = 'darksalmon'
V_DARKRED = 'darkred'
V_DATA_CENTER = 'data_center'
V_DATA_CENTRE = 'data_centre'
V_DETACHED = 'detached'
V_DIGESTER = 'digester'
V_DIMGREY = 'dimgrey'
V_DISUSED = 'disused'
V_DITCH = 'ditch'
V_DOG_PARK = 'dog_park'
V_DOME = 'dome'
V_DRAIN = 'drain'
V_DYKE = 'dyke'
V_EAST = 'east'
V_FALSE = 'false'
V_FLAT = 'flat'
V_FLORALWHITE = 'floralwhite'
V_FERRY = 'ferry'
V_FIREBRICK = 'firebrick'
V_FOOTWAY = 'footway'
V_FUCHSIA = 'fuchsia'
V_FUEL_STORAGE_TANK = 'fuel_storage_tank'  # deprecated tag in OSM
V_FUNICULAR = 'funicular'
V_GABLED = 'gabled'
V_GAMBREL = 'gambrel'
V_GARAGE = 'garage'
V_GARAGES = 'garages'
V_GARDEN = 'garden'
V_GAS = 'gas'
V_GLASS = 'glass'
V_GLASSHOUSE = 'glasshouse'
V_GOLD = 'gold'
V_GRAVE_YARD = 'grave_yard'
V_GRASS = 'grass'
V_GREEN = 'green'
V_GREENHOUSE = 'greenhouse'
V_GREY = 'grey'
V_H_FRAME = 'h-frame'  # often part of value, e.g. h-frame, h-frame_two-level, h-frame_three-level, guyed_h-frame
V_HALF_HIPPED = 'half-hipped'
V_HAMLET = 'hamlet'
V_HANGAR = 'hangar'
V_HELIPAD = 'helipad'
V_HELIPORT = 'heliport'
V_HIPPED = 'hipped'
V_HORSE_RIDING = 'horse_riding'
V_HOSPITAL = 'hospital'
V_HOUSE = 'house'
V_HOUSEBOAT = 'houseboat'
V_ILLUMINATED = 'illuminated'
V_INDIANRED = 'indianred'
V_INDOOR = 'indoor'
V_INDUSTRIAL = 'industrial'
V_INNER = 'inner'
V_ISOLATED_DWELLING = 'isolated_dwelling'
V_KIOSK = 'kiosk'
V_LANDMARK = 'landmark'
V_LEAN_TO = 'lean_to'
V_LEFT = 'left'
V_LIGHT_RAIL = 'light_rail'
V_LIGHTBLUE = 'lightblue'
V_LIGHTGREY = 'lightgrey'
V_LIGHTHOUSE = 'lighthouse'
V_LIGHTSALMON = 'lightsalmon'
V_LIGHTYELLOW = 'lightyellow'
V_LIME = 'lime'
V_LIMESTONE = 'limestone'
V_LINE = 'line'
V_LIVING_STREET = 'living_street'
V_MALL = 'mall'
V_MANSARD = 'mansard'
V_MARINA = 'marina'
V_MAROON = 'maroon'
V_MAST = 'mast'
V_METAL = 'metal'
V_MINOR_LINE = 'minor_line'
V_MOCCASIN = 'moccasin'
V_MONORAIL = 'monorail'
V_MOTORWAY = 'motorway'
V_MOTORWAY_LINK = 'motorway_link'
V_MULTIPOLYGON = 'multipolygon'
V_MULTISTOREY = 'multi-storey'
V_NARROW_GAUGE = 'narrow_gauge'
V_NAVAL_BASE = 'naval_base'
V_NAVY = 'navy'
V_NATURE_RESERVE = 'nature_reserve'
V_NO = 'no'
V_NORTH = 'north'
V_OFFICE = 'office'
V_OFFSHORE_PLATFORM = 'offshore_platform'
V_OIL_TANK = 'oil_tank'  # deprecated tag in OSM
V_OLIVE = 'olive'
V_ONION = 'onion'
V_ORANGE = 'orange'
V_ORANGERED = 'orangered'
V_ORTHODOX = 'orthodox'
V_OUTER = 'outer'
V_PARK = 'park'
V_PARKING = 'parking'
V_PATH = 'path'
V_PEDESTRIAN = 'pedestrian'
V_PIER = 'pier'
V_PINK = 'pink'
V_PILE = 'pile'
V_PITCH = 'pitch'
V_PITCHED = 'pitched'
V_PLACE_OF_WORSHIP = 'place_of_worship'
V_PLANT = 'plant'
V_PLATFORM = 'platform'
V_PLAYGROUND = 'playground'
V_POLE = 'pole'
V_PRESERVED = 'preserved'
V_PRIMARY = 'primary'
V_PRIMARY_LINK = 'primary_link'
V_PROPOSED = 'proposed'
V_PURPLE = 'purple'
V_PYLON = 'pylon'
V_PYRAMIDAL = 'pyramidal'
V_RAIL = 'rail'
V_RAILWAY = 'railway'
V_RANGE = 'range'
V_RECREATION_GROUND = 'recreation_ground'
V_RED = 'red'
V_RESIDENTIAL = 'residential'
V_RETAIL = 'retail'
V_RIGHT = 'right'
V_RIVER = 'river'
V_ROAD = 'road'
V_ROOF = 'roof'
V_ROOF_TILES = 'roof_tiles'
V_ROUND = 'round'
V_ROUNDABOUT = 'roundabout'
V_SADDLE = 'saddle'
V_SALMON = 'salmon'
V_SALTBOX = 'saltbox'
V_SANDSTONE = 'sandstone'
V_SECONDARY = 'secondary'
V_SECONDARY_LINK = 'secondary_link'
V_SERVICE = 'service'
V_SHED = 'shed'
V_SILO = 'silo'
V_SILVER = 'silver'
V_SKILLION = 'skillion'
V_SLATE = 'slate'
V_SLURRY_TANK = 'slurry_tank'
V_SNOW = 'snow'
V_SOUTH = 'south'
V_SPUR = 'spur'
V_STADIUM = 'stadium'
V_STATIC_CARAVAN = 'static_caravan'
V_STATION = 'station'
V_STEPS = 'steps'
V_STONE = 'stone'
V_STORAGE_TANK = 'storage_tank'
V_STREAM = 'stream'
V_STY = 'sty'
V_SUBURB = 'suburb'
V_SUNSET_SUNRISE = 'sunset-sunrise'
V_SUPERMARKET = 'supermarket'
V_SUBWAY = 'subway'
V_SWIMMING_AREA = 'swimming_area'
V_SWITCH = 'switch'
V_TAN = 'tan'
V_TANK = 'tank'  # deprecated tag in OSM
V_TEAL = 'teal'
V_TERMINAL = 'terminal'
V_TERRACE = 'terrace'
V_TERTIARY = 'tertiary'
V_TERTIARY_LINK = 'tertiary_link'
V_TIMBER_FRAMING = 'timber_framing'
V_TOILETS = 'toilets'
V_TOWER = 'tower'
V_TOWN = 'town'
V_TRACK = 'track'
V_TRAINING_AREA = 'training_area'
V_TRAM = 'tram'
V_TREE = 'tree'
V_TREE_HOUSE = 'tree_house'
V_TREE_ROW = 'tree_row'
V_TRUE = 'true'
V_TRUNK = 'trunk'
V_TRUNK_LINK = 'trunk_link'
V_UNCLASSIFIED = 'unclassified'
V_UNDERGROUND = 'underground'
V_VILLAGE = 'village'
V_WADI = 'wadi'
V_WAREHOUSE = 'warehouse'
V_WATER_TOWER = 'water_tower'
V_WAY = 'way'
V_WEST = 'west'
V_WHEAT = 'wheat'
V_WHITE = 'white'
V_WIND = 'wind'
V_WOOD = 'wood'
V_WORKS = 'works'
V_YELLOW = 'yellow'
V_YES = 'yes'
V_ZOO = 'zoo'


# ======================= LISTS ==================================================================================
L_GLASS_H = [V_GLASSHOUSE, V_GREENHOUSE]
L_STORAGE_TANK = [V_STORAGE_TANK, V_TANK, V_OIL_TANK, V_FUEL_STORAGE_TANK, V_DIGESTER]


# ======================= KEY-VALUE PAIRS ========================================================================

KV_AEROWAY_APRON = (K_AEROWAY, V_APRON)
KV_GENERATOR_SOURCE_WIND = (K_GENERATOR_SOURCE, V_WIND)
KV_MAN_MADE_CHIMNEY = (K_MAN_MADE, V_CHIMNEY)
KV_MAN_MADE_MAST = (K_MAN_MADE, V_MAST)
KV_MAN_MADE_PIER = (K_MAN_MADE, V_PIER)
KV_RAILWAY_PLATFORM = (K_RAILWAY, V_PLATFORM)
KV_GREENHOUSE = (K_BUILDING, V_GREENHOUSE)
KV_GLASSHOUSE = (K_BUILDING, V_GLASSHOUSE)


# ======================= VALUE PARSING ==========================================================================

def has_key_value_pair(key: str, value: str, tags_dict: t.OSMTags) -> bool:
    if (key in tags_dict) and (tags_dict[key] == value):
        return True
    return False


def is_parsable_float(str_float: str) -> bool:
    try:
        float(str_float)
        return True
    except ValueError:
        return False


def parse_int(str_int: str, default_value: int) -> int:
    """If string can be parsed then return it, otherwise return the default value."""
    try:
        x = int(str_int)
        return x
    except ValueError:
        return default_value


def parse_date_to_year(date_value: str) -> int | None:
    """Attempts to parse the start_date tag as one year. Returns None if start_date cannot be parsed.

    Cf. https://wiki.openstreetmap.org/wiki/Key:start_date
    """
    if 'BC' in date_value or 'BCE' in date_value:
        return -1
    cleaned_value = date_value.replace('s', '')
    cleaned_value = cleaned_value.replace('~', '')
    cleaned_value = cleaned_value.replace('before', '')
    cleaned_value = cleaned_value.replace('after', '')
    cleaned_value = cleaned_value.replace('mid', '')
    cleaned_value = cleaned_value.replace('late', '')
    cleaned_value = cleaned_value.replace('early', '')
    cleaned_value = cleaned_value.replace('j:', '')
    cleaned_value = cleaned_value.replace('jd:', '')
    cleaned_value = cleaned_value.replace('.', '')
    cleaned_value = cleaned_value.replace(' ', '')
    # now we assume that only either YYYY or YYYY-MM-DD is left
    if len(cleaned_value) >= 4:
        year_value = parse_int(cleaned_value[:4], 0)
        if year_value > 0:
            return year_value
    return None


def parse_multi_int_values(str_value: str) -> int:
    """Parse int values for tags, where values can be separated by semi-colons.
    E.g. for building levels, 'cables' and 'voltage' for power cables, which can have multiple values.
    If only one value is present, then that value is used, otherwise the max value as int.
    Separator for multiple values is ';'.
    If it cannot be parsed, then 0 is returned.
    For 'cables' it is assumed that if several values are submitted, then the largest number are the real cables
    and not other stuff - see https://wiki.openstreetmap.org/wiki/Key:cables how this tag should be used (never multi!).
    For 'voltage it is assumed that the highest value determines the type of pylons etc."""
    sub_values = str_value.split(';')
    return_value = 0.0
    for sub_value in sub_values:
        if is_parsable_float(sub_value.strip()):
            return_value = max(return_value, float(sub_value.strip()))
    return int(return_value)


def parse_building_levels(tags: t.OSMTags) -> float:
    """The number of levels of a building - can be a decimal number.

    https://wiki.openstreetmap.org/wiki/Key:level (levels and level) is about on which floor a feature is.
    https://wiki.openstreetmap.org/wiki/Key:building:levels is used for marking the number of above-ground
    levels of a building.

    Returns 0 if the tag is not found
    """
    proxy_levels = 0.
    if K_BUILDING_LEVELS in tags:
        if ';' in tags[K_BUILDING_LEVELS]:
            proxy_levels = float(parse_multi_int_values(tags[K_BUILDING_LEVELS]))
        elif is_parsable_float(tags[K_BUILDING_LEVELS]):
            proxy_levels = float(tags[K_BUILDING_LEVELS])
    return proxy_levels

def parse_min_building_level(tags: t.OSMTags) -> int | None:
    """The minimum level the building(-part) is at.
    If the key does not exist or the value cannot be parsed, then 0 is returned.
    https://wiki.openstreetmap.org/wiki/Key:building:min%20level?uselang=en-GB
    """
    min_level = 0
    if K_BUILDING_MIN_LEVEL in tags:
        min_level = parse_int(tags[K_BUILDING_MIN_LEVEL], 0)
    return min_level

def parse_is_building_oldish(tags: t.OSMTags) -> bool:
    """A building is oldish if the start_date is before 1945 or has traditional stone building material."""
    if K_START_DATE in tags:
        start_date = parse_date_to_year(tags[K_START_DATE])
        if start_date is not None:
            return True if start_date < 1945 else False

    # apparently we cannot use the start_date -> let us look at building:material
    if has_key_value_pair(K_BUILDING_MATERIAL, V_BRICK, tags) or \
            has_key_value_pair(K_BUILDING_MATERIAL, V_STONE, tags) or \
            has_key_value_pair(K_BUILDING_MATERIAL, V_LIMESTONE, tags) or \
            has_key_value_pair(K_BUILDING_MATERIAL, V_SANDSTONE, tags):
        return True
    return False


# ========================= CHECKS TO DIFFERENTIATE STUFF, e.g. processing in buildings vs. pylons ===============

BUILDING_KEYS = (K_BUILDING, K_BUILDING_PART)

def is_storage_tank(tags: t.OSMTags) -> bool:  # @@@ DONE
    """Whether this is a storage tank (or similar) and processed in pylons.py."""
    for building_key in BUILDING_KEYS:
        if building_key in tags and tags[building_key] in L_STORAGE_TANK:
            return True
    return K_MAN_MADE in tags and tags[K_MAN_MADE] in L_STORAGE_TANK

def is_silo(tags: t.OSMTags) -> bool:  # @@@ DONE
    """Whether this is a silo and processed in pylons.py."""
    for building_key in BUILDING_KEYS:
        if building_key in tags and tags[building_key] == V_SILO:
            return True
    return K_MAN_MADE in tags and tags[K_MAN_MADE] == V_SILO


def is_highway(tags: t.OSMTags) -> bool:
    return K_HIGHWAY in tags


def is_railway(tags: t.OSMTags) -> bool:
    return K_RAILWAY in tags


def is_rack_railway(tags: t.OSMTags) -> bool:
    """Rack can have different values, so just excluding no.

    cf. https://wiki.openstreetmap.org/wiki/Key:rack?uselang=en
    """
    if K_RACK in tags and tags[K_RACK] != V_NO:
        return True
    return False


def is_electrified_railway(tags: t.OSMTags) -> bool:
    """Whether this is an electrified railway with overhead contact line.

    Cf. https://wiki.openstreetmap.org/wiki/Key:electrified?uselang=en
    'yes' is taken into account in case not more info is available.
    """
    if K_ELECTRIFIED in tags and tags[K_ELECTRIFIED] in [V_CONTACT_LINE, V_YES]:
        return True
    elif K_CONSTRUCTION_ELECTRIFIED in tags and tags[K_CONSTRUCTION_ELECTRIFIED] in [V_CONTACT_LINE, V_YES]:
        return True
    return False


def is_oneway(tags_dict: t.OSMTags, is_motorway: bool = False) -> bool:
    if is_motorway:
        if (K_ONEWAY in tags_dict) and (tags_dict[K_ONEWAY] == V_NO):
            return False
        else:
            return True  # in motorways oneway is implied
    elif (K_ONEWAY in tags_dict) and (tags_dict[K_ONEWAY] == V_YES):
        return True
    return False


def is_roundabout(tags: t.OSMTags) -> bool:
    return K_JUNCTION in tags and tags[K_JUNCTION] in [V_ROUNDABOUT, V_CIRCULAR]


def parse_tags_lanes(tags_dict: t.OSMTags, default_lanes: int = 1) -> int:
    my_lanes = default_lanes
    if K_LANES in tags_dict:
        my_lanes = parse_int(tags_dict[K_LANES], default_lanes)
    return my_lanes


def is_tunnel(tags: t.OSMTags) -> bool:
    return K_TUNNEL in tags and tags[K_TUNNEL] not in [V_NO]


def is_bridge(tags: t.OSMTags) -> bool:
    """Returns true if the tags for this linear_obj contains the OSM key for bridge."""
    if K_MAN_MADE in tags and tags[K_MAN_MADE] == V_BRIDGE:
        return True
    if K_BRIDGE in tags and tags not in [V_NO]:
        return True
    return False


def is_replaced_bridge(tags: t.OSMTags) -> bool:
    """Returns true is this linear_obj was originally a bridge, but was changed to a non-bridge due to length.
    See method Roads._replace_short_bridges_with_ways.
    The reason to keep a replaced_tag is that else the linear_obj might be split if a node is in the water."""
    return K_REPLACED_BRIDGE_KEY in tags


def has_embankment_or_cutting(tags_dict: t.OSMTags) -> bool:
    if K_EMBANKMENT in tags_dict and tags_dict[K_EMBANKMENT] not in [V_NO]:
        return True
    elif K_CUTTING in tags_dict and tags_dict[K_CUTTING] not in [V_NO]:
        return True
    return False


def is_underground(tags: t.OSMTags) -> bool:
    """Check in tags of the building if something looks like underground - depending on parameters."""
    if K_LOCATION in tags and tags[K_LOCATION] in (V_UNDERGROUND, V_INDOOR):
        return True
    if K_INDOOR in tags and tags[K_INDOOR] != V_NO:
        return True
    if K_TUNNEL in tags and tags[K_TUNNEL] != V_NO:
        return True
    if K_LAYER in tags and parse_int(tags[K_LAYER], 0) < 0:
        if (parse_int(tags[K_LAYER], 0) + parse_building_levels(tags)) > 0:
            return False
        return True
    return False


# ================ UTILITIES =======================

def replace_building_value(tags: t.OSMTags, new_building_value: str) -> None:
    """Replaces the value of a key:building or key:building_part."""
    if K_BUILDING in tags:
        tags[K_BUILDING] = new_building_value
    elif K_BUILDING_PART in tags:
        tags[K_BUILDING_PART] = new_building_value


# ================ UNITTESTS =======================

class TestOSMStrings(unittest.TestCase):

    def test_parse_start_date(self):
        self.assertEqual(2000, parse_date_to_year('2000'))
        self.assertEqual(2000, parse_date_to_year('2000s'))
        self.assertEqual(2000, parse_date_to_year('2000-01-04'))
        self.assertEqual(2000, parse_date_to_year('late 2000'))
        self.assertIsNone(parse_date_to_year('C16'))

    def test_is_parsable_float(self):
        self.assertFalse(is_parsable_float('1,2'))
        self.assertFalse(is_parsable_float('x'))
        self.assertTrue(is_parsable_float('1.2'))

    def test_parse_multi_int_values(self):
        self.assertEqual(99, parse_multi_int_values(' 99 '), 'Correct value to start with')
        self.assertEqual(0, parse_multi_int_values(' a'), 'Not a number')
        self.assertEqual(0, parse_multi_int_values(' ;'), 'Empty with semicolon')
        self.assertEqual(99, parse_multi_int_values(' 99.1'), 'Float')
        self.assertEqual(88, parse_multi_int_values(' 88; 4'), 'Two valid numbers')
        self.assertEqual(0, parse_multi_int_values(''), 'Empty')
