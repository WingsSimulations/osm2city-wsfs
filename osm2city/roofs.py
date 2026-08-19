# SPDX-FileCopyrightText: (C) 2013 - 2026, rick@vanosten.net, radi, portree_kid, rogue
# SPDX-License-Identifier: GPL-2.0-or-later
from itertools import groupby
import logging
from math import sin, cos, radians, tan, sqrt, fabs
import random
import unittest

import shapely.geometry as shg

from osm2city import parameters
from osm2city.pySkeleton import mesh, polygon
from osm2city.static_types import enumerations as enu
from osm2city.static_types import osmstrings as s
import osm2city.textures.coverings as cov
import osm2city.utils.coordinates as coord
import osm2city.utils.gltf_io as gio


GAMBREL_ANGLE_LOWER_PART = 70
GAMBREL_HEIGHT_RATIO_LOWER_PART = 0.75


class RoofHint:
    """A set of hints for placing or constructing the roof.
    Not all buildings have a RoofHint - and most often only one of the fields will be available.

    See description in the 'how it works' section of the manual.

    If a building has an inner node, then no more simplifications should be done.

    Fields:
    * ridge_orientation: the orientation in degrees of the ridge - for gabled roofs with 4 edges. Only set
                         if there are neighbours and therefore the ridge should be aligned.
    * inner_node:        for L-shaped roofs due to neighbours or L-shaped building:
                         the node which is at the inner side in the ca. 90 deg corner as follows:
                         Tuple of tuple(lon, lat) in local coordinates.
                         The lon/lat instead of a node position is kept because due to geometry changes
                         the sequence of the outer ring could change. This way we can test.
    * node_before_inner_is_shared: only used for roof with 5 nodes to signal whether the node before inner is
                         a shared node with neighbour or after. Otherwise, there is not enough info to find the L.
    """
    __slots__ = ('ridge_orientation', 'inner_node', '_node_before_inner_is_shared')

    def __init__(self) -> None:
        self.ridge_orientation: float = -1.  # float >= 0. Only valid hint if >= 0 and then finally used in roofs.py
        self.inner_node: tuple[float, float] | None = None  # local x/y from lon/lat
        self._node_before_inner_is_shared: bool = False

    @property
    def node_before_inner_is_shared(self) -> bool:
        return self._node_before_inner_is_shared

    @node_before_inner_is_shared.setter
    def node_before_inner_is_shared(self, value: bool):
        """It is a bit special that the boolean is reversed. This is because in C++ the outer ring of a building
        is clock-wise, but in building.update_geometry() this is changed to be ccw. Therefore, 'before'
        gets 'after' and vice versa."""
        self._node_before_inner_is_shared = not value


def roof_looks_square(circumference: float, area: float) -> bool:
    """Determines if a roof's floor plan looks square.
    The formula basically states that if it was a rectangle, then the ratio between the long side length
    and the short side length should be at least 2.
    """
    if circumference < 3 * sqrt(2 * area):
        return True
    return False


def write_flat(geom_collector: gio.GeometryCollector3D, b) -> None:
    """Flat roof with or without inner rings/holes.
    """
    assert b.roof_covering is not None, 'Roof texture may not be None'
    assert b.roof_shape in (enu.RoofShape.skillion, enu.RoofShape.flat)

    outer_ring: list[gio.CVertexDTO] = list()
    idx: int = 0
    min_x: float = 99999.  # for texture uv mapping
    min_y: float = 99999.
    z_roof: float = b.beginning_of_roof_above_sea_level
    for i, pt in enumerate(b.pts_outer):
        if b.roof_shape is enu.RoofShape.skillion:
            z_roof += b.roof_height_pts[i]
        outer_ring.append(gio.CVertexDTO(gio.VertexId(idx), pt[0], pt[1], z_roof))
        idx += 1
        min_x = min(min_x, pt[0])
        min_y = min(min_y, pt[1])

    # We want the texture coordinates to be aligned with the longest edge
    outer_tuples: list[tuple[float, float]] = list()
    for pt in outer_ring:
        outer_tuples.append((pt.x, pt.y))
    angle_rotate: float  = coord.calc_angle_of_longest_edge(outer_tuples)  # relative to North
    angle_rotate = coord.calc_delta_bearing(90, angle_rotate)
    rotation_point: shg.Point = shg.Point(outer_tuples[0][0], outer_tuples[0][1])

    if not b.has_inner and len(outer_ring)  <= 4:  # we can add face directly without triangulation etc.
        geom_collector.add_faces_from_vertex_list([outer_ring], b.roof_covering, angle_rotate, rotation_point,
                                                  b.osm_id)
        return

    inner_rings: list[list[gio.CVertexDTO]] = list()
    for pt_list in b.pts_inner_list:
        inner_ring = list()
        for pt in pt_list:
            inner_ring.append(gio.CVertexDTO(gio.VertexId(idx), pt[0], pt[1], b.beginning_of_roof_above_sea_level))
            idx += 1
            min_x = min(min_x, pt[0])
            min_y = min(min_y, pt[1])
        inner_rings.append(inner_ring)

    geom_collector.add_polygon_face(outer_ring, inner_rings, b.roof_covering, angle_rotate, rotation_point, b.osm_id)

