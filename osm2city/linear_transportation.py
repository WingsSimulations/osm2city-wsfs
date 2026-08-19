# SPDX-FileCopyrightText: (C) 2014 - 2025, rick@vanosten.net, radi, portree_kid
# SPDX-License-Identifier: GPL-2.0-or-later

from collections import OrderedDict
import gzip
import logging
import math
import multiprocessing.synchronize as mps
from operator import itemgetter
import os.path as osp
import random
from typing import MutableMapping, Optional, Tuple
import unittest

import networkx as nx
import numpy as np
import shapely.geometry as shg

from osm2city import parameters, linear, plotting
import osm2city.pylons as po
from osm2city.static_types import enumerations as e
from osm2city.static_types import osmstrings as s
from osm2city.static_types import types as t
from osm2city.textures import materials as mat
import osm2city.utils.osmparser as op
from osm2city.utils import ac3d, stg_io2, utilities
import osm2city.utils.coordinates as co
import osm2city.utils.elev_probe as ep

OUR_MAGIC = "osm2transportation"  # Used in e.g. stg files to mark our edits


class Junction(object):
    """store attached ways, joint_node indices
       current usage of attached_ways_dict:
          for the_ref, ways_list in attached_ways_dict.items()
          -> for the_ref, the_junction in attached_ways_dict.items()
          for ref in self.attached_ways_dict
          -> unchanged
          for linear_obj, boolean in self.attached_ways_dict[the_ref]:
          -> junction = self.attached_ways_dict[the_ref].attached_ways
          OR __items__()
          for ref, ways_tuple_list in self.attached_ways_dict.iteritems()
          -> for ref, junction in self.attached_ways_dict.iteritems():
               junction.attached_ways
    -
    """

    def __init__(self, way, is_first, joint_nodes=None):
        self._attached_ways = [way]
        self._is_first = [is_first]
        if joint_nodes is None:
            joint_nodes = list()
        self.joint_nodes = joint_nodes  # list of tuples -- unused?
        self._left_node = None
        self._right_node = None
        self.reset()

    def reset(self):
        self._left_node = None
        self._right_node = None

    def __len__(self):
        return len(self._attached_ways)

    def append_way(self, way, is_first):
        self._attached_ways.append(way)
        self._is_first.append(is_first)

    def _use_left_node(self, way, is_left):
        i = self._attached_ways.index(way)
        assert (i == 0 or i == 1)
        return (i + self._is_first[i] + is_left) % 2 == 0

    def get_other_node(self, way, is_left: bool):
        if self._use_left_node(way, is_left):
            if self._left_node is None:
                raise KeyError
            return self._left_node
        else:
            if self._right_node is None:
                raise KeyError
            return self._right_node

    def set_other_node(self, way, is_left, node):
        """We also store cluster reference to avoid using nodes from other clusters"""
        if self._use_left_node(way, is_left):
            if self._left_node is not None:
                raise ValueError("other node already set")
            self._left_node = node
        else:
            if self._right_node is not None:
                raise ValueError("other node already set")
            self._right_node = node


LINEAR_OBJECT_ATTRIBUTE = 'obj'


class Graph(nx.Graph):
    """Inherit from nx.Graph, make accessing graph node attribute (Junction) easier"""

    def junction(self, the_ref: t.OSMId):
        """return object attached to node"""
        return self.nodes[the_ref][LINEAR_OBJECT_ATTRIBUTE]

    def add_linear_object_edge(self, linear_obj: linear.LinearObject):
        ref_first_node = linear_obj.way.refs[0]
        ref_last_node = linear_obj.way.refs[-1]
        try:
            junction0 = self.junction(ref_first_node)
            junction0.append_way(linear_obj, is_first=True)
        except KeyError:
            junction0 = Junction(linear_obj, is_first=True)  # IS_FIRST
            super().add_node(ref_first_node, obj=junction0)

        try:
            junction1 = self.junction(ref_last_node)
            junction1.append_way(linear_obj, is_first=False)
        except KeyError:
            junction1 = Junction(linear_obj, is_first=False)
            super().add_node(ref_last_node, obj=junction1)

        super().add_edge(ref_first_node, ref_last_node, obj=linear_obj)

        linear_obj.junction0 = junction0
        linear_obj.junction1 = junction1


def _process_osm_ways(nodes_dict: dict[t.OSMId, op.Node], ways_dict: dict[t.OSMId, op.Way]) -> list[op.Way]:
    """Processes the values returned from OSM and does a bit of filtering.
    Transformation to roads, railways and bridges is only done later in Roads.process()."""
    my_ways = list()
    clipping_border = shg.Polygon(parameters.get_clipping_border())

    for key, way in ways_dict.items():
        if way.osm_id in parameters.SKIP_LIST:
            logging.debug("SKIPPING OSM_ID %i", way.osm_id)
            continue

        if s.K_HIGHWAY in way.tags and way.tags[s.K_HIGHWAY] == s.V_PROPOSED:
            continue
        if s.K_RAILWAY in way.tags and way.tags[s.K_RAILWAY] == s.V_PROPOSED:
            continue

        # special case, e.g. https://www.openstreetmap.org/way/25310705
        if s.K_RAILWAY in way.tags and s.K_HIGHWAY in way.tags:
            if way.tags[s.K_HIGHWAY] == s.V_ABANDONED:
                del way.tags[s.K_HIGHWAY]
            elif way.tags[s.K_RAILWAY] == s.V_ABANDONED:
                del way.tags[s.K_RAILWAY]
            else:  # a bit arbitrary, but then again the mapping in OSM is wrong
                del way.tags[s.K_HIGHWAY]

        if s.is_highway(way.tags):
            highway_type = e.highway_type_from_osm_tags(way.tags)
            if highway_type is None:
                continue
            elif highway_type.value < parameters.HIGHWAY_TYPE_MIN:
                continue
        elif s.is_railway(way.tags):
            railway_type = e.railway_type_from_osm_tags(way.tags, parameters.USE_TRAM_LINES)
            if railway_type is None:
                continue

        split_ways = op.split_way_at_boundary(nodes_dict, way, clipping_border, op.OSMFeatureType.road)
        if split_ways:
            my_ways.extend(split_ways)

    return my_ways


def _line_string_from_way(way: op.Way, transform: co.Transformation,
                          nodes_dict: dict[t.OSMId, op.Node]) -> shg.LineString:
    osm_nodes = [nodes_dict[r] for r in way.refs]
    nodes = np.array([transform.to_local((n.lon, n.lat)) for n in osm_nodes])
    return shg.LineString(nodes)


def _remove_tunnels(ways_list: list[op.Way]) -> None:
    """Remove tunnels."""
    for the_way in reversed(ways_list):
        if s.is_tunnel(the_way.tags):
            ways_list.remove(the_way)


def _replace_bridge_tags(tags: t.OSMTags) -> None:
    """Transforms an original bridge to a non-bridge.
    Needs to be in sync with method osmstrings.is_bridge().
    """
    if s.K_BRIDGE in tags:
        tags.pop(s.K_BRIDGE)
    if s.K_MAN_MADE in tags and tags[s.K_MAN_MADE] == s.V_BRIDGE:
        tags.pop(s.K_MAN_MADE)
    tags[s.K_REPLACED_BRIDGE_KEY] = s.V_YES


