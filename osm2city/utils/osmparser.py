# SPDX-FileCopyrightText: (C) 2013 - 2026, rick@vanosten.net, radi, portree_kid
# SPDX-License-Identifier: GPL-2.0-or-later
import os
from collections import namedtuple
from enum import IntEnum, unique
import json
import logging
import multiprocessing as mp
import time
from typing import Optional
import unittest

import networkx as nx
import requests
import shapely.geometry as shg
from requests import Response

from osm2city import parameters
import osm2city.static_types.osmstrings as s
import osm2city.static_types.types as t
from osm2city.utils.coordinates import Transformation
import osm2city.utils.environment as env


PSEUDO_OSM_ID = 1  # For those nodes and ways, which get added as part of processing. Not written back to OSM.


@unique
class OSMFeatureType(IntEnum):
    building_relation = 0
    building_generated = 1
    building_owbb = 3
    landuse = 5
    road = 6
    pylon_way = 7
    generic_node = 8
    generic_way = 9


def get_next_pseudo_osm_id(osm_feature: OSMFeatureType) -> t.OSMId:
    """Constructs a pseudo id for OSM as a negative value and therefore never a real OSM value.

    Depending on which OSM feature is requesting, a different number range is returned.
    In order not to have conflicts between different processes in multiprocessing, the number range is adapted.

    In Osmosis Ids have to be sorted from low to high.
    The highest ID value will be different for each type of object (nodes, ways and relations)
    The IDs are all 64-bit signed integers at the moment, so have a theoretical limit of 2^63-1
    or 9,223,372,036,854,775,807
    See https://gis.stackexchange.com/questions/17242/what-is-the-highest-possible-value-of-osm-id
    """

    global PSEUDO_OSM_ID
    PSEUDO_OSM_ID += 1
    type_factor = 1000000000000 * osm_feature.value
    pid = mp.current_process().pid
    if not pid:
        pid = 1
    pid_factor = pid * 1000000
    return t.OSMId(-1 * (PSEUDO_OSM_ID + type_factor + pid_factor))


class OSMElement:
    __slots__ = ('osm_id', 'tags')

    def __init__(self, osm_id: t.OSMId) -> None:
        self.osm_id = osm_id
        self.tags: t.OSMTags = t.OSMTags(dict())

    def add_tag(self, key: str, value: str) -> None:
        self.tags[key] = value

    def __str__(self) -> str:
        return "<%s OSM_ID %i at %s>" % (type(self).__name__, self.osm_id, hex(id(self)))


def combine_tags(first_tags: t.OSMTags, second_tags: t.OSMTags) -> t.OSMTags:
    """Combines the tags of the first with the second, in such a way that the first wins in case of the same keys"""
    if len(second_tags) == 0:
        return t.OSMTags(dict(first_tags))
    if len(first_tags) == 0:
        return t.OSMTags(dict(second_tags))

    combined_tags = first_tags.copy()
    for key, value in second_tags.items():
        if key not in combined_tags:
            combined_tags[key] = value
    return t.OSMTags(combined_tags)


class Node(OSMElement):
    __slots__ = ('lat', 'lon', 'msl', 'v_add', 'layers', 'added_for_dist')  # the last three are written from roads.py

    def __init__(self, osm_id: t.OSMId, lat: float, lon: float, added_for_dist: bool = False) -> None:
        OSMElement.__init__(self, osm_id)
        self.lat = lat  # float value
        self.lon = lon  # float value
        # the following are mostly used in roads and linear objects/bridges
        self.msl = None  # metres above sea level (will be set by FGElev)
        self.v_add = 0.  # vertical add, such that there is some smoothness of roads despite bumpiness of FG elevation

        # If this node has been added as an extra point in roads.py to account for bumpiness of scenery.
        # This is to mark that the node can be removed, if it is rendered using shader in WS3.0
        self.added_for_dist = added_for_dist
        # For this node, which is shared among several ways: [the higher the number, the more the ways is on top])
        self.layers: dict['Way', int] = dict()

    def layer_for_way(self, way: 'Way') -> int:
        """Returns -1 if there is no entry in layers dict for the given way"""
        if way in self.layers:
            return self.layers[way]

        return -1

    @property
    def lon_lat_tuple(self) -> tuple[float, float]:
        return self.lon, self.lat

    def __str__(self):
        return 'Node with osm_id: {}'.format(self.osm_id)


