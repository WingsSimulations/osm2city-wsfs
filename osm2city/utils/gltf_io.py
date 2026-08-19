# SPDX-FileCopyrightText: (C) 2025-2026, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later

"""

Generally, one cannot reuse a vertex if it is used in faces with different textures in glTF. Here's why:

In glTF, each **primitive** (which is a collection of triangles) can only have **one material**.
Since materials define textures, all faces within a primitive must share the same texture.
Therefore:
* Create different primitives for faces with different textures (e.g. roofs vs. facades)
* If faces need different UV coordinates for the same texture, you must duplicate vertices. E.g. if
  2 buildings share a wall, you must duplicate the vertices for the wall in both buildings, because
  otherwise you have to use the same texture and the same UV-coordinates.

Vertices can only be truly reused when:
* They have the same position
* They have the same UV coordinates
* They have the same normal (if using normals)
* They use the same material/texture

In osm2city this can almost never be guaranteed (at least if using data from OSM directly).
Even e.g. on a circular roof, where we have the same faces with the same material and same uvs we
cannot reuse vertices, because then the position is different. => no vertex reuse in osm2city.

Best practice:
1. Use texture atlases** for similar materials (facades, roofs)
2. Create separate primitives for fundamentally different materials (glass vs concrete vs metal)
3. Duplicate vertices only when necessary** for UV coordinate differences

# Single texture atlas containing multiple sub-textures
# Adjust UV coordinates to reference different parts of the atlas
# Face A uses UV region [0.0-0.5, 0.0-0.5] (top-left quadrant)
# Face B uses UV region [0.5-1.0, 0.0-0.5] (top-right quadrant)

uv_coords_atlas = [
    [0.25, 0.25],  # centre of top-left quadrant
    [0.75, 0.25],  # centre of top-right quadrant
    # ... etc.
]

There is **not** always a 1:1 relationship between texture and material in glTF.
A single material can use **multiple textures** for different purposes,
and a single texture can be **reused across multiple materials**.


"""
import enum
import logging
import math
import os.path as osp
from typing import NewType
import unittest

import numpy as np

from pygltflib import (
    GLTF2,
    Scene,
    Node,
    Mesh,
    Primitive,
    Accessor,
    Attributes,
    Buffer,
    BufferView,
    Image,
    Sampler,
    Texture,
    Material,
    PbrMetallicRoughness, TextureInfo,
)

import shapely as sha
import shapely.geometry as shg

import osm2city.static_types.osmstrings as s
import osm2city.static_types.types as t
import osm2city.utils.coordinates as co
import osm2city.textures.coverings as cov


FILE_ENDING = '.gltf'
FILE_ENDING_BIN = '.bin'

VertexId = NewType('VertexId', int)

FaceId = NewType('FaceId', int)

CoveringId = NewType('CoveringId', int)


class CVertexDTO:
    """A vertex in cartesian space.
    Attributes:
        v_id: the unique vertex ID (!= osm_node_ref)
        x: the local cartesian coordinate in East-West direction
        y: the local cartesian coordinate in North-South direction
        elev: the elevation above sea level - can include correction for rounding of earth
        osm_node_ref: the OSM node reference number or None if this is not based on an OSM ref
    """
    __slots__ = ('v_id', 'x', 'y', 'elev', 'osm_node_ref')

    def __init__(self, v_id: VertexId, x: float, y: float, elev: float, osm_node_ref: t.OSMId | None = None) -> None:
        self.v_id: VertexId = v_id
        self.x: float = x
        self.y: float = y
        self.elev: float = elev
        self.osm_node_ref: t.OSMId | None = osm_node_ref

    def __str__(self) -> str:
        return f'CVertex(v_id={self.v_id}, x={self.x}, y={self.y}, elev={self.elev}, osm_node_ref={self.osm_node_ref})'


class CTMap:
    """The uv coordinates for mapping a texture onto a face per vertex - but with 0/0 in the lower left corner.

    To make it easier to map textures in cartesian space.

    Attributes:
        x: the coordinate in left to right direction
        y: the coordinate in bottom-to-top direction
    """
    __slots__ = ('x', 'y', 'repeat')

    def __init__(self, x: float, y: float, repeat: cov.RepeatType) -> None:
        self.x: float = round(x, 4)  # round a bit to reduce validation errors at boundary due to float limitations
        self.y: float = round(y, 4)
        self.repeat: cov.RepeatType = repeat
        self._validate()

    def _validate(self) -> None:
        if self.repeat is cov.RepeatType.none:
            assert self.x >= 0.0, f'x coordinate {self.x} must be >= 0.0'
            assert self.x <= 1.0, f'x coordinate {self.x} must be <= 1.0'
        assert self.y >= 0.0, f'y coordinate {self.y} must be >= 0.0'
        # FIXME assert self.y <= 1.0, f'y coordinate {self.y} must be <= 1.0'

    def __eq__(self, other: object) -> bool:
        """Compare this CTMap with another CTMap for equality.

        Args:
            other: The object to compare with

        Returns:
            True if both CTMap instances have the same x and y coordinates, False otherwise
        """
        if not isinstance(other, CTMap):
            return False
        return self.x == other.x and self.y == other.y


class CVertex(CVertexDTO):
    """Extends the CVertexDTO with a reference to a covering."""
    __slots__ = ('ct_map', 'covering')

    ELEV_MATCH_ROUND_DECIMALS: int = 1

    def __init__(self, v_id: VertexId, x: float, y: float, elev: float, osm_node_ref: t.OSMId | None,
                 ct_map: CTMap, covering: cov.CCovering) -> None:
        super().__init__(v_id, x, y, elev, osm_node_ref)
        self.ct_map: CTMap = ct_map
        self.covering: cov.CCovering = covering

    def is_matching(self, dto: CVertexDTO, ct_map: CTMap, covering: cov.CCovering) -> bool:
        if (dto.osm_node_ref and self.osm_node_ref) and dto.osm_node_ref != self.osm_node_ref:
            return False
        if covering != self.covering:
            return False
        # we do not have to check x/y, because it will be the same for the same osm_node_ref
        if round(dto.elev, 1) != round(self.elev, 1):
            return False
        if self.ct_map != ct_map:
            return False
        return True

    def create_similarity_str(self) -> str | None:
        if self.osm_node_ref is None:
            return None
        return f'{self.osm_node_ref}_{round(self.elev, 1)}'

    def copy(self, new_id: VertexId | None) -> 'CVertex':
        if new_id is None:
            return CVertex(self.v_id, self.x, self.y, self.elev, self.osm_node_ref, self.ct_map, self.covering)
        return CVertex(new_id, self.x, self.y, self.elev, self.osm_node_ref, self.ct_map, self.covering)