def _replace_short_bridges_with_ways(ways_list: list[op.Way], transform: co.Transformation,
                                     nodes_dict: dict[t.OSMId, op.Node]) -> None:
    """Remove bridge tag from short bridges, making them a simple linear_obj.
    But make sure to not remove bridges with explicit layers
    """
    for the_way in ways_list:
        if s.is_bridge(the_way.tags) and s.K_LAYER not in the_way.tags:
            bridge = _line_string_from_way(the_way, transform, nodes_dict)
            if bridge.length < parameters.BRIDGE_MIN_LENGTH:
                _replace_bridge_tags(the_way.tags)

def _check_bridge_layers(ways_list: list[op.Way], transform: co.Transformation,
                                     nodes_dict: dict[t.OSMId, op.Node]) -> None:
    """If a bridge is at layer 1, then check whether there really is a way beneath it.
    If not (e.g. if the way is crossing a small river) and there are no other way crossings
    above or below, then remove the layer tag.
    That way the bridge gets only the height of BRIDGE_MIN_HEIGHT instead of BRIDGE_LAYER_HEIGHT."""
    line_strings: dict[t.OSMId, shg.LineString] = dict()
    for the_way in ways_list:
        line_strings[the_way.osm_id] = _line_string_from_way(the_way, transform, nodes_dict)
    for the_way in ways_list:
        if s.is_bridge(the_way.tags) and s.K_LAYER in the_way.tags and int(the_way.tags[s.K_LAYER]) == 1:
            has_crossing = False
            my_line_string = line_strings[the_way.osm_id]
            for another_way in ways_list:  # we also check against our own
                another_line_string = line_strings[another_way.osm_id]
                if another_line_string.crosses(my_line_string):
                    has_crossing = True
                    break
            if not has_crossing:
                del the_way.tags[s.K_LAYER]


def _change_way_for_object(my_line: shg.LineString, original_way: op.Way, transform: co.Transformation,
                           nodes_dict: dict[t.OSMId, op.Node]) -> None:
    """Processes an original linear_obj and replaces its coordinates with the coordinates of a LineString."""
    prev_refs = original_way.refs[:]
    the_coordinates = list(my_line.coords)
    original_way.refs = utilities.match_local_coords_with_global_nodes(the_coordinates, prev_refs, nodes_dict,
                                                                       transform, original_way.osm_id, True)


def _init_way_from_existing(way: op.Way, node_references: list[t.OSMId]) -> op.Way:
    """Return a copy of linear_obj. The copy will have the same osm_id and tags, but only given refs"""
    new_way = op.Way(op.get_next_pseudo_osm_id(op.OSMFeatureType.road))
    new_way.pseudo_osm_id = way.osm_id
    new_way.tags = t.OSMTags(dict(way.tags))
    new_way.refs = node_references
    return new_way


def _split_way_for_object(my_multiline: shg.MultiLineString, original_way: op.Way,
                          transform: co.Transformation, nodes_dict: dict[t.OSMId, op.Node]) -> Optional[list[op.Way]]:
    """Processes an original linear_obj split by an object (blocked area, stg_entry) and creates additional
    linear_obj.
    If one of the line strings is shorter than parameter, then it is discarded to reduce the number of residuals.
    If the list of returned ways is empty, then it means that there were no additional ways created, which were
    longer than the min length defined by a parameter.
    If None is returned, then none of the split lines were long enough and also the original way needs to
    be removed.
    """
    is_first = True
    additional_ways = list()
    prev_refs = original_way.refs[:]
    for line in my_multiline.geoms:
        if line.length > parameters.OVERLAP_CHECK_ROAD_MIN_REMAINING:
            the_coordinates = list(line.coords)
            new_refs = utilities.match_local_coords_with_global_nodes(the_coordinates, prev_refs, nodes_dict,
                                                                      transform, original_way.osm_id, True)
            if is_first:
                is_first = False
                original_way.refs = new_refs
            else:
                new_way = _init_way_from_existing(original_way, list())
                new_way.refs = new_refs
                additional_ways.append(new_way)
    if not is_first:  # at least the original way was corrected
        return additional_ways
    return None


def _check_against_blocked_areas(ways_list: list[op.Way], transform: co.Transformation,
                                 nodes_dict: dict[t.OSMId, op.Node],
                                 blocked_areas: list[shg.Polygon], is_water: bool = False) -> list[op.Way]:
    """Makes sure that there are no ways, which go across a blocked area (e.g. airport runway).
    Ways are clipped over into two ways if intersecting. If they are contained, then they are removed."""
    if not blocked_areas:
        return ways_list

    # Need to be absolutely sure that overlapping blocked areas have been merged.
    # Otherwise, for some reason the algorithm re-creates ways when tested against overlapping areas.
    merged_areas = utilities.merge_buffers(blocked_areas)

    new_ways = list()
    for way in reversed(ways_list):
        if is_water and (s.is_bridge(way.tags) or s.is_replaced_bridge(way.tags)):
            new_ways.append(way)
            continue
        my_list = [way]
        continue_loop = True
        loop_counter = 0  # a bit of a hack because the road could almost endlessly be split up
        while continue_loop and my_list:
            if loop_counter >= 50:
                logging.info('loop broken for way %i after 50 loops', way.osm_id)
                break
            loop_counter += 1
            continue_loop = False  # only set to true if something changed
            continue_intersect = True
            for a_way in reversed(my_list):
                my_line = _line_string_from_way(a_way, transform, nodes_dict)
                for blocked_area in merged_areas:
                    if my_line.within(blocked_area):
                        my_list.remove(a_way)
                        logging.debug('removed %d because within blocked area', a_way.osm_id)
                        continue_intersect = False
                        continue_loop = True
                        break
                if continue_intersect:  # i.e. is not within any of the merged_areas
                    for blocked_area in merged_areas:
                        if my_line.disjoint(blocked_area):
                            continue
                        if my_line.intersects(blocked_area):
                            my_line_difference = my_line.difference(blocked_area)
                            if isinstance(my_line_difference, shg.LineString):
                                if my_line_difference.length < parameters.OVERLAP_CHECK_ROAD_MIN_REMAINING:
                                    my_list.remove(a_way)
                                    logging.debug('removed %d because too short', a_way.osm_id)
                                else:
                                    _change_way_for_object(my_line_difference, a_way, transform, nodes_dict)
                                    logging.debug('reduced %d', a_way.osm_id)
                                continue_loop = True
                                break
                            elif isinstance(my_line_difference, shg.MultiLineString):
                                split_ways = _split_way_for_object(my_line_difference, a_way, transform, nodes_dict)
                                if not split_ways:
                                    my_list.remove(a_way)
                                    logging.debug('removed %d because too short', a_way.osm_id)
                                elif len(split_ways) > 0:
                                    for split_way in split_ways:
                                        my_list.append(split_way)
                                    logging.debug('split %d into %d additional ways', a_way.osm_id, len(split_ways))
                                continue_loop = True
                                break
        if my_list:
            new_ways.extend(my_list)

    return new_ways


def _check_ways_sanity(ways_list: list[op.Way], prev_method_name: str) -> None:
    """Makes sure all the ways have at least 2 nodes.
    If one is found with fewer nodes, it is discarded. Should not happen, but does."""
    num_removed = 0
    for way in reversed(ways_list):
        if len(way.refs) < 2:
            logging.warning('Removing linear_obj with osm_id=%i due to only %i nodes after "%s"',
                            way.osm_id, len(way.refs), prev_method_name)
            ways_list.remove(way)
            num_removed += 1
    if num_removed > 0:
        logging.info('Removed %i ways due to only 1 node after "%s"', num_removed, prev_method_name)
    else:
        logging.info('No ways with only one node after "%s"', prev_method_name)


