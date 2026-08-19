# SPDX-FileCopyrightText: (C) 2020 - 2025, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later

"""Different enumerations used throughout the code.

Different modules can still define their own enums, but then they
shall not be used across module boundaries.
"""

from enum import unique, Enum, IntEnum
import logging
from typing import Union

from osm2city.static_types import osmstrings as s
from osm2city.static_types import types as t
import osm2city.textures.road as r



@unique
class ArchitectureStyle(IntEnum):
    """https://wiki.openstreetmap.org/wiki/Key:building:architecture"""
    romanesque = 1
    gothic = 2
    unknown = 99


@unique
class WorshipBuildingType(IntEnum):
    """See https://wiki.openstreetmap.org/wiki/Key:building or
    https://wiki.openstreetmap.org/wiki/Tag:building%3Dchurch

    Cathedral is not supported, because too close to church in shared models etc. Size of the building should be enough.
    """
    church = 10
    # not supportedOSM value = cathedral
    chapel = 12
    church_orthodox = 20  # not official tag - just to make it easier to distinguish from catholic / protestant
    mosque = 40
    synagogue = 50
    temple = 60
    shrine = 70


def deduct_worship_building_type(tags: t.OSMTags) -> WorshipBuildingType | None:
    """Return a type if the building is a worship building, Otherwise return None."""
    worship_building_type = None
    if tags[s.K_BUILDING] == s.V_CATHEDRAL:
        tags[s.K_BUILDING] = s.V_CHURCH
    try:
        worship_building_type = WorshipBuildingType.__members__[tags[s.K_BUILDING]]
    except KeyError:  # e.g. building=yes
        if s.K_AMENITY in tags and tags[s.K_AMENITY] == s.V_PLACE_OF_WORSHIP:
            if s.K_RELIGION in tags and tags[s.K_RELIGION] == s.V_CHRISTIAN:
                worship_building_type = WorshipBuildingType.church
                if s.K_DENOMINATION in tags and tags[s.K_DENOMINATION].find(s.V_ORTHODOX) > 0:
                    worship_building_type = WorshipBuildingType.church_orthodox
    return worship_building_type


@unique
class BuildingParentType(IntEnum):
    """Translated from osm2gear"""
    osm_simple_3d = 1
    pseudo_simple_3d = 2
    pseudo_row = 90


@unique
class BuildingClass(IntEnum):
    """Used to classify buildings for processing on zone level and defining height per level in some cases"""
    residential = 100
    residential_small = 110
    shed = 119  # includes garage
    terrace = 120
    apartments = 130
    commercial = 200
    retail = 300
    retail_mall = 301
    supermarket = 302
    industrial = 400
    industrial_old = 401
    industrial_other = 402
    warehouse = 410
    warehouse_old = 411
    data_centre = 420
    parking_house = 1000
    religion = 2000
    public = 3000
    farm = 4000
    airport = 5000
    undefined = 9999  # mostly because BuildingType can only be approximated to "yes"


@unique
class BuildingType(IntEnum):
    """Mostly match the value of a tag with k=building.
    If changed, then also check use in get_building_class() as well as is_...() methods in osmstrings.py.

    If value is > 1000 then it means that the name of the enum is not existing in OSM -> artificial in osm2city
    """
    yes = 1  # default
    parking = 10  # k="parking" v="multi-storey" or k="building" v="parking"
    apartments = 21
    attached = 210  # an apartment in a city block without space between buildings. Does not exist in OSM
    house = 22
    detached = 23
    residential = 24
    dormitory = 25
    terrace = 26
    bungalow = 31
    static_caravan = 32
    cabin = 33
    hut = 34
    garage = 38
    shed = 39
    commercial = 41
    office = 42
    retail = 51
    retail_mall = 9052  # if not tagged with building=retail but has shop=mall on Way level. Or has several levels
    supermarket = 53
    industrial = 61  # if tagged as such or with man_made = works and building:levels < 1.1
    # *_old below for industrial and warehouse means that
    #     * either start_date is before 1950
    #     * or building:material in (brick, stones, wood)
    # (roof shape is not seen as a reliable indicator for old [e.g. gabled]).
    industrial_old = 9062  # can have several levels
    industrial_other = 9063  # if tagged as industrial with building:levels >= 1.1 but not old
    warehouse = 65  # default warehouse with loading docks and high-level racks
    warehouse_old = 9066  # warehouse from the past tagged with several levels and/or roof:shape != flat or "old"
    data_centre = 67  # tagged with building=data_center or telecom=data_center or telecom=data_centre
    cathedral = 71
    chapel = 72
    church = 73
    mosque = 74
    temple = 75
    synagogue = 76
    public = 81
    civic = 82
    school = 83
    hospital = 84
    hotel = 85
    farm = 101
    barn = 102
    cowshed = 103
    farm_auxiliary = 104
    greenhouse = 105
    glasshouse = 106
    stable = 107
    sty = 108
    riding_hall = 109
    slurry_tank = 110
    hangar = 201
    stadium = 301
    sports_hall = 302