class CFaceDTO:
    """A data transfer object for faces in cartesian space.

    Attributes:
        vertices: the vertice objects of the face as the key, the x and y coordinates of the texture coordinates as the value.
            NB: CTMap != uv coordinates.
        covering: the covering used on the face
        check_duplicate: signal that this face should be checked for duplicate amongst other faces.
        parent_id: if this face belongs to a set of geometries (e.g. building) which have a common parent
    """
    __slots__ = ('vertices', 'covering', 'check_duplicate', 'parent_id')

    def __init__(self, vertices: dict[CVertexDTO, CTMap], covering: cov.CCovering,
                 check_duplicate: bool = False, parent_id: t.OSMId | None = None) -> None:
        self.vertices: dict[CVertexDTO, CTMap] = vertices
        self.covering: cov.CCovering = covering
        self.check_duplicate: bool = check_duplicate
        self.parent_id: t.OSMId | None = parent_id
        self._validate()

    def _validate(self) -> None:
        assert len(self.vertices) == 3 or len(self.vertices) == 4, f'face must have 3 or 4 vertices, but has {len(self.vertices)} vertices'
        vertex_ids: set[VertexId] = set()
        vertex_strings: set[str] = set()
        for v in self.vertices:
            assert v.v_id not in vertex_ids, f'face has vertex {v.v_id} twice'
            assert str(v) not in vertex_strings, f'face has vertex {v} twice'
            vertex_ids.add(v.v_id)
            vertex_strings.add(str(v))
        if not self.check_duplicate:
            assert self.parent_id is None, f'face cannot have parent_id if check_duplicate is False'


class CFace:
    """Faces in cartesian space.

    In contrast to CFaceDTO the references to CVertex are integers instead of objects references.

    Attributes:
        f_id: the unique face ID
        vertices: the reference to vertices of the face as the key, CTMap as the value.
            NB: CTMap != uv coordinates.
        covering: the covering used on the face
        check_duplicate: signal that this face should be checked for duplicate
        parent_id: if this face belongs to a set of geometries (e.g. building) which have a common parent
        _similarity_set: is an optimization only used when needed to compare a face with another based on vertices.
    """
    __slots__ = ('f_id', 'vertices', 'covering', 'check_duplicate', 'parent_id', '_similarity_set')

    def __init__(self, covering: cov.CCovering) -> None:
        self.f_id: FaceId | None = None
        self.vertices: list[CVertex] = list()
        self.covering: cov.CCovering = covering
        self.check_duplicate: bool = False
        self.parent_id: t.OSMId | None = None
        self._similarity_set: set[str] = set()

    @classmethod
    def create_from_dto(cls, face_dto: CFaceDTO) -> 'CFace':
        face = CFace(face_dto.covering)
        face.check_duplicate = face_dto.check_duplicate
        face.parent_id = face_dto.parent_id
        return face

    def add_vertex(self, c_vertex: CVertex) -> None:
        for vertex in self.vertices:
            assert vertex.v_id != c_vertex.v_id, f'Adding a vertex {vertex.v_id} which has already been added'
        self.vertices.append(c_vertex)

    def replace_all_vertices(self, new_vertices: list[CVertex]) -> None:
        self.vertices = list()
        for c_vertex in new_vertices:
            self.add_vertex(c_vertex)

    def set_f_id(self, f_id: FaceId) -> None:
        assert self.f_id is None, f'May not set f_id to {f_id} when there already is a f_id'
        self.f_id = f_id

    def populate_similarity_set(self, vertex_id_map: dict[VertexId, CVertex]) -> None:
        self._similarity_set.clear()  # should not be necessary, but just to be sure
        for vertex in self.vertices:
            similarity_str: str | None = vertex_id_map[vertex.v_id].create_similarity_str()
            if similarity_str:
                self._similarity_set.add(similarity_str)

    def has_same_vertices(self, other: 'CFace') -> bool:
        """Cannot work directly with vertex_id, because the other face might use a different covering and
        therefore the vertex would be different. Using similarity strings makes this happen across coverings."""
        if len(self._similarity_set) != len(self.vertices):  # e.g. if one or more vertices have no osm_node_ref
            return False
        return self._similarity_set == other._similarity_set

    def split_if_quad(self) -> 'CFace | None':
        """If this face has 4 vertices, then change it to one triangle and return another.

        Return None if this face already is a triangle
        """
        if len(self.vertices) == 3:
            return None

        current_vertices = self.vertices[:]
        self.vertices = list()
        self.add_vertex(current_vertices[0])
        self.add_vertex(current_vertices[1])
        self.add_vertex(current_vertices[2])

        new_face = CFace(self.covering)
        new_face.add_vertex(current_vertices[0])
        new_face.add_vertex(current_vertices[2])
        new_face.add_vertex(current_vertices[3])
        return new_face


@enum.unique
class CollectionState(enum.IntEnum):
    before_processing = 0
    processing = 1
    after_processing = 2