def _remove_short_way_segments(ways_list: list[op.Way], nodes_dict: dict[t.OSMId, op.Node]) -> None:
    """Make sure there are no almost zero length segments.

    In the tile 3088961 around Luzern in Switzerland for around 10000 ways there were 106 nodes removed.
    """
    num_refs_removed = 0
    for way in ways_list:
        if len(way.refs) == 2:
            continue
        refs_to_remove = list()
        ref_len = len(way.refs)
        for i in range(1, ref_len):
            first_node = nodes_dict[way.refs[i - 1]]
            second_node = nodes_dict[way.refs[i]]
            distance = co.calc_distance_global(first_node.lon, first_node.lat,
                                               second_node.lon, second_node.lat)
            if distance < parameters.MIN_ROAD_SEGMENT_LENGTH:
                if i == ref_len - 1:
                    refs_to_remove.append(way.refs[i - 1])  # shall not remove the last node
                else:
                    refs_to_remove.append(way.refs[i])

        for ref in refs_to_remove:
            if len(way.refs) == 2:
                break
            if ref in way.refs:  # A hack for something that actually happens (closed linear_obj?), but should not
                if way.refs.count(ref) > 1:
                    continue  # in seldom cases the same node might also be used several times (e.g. for an 8-form)
                way.refs.remove(ref)
                num_refs_removed += 1
                logging.debug('Removing ref %d from linear_obj %d due to too short segment', ref, way.osm_id)
            else:
                logging.warning('Removing ref %d from linear_obj %d not possible because ref not there',
                                ref, way.osm_id)
    logging.info('Removed %i refs in %i ways due to too short segments', num_refs_removed, len(ways_list))


def _attached_ways_dict_append(attached_ways_dict: dict[t.OSMId, list[Tuple[op.Way, bool]]], the_ref: t.OSMId,
                               the_way: op.Way, is_start: bool) -> None:
    """Append the given linear_obj to attached_ways_dict."""
    if the_ref not in attached_ways_dict:
        attached_ways_dict[the_ref] = list()
    attached_ways_dict[the_ref].append((the_way, is_start))


def _attached_ways_dict_remove(attached_ways_dict: dict[t.OSMId, list[Tuple[op.Way, bool]]], the_ref: t.OSMId,
                               the_way: op.Way, is_start: bool) -> None:
    """Remove given linear_obj from given node in attached_ways_dict"""
    if the_ref not in attached_ways_dict:
        logging.warning("not removing linear_obj %i from the ref %i because the ref is not in attached_ways_dict",
                        the_way.osm_id, the_ref)
        return
    for way_pos_tuple in attached_ways_dict[the_ref]:
        if way_pos_tuple[0] == the_way and way_pos_tuple[1] is is_start:
            logging.debug("removing linear_obj %s from node %i", the_way, the_ref)
            attached_ways_dict[the_ref].remove(way_pos_tuple)
            break


def _find_junctions(attached_ways_dict: dict[t.OSMId, list[Tuple[op.Way, bool]]],
                    ways_list: list[op.Way]) -> None:
    """Finds nodes, which are shared by at least 2 ways at the start or end of the linear_obj.

    The node may only be referenced one, otherwise unclear how to join (e.g. circular)
    """
    logging.info('Finding junctions...')
    for the_way in ways_list:
        start_ref = the_way.refs[0]
        if the_way.refs.count(start_ref) == 1:  # check only once in list
            _attached_ways_dict_append(attached_ways_dict, start_ref, the_way, True)
        end_ref = the_way.refs[-1]
        if the_way.refs.count(end_ref) == 1:
            _attached_ways_dict_append(attached_ways_dict, end_ref, the_way, False)


def _compatible_ways(way1: op.Way, way2: op.Way) -> bool:
    """Returns True if both ways are either a railway, a bridge or a highway - and have common type attributes"""
    logging.debug("trying join %i %i", way1.osm_id, way2.osm_id)
    if s.is_railway(way1.tags) != s.is_railway(way2.tags):
        logging.debug("Nope, either both or none must be railway")
        return False
    elif s.is_bridge(way1.tags) != s.is_bridge(way2.tags):
        logging.debug("Nope, either both or none must be a bridge")
        return False
    elif s.is_highway(way1.tags) != s.is_highway(way2.tags):
        logging.debug("Nope, either both or none must be a highway")
        return False
    elif s.is_highway(way1.tags) and s.is_highway(way2.tags):
        # check type
        if e.highway_type_from_osm_tags(way1.tags) != e.highway_type_from_osm_tags(way2.tags):
            logging.debug("Nope, both must be of same highway type")
            return False
        # check lit
        if linear.get_lit_type(way1.tags) != linear.get_lit_type(way2.tags):
            logging.debug("Nope, both must be of same LitType")
            return False
    elif s.is_railway(way1.tags) and s.is_railway(way2.tags):
        if e.railway_type_from_osm_tags(way1.tags, parameters.USE_TRAM_LINES) != \
                e.railway_type_from_osm_tags(way2.tags, parameters.USE_TRAM_LINES):
            logging.debug("Nope, both must be of same railway type")
            return False
        # check electrified
        if s.is_electrified_railway(way1.tags) != s.is_electrified_railway(way2.tags):
            logging.debug("Nope, both must be electrified or not")
            return False
        # check electrified
        if s.is_rack_railway(way1.tags) != s.is_rack_railway(way2.tags):
            logging.debug("Nope, both must have a rack or not")
            return False
    return True


def _find_way_by_osm_id(osm_id, ways_list: list[op.Way]):
    for the_way in ways_list:
        if the_way.osm_id == osm_id:
            return the_way
    raise ValueError("linear_obj %i not found" % osm_id)


def _join_ways(ways_list: list[op.Way], way1: op.Way, way2: op.Way,
               attached_ways_dict: dict[t.OSMId, list[Tuple[op.Way, bool]]]) -> None:
    """Join ways of compatible type, where way1's last node is way2's first node."""
    logging.debug("Joining %i and %i", way1.osm_id, way2.osm_id)
    if way1.osm_id == way2.osm_id:
        logging.debug("WARNING: Not joining linear_obj %i with itself", way1.osm_id)
        return
    _attached_ways_dict_remove(attached_ways_dict, way1.refs[-1], way1, False)
    _attached_ways_dict_remove(attached_ways_dict, way2.refs[0], way2, True)
    _attached_ways_dict_remove(attached_ways_dict, way2.refs[-1], way2, False)

    way1.refs.extend(way2.refs[1:])

    _attached_ways_dict_append(attached_ways_dict, way1.refs[-1], way1, False)

    try:
        ways_list.remove(way2)
        logging.debug("2ok")
    except ValueError:
        try:
            ways_list.remove(_find_way_by_osm_id(way2.osm_id, ways_list))
        except ValueError:
            logging.warning('Way with osm_id={} cannot be removed because cannot be found'.format(way2.osm_id))
        logging.debug("2not")