class Way(OSMElement):
    __slots__ = ('refs', 'pseudo_osm_id', 'was_split_at_end', 'complementary_split_way')

    def __init__(self, osm_id: t.OSMId) -> None:
        OSMElement.__init__(self, osm_id)
        self.refs: list[t.OSMId] = list()
        self.pseudo_osm_id = 0  # can be assigned if an existing way gets split
        # if this way was split at the end - important for power lines, railway lines etc.
        # see also method split_way_at_boundary
        self.was_split_at_end = False
        # in some circumstances we want to keep a way even if the first node started outside the tile
        self.complementary_split_way = False

    def add_ref(self, ref: t.OSMId) -> None:
        self.refs.append(ref)

    def polygon_from_osm_way(self, nodes_dict: dict[t.OSMId, Node],
                             my_coord_transformator: Transformation) -> Optional[shg.Polygon]:
        """Creates a shapely polygon in local coordinates. Or None if something is not valid."""
        my_coordinates = list()
        for ref in self.refs:
            if ref in nodes_dict:
                my_node = nodes_dict[ref]
                x, y = my_coord_transformator.to_local((my_node.lon, my_node.lat))
                my_coordinates.append((x, y))
        if len(my_coordinates) >= 3:
            my_polygon = shg.Polygon(my_coordinates)
            if not my_polygon.is_valid:  # it might be self-touching or self-crossing polygons
                clean = my_polygon.buffer(0)  # cf. http://toblerity.org/shapely/manual.html#constructive-methods
                if clean.is_valid:
                    my_polygon = clean  # it is now a Polygon or a MultiPolygon
            if my_polygon.is_valid and not my_polygon.is_empty:
                return my_polygon
        return None

    def line_string_from_osm_way(self, nodes_dict: dict[t.OSMId, Node],
                                 transformer: Transformation) -> Optional[shg.LineString]:
        my_coordinates = list()
        for ref in self.refs:
            if ref in nodes_dict:
                my_node = nodes_dict[ref]
                x, y = transformer.to_local((my_node.lon, my_node.lat))
                my_coordinates.append((x, y))
        if len(my_coordinates) >= 2:
            my_geometry = shg.LineString(my_coordinates)
            if my_geometry.is_valid and not my_geometry.is_empty:
                return my_geometry
        return None

    def simplify(self, nodes_dict: dict[t.OSMId, Node], transformer: Transformation,
                 tolerance: float) -> None:
        """Simplifies a Way. The only topology that is preserved are the start and end points.
        If the way is e.g. a road and some notes inside the way are related to other roads, then those
        intersections will topologically go away, since all inner nodes will be new."""
        if len(self.refs) < 3:
            return
        # create a line_string in local coordinates
        line_string = self.line_string_from_osm_way(nodes_dict, transformer)
        # simplify it
        line_simplified = line_string.simplify(tolerance, preserve_topology=True)
        # port the simplification back
        old_refs: list[t.OSMId] = self.refs[:]
        self.refs = list()
        line_coords = list(line_simplified.coords)
        for i, x_y in enumerate(line_coords):
            if i == 0:
                self.refs.append(old_refs[0])
            elif i == len(line_coords) - 1:
                self.refs.append(old_refs[-1])
            else:
                lon, lat = transformer.to_global((x_y[0], x_y[1]))
                new_node = Node(get_next_pseudo_osm_id(OSMFeatureType.generic_node), lat, lon)
                nodes_dict[new_node.osm_id] = new_node
                self.refs.append(new_node.osm_id)

    def is_closed(self) -> bool:
        if len(self.refs) < 3:
            return False
        if self.refs[0] == self.refs[-1]:
            return True
        return False

    def __str__(self):
        return 'Way with osm_id: {}'.format(self.osm_id)