class GeometryCollector3D:
    """Collects geometry information from OSM objects, prepares it for 3D file format, and then writes a #D file.

    Args:
        use_quads (bool): Whether to use triangles or quads - in FGFS use triangles
        smooth_edges (bool): if True, then vertices are reused at edges and normals are average
                             resulting in round edges (in FGFS).
    """
    __slots__ = ('state', '_use_quads', '_smooth_edges', '_vertex_index', '_face_index',
                 '_c_vertices', '_osm_refs_to_vertices', '_c_faces',
                 '_faces_check_duplicates', '_faces_check_to_remove', '_faces_parent_check_duplicates')

    def __init__(self, use_quads: bool, smooth_edges: bool) -> None:
        self.state: CollectionState = CollectionState.before_processing
        self._use_quads: bool = use_quads
        self._smooth_edges: bool = smooth_edges
        self._c_vertices: dict[VertexId, CVertex] = dict()
        self._osm_refs_to_vertices: dict[t.OSMId, list[CVertex]] = dict()
        self._c_faces: dict[FaceId, CFace] = dict()

        self._faces_check_duplicates: list[CFace] = list()
        self._faces_check_to_remove: set[CFace] = set()
        self._faces_parent_check_duplicates: dict[t.OSMId, list[CFace]] = dict()

        self._vertex_index: int = -1
        self._face_index: int = -1

    @property
    def smooth_edges(self) -> bool:
        return self._smooth_edges

    def _next_vertex_index(self) -> int:
        self._vertex_index += 1
        return self._vertex_index

    def _next_face_index(self) -> int:
        self._face_index += 1
        return self._face_index

    @property
    def number_vertices(self) -> int:
        return len(self._c_vertices)

    @property
    def number_faces(self) -> int:
        return len(self._c_faces)

    def process(self) -> None:
        assert self.state is CollectionState.before_processing, 'Processing can only be called if state is before_processing'
        self.state = CollectionState.processing

        self._clean_up_faces()
        if not self._use_quads:
            self._split_quads_to_triangles()

        self.state = CollectionState.after_processing

    def _clean_up_faces(self) -> None:
        for face in self._faces_check_to_remove:
            del self._c_faces[face.f_id]

        self._faces_check_duplicates = list()
        self._faces_check_to_remove = set()
        self._faces_parent_check_duplicates = dict()

    def _add_c_face(self, c_face: CFace, check_duplicate: bool = False,
                    parent_id: t.OSMId | None = None) -> FaceId | None:
        if check_duplicate:
            assert self.state is CollectionState.before_processing, 'Can only look for duplicates before processing'
            c_face.populate_similarity_set(self._c_vertices)
            do_add = self._validate_c_face_for_duplicates(c_face, parent_id)
            if not do_add:
                return None  # nothing to do

        f_id: FaceId = FaceId(self._next_face_index())
        c_face.set_f_id(f_id)
        self._c_faces[c_face.f_id] = c_face
        if check_duplicate:
            self._faces_check_duplicates.append(c_face)
            if parent_id:
                if parent_id not in self._faces_parent_check_duplicates:
                    self._faces_parent_check_duplicates[parent_id] = list()
                self._faces_parent_check_duplicates[parent_id].append(c_face)
        return f_id

    def remove_c_faces_by_id(self, face_ids: set[FaceId]) -> None:
        for face_id in face_ids:
            if face_id in self._c_faces:
                self._faces_check_to_remove.add(self._c_faces[face_id])

    def _validate_c_face_for_duplicates(self, c_face: CFace, parent_id: t.OSMId | None = None) -> bool:
        """Checks whether there are already faces with the same vertices.
        """
        do_add_parent = True
        if parent_id and parent_id in self._faces_parent_check_duplicates:
            for other_face in self._faces_parent_check_duplicates[parent_id]:
                if c_face.has_same_vertices(other_face):
                    do_add_parent = False

        # Even if it is a parent, and we already know that it should not be added,
        # we still need to check whether the existing should be removed.
        # This is because a parent could also just be an error with flickering overlap
        # We only mark the existing other for removal if not both have the same parent.
        do_add_all = True
        for other_face in self._faces_check_duplicates:
            if c_face.has_same_vertices(other_face):
                do_add_all = False
                if c_face.parent_id is None or other_face.parent_id is None:
                    self._faces_check_to_remove.add(other_face)
                elif c_face.parent_id != other_face.parent_id:
                    self._faces_check_to_remove.add(other_face)
                else:
                    pass  # nothing to do - we need at least one of the same parent id in case it is flickering
                break
        if not do_add_parent:
            return False
        return do_add_all

    def add_c_face_dto(self, face_in: CFaceDTO) -> FaceId | None:
        assert self.state is CollectionState.before_processing, 'Adding faces can only be done if state is before_processing'
        # first turn CVertexDTO into CVertex and check whether they already exist
        vertices: list[CVertex] = list()
        for dto, ct_map in face_in.vertices.items():
            c_vertex = self._add_c_vertex(dto, ct_map, face_in.covering)
            vertices.append(c_vertex)

        face = CFace.create_from_dto(face_in)
        for c_vertex in vertices:
            face.add_vertex(c_vertex)
        return self._add_c_face(face, face_in.check_duplicate, face_in.parent_id)

    def _add_c_vertex(self, dto: CVertexDTO, ct_map: CTMap, covering: cov.CCovering) -> CVertex:
        if dto.osm_node_ref and dto.osm_node_ref in self._osm_refs_to_vertices:
            for vertice in self._osm_refs_to_vertices[dto.osm_node_ref]:
                if vertice.is_matching(dto, ct_map, covering):
                    return vertice

        # nothing was found, so we have to add a new vertex
        v_id: VertexId = VertexId(self._next_vertex_index())
        c_vertex = CVertex(v_id, dto.x, dto.y, dto.elev, dto.osm_node_ref, ct_map, covering)
        self._c_vertices[v_id] = c_vertex
        if dto.osm_node_ref:
            if dto.osm_node_ref not in self._osm_refs_to_vertices:
                self._osm_refs_to_vertices[dto.osm_node_ref] = list()
            self._osm_refs_to_vertices[dto.osm_node_ref].append(c_vertex)
        return c_vertex

    def _split_quads_to_triangles(self) -> None:
        extra_faces: list[CFace] = list()  # temp collection because dict should not be changed while iterating
        for c_face in self._c_faces.values():
            extra_face = c_face.split_if_quad()
            if extra_face:
                extra_faces.append(extra_face)

        for extra_face in extra_faces:
            # duplicate checking was already done before
            self._add_c_face(extra_face, False, None)

    def get_shallow_c_vertices_clone(self) -> dict[VertexId, CVertex]:
        assert self.state is CollectionState.after_processing, 'Copying vertices can only be done after processing'
        if self._smooth_edges:
            return self._c_vertices.copy()  # preserves the sequence

        # because we do not want smooth edges, we need to make sure that the vertices are not reused
        # at edges, so we need to duplicate for each face
        used_vertices: set[VertexId] = set()
        final_vertices: dict[VertexId, CVertex] = dict()
        for c_face in self._c_faces.values():
            new_vertices: list[CVertex] = list()
            for vertex in c_face.vertices:
                if vertex.v_id not in used_vertices:
                    copy_vertex = vertex.copy(None)
                else:
                    copy_vertex = vertex.copy(VertexId(self._next_vertex_index()))
                used_vertices.add(copy_vertex.v_id)
                new_vertices.append(copy_vertex)
                final_vertices[copy_vertex.v_id] = copy_vertex
            c_face.replace_all_vertices(new_vertices)
        return final_vertices

    def get_shallow_c_faces_clone(self) -> dict[FaceId, CFace]:
        assert self.state is CollectionState.after_processing, 'Copying faces can only be done after processing'
        return self._c_faces.copy()  # preserves the sequence

    def add_faces_from_vertex_list(self, vertices: list[list[CVertexDTO]], covering: cov.CCovering,
                                   angle_rotate: float, rotation_point: shg.Point, osm_id: t.OSMId) -> set[FaceId]:
        """Based on a list of vertex lists for triangles or quads and a covering add c_Faces.

        The uv-coordinates are aligned with an angle and - if needed - stretched to fit the covering.
        """
        created_face_ids: set[FaceId] = set()
        uv_map: dict[VertexId, tuple[float, float]] = dict()
        min_x = 99999.
        min_y = 99999.
        max_x = -99999.
        max_y = -99999.
        for vertex_list in vertices:
            assert 3 <= len(vertex_list) <= 4, f'Invalid vertex list for osm_id {osm_id}: {vertex_list}'
            for vertex in vertex_list:
                pt = sha.affinity.rotate(shg.Point(vertex.x, vertex.y), angle_rotate, rotation_point)
                uv_map[vertex.v_id] = (pt.x, pt.y)
        for uv in uv_map.values():
            min_x = min(min_x, uv[0])
            min_y = min(min_y, uv[1])
            max_x = max(max_x, uv[0])
            max_y = max(max_y, uv[1])
        for v_id, uv in uv_map.items():
            uv_map[v_id] = (uv[0] - min_x, uv[1] - min_y)

        # Calculate the scaling for the texture
        # Only if the size of the polygon is larger than the texture, then we want to scale
        # i.e. make the texture artificially larger than intended (stretch to make this texture fit this roof)
        # This is needed because the texture cannot be repeated both vertically and horizontally at the same time.
        if not covering.h_can_repeat:
            assert (max_x - min_x) / covering.width <= 1., f'Texture cannot fit horizontally for osm_id {osm_id}:'
        scaling = max(1., (max_y - min_y) / covering.height)
        if not covering.v_can_stretch:
            assert scaling <= 1., f'Texture cannot fit vertically for osm_id {osm_id}:'

        for vertex_list in vertices:
            face_vertices: dict[CVertexDTO, CTMap] = dict()
            for vertex in vertex_list:
                uv = uv_map[vertex.v_id]
                face_vertices[vertex] = CTMap(uv[0] / covering.width,
                                              uv[1] / (covering.height * scaling),
                                              covering.repeat_type)
            face_id = self.add_c_face_dto(CFaceDTO(face_vertices, covering, False))
            if face_id:
                created_face_ids.add(face_id)
        return created_face_ids

    def add_polygon_face_no_holes(self, outer_ring: list[CVertexDTO], covering: cov.CCovering,
                                  angle_rotate: float, rotation_point: shg.Point, osm_id: t.OSMId) -> set[FaceId]:
        return self.add_polygon_face(outer_ring, list(), covering, angle_rotate, rotation_point, osm_id)

    def add_polygon_face(self, outer_ring: list[CVertexDTO], inner_rings: list[list[CVertexDTO]],
                         covering: cov.CCovering, angle_rotate: float, rotation_point: shg.Point,
                         osm_id: t.OSMId) -> set[FaceId]:
        # Triangulation
        orig_vertices: list[CVertexDTO] = [*outer_ring]
        outer_coords = [(v.x, v.y) for v in outer_ring]
        inner_coords: list[list[tuple[float, float]]] = list()
        for inner_ring in inner_rings:
            orig_vertices.extend(inner_ring)
            inner_coords.append([(v.x, v.y) for v in inner_ring])
        if inner_coords:
            the_polygon = shg.Polygon(outer_coords, inner_coords)
            if not the_polygon.is_valid:  # we assume something is wrong with inner rings
                the_polygon = shg.Polygon(outer_coords)
                logging.debug(f'WARNING: Invalid polygon with inner rings for osm_id {osm_id}.')
        else:
            the_polygon = shg.Polygon(outer_coords)
        triangles = sha.constrained_delaunay_triangles(the_polygon)

        # Process triangles
        vertices_for_faces: list[list[CVertexDTO]] = list()

        for triangle in triangles.geoms:
            tri_coords = list(triangle.exterior.coords)[:-1]  # Remove duplicate last point
            is_ccw = triangle.exterior.is_ccw
            if not is_ccw:
                # Reverse the order to make it CCW
                tri_coords = tri_coords[::-1]

            # Match triangle vertices after triangulation to original vertices
            face_vertices: list[CVertexDTO] = list()
            for coord in tri_coords:
                # Find matching vertex
                for v in orig_vertices:
                    if abs(v.x - coord[0]) < 0.001 and abs(v.y - coord[1]) < 0.001:
                        face_vertices.append(v)
                        break
            if len(face_vertices) == 3:
                vertices_for_faces.append(face_vertices)
            else:
                logging.debug(f'Skipping roof triangle with {len(face_vertices)} vertices for osm_id {osm_id}.')
        return self.add_faces_from_vertex_list(vertices_for_faces, covering, angle_rotate, rotation_point, osm_id)

    def add_sides(self, bot_vertices: dict[int, CVertexDTO], top_vertices: dict[int, CVertexDTO],
                  covering: cov.CCovering) -> None:
        """Add a set of side faces e.g. for a platform or a building."""
        assert len(bot_vertices) == len(top_vertices), 'The top and bottom vertices need to be the same length.'

        length = len(bot_vertices)
        for i in range(length):
            n = i + 1
            if n >= length:
                n = 0
            side_width: float = co.calc_distance_local(bot_vertices[i].x, bot_vertices[i].y,
                                                       bot_vertices[n].x, bot_vertices[n].y)
            side_height_i: float = math.fabs(top_vertices[i].elev - bot_vertices[i].elev)
            side_height_n: float = math.fabs(top_vertices[n].elev - bot_vertices[n].elev)
            self.add_c_face_dto(CFaceDTO({  # front
                bot_vertices[i]: CTMap(0., 0.,
                                       covering.repeat_type),
                bot_vertices[n]: CTMap(side_width / covering.width,0.,
                                       covering.repeat_type),
                top_vertices[n]: CTMap(side_width / covering.width, side_height_n / covering.height,
                                       covering.repeat_type),
                top_vertices[i]: CTMap(0., side_height_i / covering.height,
                                       covering.repeat_type)
            }, covering, True, None))