def _rejoin_ways(ways_list: list[op.Way], attached_ways_dict: dict[t.OSMId, list[Tuple[op.Way, bool]]],
                 transform: co.Transformation, nodes_dict: dict[t.OSMId, op.Node]) -> None:
    number_merged_ways = 0
    for ref in list(attached_ways_dict.keys()):  # dict is changed during looping, so using list of keys
        way_pos_list = attached_ways_dict[ref]
        if len(way_pos_list) < 2:
            continue

        start_dict = dict()  # dict of ways where node is start point with key=linear_obj, value=degree from north
        end_dict = dict()  # ditto for node is end point
        for way, is_start in way_pos_list:
            if is_start:
                first_node = nodes_dict[way.refs[0]]
                second_node = nodes_dict[way.refs[1]]
                angle = co.calc_angle_of_line_global(first_node.lon, first_node.lat,
                                                     second_node.lon, second_node.lat,
                                                     transform)
                start_dict[way] = angle
            else:
                first_node = nodes_dict[way.refs[-2]]
                second_node = nodes_dict[way.refs[-1]]
                angle = co.calc_angle_of_line_global(first_node.lon, first_node.lat,
                                                     second_node.lon, second_node.lat,
                                                     transform)
                end_dict[way] = angle

        # for each in end_dict search in start_dict the one with the closest angle and is a compatible linear_obj
        for end_way, end_angle in end_dict.items():
            if end_way.is_closed():
                continue  # never combine ways which are closed (e.g. roundabouts)
            candidate_way = None
            candidate_angle = 999
            for start_way, start_angle in start_dict.items():
                if start_way.is_closed():
                    continue
                if _compatible_ways(end_way, start_way):
                    if abs(start_angle - end_angle) >= 90:
                        continue  # larger angles lead to strange visuals
                    if candidate_way is None:
                        candidate_way = start_way
                        candidate_angle = start_angle
                    elif abs(candidate_angle - end_angle) > abs(start_angle - end_angle):
                        candidate_way = start_way
                        candidate_angle = start_angle

            if candidate_way is not None:
                _join_ways(ways_list, end_way, candidate_way, attached_ways_dict)
                del start_dict[candidate_way]
                number_merged_ways += 1
                logging.debug('Merging at %i ways %i and %i', ref, end_way.osm_id, candidate_way.osm_id)

    logging.info('Merged %i ways', number_merged_ways)


def _cleanup_topology(ways_list: list[op.Way], transform: co.Transformation, nodes_dict: dict[t.OSMId, op.Node]) -> None:
    """Cleans up the topology for junctions etc."""
    logging.debug("Number of ways before cleaning topology: %i" % len(ways_list))

    # a dictionary with a Node id as key. Each node has one or several ways using it in a list.
    # The entry per linear_obj is a tuple of the linear_obj object as well as whether the node is at the start
    attached_ways_dict = dict()  # Dict[int, List[Tuple[op.Way, bool]]]

    # do it again, because the references and positions have changed
    _find_junctions(attached_ways_dict, ways_list)

    _rejoin_ways(ways_list, attached_ways_dict, transform, nodes_dict)

    logging.debug("Number of ways after cleaning topology: %i" % len(ways_list))


def _check_points_on_line_distance(max_point_dist: int, ways_list: list[op.Way], nodes_dict: dict[t.OSMId, op.Node],
                                   transform: co.Transformation) -> None:
    """Based on parameter makes sure that points on a line are not too long apart for elevation probing reasons.

    If distance is longer than the related parameter, then new points are added along the line.
    Probing is not done on bridges.
    """
    for the_way in ways_list:
        if s.is_bridge(the_way.tags):
            continue

        my_new_refs = [the_way.refs[0]]
        for index in range(1, len(the_way.refs)):
            node0 = nodes_dict[the_way.refs[index - 1]]
            node1 = nodes_dict[the_way.refs[index]]
            my_line = shg.LineString([transform.to_local((node0.lon, node0.lat)),
                                      transform.to_local((node1.lon, node1.lat))])
            if my_line.length <= max_point_dist:
                my_new_refs.append(the_way.refs[index])
                continue
            else:
                additional_needed_nodes = int(my_line.length / max_point_dist)
                for x in range(additional_needed_nodes):
                    new_point = my_line.interpolate((x + 1) * max_point_dist)
                    osm_id = op.get_next_pseudo_osm_id(op.OSMFeatureType.road)
                    lon_lat = transform.to_global((new_point.x, new_point.y))
                    new_node = op.Node(osm_id, lon_lat[1], lon_lat[0], True)
                    nodes_dict[osm_id] = new_node
                    my_new_refs.append(osm_id)
                my_new_refs.append(the_way.refs[index])

        the_way.refs = my_new_refs


def _remove_unused_nodes(ways_list: list[op.Way], nodes_dict: dict[t.OSMId, op.Node]) -> dict[t.OSMId, op.Node]:
    """Remove all nodes which are not used in ways in order not to do elevation probing in vane."""
    used_nodes_dict = dict()
    for way in ways_list:
        for ref in way.refs:
            used_nodes_dict[ref] = nodes_dict[ref]
    return used_nodes_dict


def _probe_elev_at_nodes(nodes_dict: dict[t.OSMId, op.Node], fg_elev: ep.FGElev):
    """Add elevation info to all nodes."""
    for the_node in list(nodes_dict.values()):
        if math.isnan(the_node.lon) or math.isnan(the_node.lat):
            logging.error("NaN encountered while probing elevation")
            continue
        the_node.msl = fg_elev.probe_elev((the_node.lon, the_node.lat), is_global=True)


def _cut_way_at_intersection_points(intersection_points: list[shg.Point], way: op.Way,
                                    my_line: shg.LineString, transform: co.Transformation,
                                    nodes_dict: dict[t.OSMId, op.Node]) -> MutableMapping[op.Way, float]:
    """Cuts an existing linear_obj into several parts based in intersection points given as a parameter.
    Returns an OrderedDict of Ways, where the first element is always the (changed) original linear_obj, such
    that the distance from start to intersection is clear.
    Cutting also checks that the potential new cut ways have a minimum distance based on
    parameters.BUILT_UP_AREA_LIT_BUFFER, such that the splitting is not too tiny. This can lead to that
    an original linear_obj just keeps its original length despite one or several intersection points.
    Distance in the returned dictionary refers to the last point's distance along the original linear_obj, which
    is e.g. the length of the original linear_obj for the last cut linear_obj."""
    intersect_dict = dict()  # osm_id for node, distance from start
    cut_ways_dict = OrderedDict()  # key: linear_obj, value: distance of end from start of original linear_obj
    # create new global nodes
    for point in intersection_points:
        distance = my_line.project(point)
        lon, lat = transform.to_global((point.x, point.y))

        # make sure that the new node is relevant and not just a rounding residual
        add_intersection = True
        refs_to_remove = set()
        for ref in way.refs:
            ref_node = nodes_dict[ref]
            segment_length = co.calc_distance_global(lon, lat, ref_node.lon, ref_node.lat)
            if segment_length < parameters.MIN_ROAD_SEGMENT_LENGTH:
                if ref == way.refs[0] or ref == way.refs[-1]:  # ignore because it is almost at either start or end
                    add_intersection = False
                    break
                else:  # tweak so it can be used as intersection, but based on existing point
                    add_intersection = False
                    refs_to_remove.add(ref)
                    intersect_dict[ref] = distance
                    my_line = _line_string_from_way(way, transform, nodes_dict)
                    break

        for ref in refs_to_remove:
            way.refs.remove(ref)

        if add_intersection:
            new_node = op.Node(op.get_next_pseudo_osm_id(op.OSMFeatureType.road), lat, lon)
            nodes_dict[new_node.osm_id] = new_node
            intersect_dict[new_node.osm_id] = distance

    # create lines based on old and new points
    original_refs = way.refs[:]
    coords = list(my_line.coords)
    prev_orig_point_dist = 0
    is_first = True
    current_way_refs = list()
    new_way = None
    ordered_intersect_dict = OrderedDict(sorted(intersect_dict.items(), key=lambda tt: tt[1]))
    for next_index in range(len(coords) - 1):
        current_way_refs.append(original_refs[next_index])
        next_orig_point_dist = my_line.project(shg.Point(coords[next_index + 1]))
        intersects_to_remove = list()  # osm_id
        for key, distance in ordered_intersect_dict.items():
            if prev_orig_point_dist < distance < next_orig_point_dist:
                intersects_to_remove.append(key)
                # check minimal distance of linear_obj pieces
                if (distance - prev_orig_point_dist) < parameters.OWBB_BUILT_UP_BUFFER:
                    continue
                # make cut
                current_way_refs.append(key)
                if is_first:
                    is_first = False
                    way.refs = current_way_refs.copy()
                    new_way = way  # needed to have reference for closing last node below
                else:
                    new_way = op.Way(op.get_next_pseudo_osm_id(op.OSMFeatureType.road))
                    new_way.pseudo_osm_id = way.osm_id
                    new_way.tags = t.OSMTags(dict(way.tags))
                    new_way.refs = current_way_refs.copy()
                middle_distance = distance - (distance - prev_orig_point_dist) / 2
                cut_ways_dict[new_way] = middle_distance

                # restart current_way_refs with found cut point as new starting
                current_way_refs = [key]
                prev_orig_point_dist = distance

        # remove not needed intersection points
        for key in intersects_to_remove:
            del ordered_intersect_dict[key]

    # close the last node
    if is_first:  # maybe the intersection points were all below minimal distance -> nothing to do
        cut_ways_dict[way] = my_line.length / 2
    else:
        # check minimal distance of linear_obj pieces
        if (my_line.length - prev_orig_point_dist) < parameters.OWBB_BUILT_UP_BUFFER:
            # instead of new cut linear_obj extend the last cut linear_obj, but do not change its middle_distance
            # last cut_way is still "new_way", because we are not is_first
            new_way.refs.append(original_refs[-1])
        else:
            new_way = op.Way(op.get_next_pseudo_osm_id(op.OSMFeatureType.road))
            new_way.pseudo_osm_id = way.osm_id
            new_way.tags = t.OSMTags(dict(way.tags))
            new_way.refs = current_way_refs.copy()
            new_way.refs.append(original_refs[-1])
            cut_ways_dict[new_way] = my_line.length - (my_line.length - prev_orig_point_dist) / 2

    logging.debug('{} new cut ways (not including orig linear_obj) from {} intersections'.format(
        len(cut_ways_dict) - 1, len(intersection_points)))
    return cut_ways_dict


