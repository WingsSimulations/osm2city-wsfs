# SPDX-FileCopyrightText: (C) 2014 - 2025, rick@vanosten.net, radi, portree_kid
# SPDX-License-Identifier: GPL-2.0-or-later

import copy
import logging
import math
import unittest
from typing import override

import numpy as np
import scipy.interpolate as si
import shapely.geometry as shg

from osm2city import parameters
from osm2city.textures import materials as mat
from osm2city.textures import road
from osm2city.utils import ac3d
from osm2city.utils import coordinates as co
import osm2city.utils.elev_probe as ep
from osm2city.utils import osmparser as op
from osm2city.static_types import enumerations as e
from osm2city.static_types import osmstrings as s
from osm2city.static_types import types as t


def get_lit_type(tags: t.OSMTags) -> e.LitType:
    """Cf. https://taginfo.openstreetmap.org/keys/lit#values and https://wiki.openstreetmap.org/wiki/Key:lit"""
    if s.K_LIT in tags:
        if tags[s.K_LIT] in (s.V_YES, s.V_TRUE, s.V_SUNSET_SUNRISE, s.V_24_7):
            return e.LitType.yes
        if tags[s.K_LIT] in (s.V_NO, s.V_FALSE, s.V_DISUSED):
            return e.LitType.no
    return e.LitType.unknown


class WaySegment:
    """A segment of a linear_obj as a temporary storage to process nodes attributes for layers"""
    __slots__ = ('way', 'start_layer', 'end_layer', 'nodes')

    def __init__(self, way: op.Way) -> None:
        self.way = way
        self.nodes = list()

    def add_node(self, node: op.Node) -> None:
        self.nodes.append(node)

    @property
    def number_of_nodes(self) -> int:
        return len(self.nodes)

    @staticmethod
    def split_way_into_way_segments(way: op.Way, nodes_dict: dict[t.OSMId, op.Node]) -> list['WaySegment']:
        """Split is only done when a node has a layer for the specific linear_obj.

        A segment can start and/or stop at a node, which does not have a layer attribute."""
        segments = list()
        the_segment = WaySegment(way)
        the_segment.add_node(nodes_dict[way.refs[0]])
        for i in range(1, len(way.refs)):
            next_node = nodes_dict[way.refs[i]]
            the_segment.add_node(next_node)
            if the_segment.number_of_nodes == 2:
                segments.append(the_segment)
            if the_segment.number_of_nodes > 1 and next_node.layer_for_way(way) >= 0:
                the_segment = WaySegment(way)
                the_segment.add_node(next_node)
        return segments

    def calc_missing_layers_for_nodes(self) -> None:
        """Make sure each node of the segment gets a layer for the linear_obj assigned.

        Unless none of the nodes has a node with a layer at start or end (i.e. a Way in osm2city disconnected from
        other ways).
        If there is no end or start layer, then all nodes take over from the one node with a layer.
        If there is both an end and a start layer, then it is distributed half/half.
        We do NOT gradually go from e.g. layer 5 to e.g. 2, because if two ways follow each other in a shallow
        angle (e.g. junction to motorway), we want to avoid z-fighting as much as possible."""
        start_layer = self.nodes[0].layer_for_way(self.way)
        end_layer = self.nodes[-1].layer_for_way(self.way)
        if start_layer < 0 and end_layer < 0:
            start_layer = 0
            end_layer = 0
        elif start_layer < 0:
            start_layer = end_layer
        elif end_layer < 0:
            end_layer = start_layer

        switch_point = int(len(self.nodes) / 2 + 0.5) - 1
        layer = start_layer
        for i in range(0, len(self.nodes)):
            if i > switch_point:
                layer = end_layer
            self.nodes[i].layers[self.way] = layer