def write_skillion(geom_collector: gio.GeometryCollector3D, b) -> None:
    """Write a skillion roof to the geometry collector.
    By convention, the first two points are the low points of the roof.
    See building_lib.compute_roof_height
    """
    assert len(b.pts_outer) == 4
    vertices: list[gio.CVertexDTO] = list()
    for i, pt in enumerate(b.pts_outer):
        vertices.append(gio.CVertexDTO(gio.VertexId(i), pt[0], pt[1],
                        b.beginning_of_roof_above_sea_level + b.roof_height_pts[i]))
    _write_a_face(geom_collector, b.roof_covering, vertices)

def _write_a_face(geom_collector: gio.GeometryCollector3D, covering: cov.CCovering,
                  vertices: list[gio.CVertexDTO], is_facade_side: bool = False) -> None:
    """Write a piece of a roof to the geometry collector.

    If i_facade_side is true, then a special texture is used to mimic a facade side.
    """
    if len(vertices) == 4:
        geom_collector.add_c_face_dto(gio.CFaceDTO({  # front
            vertices[0]: gio.CTMap(0., 0., covering.repeat_type),
            vertices[1]: gio.CTMap(1., 0., covering.repeat_type),
            vertices[2]: gio.CTMap(1., 1., covering.repeat_type),
            vertices[3]: gio.CTMap(0., 1., covering.repeat_type)
        }, covering, False, None))
    elif len(vertices) == 3:
        geom_collector.add_c_face_dto(gio.CFaceDTO({  # front
            vertices[0]: gio.CTMap(0., 0., covering.repeat_type),
            vertices[1]: gio.CTMap(1., 0., covering.repeat_type),
            vertices[2]: gio.CTMap(0.5, 1., covering.repeat_type),
        }, covering, False, None))
    else:
        raise ValueError(f"Expected 4 vertices, got {len(vertices)}")

def _sanity_roof_height_complex(b, roof_type: str) -> float:
    if b.roof_height > 0.5:
        return b.roof_height
    else:
        logging.warning("no valid roof_height in %s for building %i", roof_type, b.osm_id)
        return enu.BUILDING_LEVEL_HEIGHT_RURAL