def _calculate_way_layers_at_node(ways_list: list[op.Way], nodes_dict: dict[t.OSMId, op.Node]) -> None:
    """At each node shared between ways determine, which layer a Way should belong to.

    Otherwise, the different textures at a given point might be fighting in the z-layer in rendering.

    A Way where the node is not at the start/end gets priority over a linear_obj, where it is at start/end.
    Then a railway gets priority over a road
    Then within a railway or road the priority is based on the value of the type
    Last a higher osm_id wins everything else equal.
    """
    # first just make sure that we have a reference for all the ways
    for the_way in ways_list:
        for ref in the_way.refs:
            node = nodes_dict[ref]
            if the_way not in node.layers:  # the same node can be several times in a Way (ring, 8)
                node.layers[the_way] = 0

    # now we need to do the sorting. If a node has none or 1 reference, then it is easy.
    # otherwise create a tuple to do the sorting (cf. https://docs.python.org/3/howto/sorting.html#key-functions)
    for key, node in nodes_dict.items():
        if len(node.layers) > 1:
            # build up a tuple with the relevant attributes for sorting (higher values = more priority)
            way_tuples = list()
            for the_way in node.layers.keys():
                if key == the_way.refs[0] or key == the_way.refs[-1]:
                    between = 0
                else:
                    between = 1
                if s.is_highway(the_way.tags):
                    type_factor = e.highway_type_from_osm_tags(the_way.tags)
                else:
                    # 100 -> railway on top of roads
                    type_factor = e.railway_type_from_osm_tags(the_way.tags, parameters.USE_TRAM_LINES) * 100
                way_tuples.append((the_way, between, type_factor, the_way.osm_id))

            # now do the sorting in steps
            way_tuples.sort(key=itemgetter(1, 2, 3))

            # based on this we can now finalize the dict
            node.layers = dict()
            for i, my_tuple in enumerate(way_tuples):
                node.layers[my_tuple[0]] = i


def _calculate_way_layers_all_nodes(ways_list: list[op.Way], nodes_dict: dict[t.OSMId, op.Node]) -> None:
    """Given the layers at intersecting nodes calculate the layers for the other nodes in all ways."""
    for the_way in ways_list:
        the_segments = linear.WaySegment.split_way_into_way_segments(the_way, nodes_dict)
        for segment in the_segments:
            segment.calc_missing_layers_for_nodes()


def _create_linear_objects(ways_list: list[op.Way], transform: co.Transformation, nodes_dict: dict[t.OSMId, op.Node],
                           fg_elev: ep.FGElev,
                           lit_areas: list[shg.Polygon], network: Graph) -> tuple[list[linear.LinearObject],
                                                                                  list[linear.LinearObject],
                                                                                  list[linear.LinearBridge]]:
    """Creates the linear objects, which will be created as scenery objects.

    Not processing parking for now (the_way.tags['amenity'] in ['parking'])
    While certainly good to have, parking in OSM is not a linear feature in general.
    We'd need to add areas.

    The returned tuple has in sequential order:
    * list of LinearObject for road
    * list of LinearObject for railway
    * list of LinearObject for bridge
    """
    roads: list[linear.LinearObject] = list()
    railways: list[linear.LinearObject] = list()
    bridges: list[linear.LinearBridge] = list()

    for the_way in ways_list:
        if s.is_highway(the_way.tags):
            highway_type = e.highway_type_from_osm_tags(the_way.tags)
            # in method Roads.store_way smaller highways already got removed
            tex, width, material_name = e.get_highway_attributes(highway_type)

        elif s.is_railway(the_way.tags):
            railway_type = e.railway_type_from_osm_tags(the_way.tags, parameters.USE_TRAM_LINES)
            tex, width, material_name = e.get_railway_attributes(railway_type, the_way.tags)
        else:
            continue

        try:
            if s.is_bridge(the_way.tags):
                obj = linear.LinearBridge(transform, fg_elev, the_way, nodes_dict, lit_areas,
                                          width, material_name, tex_coords=tex)
                bridges.append(obj)
            else:
                obj = linear.LinearObject(transform, the_way, nodes_dict, lit_areas,
                                          width, material_name, tex_coords=tex)
                if s.is_railway(the_way.tags):
                    railways.append(obj)
                else:
                    roads.append(obj)

            network.add_linear_object_edge(obj)
        except ValueError as reason:
            logging.warning("skipping OSM_ID %i: %s" % (the_way.osm_id, reason))
            continue

    return roads, railways, bridges