class GLTFWriter:
    __slots__ = ('_c_vertices', '_c_faces', '_smooth_edges',
                 '_vertices_by_covering', '_face_indices_by_covering', '_uvs_by_covering',
                 '_normals_by_covering', '_coverings', '_covering_index',
                 '_texture_indices')
    def __init__(self, c_vertices: dict[VertexId, CVertex], c_faces: dict[FaceId, CFace],
                 smooth_edges: bool) -> None:
        self._c_vertices: dict[VertexId, CVertex] = c_vertices
        self._c_faces: dict[FaceId, CFace] = c_faces
        self._smooth_edges: bool = smooth_edges
        # the following containers etc. are created during the write_to_file process for convenience (like debugging)
        self._vertices_by_covering: dict[CoveringId, np.ndarray] = dict()
        self._face_indices_by_covering: dict[CoveringId, np.ndarray] = dict()
        self._uvs_by_covering: dict[CoveringId, np.ndarray] = dict()
        self._normals_by_covering: dict[CoveringId, np.ndarray] = dict()

        self._coverings: dict[CoveringId, cov.CCovering] = dict()
        self._covering_index: int = -1

        self._texture_indices: dict[cov.CoveringTexture, int] = dict()

    def count_number_vertices(self) -> int:
        return len(self._c_vertices)

    def _next_covering_index(self) -> int:
        self._covering_index += 1
        return self._covering_index

    def _find_covering(self, incoming: cov.CCovering, do_assert: bool = False) -> CoveringId:
        for key, covering in self._coverings.items():
            if incoming == covering:
                return key
        if do_assert:
            raise AssertionError('covering not found')

        # the covering was not found, and it is OK to add it
        new_covering_id: CoveringId = CoveringId(self._next_covering_index())
        self._coverings[new_covering_id] = incoming
        return new_covering_id

    def _transform_to_arrays(self) -> None:
        all_vertices: dict[CoveringId, list[tuple[float, float, float]]] = dict()
        all_faces: dict[CoveringId, list[int]] = dict()
        all_uvs: dict[CoveringId, list[tuple[float, float]]] = dict()

        # Create mapping from the original VertexId to the array position per covering
        vertex_id_to_array_index: dict[CoveringId, dict[VertexId, int]] = dict()

        # First pass: collect vertices and create the mapping - but organize by covering first
        for c_face in self._c_faces.values():
            covering_id = self._find_covering(c_face.covering)
            if covering_id not in all_vertices:
                all_vertices[covering_id] = list()
                all_faces[covering_id] = list()
                all_uvs[covering_id] = list()
                vertex_id_to_array_index[covering_id] = dict()
            
            # Process each vertex in the face
            for c_vertex in c_face.vertices:
                # Only add vertex if we haven't seen it for this covering yet
                if c_vertex.v_id not in vertex_id_to_array_index[covering_id]:
                    array_index = len(all_vertices[covering_id])
                    vertex_id_to_array_index[covering_id][c_vertex.v_id] = array_index
                    
                    all_vertices[covering_id].append(co.cartesian_to_gltf_in_fgfs(c_vertex.x, c_vertex.y, c_vertex.elev))
                    x_tex, y_tex = c_vertex.covering.calc_absolute_texture_coordinates(c_vertex.ct_map.x, c_vertex.ct_map.y)
                    all_uvs[covering_id].append(co.cartesian_to_uv(x_tex, y_tex))

        # Second pass: collect face indices using the mapped array positions
        for c_face in self._c_faces.values():
            covering_id = self._find_covering(c_face.covering, True)
            for c_vertex in c_face.vertices:
                array_index = vertex_id_to_array_index[covering_id][c_vertex.v_id]
                all_faces[covering_id].append(array_index)

        for key in all_vertices.keys():
            self._vertices_by_covering[key] = np.array(all_vertices[key], dtype="float32")
        for key in all_faces.keys():
            self._face_indices_by_covering[key] = np.array(all_faces[key], dtype="uint32")
        for key in all_uvs.keys():
            self._uvs_by_covering[key] = np.array(all_uvs[key], dtype="float32")

    def _compute_face_normals(self, covering_id: CoveringId) -> np.ndarray:
        """Compute per-face normals (hard edges) for all triangles of a covering."""
        vertices = self._vertices_by_covering[covering_id]
        indices = self._face_indices_by_covering[covering_id]

        # Create an array to store normals per face
        num_triangles = len(indices) // 3
        face_normals = np.zeros((num_triangles, 3), dtype="float32")

        for i in range(num_triangles):
            idx0 = indices[i * 3]
            idx1 = indices[i * 3 + 1]
            idx2 = indices[i * 3 + 2]

            v0 = vertices[idx0]
            v1 = vertices[idx1]
            v2 = vertices[idx2]

            # Compute edges
            edge1 = v1 - v0
            edge2 = v2 - v0

            # Compute the cross-product for normal
            normal = np.cross(edge1, edge2)

            # Normalize
            length = np.linalg.norm(normal)
            if length > 0:
                normal = normal / length

            face_normals[i] = normal

        return face_normals

    def _compute_vertex_normals(self, covering_id: CoveringId) -> np.ndarray:
        """Compute per-vertex normals (soft edges) by averaging face normals."""
        vertices = self._vertices_by_covering[covering_id]
        indices = self._face_indices_by_covering[covering_id]

        # Initialize vertex normals accumulator
        vertex_normals = np.zeros((len(vertices), 3), dtype="float32")
        vertex_counts = np.zeros(len(vertices), dtype="float32")

        # Process each triangle
        num_triangles = len(indices) // 3
        for i in range(num_triangles):
            idx0 = indices[i * 3]
            idx1 = indices[i * 3 + 1]
            idx2 = indices[i * 3 + 2]

            v0 = vertices[idx0]
            v1 = vertices[idx1]
            v2 = vertices[idx2]

            # Compute face normal
            edge1 = v1 - v0
            edge2 = v2 - v0
            normal = np.cross(edge1, edge2)

            # Normalize face normal
            length = np.linalg.norm(normal)
            if length > 0:
                normal = normal / length

            # Accumulate this face normal to all three vertices
            vertex_normals[idx0] += normal
            vertex_normals[idx1] += normal
            vertex_normals[idx2] += normal
            vertex_counts[idx0] += 1
            vertex_counts[idx1] += 1
            vertex_counts[idx2] += 1

        # Average and normalize
        for i in range(len(vertices)):
            if vertex_counts[i] > 0:
                vertex_normals[i] = vertex_normals[i] / vertex_counts[i]
                length = np.linalg.norm(vertex_normals[i])
                if length > 0:
                    vertex_normals[i] = vertex_normals[i] / length

        return vertex_normals

    def _expand_normals_for_face_mode(self, covering_id: CoveringId, face_normals: np.ndarray) -> np.ndarray:
        """Expand face normals to per-vertex format (each vertex of a triangle gets the same face normal)."""
        indices = self._face_indices_by_covering[covering_id]
        vertices = self._vertices_by_covering[covering_id]

        # Create an array with one normal per vertex index in the index buffer
        expanded_normals = np.zeros((len(vertices), 3), dtype="float32")

        num_triangles = len(indices) // 3
        for i in range(num_triangles):
            idx0 = indices[i * 3]
            idx1 = indices[i * 3 + 1]
            idx2 = indices[i * 3 + 2]

            # Assign the same face normal to all three vertices
            # Note: This only works properly if vertices aren't shared between faces
            # For truly hard edges, vertices should be duplicated per face
            expanded_normals[idx0] = face_normals[i]
            expanded_normals[idx1] = face_normals[i]
            expanded_normals[idx2] = face_normals[i]

        return expanded_normals

    def _compute_normals(self) -> None:
        """Compute normals for all coverings.

        If self._smooth_edges is True, then compute vertex normals (smooth/soft edges based on averaging).
        Else compute face normals (hard edges based on face orientation).
        """
        for covering_id in self._vertices_by_covering.keys():
            if self._smooth_edges:
                normals = self._compute_vertex_normals(covering_id)
            else:
                face_normals = self._compute_face_normals(covering_id)
                normals = self._expand_normals_for_face_mode(covering_id, face_normals)

            self._normals_by_covering[covering_id] = normals

    def _make_texture_indices(self) -> None:
        next_texture_idx: int = 0
        for covering in self._coverings.values():
            if covering.texture not in self._texture_indices:
                self._texture_indices[covering.texture] = next_texture_idx
                next_texture_idx += 1

    def write_to_file(self, file_name: str, use_tex: bool = True) -> None:
        self._transform_to_arrays()
        self._compute_normals()

        # make sure that we either run fully with textures or none
        num_textures: int = 0
        for covering in self._coverings.values():
            if covering.texture:
                num_textures += 1
        if use_tex:
            assert num_textures == len(self._coverings), 'All coverings have to have a texture when using textures'
        else:
            assert num_textures == 0, 'None of the coverings may have a texture when not using textures'

        # Get the arrays by covering in a consistent order
        covering_ids = list(self._vertices_by_covering.keys())

        # Calculate the total byte length for the binary blob
        total_byte_length = 0
        for covering_id in covering_ids:
            total_byte_length += len(self._vertices_by_covering[covering_id].tobytes())
            total_byte_length += len(self._normals_by_covering[covering_id].tobytes())
            if use_tex:
                total_byte_length += len(self._uvs_by_covering[covering_id].tobytes())
            total_byte_length += len(self._face_indices_by_covering[covering_id].tobytes())

        # Create the glTF structure
        gltf = GLTF2()

        # Determine binary file name and URI
        assert file_name.endswith(FILE_ENDING)
        bin_file_name = file_name[:-len(FILE_ENDING)] + '.bin'
        bin_uri = osp.basename(bin_file_name)  # Just the filename for URI

        # Create a single binary buffer with URI for an external file
        gltf.buffers.append(Buffer(byteLength=total_byte_length, uri=bin_uri))

        # Build the binary blob and create buffer views/accessors per covering
        all_bytes: bytes = b''
        current_offset = 0

        # Track which accessor indices correspond to which covering
        covering_to_accessors = {}  # covering_id -> (position_accessor, normal_accessor, uv_accessor, indices_accessor)

        for covering_id in covering_ids:
            vertices = self._vertices_by_covering[covering_id]
            faces_indices = self._face_indices_by_covering[covering_id]
            normals = self._normals_by_covering[covering_id]

            vertices_bytes = vertices.tobytes()
            indices_bytes = faces_indices.tobytes()

            # Vertices buffer view
            vertex_buffer_view_idx = len(gltf.bufferViews)
            gltf.bufferViews.append(
                BufferView(
                    buffer=0,
                    byteOffset=current_offset,
                    byteLength=len(vertices_bytes),
                    target=34962  # ARRAY_BUFFER for vertex attributes
                )
            )
            all_bytes += vertices_bytes
            current_offset += len(vertices_bytes)

            # Vertices accessor
            position_accessor_idx = len(gltf.accessors)
            gltf.accessors.append(
                Accessor(
                    bufferView=vertex_buffer_view_idx,
                    byteOffset=0,
                    componentType=5126,  # FLOAT
                    count=len(vertices),
                    type="VEC3",
                    max=vertices.max(axis=0).tolist(),
                    min=vertices.min(axis=0).tolist()
                )
            )

            # Normals buffer view
            normals_bytes = normals.tobytes()

            normal_buffer_view_idx = len(gltf.bufferViews)
            gltf.bufferViews.append(
                BufferView(
                    buffer=0,
                    byteOffset=current_offset,
                    byteLength=len(normals_bytes),
                    target=34962  # ARRAY_BUFFER for vertex attributes
                )
            )
            all_bytes += normals_bytes
            current_offset += len(normals_bytes)

            # Normals accessor
            normal_accessor_idx = len(gltf.accessors)
            gltf.accessors.append(
                Accessor(
                    bufferView=normal_buffer_view_idx,
                    byteOffset=0,
                    componentType=5126,  # FLOAT
                    count=len(normals),
                    type="VEC3",
                    max=normals.max(axis=0).tolist(),
                    min=normals.min(axis=0).tolist()
                )
            )

            uv_accessor_idx = None
            if use_tex:
                uvs = self._uvs_by_covering[covering_id]
                uvs_bytes = uvs.tobytes()

                # UVs buffer view
                uv_buffer_view_idx = len(gltf.bufferViews)
                gltf.bufferViews.append(
                    BufferView(
                        buffer=0,
                        byteOffset=current_offset,
                        byteLength=len(uvs_bytes),
                        target=34962  # ARRAY_BUFFER for vertex attributes
                    )
                )
                all_bytes += uvs_bytes
                current_offset += len(uvs_bytes)

                # UVs accessor
                uv_accessor_idx = len(gltf.accessors)
                gltf.accessors.append(
                    Accessor(
                        bufferView=uv_buffer_view_idx,
                        byteOffset=0,
                        componentType=5126,  # FLOAT
                        count=len(uvs),
                        type="VEC2",
                        max=uvs.max(axis=0).tolist(),
                        min=uvs.min(axis=0).tolist()
                    )
                )

            # Indices buffer view
            indices_buffer_view_idx = len(gltf.bufferViews)
            gltf.bufferViews.append(
                BufferView(
                    buffer=0,
                    byteOffset=current_offset,
                    byteLength=len(indices_bytes),
                    target=34963  # ELEMENT_ARRAY_BUFFER for indices
                )
            )
            all_bytes += indices_bytes
            current_offset += len(indices_bytes)

            # Indices accessor
            indices_accessor_idx = len(gltf.accessors)
            gltf.accessors.append(
                Accessor(
                    bufferView=indices_buffer_view_idx,
                    byteOffset=0,
                    componentType=5125,  # UNSIGNED_INT
                    count=len(faces_indices),
                    type="SCALAR",
                    max=[int(faces_indices.max())],
                    min=[int(faces_indices.min())]
                )
            )

            covering_to_accessors[covering_id] = (position_accessor_idx, normal_accessor_idx, uv_accessor_idx, indices_accessor_idx)

        if use_tex:
            # Create external texture references
            self._make_texture_indices()

            gltf.samplers.append(Sampler(magFilter=9729,  # GL_LINEAR (linear filtering)
                                         minFilter=9986
                                         # GL_LINEAR_MIPMAP_LINEAR (for smooth minification with mipmapping)
                                         ))

            for covering_texture, index in self._texture_indices.items():
                gltf.images.append(Image(uri=covering_texture.image_path))
                gltf.textures.append(Texture(source=index, sampler=0))

        # Create materials that use the textures
        the_primitives: list[Primitive] = list()
        for c_id, c_covering in self._coverings.items():
            tex_info = None
            if use_tex:
                tex_idx = self._texture_indices[c_covering.texture]
                tex_info = TextureInfo(index=tex_idx)
            gltf.materials.append(
                Material(
                    name=c_covering.name,
                    pbrMetallicRoughness=PbrMetallicRoughness(
                        baseColorTexture=tex_info,
                        metallicFactor=c_covering.material.metallic_factor,
                        roughnessFactor=c_covering.material.roughness_factor
                    )
                )
            )

            # Get the accessor indices for this covering
            position_accessor_idx, normal_accessor_idx, uv_accessor_idx, indices_accessor_idx = covering_to_accessors[c_id]

            # Create appropriate attributes based on whether textures are used
            if use_tex:
                primitive_attributes = Attributes(POSITION=position_accessor_idx, NORMAL=normal_accessor_idx, TEXCOORD_0=uv_accessor_idx)
            else:
                primitive_attributes = Attributes(POSITION=position_accessor_idx, NORMAL=normal_accessor_idx)

            the_primitives.append(Primitive(attributes=primitive_attributes,
                                            indices=indices_accessor_idx,
                                            material=c_id))

        # Create the mesh with all primitives
        gltf.meshes.append(
            Mesh(
                primitives=the_primitives
            )
        )

        # Create a node that points to the mesh
        gltf.nodes.append(Node(mesh=0))

        # Create a scene that contains the node
        gltf.scenes.append(Scene(nodes=[0]))
        gltf.scene = 0

        # Write binary data to separate .bin file
        with open(bin_file_name, 'wb') as f:
            f.write(all_bytes)

        # Save the glTF JSON file (do NOT use set_binary_blob)
        gltf.save(file_name)
        logging.info(f"Successfully generated and saved '{file_name}' and '{bin_file_name}'")