class Member:
    __slots__ = ('ref', 'type_', 'role')

    def __init__(self, ref: t.OSMId, type_: str, role: str) -> None:
        self.ref = ref
        self.type_ = type_
        self.role = role


class Relation(OSMElement):
    __slots__ = 'members'

    def __init__(self, osm_id: t.OSMId):
        OSMElement.__init__(self, osm_id)
        self.members: list[Member] = list()

    def add_member(self, member: Member) -> None:
        self.members.append(member)

    def __str__(self):
        return 'Relation with osm_id: {}'.format(self.osm_id)


def refs_to_ring(coords_transform: Transformation, refs: list[t.OSMId],
                 nodes_dict: dict[t.OSMId, Node]) -> shg.LinearRing:
    """Accept a list of OSM refs, return a linear ring."""
    coords = []
    for ref in refs:
        c = nodes_dict[ref]
        coords.append(coords_transform.to_local((c.lon, c.lat)))

    ring = shg.polygon.LinearRing(coords)
    return ring


def closed_ways_from_multiple_ways(way_parts: list[Way]) -> list[Way]:
    """Create closed ways from multiple not closed ways where possible.
    See https://wiki.openstreetmap.org/wiki/Relation:multipolygon.
    If parts of ways cannot be used, they just get disregarded.
    The new Ways gets the osm_id from a way reused and all tags removed.
    """
    closed_ways: list[Way] = list()

    graph = nx.Graph()
    for way in way_parts:
        for i in range(len(way.refs) - 1):
            graph.add_edge(way.refs[i], way.refs[i + 1])

    cycles = nx.cycle_basis(graph)
    for cycle in cycles:  # we just reuse ways - it does not really matter
        way = Way(t.OSMId(0))
        way.refs = cycle
        way.refs.append(way.refs[0])  # cycles from networkx are not closed
        closed_ways.append(way)

        # now make sure we have the original tags
        way.tags = t.OSMTags(dict())
        ways_set = set()
        for node in cycle:
            for wp in way_parts:
                if node in wp.refs:
                    ways_set.add(wp)
                    if way.osm_id == 0:
                        way.osm_id = wp.osm_id  # reuse the id from an existing way
        for wp in ways_set:
            for key, value in wp.tags.items():
                if key not in way.tags:
                    way.tags[key] = value

    return closed_ways


OSMReadResult = namedtuple("OSMReadResult", "nodes_dict, ways_dict, relations_dict, rel_nodes_dict, rel_ways_dict")


def parse_length(str_length: str) -> float:
    """
    Transform length to meters if not yet default. Input is a string, output is a float.
    If the string cannot be parsed, then 0 is returned.
    Length (and width/height) in OSM is per-default meters cf. OSM Map Features / Units.
    Possible units can be "m" (metre), "km" (kilometre -> 0.001), "mi" (mile -> 0.00062137) and
    <feet>' <inch>" (multiply feet by 12, add inches and then multiply by 0.0254).
    Theoretically there is a blank between the number and the unit, practically there might not be.
    """
    _processed = str_length.strip().lower()
    _processed = _processed.replace(',', '.')  # decimals are sometimes with comma (e.g. in European languages)
    if _processed.endswith("km"):
        _processed = _processed.rstrip("km").strip()
        _factor = 1000
    elif _processed.endswith("m"):
        _processed = _processed.rstrip("m").strip()
        _factor = 1
    elif _processed.endswith("mi"):
        _processed = _processed.rstrip("mi").strip()
        _factor = 1609.344
    elif _processed.endswith('ft'):
        _processed = _processed.rstrip('ft').strip()
        _factor = 0.3048
    elif _processed.endswith('yrd'):
        _processed = _processed.rstrip('yrd').strip()
        _factor = 0.9144
    elif "'" in _processed:
        _processed = _processed.replace('"', '')
        _split = _processed.split("'", 1)
        _factor = 0.0254
        if s.is_parsable_float(_split[0]):
            _f_length = float(_split[0])*12
            _processed = str(_f_length)
            if 2 == len(_split):
                if s.is_parsable_float(_split[1]):
                    _processed = str(_f_length + float(_split[1]))
    else:  # assumed that no unit characters are in the string
        _factor = 1.0
    if s.is_parsable_float(_processed):
        return float(_processed) * _factor
    else:
        logging.warning('Unable to parse for length from value: %s', str_length)
        return 0.0