def _split_linear_objects(linear_objects: list[linear.LinearObject], transform: co.Transformation,
                          nodes_dict: dict[t.OSMId, op.Node], lit_areas: list[shg.Polygon],
                          type_for_logging: str) -> list[linear.LinearObject]:
    """Split linear objects such that segments with v_add = 0 are separated."""
    split: list[linear.LinearObject] = list()
    num_split = 0
    for linear_object in linear_objects:
        if len(linear_object.way.refs) == 2:
            split.append(linear_object)
            continue
        num_v_add_is_0 = 0
        for ref in linear_object.way.refs:
            if nodes_dict[ref].v_add < parameters.DELTA_V_ADD_IS_ZERO:
                num_v_add_is_0 += 1
        if num_v_add_is_0 < 2:
            split.append(linear_object)
            continue
        if num_v_add_is_0 == len(linear_object.way.refs):
            split.append(linear_object)
            continue

        # now we know there is a chance of 2 consecutive v_add_is_0
        num_split += 1
        is_first_split = True
        current_segment_refs: list[t.OSMId] = list()
        for index in range (len(linear_object.way.refs)):
            if index == 0:
                current_segment_refs.append(linear_object.way.refs[index])
                continue

            current_segment_refs.append(linear_object.way.refs[index])
            prev_v_add_is_0 = nodes_dict[linear_object.way.refs[index - 1]].v_add < parameters.DELTA_V_ADD_IS_ZERO
            current_v_add_is_0 = nodes_dict[linear_object.way.refs[index]].v_add < parameters.DELTA_V_ADD_IS_ZERO
            if prev_v_add_is_0 != current_v_add_is_0:
                new_way = _init_way_from_existing(linear_object.way, current_segment_refs)
                new_obj = linear.LinearObject(transform, new_way, nodes_dict, lit_areas,
                                              linear_object.width, linear_object.material_name, linear_object.tex)
                if is_first_split:
                    is_first_split = False
                    # new_obj.junction0 = linear_object.junction0
                split.append(new_obj)
                current_segment_refs = list()
                current_segment_refs.append(linear_object.way.refs[index])

            if index == len(linear_object.way.refs) -2:  # second last node - we must finalize
                current_segment_refs.append(linear_object.way.refs[index + 1])
                new_way = _init_way_from_existing(linear_object.way, current_segment_refs)
                new_obj = linear.LinearObject(transform, new_way, nodes_dict, lit_areas,
                                              linear_object.width, linear_object.material_name, linear_object.tex)
                # new_obj.junction1 = linear_object.junction1
                split.append(new_obj)
                break
    logging.info('Split linear objects for %s from %i objects into %i objects (%i were split)',
                 type_for_logging, len(linear_objects), len(split), num_split)
    return split


def _for_edges_in_bfs_call(func, network: Graph, nodes_dict: dict[t.OSMId, op.Node],
                           node0_set: set[int], visited_set: set[int]) -> None:
    """Start at nodes in node0_set. Breadth-first search, excluding nodes
       in visited_set.
       For each edge, call func(node0, node1, args).
       Stop search on one branch if func returns False.
    """
    while True:
        # get neighbors not visited
        next_nodes = {}
        for node0 in node0_set:
            neighbours = [n for n in nx.all_neighbors(network, node0) if n not in visited_set]
            next_nodes[node0] = neighbours

        node0_set = set()
        for n0, n1s in next_nodes.items():
            for n1 in n1s:
                if func(n0, n1, network, nodes_dict):
                    node0_set.add(n1)
                visited_set.add(n1)
        if not node0_set:
            break


def _propagate_v_add_over_edge(ref0: t.OSMId, ref1: t.OSMId, network: Graph, nodes_dict: dict[t.OSMId, op.Node]) -> bool:
    """propagate v_add over edges of graph"""
    obj: linear.LinearObject = network[ref0][ref1][LINEAR_OBJECT_ATTRIBUTE]
    dh_dx = linear.max_slope_for_road(obj)
    n0 = nodes_dict[ref0]
    n1 = nodes_dict[ref1]
    if n1.v_add > 0:
        return False
    n1.v_add = max(0, n0.msl + n0.v_add - obj.center.length * dh_dx - n1.msl)
    if n1.v_add <= 0.:
        return False
    return True


def _propagate_v_add(bridges: list[linear.LinearBridge], network: Graph, nodes_dict: dict[t.OSMId, op.Node]) -> None:
    """Start at bridges, propagate v_add through nodes in other linear objects"""
    for the_bridge in bridges:
        # build tree starting at node0
        first_node = the_bridge.way.refs[0]
        last_node = the_bridge.way.refs[-1]

        node0_set: set[int] = {last_node}  # osm_id references
        visited_set: set[int] = {first_node, last_node}  # osm_id references
        _for_edges_in_bfs_call(_propagate_v_add_over_edge, network, nodes_dict, node0_set, visited_set)
        node0_set = {first_node}
        visited_set = {first_node, last_node}
        _for_edges_in_bfs_call(_propagate_v_add_over_edge, network, nodes_dict, node0_set, visited_set)


def _process_line_feature_list(list_of_linear_objects: list[linear.LinearObject],
                               cleaned_nodes_dict: dict[t.OSMId, op.Node],
                               stg_manager: stg_io2.STGManager, file_lock: mps.Lock | None,
                               anchor: co.Vec2d) -> None:
    # prepare the rows to write to list files
    feature_lists: dict[str, list[str]] = dict()  # key is the material name
    for linear_object in list_of_linear_objects:
        is_lit = 0
        total_lit_nodes = 0
        for my_bool in linear_object.lighting:
            if my_bool:
                total_lit_nodes += 1
        if total_lit_nodes/len(linear_object.lighting) >= 0.5:
            is_lit = 1
        row_str = '{:.2f} {} 1 1 1 1'.format(linear_object.width, is_lit)
        for ref in linear_object.way.refs:
            node = cleaned_nodes_dict[ref]
            if node.added_for_dist:
                pass  # we can omit extra added nodes for bumpiness
            else:
                row_str += ' {:.6f} {:.6f}'.format(node.lon, node.lat)
        row_str += '\n'
        if linear_object.material_name not in feature_lists:
            feature_lists[linear_object.material_name] = list()
        feature_lists[linear_object.material_name].append(row_str)

    # write to list files
    total_files_written = 0
    total_lines_written = 0
    for material_name, list_of_rows in feature_lists.items():
        total_files_written += 1
        file_name = f'{stg_manager.prefix}_{material_name}.txt.gz'
        path_to_stg = stg_manager.add_line_feature_list(file_name, material_name, anchor)
        with gzip.open(osp.join(path_to_stg, file_name), 'wt') as line_feature_list_file:
            for row in list_of_rows:
                line_feature_list_file.write(row)
                total_lines_written += 1

    stg_manager.write(file_lock)

    logging.info('Written %i lines in %i files for linear feature list for transportation',
                 total_lines_written, total_files_written)


def _process_railway_overhead_lines(rail_lines: list[po.RailLine], linear_objects: list[linear.LinearObject],
                                    linear_bridges: list[linear.LinearBridge], nodes_dict: dict[t.OSMId, op.Node],
                                    transform: co.Transformation) -> None:
    for the_object in linear_objects + linear_bridges:
        # checking again for railway due to bridges
        if not s.is_railway(the_object.way.tags):
            continue
        railway_type = e.railway_type_from_osm_tags(the_object.way.tags, parameters.USE_TRAM_LINES)
        if railway_type is None:
            continue
        if not s.is_electrified_railway(the_object.way.tags):
            continue

        rail_nodes: list[po.RailNode] = list()
        for ref in the_object.way.refs:
            my_node = nodes_dict[ref]
            my_rail_node = po.RailNode(my_node.osm_id)
            my_rail_node.lat = my_node.lat
            my_rail_node.lon = my_node.lon
            my_rail_node.x, my_rail_node.y = transform.to_local((my_node.lon, my_node.lat))
            my_rail_node.elevation = my_node.msl + my_node.v_add
            rail_nodes.append(my_rail_node)
        if len(rail_nodes) > 1:
            my_coordinates = list()
            for node in rail_nodes:
                my_coordinates.append((node.x, node.y))
            my_linear = shg.LineString(my_coordinates)
            my_line = po.RailLine(the_object.way.osm_id, rail_nodes, my_linear)
            rail_lines.append(my_line)

    for rail_line in rail_lines:
        rail_line.calc_and_map(rail_lines)