def write_gable_with_corner(geom_collector: gio.GeometryCollector3D, b, roof_mat_idx: int, facade_mat_idx: int) -> None:
    """Create a gabled roof around a corner - there can be 4, 5, or 6 nodes.
    By convention, counting of nodes starts at the inner node (0) and is counter-clockwise.
    The nodes on the top are numbered as follows:
    * First gable counter-clockwise: node_10
    * Second gable counter-clockwise: node_11
    * Centre node on top where ridges meet: node_12

    See e.g. https://en.wikipedia.org/wiki/Roof#/media/File:Roof_diagram.jpg for the meaning of ridge, hip and eaves.
    """
    assert 4 <= len(b.pts_outer) <= 6

    roof_height: float = _sanity_roof_height_complex(b, 'gable_with_corner')

    # find the point closest to the RoofHint.inner_node
    shortest_dist: float = 99999
    shortest_index: int = 0
    num_nodes: int = len(b.pts_outer)
    index: int = -1  # enumerate over b.pts_outer does not seem to work due to ndarray
    for pt in b.pts_outer:
        index += 1
        dist = coord.calc_distance_local(pt[0], pt[1], b.roof_hint.inner_node[0], b.roof_hint.inner_node[1])
        if dist < shortest_dist:
            shortest_dist = dist
            shortest_index = index

    node_0 = b.pts_outer[shortest_index]
    node_1 = b.pts_outer[(shortest_index + 1) % num_nodes]
    node_2 = b.pts_outer[(shortest_index + 2) % num_nodes]
    node_3 = b.pts_outer[(shortest_index + 3) % num_nodes]
    node_4 = None
    node_5 = None
    if num_nodes > 4:
        node_4 = b.pts_outer[(shortest_index + 4) % num_nodes]
    if num_nodes == 6:
        node_5 = b.pts_outer[(shortest_index + 5) % num_nodes]

    # point_10: the first gable
    first_node = node_0
    second_node = node_1
    if num_nodes == 5:
        if b.roof_hint.node_before_inner_is_shared:
            first_node = node_1
            second_node = node_2
        # else same as for 4 nodes
    elif num_nodes == 6:
        first_node = node_1
        second_node = node_2
    node_10 = coord.calc_point_on_line_local(first_node[0], first_node[1],
                                             second_node[0], second_node[1],
                                             0.5)
    # point_11: the second gable
    first_node = node_3
    second_node = node_0
    if num_nodes == 5:
        if b.roof_hint.node_before_inner_is_shared:
            first_node = node_4
            second_node = node_0
        else:
            first_node = node_3
            second_node = node_4
    elif num_nodes == 6:
        first_node = node_4
        second_node = node_5
    node_11 = coord.calc_point_on_line_local(first_node[0], first_node[1],
                                             second_node[0], second_node[1],
                                             0.5)
    # point_12: the centre point
    first_node = node_0
    second_node = node_2
    if num_nodes == 5:
        if b.roof_hint.node_before_inner_is_shared:
            second_node = node_3
        # else same as for 4 nodes
    elif num_nodes == 6:
        second_node = node_3
    node_12 = coord.calc_point_on_line_local(first_node[0], first_node[1],
                                             second_node[0], second_node[1],
                                             0.5)

    # create the vertices
    vertices: dict[int, gio.CVertexDTO] = dict()
    vertices[0] = gio.CVertexDTO(gio.VertexId(0), node_0[0], node_0[1],
                                 b.beginning_of_roof_above_sea_level)
    vertices[1] = gio.CVertexDTO(gio.VertexId(1), node_1[0], node_1[1],
                                 b.beginning_of_roof_above_sea_level)
    vertices[2] = gio.CVertexDTO(gio.VertexId(2), node_2[0], node_2[1],
                                 b.beginning_of_roof_above_sea_level)
    vertices[3] = gio.CVertexDTO(gio.VertexId(3), node_3[0], node_3[1],
                                 b.beginning_of_roof_above_sea_level)
    if num_nodes > 4:
        vertices[4] = gio.CVertexDTO(gio.VertexId(4), node_4[0], node_4[1],
                                     b.beginning_of_roof_above_sea_level)

    if num_nodes == 6:
        vertices[5] = gio.CVertexDTO(gio.VertexId(5), node_5[0], node_5[1],
                                     b.beginning_of_roof_above_sea_level)

    vertices[10] = gio.CVertexDTO(gio.VertexId(10), node_10[0], node_10[1],
                                  b.beginning_of_roof_above_sea_level + roof_height)
    vertices[11] = gio.CVertexDTO(gio.VertexId(11), node_11[0], node_11[1],
                                  b.beginning_of_roof_above_sea_level + roof_height)
    vertices[12] = gio.CVertexDTO(gio.VertexId(12), node_12[0], node_12[1],
                                  b.beginning_of_roof_above_sea_level + roof_height)

    # now the faces
    if num_nodes == 4:
        # first inside roof side
        the_vertices: list[gio.CVertexDTO] = [vertices[0], vertices[10], vertices[12]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices)

        # first outside/back roof side
        the_vertices = [vertices[1], vertices[2], vertices[12], vertices[10]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices)

        # second outside/back roof side
        the_vertices = [vertices[2], vertices[3], vertices[11], vertices[12]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices)

        # second inside roof side
        the_vertices = [vertices[0], vertices[12], vertices[11]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices)

        # the sides where it is gabled and facade texture
        the_vertices = [vertices[0], vertices[1], vertices[10]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices, True)

        the_vertices = [vertices[3], vertices[0], vertices[11]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices, True)

    elif num_nodes == 5:
        if b.roof_hint.node_before_inner_is_shared:
            # first inside roof side
            the_vertices = [vertices[0], vertices[1], vertices[10], vertices[12]]
            _write_a_face(geom_collector, b.roof_covering, the_vertices)

            # first outside/back roof side
            the_vertices = [vertices[2], vertices[3], vertices[12], vertices[10]]
            _write_a_face(geom_collector, b.roof_covering, the_vertices)

            # second outside/back roof side
            the_vertices = [vertices[3], vertices[4], vertices[11], vertices[12]]
            _write_a_face(geom_collector, b.roof_covering, the_vertices)

            # second inside roof side
            the_vertices = [vertices[0], vertices[12], vertices[11]]
            _write_a_face(geom_collector, b.roof_covering, the_vertices)

            # the sides where it is gabled and facade texture
            the_vertices = [vertices[1], vertices[2], vertices[10]]
            _write_a_face(geom_collector, b.roof_covering, the_vertices, True)

            the_vertices = [vertices[4], vertices[0], vertices[11]]
            _write_a_face(geom_collector, b.roof_covering, the_vertices, True)
        else:
            # first inside roof side
            the_vertices = [vertices[0], vertices[10], vertices[12]]
            _write_a_face(geom_collector, b.roof_covering, the_vertices)

            # first outside/back roof side
            the_vertices = [vertices[1], vertices[2], vertices[12], vertices[10]]
            _write_a_face(geom_collector, b.roof_covering, the_vertices)

            # second outside/back roof side
            the_vertices = [vertices[2], vertices[3], vertices[11], vertices[12]]
            _write_a_face(geom_collector, b.roof_covering, the_vertices)

            # second inside roof side
            the_vertices = [vertices[4], vertices[0], vertices[12], vertices[11]]
            _write_a_face(geom_collector, b.roof_covering, the_vertices)

            # the sides where it is gabled and facade texture
            the_vertices = [vertices[0], vertices[1], vertices[10]]
            _write_a_face(geom_collector, b.roof_covering, the_vertices, True)

            the_vertices = [vertices[3], vertices[4], vertices[11]]
            _write_a_face(geom_collector, b.roof_covering, the_vertices, True)
    elif num_nodes == 6:
        # first inside roof side
        the_vertices = [vertices[0], vertices[1], vertices[10], vertices[12]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices)

        # first outside/back roof side
        the_vertices = [vertices[2], vertices[3], vertices[12], vertices[10]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices)

        # second outside/back roof side
        the_vertices = [vertices[3], vertices[4], vertices[11], vertices[12]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices)

        # second inside roof side
        the_vertices = [vertices[5], vertices[0], vertices[12], vertices[11]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices)

        # the sides where it is gabled and facade texture
        the_vertices = [vertices[1], vertices[2], vertices[10]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices, True)

        the_vertices = [vertices[4], vertices[5], vertices[11]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices, True)