def parse_building_tags_for_type(tags_dict: t.OSMTags,
                                 building_area: float | None = None) -> Union[None, BuildingType]:
    # special for parking
    if s.has_key_value_pair(s.K_PARKING, s.V_MULTISTOREY, tags_dict):
        return BuildingType.parking

    # all others
    value = None
    if s.K_BUILDING in tags_dict:
        value = tags_dict[s.K_BUILDING]
    elif s.K_BUILDING_PART in tags_dict:
        value = tags_dict[s.K_BUILDING_PART]
    if value is None:
        return None

    # we know it is a building
    my_type = BuildingType.yes
    for member in BuildingType:
        if value == member.name:
            my_type = member
            break

    # now treat special cases - the sequence of checks is significant!
    if my_type is not BuildingType.retail:
        if s.has_key_value_pair(s.K_SHOP, s.V_MALL, tags_dict):
            my_type = BuildingType.retail_mall
    if my_type is BuildingType.retail:
        if s.parse_building_levels(tags_dict) >= 1.5:
            my_type = BuildingType.retail_mall
        elif building_area is not None and building_area < BUILDING_MIN_AREA_ONE_LEVEL_LARGE_BUILDING_CLASS:
            my_type = BuildingType.retail_mall

    if my_type is BuildingType.supermarket:
        if building_area is not None and building_area < BUILDING_MIN_AREA_ONE_LEVEL_LARGE_BUILDING_CLASS:
            my_type = BuildingType.retail_mall

    if my_type is not BuildingType.industrial:
        if s.has_key_value_pair(s.K_MAN_MADE, s.V_WORKS, tags_dict):
            my_type = BuildingType.industrial
    if my_type is BuildingType.industrial:
        if s.parse_is_building_oldish(tags_dict):
            my_type = BuildingType.industrial_old
        elif s.parse_building_levels(tags_dict) > 1.1:
            my_type = BuildingType.industrial_other
        elif building_area is not None and building_area < BUILDING_MIN_AREA_ONE_LEVEL_LARGE_BUILDING_CLASS:
            my_type = BuildingType.industrial_other

    if my_type is BuildingType.warehouse:
        if s.parse_is_building_oldish(tags_dict):
            my_type = BuildingType.warehouse_old
        elif s.parse_building_levels(tags_dict) > 1.1:
            my_type = BuildingType.warehouse_old
        elif building_area is not None and building_area < BUILDING_MIN_AREA_ONE_LEVEL_LARGE_BUILDING_CLASS:
            my_type = BuildingType.warehouse_old

    if my_type is not BuildingType.data_centre:
        if s.has_key_value_pair(s.K_TELECOM, s.V_DATA_CENTER, tags_dict) or s.has_key_value_pair(s.K_TELECOM,
                                                                                                 s.V_DATA_CENTRE,
                                                                                                 tags_dict):
            my_type = BuildingType.data_centre
    if my_type is BuildingType.data_centre:
        if building_area is not None and building_area < BUILDING_MIN_AREA_ONE_LEVEL_LARGE_BUILDING_CLASS:
            my_type = BuildingType.industrial_other

    return my_type