def process_transportation(transform: co.Transformation, fg_elev: ep.FGElev, blocked_apt_areas: list[shg.Polygon],
                           stg_static_polys: list[shg.Polygon], stg_shared_polys: list[shg.Polygon],
                           lit_areas: list[shg.Polygon], water_areas: list[shg.Polygon], rail_lines: list[po.RailLine],
                           file_lock: mps.Lock | None = None) -> None:
    random.seed(42)

    osm_way_result = op.fetch_osm_data_ways_keys([s.K_HIGHWAY, s.K_RAILWAY])
    osm_nodes_dict = osm_way_result.nodes_dict
    osm_ways_dict = osm_way_result.ways_dict

    # OSM APRONS
    if parameters.OVERLAP_CHECK_APT_USE_OSM_APRON_ROADS:
        osm_result = op.fetch_osm_data_ways_key_values([s.KV_AEROWAY_APRON])
        for way in list(osm_result.ways_dict.values()):
            my_geometry = way.polygon_from_osm_way(osm_result.nodes_dict, transform)
            blocked_apt_areas.append(my_geometry)

    # add STGEntries to the blocked area mix

    extended_blocked_areas = blocked_apt_areas
    extended_blocked_areas.extend(stg_static_polys)
    extended_blocked_areas.extend(stg_shared_polys)

    logging.info("Number of ways before basic processing: %i", len(osm_ways_dict))
    ways_list = _process_osm_ways(osm_nodes_dict, osm_ways_dict)
    logging.info("Number of ways after basic processing: %i", len(ways_list))
    if not ways_list:
        logging.info("No roads and railways found -> aborting")
        return

    _remove_tunnels(ways_list)
    logging.info("Number of ways after removing tunnels: %i", len(ways_list))
    _check_bridge_layers(ways_list, transform, osm_nodes_dict)
    _replace_short_bridges_with_ways(ways_list, transform, osm_nodes_dict)

    # only use water areas, which are not small canals (if they would be broad, then there would be a bridge,
    # and we would also be fine - also after removing short bridges)
    large_water_areas = list()
    for water_area in water_areas:
        # 20 is ca. a rectangle of length 100 and width 1
        if water_area.length / math.sqrt(water_area.area) < 20:
            large_water_areas.append(water_area)
    logging.info('Reduced number of water areas from %i to %i', len(water_areas), len(large_water_areas))

    ways_list = _check_against_blocked_areas(ways_list, transform, osm_nodes_dict, large_water_areas, True)
    _check_ways_sanity(ways_list, '_check_against_blocked_areas_water')
    ways_list = _check_against_blocked_areas(ways_list, transform, osm_nodes_dict, extended_blocked_areas)
    _check_ways_sanity(ways_list, '_check_against_blocked_areas')
    logging.info("Number of ways after checking against blocked areas: %i", len(ways_list))

    _remove_short_way_segments(ways_list, osm_nodes_dict)
    _check_ways_sanity(ways_list, '_remove_short_way_segments')
    _cleanup_topology(ways_list, transform, osm_nodes_dict)
    _check_points_on_line_distance(parameters.POINTS_ON_LINE_DISTANCE_MAX, ways_list, osm_nodes_dict,
                                   transform)

    cleaned_nodes_dict = _remove_unused_nodes(ways_list, osm_nodes_dict)
    _probe_elev_at_nodes(cleaned_nodes_dict, fg_elev)

    tile_index = parameters.get_tile_index()

    # no change in topology beyond create_linear_objects() !
    logging.info("Number of ways before linear: %i ", len(ways_list))
    _calculate_way_layers_at_node(ways_list, cleaned_nodes_dict)
    _calculate_way_layers_all_nodes(ways_list, cleaned_nodes_dict)
    network = Graph()  # the edges of the graph are LinearObjects added below
    roads, railways, bridges = _create_linear_objects(ways_list, transform, cleaned_nodes_dict, fg_elev,
                                                      lit_areas, network)
    _propagate_v_add(bridges, network, cleaned_nodes_dict)

    # now that we know v_add we can do some optimisation by splitting stuff away with v_add = 0
    roads = _split_linear_objects(roads, transform, cleaned_nodes_dict, lit_areas, 'roads')
    railways = _split_linear_objects(railways, transform, cleaned_nodes_dict, lit_areas, 'railways')
    # no need (and it would be wrong) to do it for bridges

    logging.info("Number of ways after linear: %i ", len(ways_list))

    stg_manager_mesh = stg_io2.STGManager(parameters.get_output_path(), stg_io2.SceneryType.roads, OUR_MAGIC,
                                          parameters.PREFIX)
    file_name = parameters.PREFIX + '_tall.ac'
    ac_f = ac3d.File()
    ac_object_f = ac_f.new_object('all_transportation', 'Textures/osm2city/roads.png',
                                  default_swap_uv=True, default_mat_idx=mat.Material.unlit.value)
    path_to_stg = stg_manager_mesh.add_object_static(file_name, transform.anchor,
                                                     parameters.get_tile_radius(),
                                                     stg_io2.STGVerbType.object_road_rough)

    line_feature_list: list[linear.LinearObject] = list()

    total_linear_objects_written = 0
    for the_object in bridges + roads + railways:
        if parameters.USE_LINE_FEATURE_LIST_FOR_ROADS and isinstance(the_object, linear.LinearObject):
            num_v_add_is_0 = 0
            for ref in the_object.way.refs:
                if cleaned_nodes_dict[ref].v_add < parameters.DELTA_V_ADD_IS_ZERO:
                    num_v_add_is_0 += 1
            if num_v_add_is_0 == len(the_object.way.refs):
                line_feature_list.append(the_object)
                continue
        the_object.write_to(ac_object_f, fg_elev, cleaned_nodes_dict)
        total_linear_objects_written += 1

    ac_f.write(osp.join(path_to_stg, file_name))
    stg_manager_mesh.write(file_lock)

    logging.info('Written %i linear objects to mesh for transportation', total_linear_objects_written)

    stg_manager_list = stg_io2.STGManager(parameters.get_output_path(), stg_io2.SceneryType.terrain, OUR_MAGIC,
                                          parameters.PREFIX)
    _process_line_feature_list(line_feature_list, cleaned_nodes_dict, stg_manager_list, file_lock, transform.anchor)


    if parameters.C2P_PROCESS_RAIL_OVERHEAD_LINES:
        _process_railway_overhead_lines(rail_lines, railways, bridges, cleaned_nodes_dict, transform)


    if parameters.DEBUG_PLOT_ROADS:
        plotting.draw_roads(ways_list, extended_blocked_areas, transform, cleaned_nodes_dict, tile_index)