def parse_direction(str_dir: str) -> float:
    _processed = str_dir.strip().lower()
    if _processed == 'n':
        _processed = 0.
    elif _processed == 'ne':
        _processed = 45.
    elif _processed == 'e':
        _processed = 90.
    elif _processed == 'se':
        _processed = 135.
    elif _processed == 's':
        _processed = 180.
    elif _processed == 'sw':
        _processed = 225.
    elif _processed == 'w':
        _processed = 270.
    elif _processed == 'nv':
        _processed = 315.
    if isinstance(_processed, float):
        return _processed
    elif s.is_parsable_float(_processed):
        return float(_processed)
    else:
        logging.warning('Unable to parse for direction from value: %s', str_dir)
        return 0.0


def parse_generator_output(str_output: str) -> float:
    """Transforms energy output from generators to a float value of Watt.
    See https://wiki.openstreetmap.org/wiki/Key:generator:output"""
    _processed = str_output.strip().lower()
    if _processed == "yes":
        return 0
    _factor = 0.
    if _processed.endswith("gw"):
        _processed = _processed.rstrip("gw").strip()
        _factor = 1000000000
    elif _processed.endswith("mw"):
        _processed = _processed.rstrip("mw").strip()
        _factor = 1000000
    elif _processed.endswith("kw"):
        _processed = _processed.rstrip("kw").strip()
        _factor = 1000
    elif _processed.endswith("w"):
        _processed = _processed.rstrip("w").strip()
        _factor = 1.
    if s.is_parsable_float(_processed):
        return float(_processed) * _factor
    else:
        logging.warning('Unable to parse for generator output from value: %s', str_output)
        return 0.

# ==================== Overpass API


OVERPASS_ELEMENTS = 'elements'
OVERPASS_ID = 'id'
OVERPASS_LAT = 'lat'
OVERPASS_LON = 'lon'
OVERPASS_NODE = 'node'
OVERPASS_NODES = 'nodes'
OVERPASS_TAGS = 'tags'
OVERPASS_TYPE = 'type'
OVERPASS_WAY = 'way'


def _construct_overpass_key(key: str) -> str:
    return '["{}"]'.format(key)


def _construct_overpass_key_value(key_value: tuple[str, str]) -> str:
    return '["{}"="{}"]'.format(key_value[0], key_value[1])

def _create_overpass_boundary_string() -> str:
    return '{},{},{},{}'.format(parameters.BOUNDARY_SOUTH, parameters.BOUNDARY_WEST, parameters.BOUNDARY_NORTH, parameters.BOUNDARY_EAST)


def _read_flat(required_key_values: str, read_node_tags: bool) -> OSMReadResult:
    query: str = '[out:json][bbox:{}];('.format(_create_overpass_boundary_string())
    query += required_key_values
    query += ');(._;>;);out;'
    logging.debug('read_flat Overpass QL: %s', query)
    return _query(query, read_node_tags)


def fetch_osm_data_ways_keys(req_keys: list[str]) -> OSMReadResult:
    query: str = ''
    for key in req_keys:
        query+= '{}{};'.format(OVERPASS_WAY, _construct_overpass_key(key))
    return _read_flat(query, False)


def fetch_osm_data_ways_key_values(req_key_values: list[tuple[str, str]]) -> OSMReadResult:
    query: str = ''
    for kv in req_key_values:
        query+= '{}{};'.format(OVERPASS_WAY, _construct_overpass_key_value(kv))
    return _read_flat(query, False)


def fetch_osm_nodes_isolated_keys(req_keys: list[str]) -> OSMReadResult:
    query: str = ''
    for key in req_keys:
        query+= '{}{};'.format(OVERPASS_NODE, _construct_overpass_key(key))
    return _read_flat(query, True)