# ========================== Testing ============================


_THE_TEXTURES = {
    'red_roof': cov.CoveringTexture('red', 'h_red.png', 64, 64),
    'multi': cov.CoveringTexture('multi', 'h_multi.png', 128, 128)
}


_THE_MATERIALS = {
    'roof_tile': cov.CoveringMaterial('roof_tile', 0.0, 0.8),
    'concrete': cov.CoveringMaterial('concrete', 0.0, 0.9),
    'plaster': cov.CoveringMaterial('plaster', 0.0, 0.7),
}


_THE_COVERINGS = {
    'platform_concrete_green': cov.CCovering('platform_concrete_green', _THE_TEXTURES['multi'], _THE_MATERIALS['concrete'],
                                             (64, 96, 128, 128), 10, 5, s.V_DIMGREY,
                                             repeat_type=cov.RepeatType.horizontal, can_stretch_vertical=True),
    'red_roof_tile': cov.CCovering('red_roof_tile', _THE_TEXTURES['red_roof'], _THE_MATERIALS['roof_tile'],
                                   (0, 0, 64, 64), 12, 12, s.V_GREEN,
                                   repeat_type=cov.RepeatType.horizontal, can_stretch_vertical=True),
    'blue_plaster': cov.CCovering('blue_plaster', _THE_TEXTURES['multi'], _THE_MATERIALS['plaster'],
                                  (64, 0, 128, 64), 15, 15, s.V_BLUE,
                                  repeat_type=cov.RepeatType.horizontal, can_stretch_vertical=True),
}