def get_building_class(tags: t.OSMTags, building_area: float | None = None) -> BuildingClass:
    """Calculates the building type and then determines the building class.
    Should only be called for land-use guess and then once in building analysis, where it gets stored for
    further processing in a member variable.
    """
    type_ = parse_building_tags_for_type(tags, building_area)
    if type_ is None:
        return BuildingClass.undefined
    if type_ in [BuildingType.house, BuildingType.detached, BuildingType.residential]:
        return BuildingClass.residential
    elif type_ in [BuildingType.bungalow, BuildingType.static_caravan, BuildingType.cabin, BuildingType.hut]:
        return BuildingClass.residential_small
    elif type_ in [BuildingType.garage, BuildingType.shed]:
        return BuildingClass.shed
    elif type_ in [BuildingType.apartments, BuildingType.dormitory, BuildingType.hotel]:
        return BuildingClass.apartments
    elif type_ in [BuildingType.terrace]:
        return BuildingClass.terrace
    elif type_ in [BuildingType.commercial, BuildingType.office]:
        return BuildingClass.commercial
    elif type_ in [BuildingType.retail]:
        return BuildingClass.retail
    elif type_ in [BuildingType.retail_mall]:
        return BuildingClass.retail_mall
    elif type_ in [BuildingType.supermarket]:
        return BuildingClass.supermarket
    elif type_ in [BuildingType.industrial]:
        return BuildingClass.industrial
    elif type_ in [BuildingType.industrial_old]:
        return BuildingClass.industrial_old
    elif type_ in [BuildingType.industrial_other]:
        return BuildingClass.industrial_other
    elif type_ in [BuildingType.warehouse]:
        return BuildingClass.warehouse
    elif type_ in [BuildingType.warehouse_old]:
        return BuildingClass.warehouse_old
    elif type_ in [BuildingType.data_centre]:
        return BuildingClass.data_centre
    elif type_ in [BuildingType.parking]:
        return BuildingClass.parking_house
    elif type_ in [BuildingType.cathedral, BuildingType.chapel, BuildingType.church,
                   BuildingType.mosque, BuildingType.temple, BuildingType.synagogue]:
        return BuildingClass.religion
    elif type_ in [BuildingType.public, BuildingType.civic, BuildingType.school, BuildingType.hospital]:
        return BuildingClass.public
    elif type_ in [BuildingType.farm, BuildingType.barn, BuildingType.cowshed, BuildingType.farm_auxiliary,
                   BuildingType.greenhouse, BuildingType.stable, BuildingType.sty, BuildingType.riding_hall,
                   BuildingType.slurry_tank]:
        return BuildingClass.farm
    elif type_ in [BuildingType.hangar]:
        return BuildingClass.airport
    return BuildingClass.undefined  # the default / fallback, e.g. for "yes"


@unique
class SettlementType(IntEnum):
    """Values must be the same as in enumerations::SettlementType. See also documentation there."""
    centre = 9
    block = 8
    dense = 7
    periphery = 6
    rural = 5


class TreeOrigin(IntEnum):
    mapped = 1
    park = 2
    garden = 3


class TreeType(Enum):
    """The tree type needs to correspond to the available types in the FG material for (OSM) trees."""
    default = 'DeciduousBroadCover'  # a typical full-grown tree for the region - larger than a house.

    # used for gardens
    suburban = 'SubUrban'
    town = 'Town'
    urban = 'Urban'


def map_tree_type_from_settlement_type_garden(s_type: SettlementType) -> TreeType:
    if s_type is None:
        return TreeType.suburban
    elif s_type in (SettlementType.centre, SettlementType.block):
        return TreeType.urban
    elif s_type is SettlementType.dense:
        return TreeType.town
    else:
        return TreeType.suburban