class LinearObject(object):
    """
    generic linear feature, base class for road, railroad, bridge etc.
    - source is a center line (OSM way)
    - parallel_offset (left, right)
    - texture

    - 2d:   roads, railroads. Draped onto terrain.
    - 2.5d: platforms. Height, but no bottom surface.
            roads with (one/two-sided) embankment.
            set angle of embankment
    - 3d:   bridges. Surfaces all around.

    possible cases:
    1. roads: left/right LS given. No v_add. Small gradient.
      -> probe z, paint on surface
    1a. roads, side. left Nodes given, right LS given. Probe right_z.
    2. embankment: center and left/right given, v_add.
      -> probe z, add v_add
    3. bridge:

    """

    def __init__(self, transform: co.Transformation, way: op.Way, nodes_dict: dict[t.OSMId, op.Node],
                 lit_areas: list[shg.Polygon],
                 width: float, material_name: str, tex_coords: tuple[float, float] = road.EMBANKMENT_1):
        self.width = width
        self.material_name: str = material_name  # for WS30 line_feature_list
        self.way = way

        self.vectors = None  # numpy array defined in compute_angle_etc()
        self.normals = None  # numpy array defined in compute_angle_etc()
        self.angle = None  # numpy array defined in compute_angle_etc()
        self.segment_len = None  # numpy array defined in compute_angle_etc()
        self.dist = None  # numpy array defined in compute_angle_etc()

        osm_nodes: list[op.Node] = [nodes_dict[r] for r in way.refs]
        nodes: list[tuple[float, float]] = [transform.to_local((n.lon, n.lat)) for n in osm_nodes]
        self.center = shg.LineString(nodes)
        self.lighting: list[bool] = list()  # same number of elements as self.center
        self._prepare_lighting(nodes, lit_areas)
        try:
            self._compute_angle_etc()
            self.left, self.right = self._compute_sides(self.width / 2.)  # LineStrings
        except Warning as reason:
            logging.warning("Warning in OSM_ID %i: %s", self.way.osm_id, reason)
        self.tex = tex_coords  # determines which part of texture we use

        # set in roads.py
        self.junction0 = None  # linear_transportation.Junction - first node in the linear object
        self.junction1 = None  # utils.graph.Junction - last node in the linear object

    def _prepare_lighting(self, nodes: list[tuple[float, float]], lit_areas: list[shg.Polygon]) -> None:
        """Checks each node of the way whether it is in a lit area and creates a bool in a list"""
        if get_lit_type(self.way.tags) is e.LitType.yes:
            for _ in nodes:
                self.lighting.append(True)
            return
        if get_lit_type(self.way.tags) is e.LitType.no:
            for _ in nodes:
                self.lighting.append(False)
            return

        # only if LitType is unknown, then we do probe
        for node in nodes:
            point = shg.Point(node)
            is_lit = False
            for area in lit_areas:
                if area.contains(point):
                    is_lit = True
                    break
            self.lighting.append(is_lit)

    def _compute_sides(self, offset: float) -> tuple[shg.LineString, shg.LineString]:
        """Given an offset (ca. half of width) calculate left and right sides including taking care of angles."""
        n = len(self.center.coords)
        left = np.zeros((n, 2))
        right = np.zeros((n, 2))
        our_node = np.array(self.center.coords[0])
        left[0] = our_node + self.normals[0] * offset
        right[0] = our_node - self.normals[0] * offset
        for i in range(1, n - 1):
            mean_normal = (self.normals[i - 1] + self.normals[i])
            length = (mean_normal[0] ** 2 + mean_normal[1] ** 2) ** 0.5
            mean_normal /= length
            angle = (np.pi + self.angle[i - 1] - self.angle[i]) / 2.
            if abs(angle) < 0.0175:  # 1 deg
                raise ValueError('AGAIN angle > 179 in OSM_ID %i with refs %s' % (self.way.osm_id, str(self.way.refs)))
            o = abs(offset / math.sin(angle))
            our_node = np.array(self.center.coords[i])
            left[i] = our_node + mean_normal * o
            right[i] = our_node - mean_normal * o

        our_node = np.array(self.center.coords[-1])
        left[-1] = our_node + self.normals[-1] * offset
        right[-1] = our_node - self.normals[-1] * offset

        left = shg.LineString(left)
        right = shg.LineString(right)

        return left, right

    def _compute_angle_etc(self):
        """Compute normals, angle, segment_length, accumulated distance start"""
        n = len(self.center.coords)

        self.vectors = np.zeros((n - 1, 2))
        self.normals = np.zeros((n, 2))
        self.angle = np.zeros(n)
        self.segment_len = np.zeros(n)  # segment_len[-1] = 0, so loops over range(n) wont fail
        self.dist = np.zeros(n)
        cumulated_distance = 0.
        for i in range(n - 1):
            vector = np.array(self.center.coords[i + 1]) - np.array(self.center.coords[i])
            dx, dy = vector
            self.angle[i] = math.atan2(dy, dx)
            angle = np.pi - abs(self.angle[i - 1] - self.angle[i])
            if i > 0 and abs(angle) < 0.0175:  # 1 deg
                raise ValueError('CONSTR angle > 179 in OSM_ID %i at (%i, %i) with refs %s'
                                 % (self.way.osm_id, i, i - 1, str(self.way.refs)))

            self.segment_len[i] = (dy * dy + dx * dx) ** 0.5
            if self.segment_len[i] == 0:
                logging.error("osm id: %i contains a segment with zero len", self.way.osm_id)
                self.normals[i] = np.array((-dy, dx)) / 0.00000001
            else:
                self.normals[i] = np.array((-dy, dx)) / self.segment_len[i]
            cumulated_distance += self.segment_len[i]
            self.dist[i + 1] = cumulated_distance
            self.vectors[i] = vector

        self.normals[-1] = self.normals[-2]
        self.angle[-1] = self.angle[-2]

    def _write_nodes(self, obj: ac3d.Object, line_string: shg.LineString, z: list[float],
                     join: bool = False, is_left: bool = False) -> list[int]:
        """Given a LineString and z, write nodes to .ac.
           Return nodes_list
        """
        to_write = copy.copy(line_string.coords)
        nodes_list = []
        if not join:
            nodes_list += list(obj.next_node_index() + np.arange(len(to_write)))
        else:
            if self.junction0 is not None and len(self.junction0) == 2:
                try:
                    # if other node already exists, do not write a new one
                    other_node = self.junction0.get_other_node(self, is_left)  # other nodes already written:
                    to_write = to_write[1:]
                    z = z[1:]
                    nodes_list.append(other_node)
                except KeyError:
                    self.junction0.set_other_node(self, is_left, obj.next_node_index())

            # -- make list with all but last node -- we might add last node later
            nodes_list += list(obj.next_node_index() + np.arange(len(to_write) - 1))
            last_node = obj.next_node_index() + len(to_write) - 1

            if self.junction1 is not None and len(self.junction1) == 2:
                try:
                    # if other node already exists, do not write a new one
                    other_node = self.junction1.get_other_node(self, is_left)  # other nodes already written:
                    to_write = to_write[:-1]
                    z = z[:-1]
                    nodes_list.append(other_node)
                except KeyError:
                    self.junction1.set_other_node(self, is_left, last_node)
                    nodes_list.append(last_node)
            else:
                nodes_list.append(last_node)

        for i, the_node in enumerate(to_write):
            elev = z[i]
            ground_elev = co.calc_horizon_elev_local(the_node[0], the_node[1])
            obj.node(-(the_node[1]), elev - ground_elev, -(the_node[0]))

        return nodes_list

    def _write_quads(self, obj: ac3d.Object, left_nodes_list, right_nodes_list, tex_y0, tex_y1,
                     check_lit: bool = False) -> None:
        """Write a series of quads bound by left and right.
        Left/right are lists of node indices which will be used to form a series of quads.
        Material index tells whether it is lit or not.
        """
        n_nodes = len(left_nodes_list)
        assert (len(left_nodes_list) == len(right_nodes_list))
        for i in range(n_nodes - 1):
            mat_idx = mat.Material.unlit
            if check_lit:
                if self.lighting[i] or self.lighting[i + 1]:
                    mat_idx = mat.Material.lit
            xl = self.dist[i] / road.LENGTH
            xr = self.dist[i + 1] / road.LENGTH
            face = [(left_nodes_list[i], xl, tex_y0),
                    (left_nodes_list[i + 1], xr, tex_y0),
                    (right_nodes_list[i + 1], xr, tex_y1),
                    (right_nodes_list[i], xl, tex_y1)]
            obj.face(face[::-1], mat_idx=mat_idx.value)

    def _probe_ground(self, fg_elev: ep.FGElev, line_string: shg.LineString,
                      nodes_dict: dict[t.OSMId, op.Node]) -> list[float]:
        """Probe ground elevation along the given line string, return array"""
        z_array: list[float] = [fg_elev.probe_elev((the_node[0], the_node[1])) for the_node in line_string.coords]
        for i in range(0, len(self.way.refs)):
            node = nodes_dict[self.way.refs[i]]
            layer = node.layer_for_way(self.way)
            if not parameters.USE_LINE_FEATURE_LIST_FOR_ROADS:
                if layer > 0:
                    z_array[i] += layer * parameters.DISTANCE_BETWEEN_LAYERS
                z_array[i] += parameters.MIN_ABOVE_GROUND_LEVEL
        return z_array

    def _get_v_add(self, fg_elev: ep.FGElev, nodes_dict: dict[t.OSMId, op.Node]) -> tuple[list[float], list[float]]:
        """Got v_add data for first and last node. Now lift intermediate nodes.
        So far, v_add is for the centre line only.
        """
        first_node: op.Node = nodes_dict[self.way.refs[0]]
        last_node: op.Node = nodes_dict[self.way.refs[-1]]

        center_z: list[float] = self._probe_ground(fg_elev, self.center, nodes_dict)

        epsilon = 0.001

        assert (len(self.left.coords) == len(self.right.coords))
        n_nodes = len(self.left.coords)
        v_add: list[float]

        v_add_0 = first_node.v_add
        v_add_1 = last_node.v_add
        dh_dx = max_slope_for_road(self)
        msl_0 = center_z[0] + v_add_0
        msl_1 = center_z[-1] + v_add_1

        if v_add_0 <= epsilon and v_add_1 <= epsilon:
            v_add = [0.] * n_nodes
        elif v_add_0 <= epsilon:
            v_add = [max(0, msl_1 - (self.dist[-1] - self.dist[i]) * dh_dx - center_z[i])
                     for i in range(n_nodes)]
        elif v_add_1 <= epsilon:
            v_add = [max(0, msl_0 - self.dist[i] * dh_dx - center_z[i]) for i in range(n_nodes)]
        else:
            v_add = [0.] * n_nodes
            for i in range(n_nodes):
                v_add[i] = max(0, msl_0 - self.dist[i] * dh_dx - center_z[i])
                if v_add[i] < epsilon:
                    break

            for i in range(n_nodes)[::-1]:
                other_v_add = v_add[i]
                v_add[i] = max(0, msl_1 - (self.dist[-1] - self.dist[i]) * dh_dx - center_z[i])
                if other_v_add > v_add[i]:
                    v_add[i] = other_v_add
                    break

        return v_add, center_z

    def _level_out(self, fg_elev: ep.FGElev, v_add: list[float],
                   nodes_dict: dict[t.OSMId, op.Node]) -> tuple[list[float], list[float]]:
        """Given v_add, set left_z and right_z to stay below MAX_TRANSVERSE_GRADIENT.
        v_add gets updated if there is a need to raise the surface.
        """
        left_z: list[float] = self._probe_ground(fg_elev, self.left, nodes_dict)
        right_z: list[float] = self._probe_ground(fg_elev, self.right, nodes_dict)

        diff_elev: list[float] = [a - b for a, b in zip(left_z, right_z)]
        for i, the_diff in enumerate(diff_elev):
            # -- v_add larger than terrain gradient:
            #    terrain gradient doesn't matter, just create level road at v_add
            if v_add[i] > abs(the_diff / 2.):
                left_z[i] += (v_add[i] - the_diff / 2.)
                right_z[i] += (v_add[i] + the_diff / 2.)
            else:
                # v_add smaller than terrain gradient.
                # In case terrain gradient is significant, create levelled
                # road which is then higher than v_add anyway.
                # Otherwise, create sloped road and ignore v_add.
                if the_diff / self.width > parameters.MAX_TRANSVERSE_GRADIENT:  # left > right
                    right_z[i] += the_diff  # dirty
                    v_add[i] += the_diff / 2.
                elif -the_diff / self.width > parameters.MAX_TRANSVERSE_GRADIENT:  # right > left
                    left_z[i] += - the_diff  # dirty
                    v_add[i] -= the_diff / 2.  # the_diff is negative
                else:
                    # terrain gradient negligible and v_add small
                    pass
        return left_z, right_z

    def _update_v_add_on_nodes(self, z: list[float], nodes_dict: dict[t.OSMId, op.Node]) -> None:
        """We update the v_add on nodes, such that it can be used after linear objects have been written.
        E.g. for railway overhead lines.
        """
        for index in range(len(self.way.refs)):
            node = nodes_dict[self.way.refs[index]]
            node.v_add = z[index] - node.msl

    def write_to(self, obj: ac3d.Object, fg_elev: ep.FGElev, nodes_dict: dict[t.OSMId, op.Node]) -> None:
        """
           assume we are a street: flat (or elevated) on terrain, left and right edges
           #need adjacency info
           #left: node index of left
           #right:
           offset accounts for tile center
        """
        v_add, center_z = self._get_v_add(fg_elev, nodes_dict)
        left_z, right_z = self._level_out(fg_elev, v_add, nodes_dict)

        left_nodes_list = self._write_nodes(obj, self.left, left_z, join=True, is_left=True)
        right_nodes_list = self._write_nodes(obj, self.right, right_z, join=True, is_left=False)

        self._write_quads(obj, left_nodes_list, right_nodes_list, self.tex[0], self.tex[1], True)
        # Side walls of embankment
        if max(v_add) > parameters.MIN_EMBANKMENT_HEIGHT:
            left_ground_z: list[float] = self._probe_ground(fg_elev, self.left, nodes_dict)
            right_ground_z: list[float] = self._probe_ground(fg_elev, self.right, nodes_dict)

            left_ground_nodes = self._write_nodes(obj, self.left, left_ground_z)
            right_ground_nodes = self._write_nodes(obj, self.right, right_ground_z)
            self._write_quads(obj, left_ground_nodes, left_nodes_list, parameters.EMBANKMENT_TEXTURE[0],
                              parameters.EMBANKMENT_TEXTURE[1])
            self._write_quads(obj, right_nodes_list, right_ground_nodes, parameters.EMBANKMENT_TEXTURE[0],
                              parameters.EMBANKMENT_TEXTURE[1])

        self._update_v_add_on_nodes(left_z, nodes_dict)