def _create_cartesian_house(front_left: tuple[float, float], house_width: float, house_depth: float,
                            house_height: float, roof_height: float,
                            osm_ids: list[t.OSMId | None], parent_osm_id: t.OSMId | None,
                            collector_3d: GeometryCollector3D) -> None:
    house_vertices: dict[int, CVertexDTO] = {
        # ground floor
        1: CVertexDTO(VertexId(1), front_left[0], front_left[1], 0.0, osm_ids[0]),
        2: CVertexDTO(VertexId(2), front_left[0] + house_width, front_left[1], 0.0, osm_ids[1]),
        3: CVertexDTO(VertexId(3), front_left[0], front_left[1] + house_depth, 0.0, osm_ids[2]),
        4: CVertexDTO(VertexId(4), front_left[0] + house_width, front_left[1] + house_depth, 0.0, osm_ids[3]),
        # under roof
        11: CVertexDTO(VertexId(11), front_left[0], front_left[1], house_height, osm_ids[0]),
        12: CVertexDTO(VertexId(12), front_left[0] + house_width, front_left[1], house_height, osm_ids[1]),
        13: CVertexDTO(VertexId(13), front_left[0], front_left[1] + house_depth, house_height, osm_ids[2]),
        14: CVertexDTO(VertexId(14), front_left[0] + house_width, front_left[1] + house_depth, house_height, osm_ids[3]),
        # roof vertices basis
        21: CVertexDTO(VertexId(21), front_left[0], front_left[1], house_height, osm_ids[0]),
        22: CVertexDTO(VertexId(22), front_left[0] + house_width, front_left[1], house_height, osm_ids[1]),
        23: CVertexDTO(VertexId(23), front_left[0], front_left[1] + house_depth, house_height, osm_ids[2]),
        24: CVertexDTO(VertexId(24), front_left[0] + house_width, front_left[1] + house_depth, house_height, osm_ids[3]),
        #roof vertices gable
        25: CVertexDTO(VertexId(25), front_left[0], front_left[1] + 0.5*house_depth, house_height + roof_height, osm_ids[4]),
        26: CVertexDTO(VertexId(26), front_left[0] + house_width, front_left[1] + 0.5*house_depth, house_height + roof_height, osm_ids[5]),
    }

    roof_up = math.sqrt(math.pow(roof_height, 2) + math.pow(house_depth / 2, 2))

    plaster = _THE_COVERINGS['blue_plaster']
    green = _THE_COVERINGS['platform_concrete_green']
    roof = _THE_COVERINGS['red_roof_tile']

    collector_3d.add_c_face_dto(CFaceDTO({  # facade front
        house_vertices[1]: CTMap(0.0/plaster.width, 0.0/plaster.height, plaster.repeat_type),
        house_vertices[2]: CTMap(house_width/plaster.width, 0.0/plaster.height, plaster.repeat_type),
        house_vertices[12]: CTMap(house_width/plaster.width, house_height/plaster.height, plaster.repeat_type),
        house_vertices[11]: CTMap(0.0/plaster.width, house_height/plaster.height, plaster.repeat_type)
    }, plaster, True, parent_osm_id))
    collector_3d.add_c_face_dto(CFaceDTO({  # facade right
        house_vertices[2]: CTMap(0.0/plaster.width, 0.0/plaster.height, plaster.repeat_type),
        house_vertices[4]: CTMap(house_depth/plaster.width, 0.0/plaster.height, plaster.repeat_type),
        house_vertices[14]: CTMap(house_depth/plaster.width, house_height/plaster.height, plaster.repeat_type),
        house_vertices[12]: CTMap(0.0/plaster.width, house_height/plaster.height, plaster.repeat_type)
    }, plaster, True, parent_osm_id))
    collector_3d.add_c_face_dto(CFaceDTO({  # facade back
        house_vertices[4]: CTMap(0.0/plaster.width, 0.0/plaster.height, plaster.repeat_type),
        house_vertices[3]: CTMap(house_width/plaster.width, 0.0/plaster.height, plaster.repeat_type),
        house_vertices[23]: CTMap(house_width/plaster.width, house_height/plaster.height, plaster.repeat_type),
        house_vertices[14]: CTMap(0.0/plaster.width, house_height/plaster.height, plaster.repeat_type)
    }, plaster, True, parent_osm_id))
    collector_3d.add_c_face_dto(CFaceDTO({  # facade left
        house_vertices[3]: CTMap(0.0/plaster.width, 0.0/plaster.height, plaster.repeat_type),
        house_vertices[1]: CTMap(house_depth/plaster.width, 0.0/plaster.height, plaster.repeat_type),
        house_vertices[11]: CTMap(house_depth/plaster.width, house_height/plaster.height, plaster.repeat_type),
        house_vertices[13]: CTMap(0.0/plaster.width, house_height/plaster.height, plaster.repeat_type)
    }, plaster, True, parent_osm_id))
    collector_3d.add_c_face_dto(CFaceDTO({  # facade under the roof right
        house_vertices[22]: CTMap(0.0/green.width, 0.0/green.height, green.repeat_type),
        house_vertices[24]: CTMap(house_depth/green.width, 0.0/green.height, green.repeat_type),
        house_vertices[26]: CTMap(0.5*house_depth/green.width, roof_height/green.height, green.repeat_type)
    }, green,True, parent_osm_id))
    collector_3d.add_c_face_dto(CFaceDTO({  # facade under the roof right
        house_vertices[23]: CTMap(0.0/green.width, 0.0/green.height, green.repeat_type),
        house_vertices[21]: CTMap(house_depth/green.width, 0.0/green.height, green.repeat_type),
        house_vertices[25]: CTMap(0.5*house_depth/green.width, roof_height/green.height, green.repeat_type)
    }, green, True, parent_osm_id))
    collector_3d.add_c_face_dto(CFaceDTO({  # roof front
        house_vertices[21]: CTMap(0.0/roof.width, 0.0/roof.height, roof.repeat_type),
        house_vertices[22]: CTMap(house_width/roof.width, 0.0/roof.height, roof.repeat_type),
        house_vertices[26]: CTMap(house_width/roof.width, roof_up/roof.height, roof.repeat_type),
        house_vertices[25]: CTMap(0.0/roof.width, roof_up/roof.height, roof.repeat_type)
    }, roof))  # no check for duplicate
    collector_3d.add_c_face_dto(CFaceDTO({  # roof back
        house_vertices[24]: CTMap(0.0/roof.width, 0.0/roof.height, roof.repeat_type),
        house_vertices[23]: CTMap(house_width/roof.width, 0.0/roof.height, roof.repeat_type),
        house_vertices[25]: CTMap(house_width/roof.width, roof_up/roof.height, roof.repeat_type),
        house_vertices[26]: CTMap(0.0/roof.width, roof_up/roof.height, roof.repeat_type)
    }, roof))  # no check for duplicate