@unique
class RoofShape(IntEnum):
    """Matches the roof:shape in OSM, see https://wiki.openstreetmap.org/wiki/Simple_3D_buildings.

    Some of the OSM types might not be directly supported and are mapped to a different type,
    which actually is supported in osm2city.

    The enumeration should match what is provided in roofs.py and referenced in _write_roof_for_ac().

    The values need to correspond to the S value in FG BUILDING_LIST
    """
    flat = 0
    skillion = 1
    gabled = 2
    half_hipped = 3
    hipped = 4
    pyramidal = 5
    gambrel = 6
    mansard = 7
    dome = 8
    onion = 9
    round = 10
    saltbox = 11
    separate_gable_with_corner = 88  # does not exist in OSM - special case
    skeleton = 99  # does not exist in OSM


def map_osm_roof_shape(osm_roof_shape: str) -> RoofShape:
    """Maps OSM roof:shape tag to supported types in osm2city.

    See https://wiki.openstreetmap.org/wiki/Simple_3D_buildings#Roof_shape"""
    _shape = osm_roof_shape.strip()
    if len(_shape) == 0:
        return RoofShape.flat
    if _shape == s.V_FLAT:
        return RoofShape.flat
    if _shape in [s.V_SKILLION, s.V_LEAN_TO, s.V_SHED]:
        return RoofShape.skillion
    if _shape in [s.V_GABLED, s.V_HALF_HIPPED, s.V_SALTBOX, s.V_PITCHED]:
        return RoofShape.gabled
    if _shape in [s.V_GAMBREL, s.V_ROUND]:
        return RoofShape.gambrel
    if _shape in [s.V_HIPPED, s.V_MANSARD]:
        return RoofShape.hipped
    if _shape == s.V_PYRAMIDAL:
        return RoofShape.pyramidal
    if _shape == s.V_DOME:
        return RoofShape.dome
    if _shape == s.V_ONION:
        return RoofShape.onion

    # fall back for all not directly handled OSM types. The rationale for using "hipped" as default is that most
    # probably if someone actually has tried to specify a shape, then 'flat' is unlikely to be misspelled and
    # most probably a form with a ridge was meant.
    logging.debug('Not handled roof shape found: %s. Therefore transformed to "hipped".', _shape)
    return RoofShape.hipped


@unique
class PlaceType(IntEnum):
    """See https://wiki.openstreetmap.org/wiki/Key:place - only used for city and town as well as farm.
    Rest is ignored - including:
    * isolated_dwelling and allotments -> too small
    * borough: administrative and very few mappings
    * quarter; not used much in OSM and might be better off just using neighbourhood in osm2city
    * city_block and plot: too small
    """
    city = 10
    town = 20
    farm = 50  # only type allowed to remain as area as it is used to recognise land-use type


@unique
class BuildingZoneType(IntEnum):
    """The land-use type as calculated in osm2gear. See documentation in enumerations::BuildingZoneType
    The numerical values must be the same as in osm2gear, because it will be mapped from there.
    """
    aerodrome = 1
    port = 2
    industrial = 3
    retail = 4
    farmyard = 5
    commercial = 6
    residential = 7
    military = 8

    non_osm = 20
    special_processing = 30

    # FlightGear in BTG files
    # must be in line with SUPPORTED_MATERIALS in btg_io.py (except from water)
    btg_builtupcover = 201
    btg_urban = 202
    btg_town = 211
    btg_suburban = 212
    btg_construction = 221
    btg_industrial = 222
    btg_port = 223


@unique
class HighwayType(IntEnum):
    """Highway types the numbers need to be higher for priority - e.g. for layering.
    _link types are only for the situation, when they are one-way (which they do not have to be
    cf. https://wiki.openstreetmap.org/wiki/Highway_link.)
    A _link stays the same as its highway counterpart unless it is one-way. And if it is a motorway or trunk
    link, then it is downgraded to a primary road.

    https://gitlab.com/osm2city/osm2city/-/issues/127: there are options missing, which is way some highways
    are crammed into one type
    """
    roundabout = 16
    motorway = 15  # not one-way = seldom
    trunk = 14
    primary = 13  # can also be a non-one-way motorway link, trunk link or primary link
    secondary = 12  # can also be a non-one-way secondary link
    tertiary = 11  # can also be a non-one-way tertiary link
    unclassified = 10
    road = 9
    one_way_multi_lane = 8  # for now assumed to be 2 lanes
    one_way_large = 7  # for one-way links of motorway and trunk
    one_way_normal = 6
    residential = 5
    living_street = 4
    service = 3
    pedestrian = 2
    slow = 1  # cycle ways, tracks, footpaths etc.