def write_gabled_variants(geom_collector: gio.GeometryCollector3D, b) -> None:
    """Gabled or gambrel roof (or hipped if inward_meters > 0) with 4 nodes."""
    assert len(b.pts_outer) == 4
    roof_height:float = _sanity_roof_height_complex(b, 'gabled_variants')

    # get orientation if exits:
    osm_roof_orientation_exists: bool = False
    if s.K_ROOF_ORIENTATION in b.tags:
        osm_roof_orientation_exists = True
        osm_roof_orientation: str = str(b.tags[s.K_ROOF_ORIENTATION])
        if not (osm_roof_orientation in [s.V_ALONG, s.V_ACROSS]):
            osm_roof_orientation_exists = False
            osm_roof_orientation = s.V_ALONG
    else:
        osm_roof_orientation = s.V_ALONG

    # search smallest and longest sides
    i_small: int = 3
    i_long: int = 3
    l_side2: float = (b.pts_outer[0][0] - b.pts_outer[3][0])**2 + (b.pts_outer[0][1] - b.pts_outer[3][1])**2
    l_small: float = l_side2
    l_long:float  = l_side2
    
    for i in range(0, 3):
        l_side2 = (b.pts_outer[i+1][0] - b.pts_outer[i][0])**2 + (b.pts_outer[i+1][1] - b.pts_outer[i][1])**2
        if l_side2 > l_long:
            i_long = i
            l_long = l_side2
        elif l_side2 < l_small:
            i_small = i
            l_small = l_side2

    i_side = i_long  # i.e. "along"
    if osm_roof_orientation_exists:
        if osm_roof_orientation == s.V_ACROSS:
            i_side = i_small
    elif b.roof_hint is not None and b.roof_hint.ridge_orientation >= 0.:  # only override if we have neighbours
        # calculate the angle of the "along"
        along_angle: float = coord.calc_angle_of_line_local(b.pts_outer[i_long % 4][0],
                                                            b.pts_outer[i_long % 4][1],
                                                            b.pts_outer[(i_long + 1) % 4][0],
                                                            b.pts_outer[(i_long + 1) % 4][1])
        if along_angle >= 180.:
            along_angle -= 180.
        difference: float = fabs(b.roof_hint.ridge_orientation - along_angle)
        # if the difference is closer to 90 than parallel, then change the orientation
        if 45 < difference < 135:
            i_side = i_small

    seq_n: list[int] = list()  # the sequence of nodes such that 0-1 and 2-3 are along with ridge in parallel in the middle
    for i in range(0, 4):
        seq_n.append((i_side + i) % 4)

    # the corners
    vertices: list[gio.CVertexDTO] = list()
    for i, pt in enumerate(seq_n):
        vertices.append(gio.CVertexDTO(gio.VertexId(i), b.pts_outer[seq_n[i]][0], b.pts_outer[seq_n[i]][1],
                        b.beginning_of_roof_above_sea_level))

    # nodes for the ridge with indexes 4 and 5
    point_4 = coord.calc_point_on_line_local(vertices[0].x, vertices[0].y,
                                             vertices[3].x, vertices[3].y,
                                             0.5)
    point_5 = coord.calc_point_on_line_local(vertices[1].x, vertices[1].y,
                                             vertices[2].x, vertices[2].y,
                                             0.5)

    if b.roof_shape is enu.RoofShape.hipped:  # need to move the points 4 and 5 inwards
        ridge_length: float = coord.calc_distance_local(point_4[0], point_4[1], point_5[0], point_5[1])
        inward_ratio: float = 0.25
        if ridge_length > roof_height* 2.5:
            inward_ratio = roof_height / ridge_length
        point_14 = coord.calc_point_on_line_local(point_4[0], point_4[1],
                                                 point_5[0], point_5[1],
                                                 inward_ratio)
        point_15 = coord.calc_point_on_line_local(point_4[0], point_4[1],
                                                 point_5[0], point_5[1],
                                                 1 - inward_ratio)
        point_4 = point_14
        point_5 = point_15
        vertices.append(gio.CVertexDTO(gio.VertexId(4), point_14[0], point_14[1],
                                       b.beginning_of_roof_above_sea_level + roof_height))
        vertices.append(gio.CVertexDTO(gio.VertexId(5), point_15[0], point_15[1],
                                       b.beginning_of_roof_above_sea_level + roof_height))

    vertices.append(gio.CVertexDTO(gio.VertexId(4), point_4[0], point_4[1],
                                   b.beginning_of_roof_above_sea_level + roof_height))
    vertices.append(gio.CVertexDTO(gio.VertexId(5), point_5[0], point_5[1],
                                   b.beginning_of_roof_above_sea_level + roof_height))

    # after the nodes now the faces
    # The front and back have not necessarily the same length, as the
    # 4 sides might not make a perfect rectangle

    if b.roof_shape in [enu.RoofShape.gabled, enu.RoofShape.hipped]:
        # roofs
        the_vertices = [vertices[0], vertices[1], vertices[5], vertices[4]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices)
        the_vertices = [vertices[2], vertices[3], vertices[4], vertices[5]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices)

        # sides
        is_facade_covering: bool = b.roof_shape is enu.RoofShape.hipped
        the_vertices = [vertices[1], vertices[2], vertices[5]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices, is_facade_covering)
        the_vertices = [vertices[3], vertices[0], vertices[4]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices, is_facade_covering)

    else:  # b.roof_shape is RoofShape.gambrel. point_4 and point_5 on the ridge are still valid
        away_from_edge = GAMBREL_HEIGHT_RATIO_LOWER_PART * roof_height / tan(radians(GAMBREL_ANGLE_LOWER_PART))
        distance_across_left = coord.calc_distance_local(vertices[0].x, vertices[0].y,
                                                         vertices[3].x, vertices[3].y)
        distance_across_right = coord.calc_distance_local(vertices[1].x, vertices[1].y,
                                                          vertices[2].x, vertices[2].y)
        # indexes 6 and 7 on this side of the ridge and 8/9 on the other side
        factor_left = away_from_edge / distance_across_left
        factor_right = away_from_edge / distance_across_right
        point_6 = coord.calc_point_on_line_local(vertices[0].x, vertices[0].y,
                                                 vertices[3].x, vertices[3].y,
                                                 factor_left)
        point_7 = coord.calc_point_on_line_local(vertices[1].x, vertices[1].y,
                                                 vertices[2].x, vertices[2].y,
                                                 factor_right)
        point_8 = coord.calc_point_on_line_local(vertices[1].x, vertices[1].y,
                                                 vertices[2].x, vertices[2].y,
                                                 1 - factor_right)
        point_9 = coord.calc_point_on_line_local(vertices[0].x, vertices[0].y,
                                                 vertices[3].x, vertices[3].y,
                                                 1 - factor_left)
        z: float = b.beginning_of_roof_above_sea_level + GAMBREL_HEIGHT_RATIO_LOWER_PART*roof_height
        vertices.append(gio.CVertexDTO(gio.VertexId(6), point_6[0], point_6[1], z))
        vertices.append(gio.CVertexDTO(gio.VertexId(7), point_7[0], point_7[1], z))
        vertices.append(gio.CVertexDTO(gio.VertexId(8), point_8[0], point_8[1], z))
        vertices.append(gio.CVertexDTO(gio.VertexId(9), point_9[0], point_9[1], z))

        # roofs
        # lower faces front and back
        the_vertices = [vertices[0], vertices[1], vertices[7], vertices[6]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices)

        the_vertices = [vertices[2], vertices[3], vertices[9], vertices[8]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices)
        # upper faces front and back
        the_vertices = [vertices[6], vertices[7], vertices[5], vertices[4]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices)

        the_vertices = [vertices[8], vertices[9], vertices[4], vertices[5]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices)

        # side left top
        the_vertices = [vertices[9], vertices[6], vertices[4]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices)

        # side left bottom
        the_vertices = [vertices[3], vertices[0], vertices[6], vertices[9]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices)

        # side right top
        the_vertices = [vertices[7], vertices[8], vertices[5]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices)

        # side right bottom
        the_vertices = [vertices[1], vertices[2], vertices[8], vertices[7]]
        _write_a_face(geom_collector, b.roof_covering, the_vertices)