class TestLinearTransportation(unittest.TestCase):
    def test_cut_way_at_intersection_points(self):
        nodes_dict = dict()
        coords_transform = co.Transformation.create_zero_zero_transformation()
        way = op.Way(t.OSMId(1))
        way.tags["hello"] = "world"
        way.refs = [t.OSMId(1), t.OSMId(2), t.OSMId(3), t.OSMId(4), t.OSMId(5), t.OSMId(6)]
        my_line = shg.LineString([(0, 0), (0, 300), (0, 500), (0, 600), (0, 900), (0, 1000)])
        lon, lat = coords_transform.to_global((0, 0))
        nodes_dict[1] = op.Node(t.OSMId(1), lat, lon)
        lon, lat = coords_transform.to_global((0, 300))
        nodes_dict[2] = op.Node(t.OSMId(2), lat, lon)
        lon, lat = coords_transform.to_global((0, 500))
        nodes_dict[3] = op.Node(t.OSMId(3), lat, lon)
        lon, lat = coords_transform.to_global((0, 600))
        nodes_dict[4] = op.Node(t.OSMId(4), lat, lon)
        lon, lat = coords_transform.to_global((0, 900))
        nodes_dict[5] = op.Node(t.OSMId(5), lat, lon)
        lon, lat = coords_transform.to_global((0, 1000))
        nodes_dict[6] = op.Node(t.OSMId(6), lat, lon)

        msg = 'line with no intersection points -> 1 way orig'
        intersection_points = []

        cut_ways_dict = _cut_way_at_intersection_points(intersection_points, way, my_line, coords_transform, nodes_dict)
        self.assertEqual(1, len(cut_ways_dict), 'number of ways: ' + msg)
        self.assertEqual(6, len(way.refs), 'references of orig way: ' + msg)

        msg = 'line with 1 valid intersection point -> 1 way orig shorter, 1 new way'
        way.refs = [t.OSMId(1), t.OSMId(2), t.OSMId(3), t.OSMId(4), t.OSMId(5), t.OSMId(6)]
        my_line = shg.LineString([(0, 0), (0, 300), (0, 500), (0, 600), (0, 900), (0, 1000)])
        intersection_points = [shg.Point(0, 100)]
        cut_ways_dict = _cut_way_at_intersection_points(intersection_points, way, my_line, coords_transform, nodes_dict)
        self.assertEqual(2, len(cut_ways_dict), 'number of ways: ' + msg)
        self.assertEqual(2, len(way.refs), 'references of orig way: ' + msg)

        msg = 'line with one intersection point too short at start -> 1 way orig'
        way.refs = [t.OSMId(1), t.OSMId(2), t.OSMId(3), t.OSMId(4), t.OSMId(5), t.OSMId(6)]
        my_line = shg.LineString([(0, 0), (0, 300), (0, 500), (0, 600), (0, 900), (0, 1000)])
        intersection_points = [shg.Point(0, parameters.OWBB_BUILT_UP_BUFFER - 1)]
        cut_ways_dict = _cut_way_at_intersection_points(intersection_points, way, my_line, coords_transform, nodes_dict)
        self.assertEqual(1, len(cut_ways_dict), 'number of ways: ' + msg)
        self.assertEqual(6, len(way.refs), 'references of orig way: ' + msg)

        msg = 'line with 1 intersection point too short at end -> 1 way orig'
        way.refs = [t.OSMId(1), t.OSMId(2), t.OSMId(3), t.OSMId(4), t.OSMId(5), t.OSMId(6)]
        my_line = shg.LineString([(0, 0), (0, 300), (0, 500), (0, 600), (0, 900), (0, 1000)])
        intersection_points = [shg.Point(0, 1000 - (parameters.OWBB_BUILT_UP_BUFFER - 1))]
        cut_ways_dict = _cut_way_at_intersection_points(intersection_points, way, my_line, coords_transform, nodes_dict)
        self.assertEqual(1, len(cut_ways_dict), 'number of ways: ' + msg)
        self.assertEqual(7, len(way.refs), 'references of orig way: ' + msg)  # 1 more because intersec. point remains

        msg = 'line with 2 intersection points just after each other -> 1 way orig shorter, 2 new ways'
        way.refs = [t.OSMId(1), t.OSMId(2), t.OSMId(3), t.OSMId(4), t.OSMId(5), t.OSMId(6)]
        my_line = shg.LineString([(0, 0), (0, 300), (0, 500), (0, 600), (0, 900), (0, 1000)])
        intersection_points = [shg.Point(0, parameters.OWBB_BUILT_UP_BUFFER + 2),
                               shg.Point(0, 2 * parameters.OWBB_BUILT_UP_BUFFER + 10)]
        cut_ways_dict = _cut_way_at_intersection_points(intersection_points, way, my_line, coords_transform, nodes_dict)
        self.assertEqual(3, len(cut_ways_dict), 'number of ways: ' + msg)
        self.assertEqual(2, len(way.refs), 'references of orig way: ' + msg)

        msg = 'line with 6 nodes and two intersection points given in reverse order for distance -> 1 & 2 new ways'
        way.refs = [t.OSMId(1), t.OSMId(2), t.OSMId(3), t.OSMId(4), t.OSMId(5), t.OSMId(6)]
        my_line = shg.LineString([(0, 0), (0, 300), (0, 500), (0, 600), (0, 900), (0, 1000)])
        intersection_points = [shg.Point(0, 700),
                               shg.Point(0, 400)]
        cut_ways_dict = _cut_way_at_intersection_points(intersection_points, way, my_line, coords_transform, nodes_dict)
        self.assertEqual(3, len(cut_ways_dict), 'number of ways: ' + msg)
        self.assertEqual(3, len(way.refs), 'references of orig way: ' + msg)

        msg = 'line with 1 intersection point almost at start -> 1 way orig'
        way.refs = [t.OSMId(1), t.OSMId(2), t.OSMId(3), t.OSMId(4), t.OSMId(5), t.OSMId(6)]
        my_line = shg.LineString([(0, 0), (0, 300), (0, 500), (0, 600), (0, 900), (0, 1000)])
        intersection_points = [shg.Point(0, parameters.MIN_ROAD_SEGMENT_LENGTH * 0.1)]
        cut_ways_dict = _cut_way_at_intersection_points(intersection_points, way, my_line, coords_transform, nodes_dict)
        self.assertEqual(1, len(cut_ways_dict), 'number of ways: ' + msg)
        self.assertEqual(6, len(way.refs), 'references of orig way: ' + msg)

        msg = 'line with 1 intersection point almost at end -> 1 way orig'
        way.refs = [t.OSMId(1), t.OSMId(2), t.OSMId(3), t.OSMId(4), t.OSMId(5), t.OSMId(6)]
        my_line = shg.LineString([(0, 0), (0, 300), (0, 500), (0, 600), (0, 900), (0, 1000)])
        intersection_points = [shg.Point(0, parameters.MIN_ROAD_SEGMENT_LENGTH * 0.1)]
        cut_ways_dict = _cut_way_at_intersection_points(intersection_points, way, my_line, coords_transform, nodes_dict)
        self.assertEqual(1, len(cut_ways_dict), 'number of ways: ' + msg)
        self.assertEqual(6, len(way.refs), 'references of orig way: ' + msg)

        msg = 'line with 1 intersection point almost at inner-reference -> 1 way orig'
        way.refs = [t.OSMId(1), t.OSMId(2), t.OSMId(3), t.OSMId(4), t.OSMId(5), t.OSMId(6)]
        my_line = shg.LineString([(0, 0), (0, 300), (0, 500), (0, 600), (0, 900), (0, 1000)])
        intersection_points = [shg.Point(0, 500 + parameters.MIN_ROAD_SEGMENT_LENGTH * 0.1)]
        cut_ways_dict = _cut_way_at_intersection_points(intersection_points, way, my_line, coords_transform, nodes_dict)
        self.assertEqual(2, len(cut_ways_dict), 'number of ways: ' + msg)
        self.assertEqual(4, len(way.refs), 'references of orig way: ' + msg)