def highway_type_from_osm_tags(tags: t.OSMTags) -> HighwayType | None:
    """Based on OSM tags deducts the HighwayType.
    Returns None if not a highway or unknown value.
    """
    if s.K_HIGHWAY in tags:
        value = tags[s.K_HIGHWAY]
    else:
        return None

    if s.is_roundabout(tags):
        return HighwayType.roundabout

    if s.is_oneway(tags):
        if s.parse_tags_lanes(tags) > 1:
            return HighwayType.one_way_multi_lane
        if value in [s.V_TRUNK, s.V_MOTORWAY_LINK, s.V_TRUNK_LINK]:
            return HighwayType.one_way_large
        else:
            return HighwayType.one_way_normal

    # now we can assume it is not one-way
    if value in [s.V_MOTORWAY]:
        return HighwayType.motorway
    elif value in [s.V_TRUNK]:
        return HighwayType.trunk
    elif value in [s.V_PRIMARY, s.V_PRIMARY_LINK, s.V_MOTORWAY_LINK, s.V_TRUNK_LINK]:
        return HighwayType.primary
    elif value in [s.V_SECONDARY, s.V_SECONDARY_LINK]:
        return HighwayType.secondary
    elif value in [s.V_TERTIARY, s.V_TERTIARY_LINK]:
        return HighwayType.tertiary
    elif value == s.V_UNCLASSIFIED:
        return HighwayType.unclassified
    elif value == s.V_ROAD:
        return HighwayType.road
    elif value == s.V_RESIDENTIAL:
        return HighwayType.residential
    elif value == s.V_LIVING_STREET:
        return HighwayType.living_street
    elif value == s.V_SERVICE:
        return HighwayType.service
    elif value == s.V_PEDESTRIAN:
        return HighwayType.pedestrian
    elif value in [s.V_TRACK, s.V_FOOTWAY, s.V_CYCLEWAY, s.V_BRIDLEWAY, s.V_STEPS, s.V_PATH]:
        return HighwayType.slow
    else:
        return None


@unique
class RailwayType(IntEnum):
    normal = 5
    narrow = 3
    light = 1


def railway_type_from_osm_tags(tags: t.OSMTags, use_tram_lines: bool) -> RailwayType | None:
    """Based on OSM tags deducts the RailwayType.
    Returns None if not a railway or not used or an unknown value.

    See also RailwayLineType in models.py (not used here)

    Not taken into account:
    * abandoned
    * construction
    * funicular
    * miniature
    * monorail
    """
    if s.K_RAILWAY in tags:
        value = tags[s.K_RAILWAY]
    else:
        return None

    if value in [s.V_RAIL, s.V_DISUSED, s.V_PRESERVED, s.V_SUBWAY]:
        # disused != abandoned cf. https://wiki.openstreetmap.org/wiki/Key:abandoned:
        return RailwayType.normal
    elif value in [s.V_NARROW_GAUGE]:
        return RailwayType.narrow
    elif value in [s.V_LIGHT_RAIL]:
        return RailwayType.light
    elif use_tram_lines and value == s.V_TRAM:
        return RailwayType.light
    else:
        return None


def _calc_railway_gauge(tags: t.OSMTags) -> float:
    """Based on railway tags determine the width in meters (3.18 meters for normal gauge)."""
    width = 1435  # millimeters
    if tags[s.K_RAILWAY] in [s.V_NARROW_GAUGE]:
        width = 1000
    if s.K_GAUGE in tags:
        if s.is_parsable_float(tags[s.K_GAUGE]):
            width = float(tags[s.K_GAUGE])
    return width / 1000 * 128 / 57  # in the texture roads.png the track uses 57 out of 128 pixels