def write_pyramidal(geom_collector: gio.GeometryCollector3D, b) -> None:
    """Pyramidal, dome or onion roof."""
    roof_height: float = _sanity_roof_height_complex(b, 'pyramidal')

    # add nodes for each of the corners
    prev_ring: list[gio.CVertexDTO] = list()
    for i, pt in enumerate(b.pts_outer):
        prev_ring.append(gio.CVertexDTO(gio.VertexId(i), pt[0], pt[1],
                         b.beginning_of_roof_above_sea_level))

    # calculate node for the middle node of the roof
    x_centre: float = sum([vertex.x for vertex in prev_ring])/len(prev_ring)
    y_centre: float = sum([vertex.y for vertex in prev_ring])/len(prev_ring)

    n_pts: int = len(prev_ring)

    if b.roof_shape in [enu.RoofShape.dome, enu.RoofShape.onion]:
        # For dome and onion we need to add new rings and faces before the top
        height_share = list()  # the share of the roof height by each ring
        radius_share = list()  # the share of the radius by each ring
        if b.roof_shape is enu.RoofShape.dome:  # we use five additional rings
            height_share = [sin(radians(90 / 6)),
                            sin(radians(90 * 2 / 6)),
                            sin(radians(90 * 3 / 6)),
                            sin(radians(90 * 4 / 6)),
                            sin(radians(90 * 5 / 6))]
            radius_share = [cos(radians(90 / 6)),
                            cos(radians(90 * 2 / 6)),
                            cos(radians(90 * 3 / 6)),
                            cos(radians(90 * 4 / 6)),
                            cos(radians(90 * 5 / 6))]
        else:  # we use five additional rings based on guessed values - onion diameter gets broader than drum
            height_share = [.1, .2, .3, .4, .5, .7]
            radius_share = [1.2, 1.25, 1.2, 1., .6, .2]

        prev_index: int = n_pts
        for r in range(0, len(height_share)):
            ring: list[gio.CVertexDTO]  = list()
            # calculate the new points of the ring
            for i, pt in enumerate(b.pts_outer):
                x, y = coord.calc_point_on_line_local(pt[0], pt[1], x_centre, y_centre, 1 - radius_share[r])
                ring.append(gio.CVertexDTO(gio.VertexId(i + prev_index), x, y,
                            b.beginning_of_roof_above_sea_level + roof_height * height_share[r]))
            # create the faces
            for i in range(0, n_pts):
                j = (i + 1) % n_pts
                the_vertices = [prev_ring[i], prev_ring[j], ring[j], ring[i]]
                _write_a_face(geom_collector, b.roof_covering, the_vertices)
            prev_ring = ring
            prev_index += n_pts
    # else: nothing to do - we just do the top

    # create the top
    top_vertex = gio.CVertexDTO(gio.VertexId(999), x_centre, y_centre,
                                b.beginning_of_roof_above_sea_level + roof_height)
    # create the faces
    for i in range(0, n_pts):
        j = (i + 1) % n_pts
        the_vertices = [prev_ring[i], prev_ring[j], top_vertex]
        _write_a_face(geom_collector, b.roof_covering, the_vertices)