def fetch_osm_nodes_isolated_key_values(req_key_values: list[tuple[str, str]]) -> OSMReadResult:
    query: str = ''
    for kv in req_key_values:
        query+= '{}{};'.format(OVERPASS_NODE, _construct_overpass_key_value(kv))
    return _read_flat(query, True)


def _make_overpass_request(query: str) -> str:
    hash_value = hash(query)
    filename = os.path.join(parameters.CACHE_DIR_O2C,
                            f'osm2city_requests_{hash_value}_{parameters.TILE_INDEX}.json')

    if parameters.CACHE_REQUESTS:
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                return f.read()

    r: Response | None = None
    success = False
    max_retries = int(env.get_env_parameter('O2C_OVERPASS_MAX_RETRIES'))
    retry_delay = float(env.get_env_parameter('O2C_OVERPASS_RETRY_DELAY'))
    retry_backoff = float(env.get_env_parameter('O2C_OVERPASS_RETRY_BACKOFF_FACTOR'))
    for retry in range(max_retries):
        try:
            r = requests.put(url=env.get_env_parameter('O2C_OVERPASS_API'), data=query, timeout=(
                int(env.get_env_parameter('O2C_OVERPASS_CONNECT_TIMEOUT')),
                int(env.get_env_parameter('O2C_OVERPASS_READ_TIMEOUT'))
            ))
            success = r.status_code == 200 or r.status_code == 203
            if not success:
                logging.warning('Calling Overpass API returned a not suitable status code: %i',
                                r.status_code)
        except requests.exceptions.RequestException as e:
            logging.warning('Calling Overpass API resulted in exception: %s', e, exc_info=True)
            success = False
        if success:
            break
        time.sleep(retry_delay)
        retry_delay *= retry_backoff
        logging.warning('Retrying Overpass API after problem')

    if not success:
        raise RuntimeError('Unable to get a valid result from Overpass API - giving up after {} retries'.format(max_retries))

    text = r.text if r and r.text is not None else ''

    if parameters.CACHE_REQUESTS:
        with open(filename, 'w') as f:
            f.write(text)

    return text

def _query(query: str, read_node_tags: bool) -> OSMReadResult:
    text = _make_overpass_request(query)

    ways_dict: dict[t.OSMId, Way] = dict()
    nodes_dict: dict[t.OSMId, Node] = dict()

    if text.strip() and not text.startswith('<?xml'): # empty string and whitespace can still result in json.JSONDecodeError
        json_result = json.loads(text)
        for element in json_result[OVERPASS_ELEMENTS]:
            osm_id = element[OVERPASS_ID]
            tags: t.OSMTags = t.OSMTags(dict())
            read_tags = True
            if element[OVERPASS_TYPE] == OVERPASS_NODE and read_node_tags is False:
                read_tags = False
            if read_tags and OVERPASS_TAGS in element:
                for key, val in element[OVERPASS_TAGS].items():
                    tags[key] = val

            if element[OVERPASS_TYPE] == OVERPASS_NODE:
                node = Node(osm_id, element[OVERPASS_LAT], element[OVERPASS_LON])
                node.tags = tags
                nodes_dict[node.osm_id] = node
            if element[OVERPASS_TYPE] == OVERPASS_WAY:
                way = Way(osm_id)
                way.tags = tags
                way.refs = element[OVERPASS_NODES]
                ways_dict[way.osm_id] = way

    return OSMReadResult(nodes_dict=nodes_dict, ways_dict=ways_dict,
                         relations_dict=None, rel_nodes_dict=None, rel_ways_dict=None)


# ============== Other stuff