def get_railway_attributes(railway_type: RailwayType, tags: t.OSMTags) -> tuple[tuple[float, float], float, str]:
    if railway_type is RailwayType.normal:
        tex = r.TRACK
    elif railway_type is RailwayType.narrow:
        tex = r.TRACK  # FIXME: should use proper narrow texture
    else:
        tex = r.TRAMWAY
    return tex, _calc_railway_gauge(tags), 'ws30Railway'


def get_highway_attributes(highway_type: HighwayType) -> tuple[tuple[float, float], float, str]:
    """This must be aligned with enumerations.HighwayType as well as textures.road and
    linear_transportation.create_linear_objects."""
    material_type = 'ws30Road'
    if highway_type is HighwayType.roundabout:
        tex = r.ROAD_1
        width = 6.
    elif highway_type is HighwayType.motorway:
        tex = r.ROAD_2
        width = 6.
    elif highway_type in [HighwayType.primary, HighwayType.trunk]:
        tex = r.ROAD_2
        width = 6.
    elif highway_type in [HighwayType.secondary]:
        tex = r.ROAD_2
        width = 6.
    elif highway_type in [HighwayType.tertiary, HighwayType.unclassified, HighwayType.road]:
        tex = r.ROAD_1
        width = 6.
    elif highway_type in [HighwayType.one_way_multi_lane]:
        tex = r.ROAD_3  # fake now because texture/shader not available
        width = 6.
        material_type = 'ws30Freeway'
    elif highway_type in [HighwayType.one_way_large]:
        tex = r.ROAD_1  # fake now because texture/shader not available
        width = 4.
    elif highway_type in [HighwayType.one_way_normal]:
        tex = r.ROAD_1  # fake now because texture/shader not available
        width = 3.
    elif highway_type in [HighwayType.residential, HighwayType.service]:
        tex = r.ROAD_1
        width = 4.
    else:
        tex = r.ROAD_1
        width = 4.
    return tex, width, material_type


@unique
class LitType(IntEnum):
    yes = 0
    no = 1
    unknown = 2


# ================================ CONSTANTS =========================================
# Should not be changed unless all dependencies have been thoroughly checked.

# The height per level. This value should not be changed unless special textures are used.

# For settlement types ``centre``, ``block`` and ``dense``.
# If a building is of class ``commercial``, ``retail``, ``public`` or
# ``parking_house``, then this height is always used.
BUILDING_LEVEL_HEIGHT_URBAN = 3.5

BUILDING_LEVEL_HEIGHT_RURAL = 2.5  # ditto including periphery and rural

BUILDING_LEVEL_HEIGHT_RETAIL = 6.  # 1 level only
BUILDING_LEVEL_HEIGHT_RETAIL_MALL = 4.  # potentially multiple levels
BUILDING_LEVEL_HEIGHT_SUPERMARKET = 8.  # 1 level only
BUILDING_LEVEL_HEIGHT_INDUSTRIAL = 8.  # 1 level only
BUILDING_LEVEL_HEIGHT_INDUSTRIAL_OLD = 4.  # potentially multiple levels
BUILDING_LEVEL_HEIGHT_INDUSTRIAL_OTHER = 4.  # potentially multiple levels
BUILDING_LEVEL_HEIGHT_WAREHOUSE = 12.  # 1 level only
BUILDING_LEVEL_HEIGHT_WAREHOUSE_OLD = 4.  # potentially multiple levels
BUILDING_LEVEL_HEIGHT_DATA_CENTRE = 10.  # 1 level only


# For certain large BuildingClasses with only 1 level make sure there is a minimum size of area
# e.g. retail, supermarket, industry, warehouse, data_centre
BUILDING_MIN_AREA_ONE_LEVEL_LARGE_BUILDING_CLASS = 2000  # because parameters is not available here