def _add_skeleton_faces(geom_collector: gio.GeometryCollector3D, b, roof_mesh: mesh.Mesh) -> bool:
    """Adds the nodes and faces for a skeleton roof.
    Processing is done similarly to _add_flat_faces(...). However, min/max and rotation etc. need to be done
    per original face instead of across all triangles - uv_mapping is contrary to flat per face (or you could
    look at flat as being one face only - which it is).
    """
    sanitized_faces: list[list[int]] = list()
    for face in roof_mesh.faces:  # face is a list of vertex indexes list[int]
        # sanitize to make sure that the same node is not referenced more than once - happens sometimes
        sanitized_face: list[int] = [key for key, _ in groupby(face)]
        if sanitized_face[0] == sanitized_face[-1]:
            sanitized_face.pop()
        if len(sanitized_face) < 3:
            return False
        sanitized_faces.append(sanitized_face)

    # Now that we know that all faces are valid, we can start processing them.
    all_face_ids: set[gio.FaceId] = set()
    prev_ring: list[gio.CVertexDTO] = list()
    for i, pt in enumerate(b.pts_outer):
        prev_ring.append(gio.CVertexDTO(gio.VertexId(i), pt[0], pt[1],
                         b.beginning_of_roof_above_sea_level))
    for sanitized_face in sanitized_faces:
        try:
            reversed_face: list[int] = sanitized_face[::-1]  # reverse the list so it is ccw

            idx_1: int = -1
            idx_2: int = -1
            for i in reversed_face:
                if roof_mesh.vertices[i].z < 0.01: # the z values at the roof beginning are 0.0
                    if idx_1 < 0:
                        idx_1 = i
                    elif idx_2 < 0:
                        idx_2 = i
                    if idx_1 >= 0 and idx_2 >= 0:
                        break

            if idx_1 < 0 or idx_2 < 0:
                raise Exception("Could not find the two vertices with lowest z for face %s" % sanitized_face)

            angle_rotate: float = coord.calc_angle_of_line_local(roof_mesh.vertices[idx_1].x,
                                                                 roof_mesh.vertices[idx_1].y,
                                                                 roof_mesh.vertices[idx_2].x,
                                                                 roof_mesh.vertices[idx_2].y)
            angle_rotate = angle_rotate + 90.
            rotation_point: shg.Point = shg.Point(roof_mesh.vertices[reversed_face[0]].x,
                                                   roof_mesh.vertices[reversed_face[0]].y)

            vertices_final: list[gio.CVertexDTO] = list()
            for i in reversed_face:
                vertices_final.append(gio.CVertexDTO(gio.VertexId(i), roof_mesh.vertices[i].x, roof_mesh.vertices[i].y,
                                                      roof_mesh.vertices[i].z + b.beginning_of_roof_above_sea_level))
            new_face_ids = geom_collector.add_polygon_face_no_holes(vertices_final, b.roof_covering,
                                                                    angle_rotate, rotation_point, b.osm_id)
            all_face_ids.update(new_face_ids)
        except Exception as reason:
            logging.debug("ERROR: while creating 3d roof (OSM_ID %s, %s)" % (b.osm_id, reason))
            geom_collector.remove_c_faces_by_id(all_face_ids)  # clean up already written faces
            return False
    return True