def split_way_at_boundary(nodes_dict: dict[t.OSMId, Node], original_way: Way, clipping_border: shg.Polygon,
                          osm_feature: OSMFeatureType) -> list[Way]:
    """Splits a way (e.g. road) at the clipping border into 0 to n ways.
    See also explanation/scenario in the method 'complementary_split_way_at_boundary'.
    A way can be totally inside a boundary, totally outside a boundary, intersect one or several times.
    Splitting is tested at existing nodes of the way. A split way's first node is always inside the boundary.
    A split way's last point can be inside the boundary (the last node of the original way) or
    the first node outside the boundary (such that across tile boundaries there is a continuation)."""
    resulting_split_ways = list()
    next_split_way = Way(original_way.osm_id)  # the first (and maybe only) way does not get a pseudo_id
    next_split_way.tags = original_way.tags
    previous_inside = False
    for node_ref_in_original_way in original_way.refs:
        current_node = nodes_dict[node_ref_in_original_way]
        if clipping_border.contains(shg.Point(current_node.lon, current_node.lat)):
            next_split_way.refs.append(node_ref_in_original_way)
            previous_inside = True
        else:  # we are now outside the clipping area
            if previous_inside:
                next_split_way.refs.append(node_ref_in_original_way)
                next_split_way.was_split_at_end = True
                if len(next_split_way.refs) >= 2:
                    resulting_split_ways.append(next_split_way)

                # now make a new possible next_split_way for other refs - starting from this one
                next_split_way = Way(original_way.osm_id)
                next_split_way.tags = original_way.tags
                next_split_way.pseudo_osm_id = get_next_pseudo_osm_id(osm_feature)
                previous_inside = False
            # nothing to do if previous also outside - we just discard it

    if len(next_split_way.refs) >= 2:
        resulting_split_ways.append(next_split_way)
    return resulting_split_ways


def complementary_split_way_at_boundary(nodes_dict: dict[t.OSMId, Node], original_way: Way, clipping_border: shg.Polygon,
                                        osm_feature: OSMFeatureType) -> list[Way]:
    """See the method 'split_way_at_boundary'.
    Immagine a Way with point A in the tile U, point B in tile V, point C in tile V, point D
    in tile U gain and finally point E in tile V.
    This would result in a Way(A->B) plus Way(D->E) when processing tile U and a Way(B->C->D) in tile V.
    So everything is covered.
    However, in WS3.0 the linear features for roads/railways etc. get clipped at the tile border in SimGear, so
    we would actually only have Way(A->cut before B), Way(D->E) and Way(B->C->cut before D).
    Therefore, we need to also have all the Ways being cut at the boundary on when processing the other side
    of the tile, i.e. for tile U we also need Way(C->D), which then gets to Way(cut before D, D), and
    for tile V we also need Way(A->B), which then gets to Way(cut before B, B)."""
    resulting_complementary_ways = list()
    last_ref_outside = None
    previous_inside = False
    for node_ref_in_original_way in original_way.refs:
        current_node = nodes_dict[node_ref_in_original_way]
        if clipping_border.contains(shg.Point(current_node.lon, current_node.lat)):
            if previous_inside is False and last_ref_outside is not None:
                next_split_way = Way(original_way.osm_id)
                next_split_way.refs.append(last_ref_outside)
                next_split_way.refs.append(node_ref_in_original_way)
                next_split_way.pseudo_osm_id = get_next_pseudo_osm_id(osm_feature)
                next_split_way.complementary_split_way = True
                resulting_complementary_ways.append(next_split_way)
            previous_inside = True
            last_ref_outside = None
        else:  # we are now outside the clipping area
            last_ref_outside = node_ref_in_original_way
            previous_inside = False

    return resulting_complementary_ways


# ================ UNITTESTS =======================