class TestGeometryCollector3D(unittest.TestCase):
    """Test GeometryCollector3D class"""

    def setUp(self):
        pass

    def test_geom_collector_two_houses(self) -> None:
        path_name = '/home/vanosten/custom-fg-scenery/'
        # houses have a common parent
        geom_collector = GeometryCollector3D(False, True)
        # 2 houses which have overlapping OSM_Ids and therefore share some vertices and faces.
        # The first house has floor plan 1-2-3-4 and gable at 5-6.
        # The second house has floor plan 2-12-14-4 and gable 6-16.
        # => there is a common wall 2-4
        #
        #  3----4----14
        #  |    |    |
        #  5....6....16
        #  |    |    |
        #  1----2----12
        the_parent_osm_id = t.OSMId(99)
        the_osm_ids_1: list[t.OSMId] = [t.OSMId(1), t.OSMId(2), t.OSMId(3), t.OSMId(4), t.OSMId(5), t.OSMId(6)]
        _create_cartesian_house((0., 0.), 10., 8., 3., 2.,
                                the_osm_ids_1, the_parent_osm_id, geom_collector)
        self.assertEqual(30, geom_collector.number_vertices, 'Vertices after first house with parent')
        self.assertEqual(8, geom_collector.number_faces, 'Faces after first house with parent')
        the_osm_ids_2: list[t.OSMId] = [t.OSMId(2), t.OSMId(12), t.OSMId(4), t.OSMId(14), t.OSMId(6), t.OSMId(16)]
        _create_cartesian_house((10., 0.), 10., 8., 3., 2.,
                                the_osm_ids_2, the_parent_osm_id, geom_collector)
        self.assertEqual(53, geom_collector.number_vertices, 'Vertices after second house with parent')
        self.assertEqual(14, geom_collector.number_faces, 'Faces after second house with parent')
        geom_collector.process()
        self.assertEqual(53, geom_collector.number_vertices, 'Unchanged vertices after processing with parent')
        # no faces are removed because one common side is kept between houses
        self.assertEqual(25, geom_collector.number_faces, 'New triangles after processing with parent due to triangles')

        gltf_writer = GLTFWriter(geom_collector.get_shallow_c_vertices_clone(),
                                 geom_collector.get_shallow_c_faces_clone(),
                                 geom_collector.smooth_edges)
        gltf_writer.write_to_file(osp.join(path_name, 'house_parent' + FILE_ENDING), True)

        # now without a common parent
        geom_collector = GeometryCollector3D(False, True)  # reset
        the_parent_osm_id = None
        _create_cartesian_house((0., 0.), 10., 8., 3., 2.,
                                the_osm_ids_1, the_parent_osm_id, geom_collector)
        self.assertEqual(30, geom_collector.number_vertices, 'Vertices after first house no parent')
        self.assertEqual(8, geom_collector.number_faces, 'Faces after first house no parent')
        _create_cartesian_house((10., 0.), 10., 8., 3., 2.,
                                the_osm_ids_2, the_parent_osm_id, geom_collector)
        self.assertEqual(53, geom_collector.number_vertices, 'Vertices after second house no parent')
        self.assertEqual(14, geom_collector.number_faces, 'Faces after second house no parent')
        geom_collector.process()
        self.assertEqual(53, geom_collector.number_vertices, 'Unchanged vertices after processing no parent')
        # 2 faces out of 14 are deleted (wall and under roof between houses), 10 added due to triangles
        # (no triangles for 2 times under the roof)
        self.assertEqual(22, geom_collector.number_faces, 'Cleaned faces and new triangles after processing no parent due to triangles')

        gltf_writer = GLTFWriter(geom_collector.get_shallow_c_vertices_clone(),
                                 geom_collector.get_shallow_c_faces_clone(),
                                 geom_collector.smooth_edges)
        self.assertEqual(53, gltf_writer.count_number_vertices(), 'Vertices in GLTFWriter no parent')
        gltf_writer.write_to_file(osp.join(path_name, 'house_no_parent' + FILE_ENDING), True)

        # now without a common parent and sharp edges
        geom_collector = GeometryCollector3D(False, False)  # reset
        the_parent_osm_id = None
        _create_cartesian_house((0., 0.), 10., 8., 3., 2.,
                                the_osm_ids_1, the_parent_osm_id, geom_collector)
        self.assertEqual(30, geom_collector.number_vertices, 'Vertices after first house no parent sharp edges')
        self.assertEqual(8, geom_collector.number_faces, 'Faces after first house no parent sharp edges')
        _create_cartesian_house((10., 0.), 10., 8., 3., 2.,
                                the_osm_ids_2, the_parent_osm_id, geom_collector)
        self.assertEqual(53, geom_collector.number_vertices, 'Vertices after second house no parent sharp edges')
        self.assertEqual(14, geom_collector.number_faces, 'Faces after second house no parent sharp edges')
        geom_collector.process()
        self.assertEqual(53, geom_collector.number_vertices, 'Unchanged vertices after processing no parent sharp edges')
        # 2 faces out of 14 are deleted (wall and under roof between houses), 10 added due to triangles
        # (no triangles for 2 times under the roof)
        self.assertEqual(22, geom_collector.number_faces, 'Cleaned faces and new triangles after processing no parent sharp edges due to triangles')

        gltf_writer = GLTFWriter(geom_collector.get_shallow_c_vertices_clone(),
                                 geom_collector.get_shallow_c_faces_clone(),
                                 geom_collector.smooth_edges)
        self.assertEqual(3*22, gltf_writer.count_number_vertices(), 'Vertices in GLTFWriter no parent sharp edges')
        gltf_writer.write_to_file(osp.join(path_name, 'house_no_parent_sharp' + FILE_ENDING), True)

        # now without osm_node_refs
        geom_collector = GeometryCollector3D(False, False)  # reset
        the_parent_osm_id = None
        the_osm_ids_1: list[t.OSMId | None] = [None, None, None, None, None, None]
        _create_cartesian_house((0., 0.), 10., 8., 3., 2.,
                                the_osm_ids_1, the_parent_osm_id, geom_collector)
        self.assertEqual(30, geom_collector.number_vertices, 'Vertices after first house no node refs')
        self.assertEqual(8, geom_collector.number_faces, 'Faces after first house no node refs')
        _create_cartesian_house((10., 0.), 10., 8., 3., 2.,
                                the_osm_ids_2, the_parent_osm_id, geom_collector)
        self.assertEqual(60, geom_collector.number_vertices, 'Vertices after second house no node refs')
        self.assertEqual(16, geom_collector.number_faces, 'Faces after second house no node refs')
        geom_collector.process()
        self.assertEqual(60, geom_collector.number_vertices, 'Unchanged vertices after processing no parent')
        self.assertEqual(28, geom_collector.number_faces, 'Cleaned faces and new triangles after processing no node refs due to triangles')

        gltf_writer = GLTFWriter(geom_collector.get_shallow_c_vertices_clone(),
                                 geom_collector.get_shallow_c_faces_clone(),
                                 geom_collector.smooth_edges)
        self.assertEqual(3*28, gltf_writer.count_number_vertices(), 'Vertices in GLTFWriter no parent sharp edges')
        gltf_writer.write_to_file(osp.join(path_name, 'house_no_node_refs' + FILE_ENDING), True)