class DeckShapeLinear(object):
    def __init__(self, h0: float, h1: float) -> None:
        self.h0 = h0  # height of start node (msl)
        self.h1 = h1  # height of end node (msl)

    def _compute(self, x: float) -> float:
        return (1-x) * self.h0 + x * self.h1

    def __call__(self, ratio):
        try:
            return [self._compute(x) for x in ratio]
        except TypeError:
            return self._compute(ratio)


class LinearBridge(LinearObject):
    def __init__(self, transform: co.Transformation, fg_elev: ep.FGElev, way: op.Way, nodes_dict: dict[t.OSMId, op.Node],
                 lit_areas: list[shg.Polygon],
                 width: float, material_name: str, tex_coords: tuple[float, float] = road.EMBANKMENT_2):
        super().__init__(transform, way, nodes_dict, lit_areas, width, material_name, tex_coords)
        # -- prepare elevation spline
        #    probe elev at n_probes locations
        n_probes = max(int(self.center.length / 5.), 3)
        probe_locations_nondim = np.linspace(0, 1., n_probes)
        elevs = np.zeros(n_probes)
        for i, l in enumerate(probe_locations_nondim):
            local_point = self.center.interpolate(l, normalized=True)
            elevs[i] = fg_elev.probe_elev((local_point.coords[0][0], local_point.coords[0][1]))
        self.elev_spline: si.interp1d = si.interp1d(probe_locations_nondim, elevs)
        self._prep_height(nodes_dict, fg_elev)

        # properties
        self.pillar_r0 = 0.
        self.pillar_r1 = 0.
        self.pillar_nnodes = 0

    def _elev(self, linear_dist: list[float], normalized: bool = True):
        """Given linear distance [m], interpolate and return terrain elevation for a point at distance on the line"""
        if not normalized:
            linear_dist /= self.center.length
        return self.elev_spline(linear_dist)

    def _prep_height(self, nodes_dict: dict[t.OSMId, op.Node], fg_elev: ep.FGElev):
        """Preliminary deck shape depending on elevations. Write required v_add to end nodes.

        msl ... (metres above sea level) is for values from probing the terrain.
        deck_msl ... are corrected to fulfill constraints:
            * if the bridge has a LAYER tag, then the middle of the bridge needs to be at least as much above the
              terrain (msl) I.e. msl + parameters.BRIDGE_LAYER_HEIGHT
            * if the bridge does not have a LAYER tag, then it is assumed 0 (default in OSM) and the middle of the
              bridge needs to be at least parameters.BRIDGE_MIN_HEIGHT above terrain.
            * the start and end of the bridge must be at least 1 metre (hard-coded) above the terrain.

        Theoretically, using the middle to check the constraints (especially for LAYER) is a bit arbitrary, because
        another way could be very close below either end of the bridge - and the middle does not have to be the
        highest point. It is just a bit easier to do like this - and often with sufficiently good results.
        """
        node_first = nodes_dict[self.way.refs[0]]
        node_last = nodes_dict[self.way.refs[-1]]

        msl_mid = self._elev([0.5])

        msl = np.array([fg_elev.probe_elev((the_node[0], the_node[1])) for the_node in self.center.coords])

        deck_msl = msl.copy()
        deck_msl[0] += node_first.v_add
        deck_msl[-1] += node_last.v_add

        if deck_msl[-1] > deck_msl[0]:
            hi_end = -1
            lo_end = 0
        else:
            hi_end = 0
            lo_end = -1
        self.deck_shape_linear = DeckShapeLinear(deck_msl[0], deck_msl[-1])
        try:
            required_height = parameters.BRIDGE_LAYER_HEIGHT * int(self.way.tags[s.K_LAYER])
        except KeyError:
            required_height = parameters.BRIDGE_MIN_HEIGHT  # e.g. if bridge over water

        if (self.deck_shape_linear(0.5) - msl_mid) > required_height:
            return

        dh_dx = max_slope_for_road(self)

        # need to elevate one or both ends
        deck_msl_mid = msl_mid + required_height
        if deck_msl[hi_end] > deck_msl_mid:  # only elevate lower end
            deck_msl[lo_end] = max(deck_msl[hi_end] - 2 * (deck_msl[hi_end] - deck_msl_mid),
                                   deck_msl[hi_end] - dh_dx * self.center.length)
        else:  # elevate both ends to same msl
            deck_msl[hi_end] = deck_msl[lo_end] = deck_msl_mid

        v_add = np.maximum(deck_msl - msl, np.ones_like(deck_msl))  # makes sure that at least 1 metre above

        _, _ = self._level_out(fg_elev, v_add, nodes_dict)
        deck_msl = msl + v_add

        self.deck_shape_linear = DeckShapeLinear(deck_msl[0], deck_msl[-1])

        node_first.v_add = v_add[0]
        node_last.v_add = v_add[-1]

    def _deck_height(self, linear_dist: float, normalized: bool = True):
        """Given linear distance [m], interpolate and return deck height"""
        if not normalized and self.center.length != 0:
            linear_dist /= self.center.length
        return self.deck_shape_linear(linear_dist)

    def _pillar(self, obj: ac3d.Object, x: float, y: float, h0: float, h1: float, angle: float):
        self.pillar_r0 = 1.
        self.pillar_r1 = 0.5
        self.pillar_nnodes = 8

        ground_elev = co.calc_horizon_elev_local(x, y)

        rx = self.pillar_r0
        ry = self.pillar_r1

        nodes_list = []
        ofs = obj.next_node_index()
        vert = ""
        r = np.array([[np.cos(-angle), -np.sin(-angle)],
                      [np.sin(-angle),  np.cos(-angle)]])
        for a in np.linspace(0, 2*np.pi, self.pillar_nnodes, endpoint=False):
            a += np.pi/self.pillar_nnodes
            node = np.array([rx*np.cos(a), ry*np.sin(a)])
            node = np.dot(r, node)
            obj.node(-(y+node[0]), h1 - ground_elev, -(x+node[1]))
        for a in np.linspace(0, 2*np.pi, self.pillar_nnodes, endpoint=False):
            a += np.pi/self.pillar_nnodes
            node = np.array([rx*np.cos(a), ry*np.sin(a)])
            node = np.dot(r, node)
            obj.node(-(y+node[0]), h0 - ground_elev, -(x+node[1]))

        for i in range(self.pillar_nnodes-1):
            face = [(ofs + i, 0, road.BOTTOM[0]),
                    (ofs + i + 1, 1, road.BOTTOM[0]),
                    (ofs + i + 1 + self.pillar_nnodes, 1, road.BOTTOM[1]),
                    (ofs + i + self.pillar_nnodes, 0, road.BOTTOM[1])]
            obj.face(face)

        i = self.pillar_nnodes - 1
        face = [(ofs + i, 0, road.BOTTOM[0]),
                (ofs, 1, road.BOTTOM[0]),
                (ofs + self.pillar_nnodes, 1, road.BOTTOM[1]),
                (ofs + i + self.pillar_nnodes, 0, road.BOTTOM[1])]
        obj.face(face)

        nodes_list.append(face)

        return ofs + 2*self.pillar_nnodes, vert, nodes_list

    @override
    def write_to(self, obj: ac3d.Object, fg_elev: ep.FGElev, nodes_dict: dict[t.OSMId, op.Node]) -> None:
        """
        write
        - deck
        - sides
        - bottom
        - pillars

        needs
        - pillar positions
        - deck elev
        -
        """
        n_nodes = len(self.left.coords)
        z = np.zeros(n_nodes)  # deck height
        length = 0.
        for i in range(n_nodes):
            z[i] = self._deck_height(length, normalized=False)
            node = nodes_dict[self.way.refs[i]]
            layer = node.layer_for_way(self.way)
            if parameters.USE_LINE_FEATURE_LIST_FOR_ROADS is False:
                if layer > 0:
                    z[i] += layer * parameters.DISTANCE_BETWEEN_LAYERS
                z[i] += parameters.MIN_ABOVE_GROUND_LEVEL
            length += self.segment_len[i]

        left_top_nodes = self._write_nodes(obj, self.left, z, join=True, is_left=True)
        right_top_nodes = self._write_nodes(obj, self.right, z, join=True, is_left=False)

        left_bottom_edge, right_bottom_edge = self._compute_sides(self.width / 2 * 0.85)
        left_bottom_nodes = self._write_nodes(obj, left_bottom_edge, z - parameters.BRIDGE_BODY_HEIGHT)
        right_bottom_nodes = self._write_nodes(obj, right_bottom_edge, z - parameters.BRIDGE_BODY_HEIGHT)
        # -- top
        self._write_quads(obj, left_top_nodes, right_top_nodes, self.tex[0], self.tex[1], True)

        # -- right
        self._write_quads(obj, right_top_nodes, right_bottom_nodes, road.BRIDGE_1[1],
                          road.BRIDGE_1[0])

        # -- left
        self._write_quads(obj, left_bottom_nodes, left_top_nodes, road.BRIDGE_1[0], road.BRIDGE_1[1])

        # -- bottom
        self._write_quads(obj, right_bottom_nodes, left_bottom_nodes, road.BOTTOM[0], road.BOTTOM[1])

        # -- end wall 1
        the_node = self.left.coords[0]
        elev = fg_elev.probe_elev(the_node)
        ground_elev = co.calc_horizon_elev_local(the_node[0], the_node[1])
        left_bottom_node = obj.node(-the_node[1], elev - ground_elev, -the_node[0])

        the_node = self.right.coords[0]
        elev = fg_elev.probe_elev(the_node)
        ground_elev = co.calc_horizon_elev_local(the_node[0], the_node[1])
        right_bottom_node = obj.node(-the_node[1], elev - ground_elev, -the_node[0])

        face = [(left_top_nodes[0], 0, parameters.EMBANKMENT_TEXTURE[0]),
                (right_top_nodes[0], 0, parameters.EMBANKMENT_TEXTURE[1]),
                (right_bottom_node, 1, parameters.EMBANKMENT_TEXTURE[1]),
                (left_bottom_node, 1, parameters.EMBANKMENT_TEXTURE[0])]
        obj.face(face)

        # -- end wall 2
        the_node = self.left.coords[-1]
        elev = fg_elev.probe_elev(the_node)
        ground_elev = co.calc_horizon_elev_local(the_node[0], the_node[1])
        left_bottom_node = obj.node(-the_node[1], elev - ground_elev, -the_node[0])

        the_node = self.right.coords[-1]
        elev = fg_elev.probe_elev(the_node)
        ground_elev = co.calc_horizon_elev_local(the_node[0], the_node[1])
        right_bottom_node = obj.node(-the_node[1], elev - ground_elev, -the_node[0])

        face = [(left_top_nodes[-1], 0, parameters.EMBANKMENT_TEXTURE[0]),
                (right_top_nodes[-1], 0, parameters.EMBANKMENT_TEXTURE[1]),
                (right_bottom_node, 1, parameters.EMBANKMENT_TEXTURE[1]),
                (left_bottom_node, 1, parameters.EMBANKMENT_TEXTURE[0])]
        obj.face(face[::-1])

        # pillars
        for i in range(1, n_nodes-1):
            z0 = fg_elev.probe_elev((self.center.coords[i][0], self.center.coords[i][1])) - 1.
            point = self.center.coords[i]
            self._pillar(obj, point[0], point[1], z0, z[i], self.angle[i])

        self._update_v_add_on_nodes(z, nodes_dict)