class TestOSMParser(unittest.TestCase):
    def test_parse_length(self):
        self.assertAlmostEqual(1.2, parse_length(' 1.2 '), 2, "Correct number with trailing spaces")
        self.assertAlmostEqual(1.2, parse_length(' 1,2 '), 2, "Correct number with comma as decimal separator")
        self.assertAlmostEqual(1.2, parse_length(' 1.2 m'), 2, "Correct number with meter unit incl. space")
        self.assertAlmostEqual(1.2, parse_length(' 1.2m'), 2, "Correct number with meter unit without space")
        self.assertAlmostEqual(1200., parse_length(' 1.2 km'), 2, "Correct number with km unit incl. space")
        self.assertAlmostEqual(2092.1472, parse_length(' 1.3mi'), 2, "Correct number with mile unit without space")
        self.assertAlmostEqual(3.048, parse_length("10'"), 2, "Correct number with feet unit without space")
        self.assertAlmostEqual(3.073, parse_length('10\'1"'), 2, "Correct number with feet unit without space")
        self.assertEqual(0, parse_length('m'), "Only valid unit")
        self.assertEqual(0, parse_length('"'), "Only inches, no feet")

    def test_parse_direction(self):
        self.assertAlmostEqual(180.0, parse_direction('s '), 2)
        self.assertAlmostEqual(125.5, parse_direction(' 125.5 '), 2)
        self.assertAlmostEqual(0.0, parse_direction(' foo '), 2)

    def test_parse_generator_output(self):
        self.assertAlmostEqual(0., parse_generator_output(' 2.3 '), 2, "Correct number with trailing spaces")
        self.assertAlmostEqual(2.3, parse_generator_output(' 2.3 W'), 2, "Correct number with Watt unit incl. space")
        self.assertAlmostEqual(2.3, parse_generator_output('2.3W'), 2, "Correct number with Watt unit without space")
        self.assertAlmostEqual(2300., parse_generator_output(' 2.3 kW'), 2, "Correct number with kW unit incl. space")
        self.assertAlmostEqual(2300000., parse_generator_output(' 2.3 MW'), 2, "Correct number with MW unit incl. space")
        self.assertAlmostEqual(300000000., parse_generator_output(' 0.3GW'), 2, "Correct number with GW unit w/o space")
        self.assertAlmostEqual(0., parse_generator_output(' 0.3 XW'), 2, "Correct number with unknown unit")

    def test_closed_ways_from_multiple_ways(self):
        way_unrelated = Way(t.OSMId(1))
        way_unrelated.refs = [t.OSMId(90), t.OSMId(91)]

        way_no_ring0 = Way(t.OSMId(2))
        way_no_ring0.refs = [t.OSMId(80), t.OSMId(81), t.OSMId(82)]
        way_no_ring1 = Way(t.OSMId(3))
        way_no_ring1.refs = [t.OSMId(80), t.OSMId(83)]

        way_a_0 = Way(t.OSMId(4))
        way_a_0.refs = [t.OSMId(1), t.OSMId(2), t.OSMId(3), t.OSMId(4)]
        way_a_0.tags = t.OSMTags({'ring0': 'a_0', 'building': 'yes'})
        way_a_1 = Way(t.OSMId(5))
        way_a_1.refs = [t.OSMId(4), t.OSMId(5), t.OSMId(6), t.OSMId(1)]
        way_a_1.tags = t.OSMTags({'ring1': 'a_1', 'building': 'yes'})

        way_b_0 = Way(t.OSMId(6))
        way_b_0.refs = [t.OSMId(11), t.OSMId(12), t.OSMId(13), t.OSMId(14)]
        way_b_0.tags = t.OSMTags({'ring0': 'b_0', 'building': 'yes'})
        way_b_1 = Way(t.OSMId(7))
        way_b_1.refs = [t.OSMId(16), t.OSMId(15), t.OSMId(14)]
        way_b_1.tags = t.OSMTags({'ring1': 'b_1', 'building': 'yes'})
        way_b_2 = Way(t.OSMId(8))
        way_b_2.refs = [t.OSMId(16), t.OSMId(17), t.OSMId(18), t.OSMId(11)]
        way_b_2.tags = t.OSMTags({'ring2': 'b_2', 'building': 'yes'})

        closed_ways = closed_ways_from_multiple_ways([way_b_0, way_a_1, way_unrelated, way_a_0, way_b_2, way_no_ring1,
                                                      way_b_1, way_no_ring0])
        self.assertEqual(2, len(closed_ways))

    def test_combine_tags(self):
        first_dict = t.OSMTags({'1': '1', '2': '2', '3': '3'})
        second_dict = t.OSMTags({'3': '99', '4': '4'})
        combined_tags = combine_tags(first_dict, second_dict)
        self.assertEqual(4, len(combined_tags))