def write_skeleton(geom_collector: gio.GeometryCollector3D, b) -> bool:
    """Attempt to create a skeleton roof using pyskeleton.
    The code also does tessellation like for flat roofs, because almost always there will be faces with more
    than 4 vertices.
    If there is an error, then the method returns False (ideally before something is written to the 3D-object).
    """
    vertices = b.pts_outer
    no = len(b.pts_outer)
    edges = [(i, i+1) for i in range(no-1)]
    edges.append((no-1, 0))
    speeds = [1.] * no

    roof_mesh: mesh.Mesh | None = None  # osm2city/pyskeleton/mesh.py
    poly = polygon.Polygon(vertices, edges, speeds)
    if s.K_ROOF_ANGLE in b.tags:
        angle = float(b.tags[s.K_ROOF_ANGLE])
    else:
        angle = random.uniform(parameters.BUILDING_SKEL_ROOFS_MIN_ANGLE, parameters.BUILDING_SKEL_ROOFS_MAX_ANGLE)
    roof_height = 0.
    try:
        while angle > 0:
            roof_mesh = poly.roof_3D(radians(angle))
            # roof.mesh.vertices
            roof_height = max([p[2] for p in roof_mesh.vertices])
            if roof_height < parameters.BUILDING_SKEL_ROOF_MAX_HEIGHT:
                break
            # We'll just flatten the roof then instead of losing it
            angle -= parameters.BUILDING_SKEL_ROOFS_ANGLE_STEP
    except Exception as reason:
        logging.debug("ERROR: while creating 3d roof (OSM_ID %s, %s)" % (b.osm_id, reason))
        return False

    if roof_height > parameters.BUILDING_SKEL_ROOF_MAX_HEIGHT:
        logging.debug("Skeleton roof too high %g > %g - and therefore not accepted",
                      roof_height, parameters.BUILDING_SKEL_ROOF_MAX_HEIGHT)
        return False

    # The following is a hack as in certain (not further investigated situations) the dimensions can get out
    # of control generating e+07 numbers, which cannot be right.
    # FG crashes if an ac-file has such values.
    for p in roof_mesh.vertices:
        if fabs(p[0] - b.polygon.centroid.x) > parameters.BUILDING_SKEL_MAX_DIST_FROM_CENTROID or (
                fabs(p[1] - b.polygon.centroid.y) > parameters.BUILDING_SKEL_MAX_DIST_FROM_CENTROID):
            logging.debug("Skeleton roof might be broken - and therefore not accepted")
            return False

    return _add_skeleton_faces(geom_collector, b, roof_mesh)

# ================ UNITTESTS =======================


class TestRoofs(unittest.TestCase):
    def test_roof_looks_square(self):
        long_side = 1
        short_side = 1
        self.assertTrue(roof_looks_square(2*long_side + 2*short_side, long_side*short_side), "square")
        long_side = 1.5
        short_side = 1
        self.assertTrue(roof_looks_square(2*long_side + 2*short_side, long_side*short_side), "almost square")
        long_side = 2
        short_side = 1
        self.assertFalse(roof_looks_square(2*long_side + 2*short_side, long_side*short_side), "1:2 ratio")
        long_side = 2.1
        short_side = 1
        self.assertFalse(roof_looks_square(2*long_side + 2*short_side, long_side*short_side), "ratio larger than 1:2")