def max_slope_for_road(obj: LinearObject) -> float:
    # must be aligned with accepted railways in Roads._create_linear_objects
    if s.K_RAILWAY in obj.way.tags:
        if s.is_rack_railway(obj.way.tags):
            return parameters.MAX_SLOPE_RACK
        if obj.way.tags[s.K_RAILWAY] == s.V_TRAM:
            return parameters.MAX_SLOPE_TRAM
        return parameters.MAX_SLOPE_RAILWAY
    else:  # s.K_HIGHWAY
        if obj.way.tags[s.K_HIGHWAY] in [s.V_MOTORWAY]:
            return parameters.MAX_SLOPE_MOTORWAY
    return parameters.MAX_SLOPE_ROAD


# ================ UNITTESTS =======================

class TestLinear(unittest.TestCase):
    def test_assign_missing_node_layers(self) -> None:
        nodes_dict = dict()
        coords_transform = co.Transformation.create_zero_zero_transformation()
        way = op.Way(t.OSMId(1))
        way.tags["hello"] = "world"
        lon, lat = coords_transform.to_global((0, 0))
        node_1 = op.Node(t.OSMId(1), lat, lon)
        nodes_dict[1] = node_1
        lon, lat = coords_transform.to_global((0, 300))
        node_2 = op.Node(t.OSMId(2), lat, lon)
        nodes_dict[2] = node_2
        lon, lat = coords_transform.to_global((0, 500))
        node_3 = op.Node(t.OSMId(3), lat, lon)
        nodes_dict[3] = node_3
        lon, lat = coords_transform.to_global((0, 600))
        node_4 = op.Node(t.OSMId(4), lat, lon)
        nodes_dict[4] = node_4
        node_4.layers[way] = 4  # just use the index as layer to make it easy
        lon, lat = coords_transform.to_global((0, 900))
        node_5 = op.Node(t.OSMId(5), lat, lon)
        nodes_dict[5] = node_5
        node_5.layers[way] = 5
        lon, lat = coords_transform.to_global((0, 1000))
        node_6 = op.Node(t.OSMId(6), lat, lon)
        nodes_dict[6] = node_6
        node_6.layers[way] = 6

        # test the splitting into segments
        way.refs = [t.OSMId(4), t.OSMId(5)]
        segments = WaySegment.split_way_into_way_segments(way, nodes_dict)
        self.assertEqual(1, len(segments), '2 nodes both having layers')

        way.refs = [t.OSMId(1), t.OSMId(2)]
        segments = WaySegment.split_way_into_way_segments(way, nodes_dict)
        self.assertEqual(1, len(segments), '2 nodes none having layers')

        way.refs = [t.OSMId(1), t.OSMId(4), t.OSMId(5)]
        segments = WaySegment.split_way_into_way_segments(way, nodes_dict)
        self.assertEqual(2, len(segments), '3 nodes last 2 having layers')

        way.refs = [t.OSMId(4), t.OSMId(5), t.OSMId(1)]
        segments = WaySegment.split_way_into_way_segments(way, nodes_dict)
        self.assertEqual(2, len(segments), '3 nodes last having no layers')

        way.refs = [t.OSMId(4), t.OSMId(1), t.OSMId(5)]
        segments = WaySegment.split_way_into_way_segments(way, nodes_dict)
        self.assertEqual(1, len(segments), '3 nodes middle having no layers')

        # test layers
        way.refs = [t.OSMId(1), t.OSMId(2)]
        my_segment = WaySegment.split_way_into_way_segments(way, nodes_dict)[0]
        my_segment.calc_missing_layers_for_nodes()
        self.assertEqual(0, my_segment.nodes[0].layers[way], 'First node in 2 nodes none having layers')
        self.assertEqual(0, my_segment.nodes[1].layers[way], 'Second node in 2 nodes none having layers')

        way.refs = [t.OSMId(4), t.OSMId(5)]
        my_segment = WaySegment.split_way_into_way_segments(way, nodes_dict)[0]
        my_segment.calc_missing_layers_for_nodes()
        self.assertEqual(4, my_segment.nodes[0].layers[way], 'First node in 2 nodes with having layers')
        self.assertEqual(5, my_segment.nodes[1].layers[way], 'Second node in 2 nodes with having layers')

        way.refs = [t.OSMId(1), t.OSMId(2), t.OSMId(4)]
        del node_1.layers[way]
        del node_2.layers[way]
        my_segment = WaySegment.split_way_into_way_segments(way, nodes_dict)[0]
        my_segment.calc_missing_layers_for_nodes()
        self.assertEqual(4, my_segment.nodes[0].layers[way], 'First node in 3 nodes last having layers')
        self.assertEqual(4, my_segment.nodes[1].layers[way], 'Second node in 3 nodes last having layers')
        self.assertEqual(4, my_segment.nodes[2].layers[way], 'Third node in 3 nodes last having layers')

        way.refs = [t.OSMId(5), t.OSMId(1), t.OSMId(2)]
        del node_1.layers[way]
        del node_2.layers[way]
        my_segment = WaySegment.split_way_into_way_segments(way, nodes_dict)[0]
        my_segment.calc_missing_layers_for_nodes()
        self.assertEqual(5, my_segment.nodes[0].layers[way], 'First node in 3 nodes first having layers')
        self.assertEqual(5, my_segment.nodes[1].layers[way], 'Second node in 3 nodes first having layers')
        self.assertEqual(5, my_segment.nodes[2].layers[way], 'Third node in 3 nodes first having layers')

        way.refs = [t.OSMId(6), t.OSMId(1), t.OSMId(4)]
        del node_1.layers[way]
        my_segment = WaySegment.split_way_into_way_segments(way, nodes_dict)[0]
        my_segment.calc_missing_layers_for_nodes()
        self.assertEqual(6, my_segment.nodes[0].layers[way], 'First node in 3 nodes middle having no layers')
        self.assertEqual(6, my_segment.nodes[1].layers[way], 'Second node in 3 nodes middle having no layers')
        self.assertEqual(4, my_segment.nodes[2].layers[way], 'Third node in 3 nodes middle having no layers')

        way.refs = [t.OSMId(6), t.OSMId(1), t.OSMId(2), t.OSMId(3), t.OSMId(4)]
        del node_1.layers[way]
        del node_2.layers[way]
        my_segment = WaySegment.split_way_into_way_segments(way, nodes_dict)[0]
        my_segment.calc_missing_layers_for_nodes()
        self.assertEqual(6, my_segment.nodes[0].layers[way], 'First node in 5 nodes middle having no layers')
        self.assertEqual(6, my_segment.nodes[1].layers[way], 'Second node in 5 nodes middle having no layers')
        self.assertEqual(6, my_segment.nodes[2].layers[way], 'Third node in 5 nodes middle having no layers')
        self.assertEqual(4, my_segment.nodes[3].layers[way], 'Forth node in 5 nodes middle having no layers')
        self.assertEqual(4, my_segment.nodes[4].layers[way], 'Fifth node in 5 nodes middle having no layers')
