# SPDX-FileCopyrightText: (C) 2013 - 2025, rick@vanosten.net, radi, portree_kid
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Script part of osm2city which takes OpenStreetMap data as input and generates data to be used in FlightGear
   * overground power lines
   * aerialways
   * railway overlines
   * streetlamps
"""

from enum import IntEnum, unique
import logging
import math
import multiprocessing.synchronize as mps
import os
import random
from typing import override
import unittest

import shapely.geometry as shg
from shapely.geometry.base import JOIN_STYLE

from osm2city import parameters
import osm2city.static_types.enumerations as e
import osm2city.static_types.osmstrings as s
import osm2city.static_types.shared_models as sm
import osm2city.static_types.types as t
import osm2city.textures.coverings as cov
from osm2city.utils import coordinates as co
import osm2city.utils.elev_probe as ep
import osm2city.utils.gltf_io as gio
from osm2city.utils import stg_io2
from osm2city.utils import osmparser as op
from utils.stg_io2 import STGVerbType

PYLONS_MAGIC = 'pylons'


class CableVertex(object):
    __slots__ = ('out', 'height', 'top_cable', 'no_catenary', 'x', 'y', 'elevation')

    def __init__(self, out: float, height: float, top_cable: bool = False, no_catenary: bool = False) -> None:
        self.out = out  # the distance from the middle vertical line of the pylon
        self.height = height  # the distance above ground relative to the pylon's ground level (y-axis in ac-file)
        self.top_cable = top_cable  # for the cables at the top, which are not executing the main task
        self.no_catenary = no_catenary  # for cables which should not bend, e.g. lower cable of rail overhead line
        self.x = 0.0  # local position x
        self.y = 0.0  # local position y
        self.elevation = 0.0  # elevation above sea level in meters

    def calc_position(self, pylon_x: float, pylon_y: float, pylon_elevation: float, pylon_heading: float) -> None:
        self.elevation = pylon_elevation + self.height
        self.x = pylon_x + math.sin(math.radians(pylon_heading + 90))*self.out
        self.y = pylon_y + math.cos(math.radians(pylon_heading + 90))*self.out

    def set_position(self, x: float, y: float, elevation: float) -> None:
        self.x = x
        self.y = y
        self.elevation = elevation


class Cable(object):
    __slots__ = ('start_cable_vertex', 'end_cable_vertex', 'vertices', 'radius', 'heading')

    def __init__(self, start_cable_vertex: CableVertex, end_cable_vertex: CableVertex, radius: float,
                 number_extra_vertices: int, catenary_a: int, distance: float) -> None:
        """
        A Cable between two vertices. The radius is approximated with a triangle with sides of length 2*radius.
        If both the number of extra_vertices and the catenary_a are > 0, then the Cable gets a sag based on
        a catenary function.
        """
        self.start_cable_vertex = start_cable_vertex
        self.end_cable_vertex = end_cable_vertex
        self.vertices = [self.start_cable_vertex, self.end_cable_vertex]
        self.radius = radius
        self.heading = co.calc_angle_of_line_local(start_cable_vertex.x, start_cable_vertex.y,
                                                   end_cable_vertex.x, end_cable_vertex.y)

        if (number_extra_vertices > 0) and (catenary_a > 0) and (distance >= parameters.C2P_CATENARY_MIN_DISTANCE):
            self._make_catenary_cable(number_extra_vertices, catenary_a)

    def _make_catenary_cable(self, number_extra_vertices: int, catenary_a: int) -> None:
        """
        Transforms the cable into one with more vertices and some sagging based on a catenary function.
        If there is a considerable difference in elevation between the two pylons, then gravity would have to
        be taken into account https://en.wikipedia.org/wiki/File:Catenary-tension.png.
        However, the elevation correction actually already helps quite a bit, because the x/y are kept constant.
        """
        cable_distance = co.calc_distance_local(self.start_cable_vertex.x, self.start_cable_vertex.y,
                                                self.end_cable_vertex.x, self.end_cable_vertex.y)
        part_distance = cable_distance / (1 + number_extra_vertices)
        pylon_y = catenary_a * math.cosh((cable_distance / 2) / catenary_a)
        part_elevation = ((self.start_cable_vertex.elevation - self.end_cable_vertex.elevation) /
                          (1 + number_extra_vertices))
        for i in range(1, number_extra_vertices + 1):
            x = self.start_cable_vertex.x + i * part_distance * math.sin(math.radians(self.heading))
            y = self.start_cable_vertex.y + i * part_distance * math.cos(math.radians(self.heading))
            catenary_x = i * part_distance - (cable_distance / 2)
            elevation = catenary_a * math.cosh(catenary_x / catenary_a)  # pure catenary y-position
            elevation = self.start_cable_vertex.elevation - (pylon_y - elevation)  # relative distance to start pylon
            elevation -= i * part_elevation  # correct for elevation difference between the 2 pylons
            v = CableVertex(0, 0)
            v.set_position(x, y, elevation)
            self.vertices.insert(i, v)

    def add_to_geom_collector(self, geom_collector: gio.GeometryCollector3D, covering: cov.CCovering) -> None:
        """Adds the cable to the geometry collector.

        Returns the number of vertices added to the geometry collector.
        """
        added_vertices: int = 0
        vertices: dict[int, gio.CVertexDTO] = dict()
        for i in range(0, len(self.vertices) - 1):
            v_idx = added_vertices
            # triangle on the left side around the cable vertex
            cv = self.vertices[i]
            vertices[v_idx + 0] = gio.CVertexDTO(gio.VertexId(v_idx + 0),
                                                 cv.x + math.sin(math.radians(self.heading + 90))*self.radius,
                                                 cv.y + math.cos(math.radians(self.heading + 90))*self.radius,
                                                 cv.elevation - self.radius)
            vertices[v_idx + 1] = gio.CVertexDTO(gio.VertexId(v_idx + 1),
                                                 cv.x - math.sin(math.radians(self.heading + 90))*self.radius,
                                                 cv.y - math.cos(math.radians(self.heading + 90))*self.radius,
                                                 cv.elevation - self.radius)
            vertices[v_idx + 2] = gio.CVertexDTO(gio.VertexId(v_idx + 2), cv.x, cv.y,
                                                 cv.elevation + self.radius)
            # triangle on the right side around the cable vertex
            cv = self.vertices[i+1]
            vertices[v_idx + 3] = gio.CVertexDTO(gio.VertexId(v_idx + 3),
                                                 cv.x + math.sin(math.radians(self.heading + 90))*self.radius,
                                                 cv.y + math.cos(math.radians(self.heading + 90))*self.radius,
                                                 cv.elevation - self.radius)
            vertices[v_idx + 4] = gio.CVertexDTO(gio.VertexId(v_idx + 4),
                                                 cv.x - math.sin(math.radians(self.heading + 90))*self.radius,
                                                 cv.y - math.cos(math.radians(self.heading + 90))*self.radius,
                                                 cv.elevation - self.radius)
            vertices[v_idx + 5] = gio.CVertexDTO(gio.VertexId(v_idx + 5), cv.x, cv.y,
                                                 cv.elevation + self.radius)
            added_vertices += 6

            # the 3 faces between the 2 triangles - only faces along, no faces at the start and the end of the cable
            geom_collector.add_c_face_dto(gio.CFaceDTO({  # front
                vertices[v_idx + 0]: gio.CTMap(0., 0., covering.repeat_type),
                vertices[v_idx + 3]: gio.CTMap(1., 0., covering.repeat_type),
                vertices[v_idx + 5]: gio.CTMap(1., 1., covering.repeat_type),
                vertices[v_idx + 2]: gio.CTMap(0., 1., covering.repeat_type)
            }, covering, False, None))
            geom_collector.add_c_face_dto(gio.CFaceDTO({  # bottom
                vertices[v_idx + 0]: gio.CTMap(0., 1., covering.repeat_type),
                vertices[v_idx + 1]: gio.CTMap(0., 0., covering.repeat_type),
                vertices[v_idx + 4]: gio.CTMap(1., 0., covering.repeat_type),
                vertices[v_idx + 3]: gio.CTMap(1., 1., covering.repeat_type)
            }, covering, False, None))
            geom_collector.add_c_face_dto(gio.CFaceDTO({  # back
                vertices[v_idx + 4]: gio.CTMap(0., 0., covering.repeat_type),
                vertices[v_idx + 1]: gio.CTMap(1., 0., covering.repeat_type),
                vertices[v_idx + 2]: gio.CTMap(1., 1., covering.repeat_type),
                vertices[v_idx + 5]: gio.CTMap(0., 1., covering.repeat_type)
            }, covering, False, None))


@unique
class PylonDirectionType(IntEnum):
    normal = 0  # in ac-file mast is on the left side, stuff on the right side along x-axis
    mirror = 1
    start = 2
    end = 3


def _create_h_frame_25_pylon_vertices() -> list[CableVertex]:
    vertices = [
        CableVertex(-7.25, 18.),
        CableVertex(0., 18.),
        CableVertex(7.25, 18.)
    ]
    return vertices


def _create_steel_single_pylon_30_vertices() -> list[CableVertex]:
    vertices = [
        CableVertex(3.65, 18.3),
        CableVertex(-3.65, 22.3),
        CableVertex(3.65, 26.3)
    ]
    return vertices


def _create_generic_pylon_25_vertices() -> list[CableVertex]:
    vertices = [CableVertex(5.0, 12.6),
                CableVertex(-5.0, 12.6),
                CableVertex(5.0, 16.8),
                CableVertex(-5.0, 16.8),
                CableVertex(5.0, 21.0),
                CableVertex(-5.0, 21.0),
                CableVertex(0.0, 25.2, top_cable=True)]
    return vertices


def _create_generic_pylon_50_vertices() -> list[CableVertex]:
    vertices = [CableVertex(10.0, 25.2),
                CableVertex(-10.0, 25.2),
                CableVertex(10.0, 33.6),
                CableVertex(-10.0, 33.6),
                CableVertex(10.0, 42.0),
                CableVertex(-10.0, 42.0),
                CableVertex(0.0, 50.4, top_cable=True)]
    return vertices


def _create_generic_pylon_100_vertices() -> list[CableVertex]:
    vertices = [CableVertex(20.0, 50.4),
                CableVertex(-20.0, 50.4),
                CableVertex(20.0, 67.2),
                CableVertex(-20.0, 67.2),
                CableVertex(20.0, 84.0),
                CableVertex(-20.0, 84.0),
                CableVertex(0.0, 100.8, top_cable=True)]
    return vertices


def _create_wooden_pole_14m_vertices() -> list[CableVertex]:
    vertices = [CableVertex(1.7, 14.4),
                CableVertex(-1.7, 14.4),
                CableVertex(2.7, 12.6),
                CableVertex(0.7, 12.6),
                CableVertex(-2.7, 12.6),
                CableVertex(-0.7, 12.6)]
    return vertices


def _create_drag_lift_pylon() -> list[CableVertex]:
    vertices = [CableVertex(2.8, 8.1),
                CableVertex(-0.8, 8.1)]
    return vertices


def _create_drag_lift_in_osm_building() -> list[CableVertex]:
    vertices = [CableVertex(2.8, 3.0),
                CableVertex(-0.8, 3.0)]
    return vertices


# for normal gauge width (1.43 metres) the rail texture incl. gravel is ca. 1.61. metres
# We keep the distance also for narrow gauge, because the vehicles on narrow gauge are not much smaller than standard
RAIL_MAST_DIST = 1.8


def _create_rail_power_vertices(direction_type) -> list[CableVertex]:
    if direction_type is PylonDirectionType.mirror:
        vertices = [CableVertex(-1*RAIL_MAST_DIST, 5.85),
                    CableVertex(-1*RAIL_MAST_DIST, 4.95, no_catenary=True)]
    else:
        vertices = [CableVertex(RAIL_MAST_DIST, 5.85),
                    CableVertex(RAIL_MAST_DIST, 4.95, no_catenary=True)]
    return vertices


def _create_rail_stop_tension() -> list[CableVertex]:
    vertices = [CableVertex(0, 5.35),
                CableVertex(0, 4.95, no_catenary=True)]
    return vertices


def _get_cable_vertices(pylon_model: str, direction_type: PylonDirectionType) -> list[CableVertex]:
    if sm.POWER_PYLON_GENERIC_PYLON_25M == pylon_model:
        return _create_generic_pylon_25_vertices()
    elif sm.POWER_PYLON_GENERIC_PYLON_50M == pylon_model:
        return _create_generic_pylon_50_vertices()
    elif sm.POWER_PYLON_GENERIC_PYLON_100M == pylon_model:
        return _create_generic_pylon_100_vertices()
    elif sm.POWER_PYLON_STEEL_SINGLE_30M == pylon_model:
        return _create_steel_single_pylon_30_vertices()
    elif sm.POWER_PYLON_H_FRAME_WOOD_25M == pylon_model or sm.POWER_PYLON_H_FRAME_STEEL_25M == pylon_model:
        return _create_h_frame_25_pylon_vertices()
    elif "drag_lift_pylon" in pylon_model:
        return _create_drag_lift_pylon()
    elif "drag_lift_in_osm_building" in pylon_model:
        return _create_drag_lift_in_osm_building()
    elif sm.POWER_PYLON_WOODEN_POLE_14M == pylon_model:
        return _create_wooden_pole_14m_vertices()
    elif sm.RAIL_POWER_PYLON == pylon_model:
        return _create_rail_power_vertices(direction_type)
    elif sm.RAIL_STOP_TENSION == pylon_model:
        return _create_rail_stop_tension()
    else:
        text = 'Pylon model not found for creating cable vertices: {}'.format(pylon_model)
        raise Exception(text)


@unique
class PylonType(IntEnum):
    unspecified = 0
    power_tower = 11  # OSM-key = "power", value = "tower"
    power_pole = 12  # OSM-key = "power", value = "pole"
    aerialway_pylon = 21  # OSM-key = "aerialway", value = "pylon"
    aerialway_station = 22  # OSM-key = "aerialway", value = "station"

    railway_virtual = 30  # only used at endpoints of RailLine for calcs - not used for visual masts
    railway_single = 31
    railway_double = 32
    railway_stop = 33


class SharedPylon(object):

    __slots__ = ('osm_id', 'type_', 'x', 'y', 'elevation', 'heading', 'pylon_model', 'needs_stg_entry',
                 'direction_type', 'height', 'material', 'design')
    def __init__(self):
        self.osm_id: t.OSMId | None = None
        self.type_ = PylonType.unspecified
        self.x: float = 0.0  # local position x
        self.y: float = 0.0  # local position y
        self.elevation: float = 0.0  # elevation above sea level in meters
        self.heading: float | None = 0.0  # heading of pylon in degrees
        self.pylon_model = None  # the path to the ac/xml model
        self.needs_stg_entry = True
        self.direction_type = PylonDirectionType.normal  # correction for which direction mast looks at
        self.height: float = 0.  # only used for a few pylons - e.g. power poles
        self.material: str | None = None
        self.design: str | None = None

    def make_instanced_entry(self, collector: stg_io2.ObjectInstancedListCollector) -> None:
        if not self.needs_stg_entry:
            return
        
        direction_correction = 0
        if self.direction_type is PylonDirectionType.mirror:
            direction_correction = 180
        elif self.direction_type is PylonDirectionType.end:
            direction_correction = 0
        elif self.direction_type is PylonDirectionType.start:
            direction_correction = 180
        
        entry = stg_io2.ObjectInstancedListEntry(self.osm_id)
        entry.add_position_local_coordinates(self.x, self.y, self.elevation)
        if self.heading is not None:
            entry.add_orientation_local_coordinates(self.heading + direction_correction)
        collector.add_entry(self.pylon_model, entry)


class Chimney(SharedPylon):
    def __init__(self, osm_id: t.OSMId, x: float, y: float, elevation: float, tags: t.OSMTags) -> None:
        super().__init__()
        self.osm_id = osm_id
        self.x = x
        self.y = y
        self.height = parameters.C2P_CHIMNEY_DEFAULT_HEIGHT  # the height of the chimney
        variation = random.uniform(0, parameters.C2P_CHIMNEY_DEFAULT_HEIGHT_VARIATION)
        self.height += variation
        if s.K_HEIGHT in tags:
            self.height = op.parse_length(tags[s.K_HEIGHT])

        bricks = False
        if s.K_BUILDING_MATERIAL in tags and tags[s.K_BUILDING_MATERIAL] == s.V_BRICK:
            bricks = True
        else:  # determine brick material randomly
            ratio = random.uniform(0, 1)
            if ratio <= parameters.C2P_CHIMNEY_BRICK_RATION:
                bricks = True
        if bricks:
            self.pylon_model = sm.CHIMNEY_BRICK_502M
            model_height = 502.
            if self.height > 502.:
                self.height = 502.
        else:
            if self.height <= 120.:
                model_height = 120
                self.pylon_model = sm.CHIMNEY_TPS_DRUJBA2
            else:
                if self.height <= 205.:
                    model_height = 205.
                    self.pylon_model = sm.CHIMNEY_BOESDORF
                elif 205 < self.height < 250:
                    model_height = 250.
                    self.pylon_model = sm.CHIMNEY_KW_ALTBACH
                else:
                    if self.height > 500:
                        self.height = 500.
                    self.pylon_model = sm.CHIMNEY_GENERIC_01
                    model_height = 500.
        # correct elevation to account for model height vs. chimney height
        self.elevation = elevation - (model_height - self.height)


def _process_osm_chimneys_nodes(osm_nodes_dict: dict[t.OSMId, op.Node], coords_transform: co.Transformation,
                                fg_elev: ep.FGElev) -> list[Chimney]:
    chimneys: list[Chimney] = list()

    for key, node in osm_nodes_dict.items():
        elev = fg_elev.probe_elev((node.lon, node.lat), True)
        x, y = coords_transform.to_local((node.lon, node.lat))
        chimney = Chimney(key, x, y, elev, node.tags)
        if chimney.height >= parameters.C2P_CHIMNEY_MIN_HEIGHT:
            chimneys.append(chimney)
    return chimneys


def _process_osm_chimneys_ways(nodes_dict, ways_dict, my_coord_transformator,
                               fg_elev: ep.FGElev) -> list[Chimney]:
    chimneys: list[Chimney] = list()
    for way in list(ways_dict.values()):
        for key in way.tags:
            my_coordinates = list()
            for ref in way.refs:
                if ref in nodes_dict:
                    my_node = nodes_dict[ref]
                    my_coordinates.append(my_coord_transformator.to_local((my_node.lon, my_node.lat)))
            if 2 < len(my_coordinates):
                my_polygon = shg.Polygon(my_coordinates)
                if my_polygon.is_valid and not my_polygon.is_empty:
                    my_centroid = my_polygon.centroid
                    elev = fg_elev.probe_elev((my_centroid.x, my_centroid.y), False)
                    chimney = Chimney(key, my_centroid.x, my_centroid.y, elev, way.tags)
                    if chimney.height >= parameters.C2P_CHIMNEY_MIN_HEIGHT:
                        chimneys.append(chimney)
    return chimneys


class CommunicationMast(SharedPylon):
    def __init__(self, osm_id: t.OSMId, x: float, y: float, elevation: float, tags: t.OSMTags) -> None:
        super().__init__()
        self.osm_id = osm_id
        self.x = x
        self.y = y
        self.height = parameters.C2P_COMMUNICATION_MAST_DEFAULT_HEIGHT
        if s.K_HEIGHT in tags:
            self.height = op.parse_length(tags[s.K_HEIGHT])

        is_micro_tele: bool = s.K_COMMUNICATION_MICRO_WAVE in tags and tags[s.K_COMMUNICATION_MICRO_WAVE] == s.V_YES
        if not is_micro_tele:
            is_micro_tele = s.K_COMMUNICATION_TELEVISION in tags and tags[s.K_COMMUNICATION_TELEVISION] == s.V_YES
        is_mobile: bool = s.K_COMMUNICATION_MOBILE_PHONE in tags and tags[s.K_COMMUNICATION_MOBILE_PHONE] == s.V_YES
        is_radio: bool = s.K_COMMUNICATION_RADIO in tags and tags[s.K_COMMUNICATION_RADIO] == s.V_YES

        if is_radio and self.height > 40:
            if self.height < 60:
                self.pylon_model = sm.COMMUNICATION_MAST_MIL_ANTENNA_45M
            else:
                self.pylon_model = sm.COMMUNICATION_MAST_MIL_ANTENNA_61M
        elif is_micro_tele and not is_mobile:
            if self.height < 30:
                self.pylon_model = sm.COMMUNICATION_MAST_ANTENNA4
            else:
                self.pylon_model = sm.COMMUNICATION_MAST_BASE_CLAPE_3
        else:
            if 30 < self.height < 35:
                self.pylon_model = sm.COMMUNICATION_MAST_BASE_CLAPE_4
            else:
                model_height = 72
                self.pylon_model = random.choice([sm.COMMUNICATION_MAST_CELL_MONO_1,
                                                  sm.COMMUNICATION_MAST_CELL_MONO_2,
                                                  sm.COMMUNICATION_MAST_CELL_MONO_3])
                if self.height > model_height:
                    self.height = model_height
                else:
                    # correct elevation to account for model height vs. chimney height
                    self.elevation = elevation - (model_height - self.height)

    @staticmethod
    def valid_communication_mast(tags: t.OSMTags) -> bool:
        if s.K_MAN_MADE in tags and tags[s.K_MAN_MADE] == s.V_MAST:
            if s.K_TOWER_TYPE in tags and tags[s.K_TOWER_TYPE] == s.V_COMMUNICATION:
                return True
        return False


def _process_osm_communication_mast_nodes(osm_nodes_dict: dict[t.OSMId, op.Node], coords_transform: co.Transformation,
                                          fg_elev: ep.FGElev) -> list[CommunicationMast]:
    masts: list[CommunicationMast] = list()

    for key, node in osm_nodes_dict.items():
        if not CommunicationMast.valid_communication_mast(node.tags):
            continue
        elev = fg_elev.probe_elev((node.lon, node.lat), True)
        x, y = coords_transform.to_local((node.lon, node.lat))
        mast = CommunicationMast(key, x, y, elev, node.tags)
        if mast.height >= parameters.C2P_COMMUNICATION_MAST_MIN_HEIGHT:
            masts.append(mast)
    return masts


def _process_osm_communication_mast_ways(nodes_dict, ways_dict, my_coord_transformator,
                               fg_elev: ep.FGElev) -> list[CommunicationMast]:
    masts: list[CommunicationMast] = list()
    for way in list(ways_dict.values()):
        if not CommunicationMast.valid_communication_mast(way.tags):
            continue
        for key in way.tags:
            my_coordinates = list()
            for ref in way.refs:
                if ref in nodes_dict:
                    my_node = nodes_dict[ref]
                    my_coordinates.append(my_coord_transformator.to_local((my_node.lon, my_node.lat)))
            if 2 < len(my_coordinates):
                my_polygon = shg.Polygon(my_coordinates)
                if my_polygon.is_valid and not my_polygon.is_empty:
                    my_centroid = my_polygon.centroid
                    elev = fg_elev.probe_elev((my_centroid.x, my_centroid.y), False)
                    mast = CommunicationMast(key, my_centroid.x, my_centroid.y, elev, way.tags)
                    if mast.height >= parameters.C2P_COMMUNICATION_MAST_MIN_HEIGHT:
                        masts.append(mast)
    return masts


class StorageTank(SharedPylon):
    """A storage tank or a silo."""
    def __init__(self, osm_id: t.OSMId, x: float, y: float, tags: t.OSMTags, radius: float,
                 elevation: float) -> None:
        super().__init__()
        self.osm_id = osm_id
        self.x = x
        self.y = y
        self.elevation = elevation
        diameter = radius * 2

        # Try to guess a suitable shared model
        # In general we take the .ac models, even though some small detail might be shown from far away
        if s.is_silo(tags):
            if diameter < 18:
                self.pylon_model = sm.SILO_8M
            else:
                self.pylon_model = sm.SILO_20M
        else:  # storage tank
            if s.K_CONTENT in tags and tags[s.K_CONTENT] == s.V_GAS:
                self.pylon_model = sm.STORAGE_TANK_GENERIC_PRESSURE_VESSEL_10M
                if 15 <= diameter < 25:
                    self.pylon_model = sm.STORAGE_TANK_GENERIC_PRESSURE_VESSEL_20M
                elif 25 <= diameter < 35:
                    self.pylon_model = sm.STORAGE_TANK_GENERIC_PRESSURE_VESSEL_30M
                elif 35 <= diameter < 41:
                    self.pylon_model = sm.STORAGE_TANK_GENERIC_PRESSURE_VESSEL_40M
                elif 41 <= diameter <= 75:
                    self.pylon_model = sm.STORAGE_TANK_GASOMETER
                if diameter > 75:
                    self.pylon_model = sm.STORAGE_TANK_HC_TANK  # 80 metres
            else:  # assuming fuel or oil
                if diameter < 11:
                    self.pylon_model = sm.STORAGE_TANK_KOFF_TANK_10M
                elif 11 <= diameter < 13:
                    self.pylon_model = sm.STORAGE_TANK_KOFF_TANK_12M
                elif 13 <= diameter < 18:
                    self.pylon_model = sm.STORAGE_TANK_KOFF_TANK_13M
                elif 18 <= diameter < 25:
                    self.pylon_model = sm.STORAGE_TANK_KOFF_TANK_20M
                elif 25 <= diameter < 55:
                    self.pylon_model = sm.STORAGE_TANK_KOFF_TANK_30M
                elif 55 <= diameter < 74:
                    self.pylon_model = sm.STORAGE_TANK_API_65M
                else:
                    self.pylon_model = sm.STORAGE_TANK_AGIP_80M


class WindTurbine(SharedPylon):
    __slots__ = ('lon', 'lat', 'generator_output', 'generator_type_horizontal', 'offshore',
                 'rotor_diameter', 'manufacturer', 'manufacturer_type', 'illuminated', 'wind_farm')
    def __init__(self, osm_id: t.OSMId, lon: float, lat: float, x: float, y: float,
                 generator_output: float, tags: t.OSMTags) -> None:
        super().__init__()
        self.osm_id = osm_id
        self.lon: float = lon
        self.lat: float = lat
        self.x = x  # only used for compatibility with SharedPylon
        self.y = y  # ditto
        self.generator_output = generator_output
        self.generator_type_horizontal = True
        if s.K_GENERATOR_TYPE in tags and tags[s.K_GENERATOR_TYPE].lower() == "vertical_axis":
            self.generator_type_horizontal = False
        self.offshore = s.K_OFFSHORE in tags and tags[s.K_OFFSHORE].lower() == s.V_YES
        self.height = 0.
        if s.K_HEIGHT in tags:
            self.height = op.parse_length(tags[s.K_HEIGHT])
        elif s.K_SEAMARK_LANDMARK_HEIGHT in tags:
            self.height = op.parse_length(tags[s.K_SEAMARK_LANDMARK_HEIGHT])
        self.rotor_diameter = 0.0
        if s.K_ROTOR_DIAMETER in tags:
            self.rotor_diameter = op.parse_length(tags[s.K_ROTOR_DIAMETER])
        self.manufacturer = None
        if s.K_MANUFACTURER in tags:
            self.manufacturer = tags[s.K_MANUFACTURER]
        self.manufacturer_type = None
        if s.K_MANUFACTURER_TYPE in tags:
            self.manufacturer_type = tags[s.K_MANUFACTURER_TYPE]
        # illumination
        self.illuminated = s.K_SEAMARK_LANDMARK_STATUS in tags and tags[s.K_SEAMARK_LANDMARK_STATUS] == s.V_ILLUMINATED
        if not self.illuminated:
            self.illuminated = s.K_SEAMARK_STATUS in tags and tags[s.K_SEAMARK_STATUS] == s.V_ILLUMINATED
        # wind farm id (artificial - see process_osm_wind_turbines)
        self.wind_farm = None

    def set_offshore_from_probe(self, is_solid: bool):
        """Offshore can be set from OSM tags and be challenged through elevation/water probing."""
        if self.offshore and is_solid:
            logging.debug("Overriding offshore to onshore based on probing for osm_id = {}.".format(self.osm_id))
            self.offshore = False
        if not self.offshore and not is_solid:
            logging.debug("Overriding onshore to offshore based on probing for osm_id = {}.".format(self.osm_id))
            self.offshore = True

    @staticmethod
    def determine_shared_model(height: float, generator_output: float, is_offshore: bool, is_lit: bool) -> str:
        """The relation between height and generator_output are pure guesses and some randomness.
        More intelligent heuristics could also take into account distance between turbines in a farm as an indicator."""
        if is_offshore:
            shared_model = sm.WIND_TURBINE_VESTAS_V80_SEA
            if height > 70 or generator_output > 3000000:
                shared_model = sm.WIND_TURBINE_VESTAS_OFFSHORE_140M

        else:
            if height == 0 and generator_output == 0:
                if is_lit:
                    shared_model = sm.WIND_TURBINE_DEFAULT_FLASH
                else:
                    shared_model = sm.WIND_TURBINE_DEFAULT
            elif height > 50 or generator_output > 1000000:
                shared_model = sm.WIND_TURBINE_E82_78M
                if height > 84 or generator_output > 3000000:
                    shared_model = sm.WIND_TURBINE_E82_85M
                if height > 97 or generator_output > 3200000:
                    shared_model = sm.WIND_TURBINE_E82_98M
                if height > 107 or generator_output > 3500000:
                    shared_model = sm.WIND_TURBINE_E82_108M
                if height > 137 or generator_output > 4000000:
                    shared_model = sm.WIND_TURBINE_E82_138M
            else:
                shared_model = sm.WIND_TURBINE_LAG18_18M_OBST if is_lit else sm.WIND_TURBINE_LAG18_18M
                if height >= 24 or generator_output > 20000:
                    shared_model = sm.WIND_TURBINE_LAG18_24M_OBST if is_lit else sm.WIND_TURBINE_LAG18_24M
                if height >= 30 or generator_output > 30000:
                    shared_model = sm.WIND_TURBINE_LAG18_30M_OBST if is_lit else sm.WIND_TURBINE_LAG18_30M
                if height >= 39 or generator_output > 40000:
                    shared_model = sm.WIND_TURBINE_LAG18_39M_OBST if is_lit else sm.WIND_TURBINE_LAG18_39M
        logging.debug("Wind turbine shared model chosen: {}".format(shared_model))
        return shared_model

    def make_stg_entry(self, my_stg_mgr: stg_io2.STGManager) -> None:
        # special for Vestas_Off_Shore140M.xml
        if self.pylon_model == sm.WIND_TURBINE_VESTAS_OFFSHORE_140M:
            my_stg_mgr.add_object_shared(sm.WIND_TURBINE_VESTAS_BASE, co.Vec2d(self.lon, self.lat),
                                         self.elevation, 0)
            # no need to add 12m to elevation for Vestas_Off_Shore140M.xml - ac-model already takes care
        my_stg_mgr.add_object_shared(self.pylon_model, co.Vec2d(self.lon, self.lat), self.elevation, 0)

    @override
    def make_instanced_entry(self, collector: stg_io2.ObjectInstancedListCollector) -> None:
        raise ValueError('Wind turbines cannot be instantiated due to xml')


class WindFarm(object):
    def __init__(self) -> None:
        self.turbines = set()

    def add_turbine(self, turbine: WindTurbine) -> None:
        self.turbines.add(turbine)

    def determine_shared_model(self):
        """Stupidly assumes that all turbines actually belong to same farm and have the same type.
        In the end assigns shared model to all turbines in the farm."""

        # first do some statistics
        max_height = 0
        max_generator_output = 0
        number_offshore = 0
        number_illuminated = 0
        for turbine in self.turbines:
            max_height = max(max_height, turbine.height)
            max_generator_output = max(max_generator_output, turbine.generator_output)
            if turbine.offshore:
                number_offshore += 1
            if turbine.illuminated:
                number_illuminated += 1
        is_offshore = number_offshore > len(self.turbines) / 2
        is_illuminated = number_illuminated > 0

        # then determine model based on "average"
        shared_model = WindTurbine.determine_shared_model(max_height, max_generator_output, is_offshore, is_illuminated)
        for turbine in self.turbines:
            turbine.pylon_model = shared_model


def _process_osm_wind_turbines(osm_nodes_dict: dict[t.OSMId, op.Node], coords_transform: co.Transformation,
                               fg_elev: ep.FGElev, stg_entries: list[stg_io2.STGEntry]) -> list[WindTurbine]:
    my_wind_turbines = list()
    wind_farms = list()

    # make sure no existing shared objects are duplicated. Do not care what shared object within distance
    # find relevant / valid wind turbines
    for key, node in osm_nodes_dict.items():
        if s.K_GENERATOR_SOURCE in node.tags and node.tags[s.K_GENERATOR_SOURCE] == s.V_WIND:
            if s.K_GENERATOR_OUTPUT_ELECTRICITY in node.tags:
                # first check against existing
                shared_within_distance = False
                for entry in stg_entries:
                    if entry.verb_type is stg_io2.STGVerbType.object_shared:
                        if co.calc_distance_global(entry.lon, entry.lat, node.lon, node.lat) < \
                                parameters.C2P_WIND_TURBINE_MIN_DISTANCE_SHARED_OBJECT:
                            logging.debug("Excluding turbine osm_id = {} - overlaps shared object.".format(node.osm_id))
                            shared_within_distance = True
                            break
                if shared_within_distance:
                    continue
                generator_output = op.parse_generator_output(node.tags["generator:output:electricity"])
                x, y = coords_transform.to_local((node.lon, node.lat))
                turbine = WindTurbine(key, node.lon, node.lat, x, y, generator_output, node.tags)
                probe_tuple = fg_elev.probe((node.lon, node.lat), True)
                turbine.elevation = probe_tuple[0]
                turbine.set_offshore_from_probe(probe_tuple[1])
                my_wind_turbines.append(turbine)
            else:
                logging.debug("Skipped wind turbine osm_id = {}: need tag 'generator:output:electricity'".format(key))
                continue

    # Create wind farms to help determine model, illumination etc.
    # http://wiki.openstreetmap.org/wiki/Relations/Proposed/Site site=wind_farm is not used a lot
    # Therefore brute force based on distance
    for i in range(1, len(my_wind_turbines)):
        for j in range(i + 1, len(my_wind_turbines)):
            if co.calc_distance_local(my_wind_turbines[i].x, my_wind_turbines[i].y,
                                      my_wind_turbines[j].x, my_wind_turbines[j].y) \
                    <= parameters.C2P_WIND_TURBINE_MAX_DISTANCE_WITHIN_WIND_FARM:
                my_wind_farm = my_wind_turbines[i].wind_farm
                if my_wind_farm is None:
                    my_wind_farm = WindFarm()
                    wind_farms.append(my_wind_farm)
                    my_wind_farm.add_turbine(my_wind_turbines[i])
                    my_wind_turbines[i].wind_farm = my_wind_farm
                my_wind_farm.add_turbine(my_wind_turbines[j])
                my_wind_turbines[j].wind_farm = my_wind_farm

    logging.debug("Found {} wind farms".format(len(wind_farms)))

    # assign models in farms
    for farm in wind_farms:
        farm.determine_shared_model()
    # assign to those outside of a farm
    for turbine in my_wind_turbines:
        if turbine.wind_farm is None:
            turbine.pylon_model = WindTurbine.determine_shared_model(turbine.height, turbine.generator_output,
                                                                     turbine.offshore, turbine.illuminated)

    return my_wind_turbines


class Pylon(SharedPylon):
    """For over the ground power lines, communication lines or aerialways."""
    def __init__(self, osm_id: t.OSMId):
        super().__init__()
        self.osm_id = osm_id
        self.structure = None
        self.colour = None
        self.prev_pylon = None
        self.next_pylon = None
        self.in_osm_building = False  # a pylon can be in an OSM Way/building, in which case it should not be drawn

    def calc_pylon_model(self, pylon_model):
        if self.type_ is PylonType.aerialway_station:
            if self.in_osm_building:
                self.needs_stg_entry = False
                self.pylon_model = pylon_model + "_in_osm_building"
            else:
                if not self.prev_pylon:
                    self.pylon_model = pylon_model + "_start_station"
                else:
                    self.pylon_model = pylon_model + "_end_station"
        else:
            self.pylon_model = pylon_model


class LineWithoutCables(object):
    __slots__ = ('osm_id', 'shared_pylons')

    def __init__(self, osm_id: t.OSMId):
        self.osm_id: t.OSMId = osm_id
        self.shared_pylons: list[SharedPylon] = list()

    def make_instance_entries(self, instanced_collector: stg_io2.ObjectInstancedListCollector) -> None:
        for my_pylon in self.shared_pylons:
            my_pylon.make_instanced_entry(instanced_collector)


class StreetlampWay(LineWithoutCables):
    def __init__(self, osm_id: t.OSMId, highway):
        super().__init__(osm_id)
        self.highway = highway

    @staticmethod
    def has_lamps(highway_type):
        if highway_type is e.HighwayType.slow:
            return False
        return True

    def calc_and_map(self, fg_elev: ep.FGElev) -> None:
        if self.highway.is_roundabout:
            shared_pylon = SharedPylon()
            shared_pylon.pylon_model = sm.STREETLAMP_3  # not using xml for effect
            p = shg.Polygon(self.highway.linear)
            shared_pylon.x = p.centroid.x
            shared_pylon.y = p.centroid.y
            self.shared_pylons.append(shared_pylon)
        else:
            model = sm.STREETLAMP_2  # not using xml for effect
            default_distance = parameters.C2P_STREETLAMPS_OTHER_DISTANCE
            parallel_offset = self.highway.get_width()/2
            if self.highway.type_ in [e.HighwayType.service, e.HighwayType.residential,
                                      e.HighwayType.living_street, e.HighwayType.pedestrian]:
                model = sm.STREETLAMP_1  # not using xml for effect
                default_distance = parameters.C2P_STREETLAMPS_RESIDENTIAL_DISTANCE

            self.shared_pylons = []  # list of SharedPylon
            x, y = self.highway.linear.coords[0]
            shared_pylon = SharedPylon()
            shared_pylon.x = x
            shared_pylon.y = y
            shared_pylon.needs_stg_entry = False
            shared_pylon.elevation = fg_elev.probe_elev((x, y), False)
            self.shared_pylons.append(shared_pylon)  # used for calculating heading - especially if only one lamp

            my_right_parallel = self.highway.linear.parallel_offset(parallel_offset, 'right', join_style=1)
            my_right_parallel_length = my_right_parallel.length
            current_distance = 10  # the distance from the origin of the current streetlamp

            while True:
                if current_distance > my_right_parallel_length:
                    break
                point_on_line = my_right_parallel.interpolate(my_right_parallel_length - current_distance)
                shared_pylon = SharedPylon()
                shared_pylon.x = point_on_line.x
                shared_pylon.y = point_on_line.y
                shared_pylon.pylon_model = model
                shared_pylon.direction_type = PylonDirectionType.mirror
                shared_pylon.elevation = fg_elev.probe_elev((x, y), False)
                self.shared_pylons.append(shared_pylon)
                current_distance += default_distance

            # calculate heading
            # FIXME: should be better done using the street angle instead of pylons
            if len(self.shared_pylons) > 1:
                _calc_heading_nodes(self.shared_pylons)


class WaySegment(object):
    """Represents the part between the pylons and is a container for the cables"""
    __slots__ = ('start_pylon', 'end_pylon', 'cables', 'length', 'heading')

    def __init__(self, start_pylon: SharedPylon, end_pylon: SharedPylon):
        self.start_pylon = start_pylon
        self.end_pylon = end_pylon
        self.cables = []
        self.length = co.calc_distance_local(start_pylon.x, start_pylon.y, end_pylon.x, end_pylon.y)
        self.heading = co.calc_angle_of_line_local(start_pylon.x, start_pylon.y, end_pylon.x, end_pylon.y)


class Line(LineWithoutCables):
    __slots__ = ('way_segments', 'length', 'original_osm_way')

    def __init__(self, osm_id: t.OSMId) -> None:
        super().__init__(osm_id)
        self.way_segments = []
        self.length = 0.0  # the total length of all segments
        self.original_osm_way = None

    def _calc_segments(self) -> float:
        """Creates the segments of this WayLine and calculates the total length.
        Returns the maximum length of segments"""
        max_length = 0.0
        total_length = 0.0
        self.way_segments = []  # if this method would be called twice by mistake
        for x in range(0, len(self.shared_pylons) - 1):
            segment = WaySegment(self.shared_pylons[x], self.shared_pylons[x + 1])
            self.way_segments.append(segment)
            if segment.length > max_length:
                max_length = segment.length
            total_length += segment.length
        self.length = total_length
        return max_length

    def _calc_cables(self, radius: float, number_extra_vertices: int, catenary_a: int) -> None:
        """
        Creates the cables per WaySegment. First, find the start and end points depending on the pylon model.
        Then calculate the local positions of all start and end points.
        Afterwards use the start and end points to create all cables for a given WaySegment
        """
        for segment in self.way_segments:
            start_cable_vertices = _get_cable_vertices(segment.start_pylon.pylon_model,
                                                       segment.start_pylon.direction_type)
            end_cable_vertices = _get_cable_vertices(segment.end_pylon.pylon_model,
                                                     segment.end_pylon.direction_type)

            # make sure sagging is not too much -> correct catenary_a if needed
            min_cable_height = 9999
            max_sagging = 1
            for vertex in start_cable_vertices:
                min_cable_height = min(min_cable_height, vertex.height)
                max_sagging = parameters.C2P_CATENARY_A_MAX_SAGGING * min_cable_height

            max_sagging_catenary_a, b = _optimize_catenary(segment.length/2, 100 * catenary_a, max_sagging, 0.01)
            corrected_catenary_a = catenary_a
            if max_sagging_catenary_a > catenary_a:  # the larger the catenary_a, the less sagging
                corrected_catenary_a = max_sagging_catenary_a
                logging.debug("Changed catenary_a from {} to {}".format(catenary_a, max_sagging_catenary_a))

            # now create cables with acceptable sagging
            for i in range(0, len(start_cable_vertices)):
                my_radius = radius
                my_number_extra_vertices = number_extra_vertices
                start_cable_vertices[i].calc_position(segment.start_pylon.x, segment.start_pylon.y,
                                                      segment.start_pylon.elevation, segment.start_pylon.heading)
                end_cable_vertices[i].calc_position(segment.end_pylon.x, segment.end_pylon.y,
                                                    segment.end_pylon.elevation, segment.end_pylon.heading)
                if start_cable_vertices[i].top_cable:
                    my_radius = parameters.C2P_RADIUS_TOP_LINE
                if start_cable_vertices[i].no_catenary:
                    my_number_extra_vertices = 0
                cable = Cable(start_cable_vertices[i], end_cable_vertices[i], my_radius, my_number_extra_vertices,
                              corrected_catenary_a, segment.length)
                segment.cables.append(cable)


@unique
class WayLineType(IntEnum):
    unspecified = 0
    power_line = 11  # OSM-key = "power", value = "line"
    power_minor = 12  # OSM-key = "power", value = "minor_line"
    aerialway_cable_car = 21  # OSM-key = "aerialway", value = "cable_car"
    aerialway_chair_lift = 22  # OSM-key = "aerialway", value = "chair_lift" or "mixed_lift"
    aerialway_drag_lift = 23  # OSM-key = "aerialway", value = "drag_lift" or "t-bar" or "j-bar" or "platter"
    aerialway_gondola = 24  # OSM-key = "aerialway", value = "gondola"
    aerialway_goods = 25  # OSM-key = "aerialway", value = "goods"


class WayLine(Line):  # The name "Line" is also used in e.g. SymPy

    def __init__(self, osm_id: t.OSMId) -> None:
        super().__init__(osm_id)
        self.type_ = WayLineType.unspecified  # cf. class constants TYPE_*
        self.voltage = 0  # from osm-tag "voltage"
        self.cables = 0  # from osm-tag "cables"
        self.wires = None  # from osm-tag "wires"

    def is_aerialway(self) -> bool:
        return self.type_ not in (WayLineType.power_line, WayLineType.power_minor)

    def calc_and_map(self) -> None:
        """Calculates various aspects of the line and its nodes and attempt to correct if needed. """
        max_length = self._calc_segments()
        if self.is_aerialway():
            pylon_model = self._calc_and_map_aerialway()
        else:
            pylon_model = self._calc_and_map_powerline(max_length)
        for my_pylon in self.shared_pylons:
            my_pylon.pylon_model = pylon_model

        _calc_heading_nodes(self.shared_pylons)

        # calc cables
        radius = parameters.C2P_RADIUS_POWER_LINE
        number_extra_vertices = parameters.C2P_EXTRA_VERTICES_POWER_LINE
        catenary_a = parameters.C2P_CATENARY_A_POWER_LINE
        if self.type_ is WayLineType.power_minor:
            radius = parameters.C2P_RADIUS_POWER_MINOR_LINE
            number_extra_vertices = parameters.C2P_EXTRA_VERTICES_POWER_MINOR_LINE
            catenary_a = parameters.C2P_CATENARY_A_POWER_MINOR_LINE
        elif self.type_ is WayLineType.aerialway_cable_car:
            radius = parameters.C2P_RADIUS_AERIALWAY_CABLE_CAR
            number_extra_vertices = parameters.C2P_EXTRA_VERTICES_AERIALWAY_CABLE_CAR
            catenary_a = parameters.C2P_CATENARY_A_AERIALWAY_CABLE_CAR
        elif self.type_ is WayLineType.aerialway_chair_lift:
            radius = parameters.C2P_RADIUS_AERIALWAY_CHAIR_LIFT
            number_extra_vertices = parameters.C2P_EXTRA_VERTICES_AERIALWAY_CHAIR_LIFT
            catenary_a = parameters.C2P_CATENARY_A_AERIALWAY_CHAIR_LIFT
        elif self.type_ is WayLineType.aerialway_drag_lift:
            radius = parameters.C2P_RADIUS_AERIALWAY_DRAG_LIFT
            number_extra_vertices = parameters.C2P_EXTRA_VERTICES_AERIALWAY_DRAG_LIFT
            catenary_a = parameters.C2P_CATENARY_A_AERIALWAY_DRAG_LIFT
        elif self.type_ is WayLineType.aerialway_gondola:
            radius = parameters.C2P_RADIUS_AERIALWAY_GONDOLA
            number_extra_vertices = parameters.C2P_EXTRA_VERTICES_AERIALWAY_GONDOLA
            catenary_a = parameters.C2P_CATENARY_A_AERIALWAY_GONDOLA
        elif self.type_ is WayLineType.aerialway_goods:
            radius = parameters.C2P_RADIUS_AERIALWAY_GOODS
            number_extra_vertices = parameters.C2P_EXTRA_VERTICES_AERIALWAY_GOODS
            catenary_a = parameters.C2P_CATENARY_A_AERIALWAY_GOODS
        self._calc_cables(radius, number_extra_vertices, catenary_a)

    def _calc_and_map_aerialway(self) -> str:
        pylon_model = sm.AERIALWAY_DRAG_LIFT_PYLON
        return pylon_model

    def _calc_and_map_powerline(self, max_length: float) -> str:
        """
        Danish rules of thumb:
        400KV: height 30-42 meter, distance 200-420 meter, sagging 4.5-13 meter, a_value 1110-1698
        150KV: height 25-32 meter, distance 180-350 meter, sagging 2.5-9 meter, a_value 1614-1702
        60KV: height 15-25 meter, distance 100-250 meter, sagging 1-5 meter, a_value 1238-1561
        The a_value for the catenary function has been calculated with _optimize_catenary().
        """
        # calculate min, max, averages etc.
        max_height = 0.0
        average_height = 0.0
        found = 0
        nbr_poles = 0
        nbr_towers = 0
        is_wood: bool | None = None
        is_h_frame: bool | None = None
        for my_pylon in self.shared_pylons:
            if my_pylon.type_ is PylonType.power_tower:
                nbr_towers += 1
            elif my_pylon.type_ is PylonType.power_pole:
                nbr_poles += 1
            if my_pylon.height > 0:
                average_height += my_pylon.height
                found += 1
            if my_pylon.height > max_height:
                max_height = my_pylon.height
            if my_pylon.material and is_wood is None:  # we only test once
                is_wood = my_pylon.material == s.V_WOOD
            if my_pylon.design and is_h_frame is None:  # we only test once
                is_h_frame = s.V_H_FRAME in my_pylon.design
        if found > 0:
            average_height /= found

        # use statistics to determine type_ and pylon_model
        if self.type_ is WayLineType.power_minor and \
                (nbr_towers <= nbr_poles and max_height <= 25.0 and max_length <= 250.0):
            self.type_ = WayLineType.power_minor
            pylon_model = sm.POWER_PYLON_WOODEN_POLE_14M
        else:
            self.type_ = WayLineType.power_line
            if is_wood and average_height < 35.0:
                pylon_model = sm.POWER_PYLON_H_FRAME_WOOD_25M
            elif is_h_frame and average_height < 35.0:
                pylon_model = sm.POWER_PYLON_H_FRAME_STEEL_25M
            elif 0 < self.cables < 4 and average_height < 35.0:
                pylon_model = sm.POWER_PYLON_STEEL_SINGLE_30M
            # fall back to generic towers
            elif average_height < 35.0 and max_length < 300.0:
                pylon_model = sm.POWER_PYLON_GENERIC_PYLON_25M
            elif average_height < 75.0 and max_length < 500.0:
                pylon_model = sm.POWER_PYLON_GENERIC_PYLON_50M
            elif parameters.C2P_POWER_LINE_ALLOW_100M:
                pylon_model = sm.POWER_PYLON_GENERIC_PYLON_100M
            else:
                pylon_model = sm.POWER_PYLON_GENERIC_PYLON_50M
            # check special stuff

        return pylon_model


class RailNode:
    def __init__(self, osm_id: t.OSMId):
        self.osm_id = osm_id
        self.switch = False
        self.buffer_stop = False
        self.lon = 0.0  # longitude coordinate in decimal as a float
        self.lat = 0.0  # latitude coordinate in decimal as a float
        self.x = 0.0  # local position x
        self.y = 0.0  # local position y
        self.elevation = 0.0  # elevation above sea level in meters


class RailMast(SharedPylon):
    __slots__ = 'point_on_line'

    def __init__(self, type_: PylonType, point_on_line: shg.Point, mast_point: shg.Point,
                 direction_type: PylonDirectionType, elevation: float) -> None:
        super().__init__()
        self.type_ = type_
        self.point_on_line = point_on_line
        self.x = mast_point.x
        self.y = mast_point.y
        self.pylon_model = sm.RAIL_POWER_PYLON
        if self.type_ is PylonType.railway_virtual:
            self.needs_stg_entry = False
        elif self.type_ is PylonType.railway_stop:
            self.pylon_model = sm.RAIL_STOP_TENSION
        self.direction_type = direction_type
        self.elevation = elevation


class RailLine(Line):
    """Used to create electrical lines.

    No difference is made between normal and narrow gauges"""
    __slots__ = ('nodes', 'linear', '_elevation_points')

    DEFAULT_MAST_DISTANCE = 60  # if this is changed then mast algorithm for radius below must be adapted
    OFFSET = 20  # the offset from end points
    MAX_DEVIATION = 1  # The distance the overhead line can be off from the centre
    MAST_BUFFER = 3.0


    def __init__(self, osm_id: t.OSMId, nodes: list[RailNode], linear: shg.LineString):
        super().__init__(osm_id)
        self.nodes: list[RailNode] = nodes
        self.linear: shg.LineString = linear

        # calculate interpolation points for elevation based on rail nodes, because then we also get v_add etc.
        # on a bridge or embankment, which fgelev alone would not give us -> interpolation needed
        self._elevation_points: list[tuple[float, float]] = list()
        node = self.nodes[0]
        self._elevation_points.append((0., node.elevation))
        for index in range(1, len(self.nodes) - 1):
            node = self.nodes[index]
            self._elevation_points.append((self.linear.project(shg.Point(node.x, node.y)), node.elevation))
        node = self.nodes[-1]
        self._elevation_points.append((self.linear.length, node.elevation))

    def _interpolate_elevation(self, dist_from_start: float) -> float:
        second_idx = 1
        while True:
            if math.fabs(self._elevation_points[second_idx][0] - dist_from_start) < 1.0:
                return self._elevation_points[second_idx][1]  # keep it simple and avoid diff == 0.

            if self._elevation_points[second_idx][0] < dist_from_start:
                second_idx += 1
            else:
                break
        diff_elevation = self._elevation_points[second_idx][1] - self._elevation_points[second_idx - 1][1]
        diff_dist = self._elevation_points[second_idx][0] - self._elevation_points[second_idx - 1][0]
        ratio = (dist_from_start - self._elevation_points[second_idx - 1][0]) / diff_dist
        return self._elevation_points[second_idx -1 ][1] + diff_elevation * ratio

    def calc_and_map(self, rail_lines_list) -> None:
        current_distance = 0  # the distance from the origin of the current mast
        my_length = self.linear.length  # omit recalculating length all the time
        # offset must be same as create_rail_power_vertices()
        my_right_parallel = self.linear.parallel_offset(-1*RAIL_MAST_DIST, side='right', join_style=JOIN_STYLE.round)
        my_right_parallel_length = my_right_parallel.length
        my_left_parallel = self.linear.parallel_offset(-1*RAIL_MAST_DIST, side='left', join_style=JOIN_STYLE.round)
        my_left_parallel_length = my_left_parallel.length

        # virtual start point
        point_on_line = self.linear.interpolate(0)
        mast_point = my_right_parallel.interpolate(0)
        if self.nodes[0].buffer_stop:
            rail_mast = RailMast(PylonType.railway_stop, point_on_line, point_on_line, PylonDirectionType.start,
                                 self.nodes[0].elevation)
        else:
            rail_mast = RailMast(PylonType.railway_virtual, point_on_line, mast_point, PylonDirectionType.normal,
                                 self.nodes[0].elevation)
        self.shared_pylons.append(rail_mast)
        prev_point = point_on_line

        # get the first mast point
        if my_length < RailLine.DEFAULT_MAST_DISTANCE:
            current_distance += (my_length / 2)
            point_on_line = self.linear.interpolate(current_distance)
            mast_point = my_right_parallel.interpolate(current_distance * (my_right_parallel_length / my_length))
            is_right = self.check_mast_left_right(mast_point, rail_lines_list)
            if is_right:
                direction_type = PylonDirectionType.normal
            else:
                direction_type = PylonDirectionType.mirror
                mast_point = my_left_parallel.interpolate(current_distance * (my_left_parallel_length / my_length))
            rail_mast = RailMast(PylonType.railway_single, point_on_line, mast_point, direction_type,
                                 self._interpolate_elevation(current_distance))
            self.shared_pylons.append(rail_mast)
        else:
            current_distance += RailLine.OFFSET
            point_on_line = self.linear.interpolate(current_distance)
            mast_point = my_right_parallel.interpolate(current_distance * (my_right_parallel_length / my_length))
            is_right = self.check_mast_left_right(mast_point, rail_lines_list)
            if is_right:
                direction_type = PylonDirectionType.normal
            else:
                direction_type = PylonDirectionType.mirror
                mast_point = my_left_parallel.interpolate(current_distance * (my_left_parallel_length / my_length))
            rail_mast = RailMast(PylonType.railway_single, point_on_line, mast_point, direction_type,
                                 self._interpolate_elevation(current_distance))
            self.shared_pylons.append(rail_mast)
            prev_angle = co.calc_angle_of_line_local(prev_point.x, prev_point.y, point_on_line.x, point_on_line.y)
            prev_point = point_on_line
            # find new masts along the line with a simple approximation for less distance between masts
            # if the radius gets tighter
            while True:
                if (my_length - current_distance) <= RailLine.OFFSET:
                    break
                min_distance = my_length - current_distance - RailLine.OFFSET
                if min_distance < RailLine.DEFAULT_MAST_DISTANCE:
                    current_distance += min_distance
                else:
                    test_distance = current_distance + RailLine.DEFAULT_MAST_DISTANCE
                    point_on_line = self.linear.interpolate(test_distance)
                    new_angle = co.calc_angle_of_line_local(prev_point.x, prev_point.y,
                                                            point_on_line.x, point_on_line.y)
                    difference = abs(new_angle - prev_angle)
                    if difference >= 25:
                        current_distance += 10
                    elif difference >= 20:
                        current_distance += 20
                    elif difference >= 15:
                        current_distance += 30
                    elif difference >= 10:
                        current_distance += 40
                    elif difference >= 5:
                        current_distance += 50
                    else:
                        current_distance += RailLine.DEFAULT_MAST_DISTANCE
                point_on_line = self.linear.interpolate(current_distance)
                mast_point = my_right_parallel.interpolate(current_distance * (my_right_parallel_length / my_length))
                is_right = self.check_mast_left_right(mast_point, rail_lines_list)
                if is_right:
                    direction_type = PylonDirectionType.normal
                else:
                    direction_type = PylonDirectionType.mirror
                    mast_point = my_left_parallel.interpolate(current_distance * (my_left_parallel_length / my_length))
                rail_mast = RailMast(PylonType.railway_single, point_on_line, mast_point, direction_type,
                                     self._interpolate_elevation(current_distance))
                self.shared_pylons.append(rail_mast)
                prev_angle = co.calc_angle_of_line_local(prev_point.x, prev_point.y,
                                                         point_on_line.x, point_on_line.y)
                prev_point = point_on_line

        # virtual end point
        point_on_line = self.linear.interpolate(my_length)
        mast_point = my_right_parallel.interpolate(my_right_parallel_length)
        if self.nodes[-1].buffer_stop:
            rail_mast = RailMast(PylonType.railway_stop, point_on_line, point_on_line, PylonDirectionType.end,
                                 self.nodes[-1].elevation)
        else:
            rail_mast = RailMast(PylonType.railway_virtual, point_on_line, mast_point, PylonDirectionType.normal,
                                 self.nodes[-1].elevation)
        self.shared_pylons.append(rail_mast)

        # calculate heading
        _calc_heading_nodes(self.shared_pylons)

        # segments
        self._calc_segments()

        # cables
        self._calc_cables(parameters.C2P_RADIUS_OVERHEAD_LINE, parameters.C2P_EXTRA_VERTICES_OVERHEAD_LINE,
                          parameters.C2P_CATENARY_A_OVERHEAD_LINE)

    def check_mast_left_right(self, mast_point, rail_lines_list):
        mast_buffer = mast_point.buffer(RailLine.MAST_BUFFER)
        is_right = True
        for my_line in rail_lines_list:
            if (my_line.osm_id != self.osm_id) and mast_buffer.intersects(my_line.linear):
                is_right = False
                break
        return is_right


def process_osm_power_aerialway(req_keys: list[str], fg_elev: ep.FGElev, my_coord_transformator,
                                building_refs: list[shg.Polygon]) -> tuple[list[WayLine], list[WayLine]]:
    """
    Transforms a dict of Node and a dict of Way OSMElements from op.py to a dict of WayLine objects for
    electrical power lines and a dict of WayLine objects for aerialways. Nodes are transformed to Pylons.
    The elevation of the pylons is calculated as part of this process.
    """
    osm_way_result = op.fetch_osm_data_ways_keys(req_keys)
    nodes_dict = osm_way_result.nodes_dict
    ways_dict = osm_way_result.ways_dict

    my_powerlines: dict[t.OSMId, WayLine] = {}
    my_aerialways: dict[t.OSMId, WayLine] = {}
    my_shared_nodes: dict[t.OSMId, list[WayLine]] = {}  # node osm_id as key
    clipping_border = shg.Polygon(parameters.get_clipping_border())

    way_lines: list[WayLine] = list()

    for way in list(ways_dict.values()):
        my_line = WayLine(way.osm_id)
        for key in way.tags:
            value = way.tags[key]
            if s.K_POWER == key:
                if s.V_LINE == value:
                    my_line.type_ = WayLineType.power_line
                elif s.V_MINOR_LINE == value:
                    my_line.type_ = WayLineType.power_minor
            elif s.K_AERIALWAY == key:
                if "cable_car" == value:
                    my_line.type_ = WayLineType.aerialway_cable_car
                elif value in ["chair_lift", "mixed_lift"]:
                    my_line.type_ = WayLineType.aerialway_chair_lift
                elif value in ["drag_lift", "t-bar", "j-bar", "platter"]:
                    my_line.type_ = WayLineType.aerialway_drag_lift
                elif "gondola" == value:
                    my_line.type_ = WayLineType.aerialway_gondola
                elif "goods" == value:
                    my_line.type_ = WayLineType.aerialway_goods
            #  special values
            elif s.K_CABLES == key:
                my_line.cables = s.parse_multi_int_values(value)
            elif s.K_VOLTAGE == key:
                my_line.voltage = s.parse_multi_int_values(value)
            elif s.K_WIRES == key:
                my_line.wires = value  # is a string, cf. http://wiki.openstreetmap.org/wiki/Key:wires
        if my_line.type_ is WayLineType.unspecified:
            continue
        if my_line.is_aerialway():
            first_node = nodes_dict[way.refs[0]]
            if not clipping_border.contains(shg.Point(first_node.lon, first_node.lat)):
                continue
            else:
                my_line.original_osm_way = way
                way_lines.append(my_line)
        else:
            split_ways = op.split_way_at_boundary(nodes_dict, way, clipping_border, op.OSMFeatureType.pylon_way)
            if not split_ways:
                continue
            else:
                for split_way in split_ways:
                    split_line = WayLine(way.osm_id)
                    if split_way.pseudo_osm_id != 0:
                        split_line.osm_id = way.pseudo_osm_id
                    split_line.original_osm_way = split_way
                    split_line.type_ = my_line.type_
                    split_line.cables = my_line.cables
                    split_line.voltage = my_line.voltage
                    if my_line.wires is not None:
                        split_line.wires = my_line.wires
                    way_lines.append(split_line)

    for my_line in way_lines:
        prev_pylon = None
        for ref in my_line.original_osm_way.refs:
            if ref in nodes_dict:
                my_node = nodes_dict[ref]
                my_pylon = Pylon(my_node.osm_id)
                my_pylon.lat = my_node.lat
                my_pylon.lon = my_node.lon
                my_pylon.x, my_pylon.y = my_coord_transformator.to_local((my_node.lon, my_node.lat))
                my_pylon.elevation = fg_elev.probe_elev((my_pylon.lon, my_pylon.lat), True)
                for key in my_node.tags:
                    value = my_node.tags[key]
                    if s.K_POWER == key:
                        if s.V_TOWER == value:
                            my_pylon.type_ = PylonType.power_tower
                        elif s.V_POLE == value:
                            my_pylon.type_ = PylonType.power_pole
                    elif s.K_AERIALWAY == key:
                        if s.V_PYLON == value:
                            my_pylon.type_ = PylonType.aerialway_pylon
                        elif s.V_STATION == value:
                            my_pylon.type_ = PylonType.aerialway_station
                            my_point = shg.Point(my_pylon.x, my_pylon.y)
                            for building_ref in building_refs:
                                if building_ref.contains(my_point):
                                    my_pylon.in_osm_building = True
                                    logging.debug('Station with osm_id = %s found within building reference',
                                                  my_pylon.osm_id)
                                    break
                    elif s.K_HEIGHT == key:
                        my_pylon.height = op.parse_length(value)
                    elif s.K_STRUCTURE == key:
                        my_pylon.structure = value
                    elif s.K_MATERIAL == key:
                        my_pylon.material = value
                    elif s.K_DESIGN == value:
                        my_pylon.design = value
                if my_pylon.elevation != ep.FG_ELEV_NO_ELEV:  # otherwise it is outside tile boundaries
                    my_line.shared_pylons.append(my_pylon)
                else:
                    logging.debug('Node outside of boundaries and therefore ignored: osm_id = %s', my_node.osm_id)
                if prev_pylon is not None:
                    prev_pylon.next_pylon = my_pylon
                    my_pylon.prev_pylon = prev_pylon
                prev_pylon = my_pylon
        if len(my_line.shared_pylons) > 1:
            for the_node in [my_line.shared_pylons[0], my_line.shared_pylons[-1]]:
                if the_node.osm_id in my_shared_nodes:
                    my_shared_nodes[the_node.osm_id].append(my_line)
                else:
                    my_shared_nodes[the_node.osm_id] = [my_line]
            if my_line.is_aerialway():
                my_aerialways[my_line.osm_id] = my_line
            else:
                my_powerlines[my_line.osm_id] = my_line
        else:
            logging.warning('Line could not be validated or corrected. osm_id = %s', my_line.osm_id)

    for key in list(my_shared_nodes.keys()):  # cannot iterate over .items() because changing dict content
        shared_node = my_shared_nodes[key]
        if not shared_node:
            continue
        if shared_node[0].is_aerialway():  # only attempt to merge power lines
            continue
        if (len(shared_node) == 2) and (shared_node[0].type_ == shared_node[1].type_):
            my_osm_id = shared_node[1].osm_id
            try:
                _merge_lines(key, shared_node[0], shared_node[1], my_shared_nodes)
                del my_powerlines[my_osm_id]
                del my_shared_nodes[key]
                logging.debug("Merged two lines with node osm_id: %s", key)
            except Exception as exc:
                logging.error(exc)
        elif len(shared_node) > 2:
            logging.debug("WARNING: node referenced in more than 2 ways. Most likely OSM problem. Node osm_id: %s", key)

    return list(my_powerlines.values()), list(my_aerialways.values())


def _find_connecting_line(key, lines, max_allowed_angle=360):
    """
    In the array of lines checks which 2 lines have an angle closest to 180 degrees at the end node key.
    Looked at the second last node and end node (key).
    If the found angle is larger than the max_allowed_angle at the end, then -1 is returned for pos1
    """
    angles = []
    # Get the angle of each line
    for line in lines:
        if line.nodes[0].osm_id == key:
            angle = co.calc_angle_of_line_local(line.nodes[0].x, line.nodes[0].y,
                                                line.nodes[1].x, line.nodes[1].y)
        elif line.nodes[-1].osm_id == key:
            angle = co.calc_angle_of_line_local(line.nodes[-1].x, line.nodes[-1].y,
                                                line.nodes[-2].x, line.nodes[-2].y)
        else:
            raise Exception("The referenced node is not at the beginning or end of line0")
        angles.append(angle)
    # Get the angles between all line pairs and find the one closest to 180 degrees
    pos1 = 0
    pos2 = 1
    max_angle = 500
    for i in range(0, len(angles) - 1):
        for j in range(i + 1, len(angles)):
            angle_between = abs(abs(angles[i] - angles[j]) - 180)
            if angle_between < max_angle:
                max_angle = angle_between
                pos1 = i
                pos2 = j
    if max_angle > max_allowed_angle:
        pos1 = -1
    return pos1, pos2


def _merge_lines(osm_id: t.OSMId, line0, line1, shared_nodes):
    """
    Takes 2 Line objects and attempts to merge them at a given node.
    The added/merged pylons are in line0 in the correct sequence.
    Makes sure that line1 is replaced by line0 in shared_nodes.
    Raises Exception if the referenced node is not at the beginning or end of the two lines.
    """
    # Little trick to work with both WayLines and RailLines
    line0_nodes = line0.shared_pylons
    line1_nodes = line1.shared_pylons
    if isinstance(line0, RailLine):
        line0_nodes = line0.nodes
        line1_nodes = line1.nodes

    if line0_nodes[0].osm_id == osm_id:
        line0_first = True
    elif line0_nodes[-1].osm_id == osm_id:
        line0_first = False
    else:
        raise Exception("The referenced node is not at the beginning or end of line0")
    if line1_nodes[0].osm_id == osm_id:
        line1_first = True
    elif line1_nodes[-1].osm_id == osm_id:
        line1_first = False
    else:
        raise Exception("The referenced node is not at the beginning or end of line1")

    # combine line1 into line0 in correct sequence (e.g. line0(A,B) + line1(C,B) -> line0(A,B,C)
    if (line0_first is False) and (line1_first is True):
        for x in range(1, len(line1_nodes)):
            line0_nodes.append(line1_nodes[x])
    elif (line0_first is False) and (line1_first is False):
        for x in range(0, len(line1_nodes) - 1):
            line0_nodes.append(line1_nodes[len(line1_nodes) - x - 2])
    elif (line0_first is True) and (line1_first is True):
        for x in range(1, len(line1_nodes)):
            line0_nodes.insert(0, line1_nodes[x])
    else:
        for x in range(0, len(line1_nodes) - 1):
            line0_nodes.insert(0, line1_nodes[len(line1_nodes) - x - 2])

    # set back little trick
    if isinstance(line0, RailLine):
        line0.nodes = line0_nodes
        line1.nodes = line1_nodes
    else:
        line0.shared_pylons = line0_nodes
        line1.shared_pylons = line1_nodes

    # in shared_nodes replace line1 with line2
    for shared_node in list(shared_nodes.values()):
        has_line0 = False
        pos_line1 = -1
        for i in range(0, len(shared_node)):
            if shared_node[i].osm_id == line0.osm_id:
                has_line0 = True
            if shared_node[i].osm_id == line1.osm_id:
                pos_line1 = i
        if pos_line1 >= 0:
            del shared_node[pos_line1]
            if not has_line0:
                shared_node.append(line0)


def write_cables(lines: list[Line], coords_transform: co.Transformation, my_stg_mgr: stg_io2.STGManager,
                 details: bool = False) -> None:
    file_name: str = parameters.PREFIX
    if details:
        file_name += 'd'
    file_name += 'c' + gio.FILE_ENDING
    path_to_stg = my_stg_mgr.add_object_static(file_name, coords_transform.anchor,
                                               parameters.get_tile_radius(), STGVerbType.object_static)
    geom_collector = gio.GeometryCollector3D(False, False)
    for line in lines:
        for way_segment in line.way_segments:
            for cable in way_segment.cables:
                cable.add_to_geom_collector(geom_collector, cov.COV_CABLE)

    geom_collector.process()
    gltf_writer = gio.GLTFWriter(geom_collector.get_shallow_c_vertices_clone(),
                                 geom_collector.get_shallow_c_faces_clone(),
                                 geom_collector.smooth_edges)
    gltf_writer.write_to_file(os.path.join(path_to_stg, file_name), True)


def write_instance_entries_pylons_for_line(lines_list: list[LineWithoutCables],
                                           instanced_collector: stg_io2.ObjectInstancedListCollector) -> None:
    for line in lines_list:
        line.make_instance_entries(instanced_collector)


def _calc_heading_nodes(nodes_array: list[SharedPylon]) -> None:
    """Calculates the headings of nodes in a line based on a medium angle.
    Nodes must have a heading, x and y attribute"""
    current_pylon = nodes_array[0]
    next_pylon = nodes_array[1]
    current_angle = co.calc_angle_of_line_local(current_pylon.x, current_pylon.y, next_pylon.x, next_pylon.y)
    current_pylon.heading = current_angle
    for x in range(1, len(nodes_array) - 1):
        prev_angle = current_angle
        current_pylon = nodes_array[x]
        next_pylon = nodes_array[x + 1]
        current_angle = co.calc_angle_of_line_local(current_pylon.x, current_pylon.y, next_pylon.x, next_pylon.y)
        current_pylon.heading = _calc_middle_angle(prev_angle, current_angle)
    nodes_array[-1].heading = current_angle


def _calc_middle_angle(angle_line1, angle_line2):
    """Returns the angle halfway between two lines"""
    if angle_line1 == angle_line2:
        middle = angle_line1
    elif angle_line1 > angle_line2:
        if 0 == angle_line2:
            middle = _calc_middle_angle(angle_line1, 360)
        else:
            middle = angle_line1 - (angle_line1 - angle_line2) / 2
    else:
        if math.fabs(angle_line2 - angle_line1) > 180:
            middle = _calc_middle_angle(angle_line1 + 360, angle_line2)
        else:
            middle = angle_line2 - (angle_line2 - angle_line1) / 2
    if 360 <= middle:
        middle -= 360
    return middle


def _stg_angle(angle_normal):
    """Returns the input angle in degrees to an angle for the stg-file in degrees.
    stg-files use angles counter-clockwise starting with 0 in North."""
    if 0 == angle_normal:
        return 0
    else:
        return 360 - angle_normal


def _optimize_catenary(half_distance_pylons: float, max_value: float, sag: float, max_variation: float):
    """
    Calculates the parameter _a_ for a catenary with a given sag between the pylons and a max_variation.
    See https://en.wikipedia.org/wiki/Catenary
    Max variation is factor applied to sag.
    """
    my_variation = sag * max_variation
    try:
        for a in range(1, int(max_value)):
            value = a * math.cosh(float(half_distance_pylons)/a) - a  # float() needed to make sure result is float
            if (value >= (sag - my_variation)) and (value <= (sag + my_variation)):
                return a, value
    except OverflowError:
        return -1, -1
    return -1, -1


def process_osm_building_refs(my_coord_transformator, fg_elev: ep.FGElev,
                              storage_tanks: list[StorageTank]) -> list[shg.Polygon]:
    """Takes all buildings to be used as potential blocking areas. At the same time processes storage tanks.
    Storage tanks are in OSM mapped as buildings, but with special tags. In FG use shared model.
    Storage tanks get updated by passed as reference list.
    https://wiki.openstreetmap.org/wiki/Tag:man%20made=storage%20tank?uselang=en-US.
    """
    osm_way_result = op.fetch_osm_data_ways_keys([s.K_BUILDING])
    nodes_dict = osm_way_result.nodes_dict
    ways_dict = osm_way_result.ways_dict

    my_buildings: list[shg.Polygon] = list()
    clipping_border = shg.Polygon(parameters.get_clipping_border())

    for way in list(ways_dict.values()):
        my_node = None
        for key in way.tags:
            if s.K_BUILDING == key:
                my_coordinates = list()
                for ref in way.refs:
                    if ref in nodes_dict:
                        my_node = nodes_dict[ref]
                        my_coordinates.append(my_coord_transformator.to_local((my_node.lon, my_node.lat)))
                if 2 < len(my_coordinates):
                    my_polygon = shg.Polygon(my_coordinates)
                    if my_polygon.is_valid and not my_polygon.is_empty:
                        my_buildings.append(my_polygon.convex_hull)
                        # process storage tanks
                        if parameters.C2P_PROCESS_STORAGE_TANKS:
                            if s.is_storage_tank(way.tags) or s.is_silo(way.tags):
                                my_centroid = my_polygon.centroid
                                lon, lat = my_coord_transformator.to_global((my_centroid.x, my_centroid.y))
                                if not clipping_border.contains(shg.Point(lon, lat)):
                                    continue
                                radius = co.calc_distance_global(lon, lat, my_node.lon, my_node.lat)
                                if radius < 5:  # we do not want very small objects
                                    continue
                                elev = fg_elev.probe_elev((lon, lat), True)
                                storage_tanks.append(StorageTank(way.osm_id, my_centroid.x, my_centroid.y, way.tags,
                                                                 radius, elev))
    logging.info("Found {} storage tanks".format(len(storage_tanks)))
    return my_buildings


class LinearOSMFeature:
    def __init__(self, osm_id: t.OSMId):
        self.osm_id = osm_id
        self.type_ = None
        self.linear = None  # The LinearString of the line

    def get_width(self):
        """The width incl. border as a float in meters"""
        raise NotImplementedError("Please implement this method")


@unique
class HighwayLightingType(IntEnum):
    """Describes the lighting of a highway based on where information comes from. OSM key overwrites if present."""
    undefined = 0  # no lit OSM key
    lit_yes = 1  # OSM lit=yes
    lit_no = 2  # OSM lit=no


class Highway(LinearOSMFeature):

    def __init__(self, osm_id: t.OSMId) -> None:
        super().__init__(osm_id)
        self.is_roundabout = False
        self.lighting_type = HighwayLightingType.undefined

    def get_width(self) -> float:
        _, width, _ = e.get_highway_attributes(self.type_)
        return width


def process_osm_highways(my_coord_transformator) -> dict[t.OSMId, Highway]:
    osm_way_result = op.fetch_osm_data_ways_keys([s.K_HIGHWAY])
    nodes_dict = osm_way_result.nodes_dict
    ways_dict = osm_way_result.ways_dict

    my_highways: dict[t.OSMId, Highway] = dict()

    for way in list(ways_dict.values()):
        my_highway = Highway(way.osm_id)
        valid_highway = False
        is_challenged = False
        for key in way.tags:
            value = way.tags[key]
            if s.K_HIGHWAY == key:
                valid_highway = True
                my_highway.type_ = e.highway_type_from_osm_tags(way.tags)
                if None is my_highway.type_:
                    valid_highway = False
            elif (s.K_TUNNEL == key) and (s.V_YES == value):
                is_challenged = True
            elif (s.K_JUNCTION == key) and (s.V_ROUNDABOUT == value):
                my_highway.is_roundabout = True
            elif s.K_LIT == key:
                if s.V_YES == value:
                    my_highway.lighting_type = HighwayLightingType.lit_yes
                else:
                    my_highway.lighting_type = HighwayLightingType.lit_no
        if valid_highway and not is_challenged:
            # Process the Nodes
            my_coordinates = list()
            for ref in way.refs:
                if ref in nodes_dict:
                    my_node = nodes_dict[ref]
                    x, y = my_coord_transformator.to_local((my_node.lon, my_node.lat))
                    my_coordinates.append((x, y))
            if len(my_coordinates) >= 2:
                my_highway.linear = shg.LineString(my_coordinates)
                my_highways[my_highway.osm_id] = my_highway

    return my_highways


def process_highways_for_streetlamps(my_highways: dict[t.OSMId, Highway], lit_areas: list[shg.Polygon]) \
        -> list[StreetlampWay]:
    """
    Test whether the highway is within appropriate land use or intersects with appropriate land use
    No attempt to merge lines because most probably the lines are split at crossing.
    No attempt to guess whether there is a division in the centre, where a streetlamp with two lamps could be
    placed - e.g. using a combination of highway type, one-way, number of lanes etc
    """
    my_streetlamps: dict[t.OSMId, StreetlampWay] = dict()
    total = 0
    lit = 0
    for key in list(my_highways.keys()):
        total += 1
        my_highway = my_highways[key]
        if not StreetlampWay.has_lamps(my_highway.type_):
            continue
        is_within = False
        intersections = []
        if my_highway.lighting_type is HighwayLightingType.lit_yes:
            my_streetlamps[my_highway.osm_id] = StreetlampWay(my_highway.osm_id, my_highway)
            lit += 1
            continue  # use no matter what
        elif my_highway.lighting_type is HighwayLightingType.lit_no:
            continue  # nothing to do

        for lit_area in lit_areas:
            if my_highway.linear.within(lit_area):
                is_within = True
                break
            elif my_highway.linear.intersects(lit_area):
                intersections.append(my_highway.linear.intersection(lit_area))
        if is_within:
            my_streetlamps[my_highway.osm_id] = StreetlampWay(my_highway.osm_id, my_highway)
        else:
            if intersections:
                for intersection in intersections:
                    if isinstance(intersection, shg.MultiLineString):
                        for my_line in intersection.geoms:
                            if isinstance(my_line, shg.LineString):
                                intersections.append(my_line)
                        continue
                    elif isinstance(intersection, shg.LineString):
                        new_highway = Highway(op.get_next_pseudo_osm_id(op.OSMFeatureType.road))
                        new_highway.type_ = my_highway.type_
                        new_highway.linear = intersection
                        my_streetlamps[new_highway.osm_id] = StreetlampWay(new_highway.osm_id, new_highway)
                del my_highways[key]

    # Remove the too short lines
    for key in list(my_streetlamps.keys()):
        my_streetlamp = my_streetlamps[key]
        if not isinstance(my_streetlamp.highway.linear, shg.LineString):
            del my_streetlamps[key]
        elif my_streetlamp.highway.is_roundabout and\
                (50 > my_streetlamp.highway.linear.length or 300 < my_streetlamp.highway.linear.length):
            del my_streetlamps[key]
        elif my_streetlamp.highway.linear.length < parameters.C2P_STREETLAMPS_MIN_STREET_LENGTH:
            del my_streetlamps[key]

    return list(my_streetlamps.values())


def process_pylons(coords_transform: co.Transformation, fg_elev: ep.FGElev,
                   stg_entries: list[stg_io2.STGEntry],
                   file_lock: mps.Lock | None = None) -> None:
    # Transform to real objects
    logging.info("Transforming OSM data to Line and Pylon objects")

    # References for buildings
    building_refs: list[shg.Polygon] = list()
    storage_tanks: list[StorageTank] = list()
    if parameters.C2P_PROCESS_POWERLINES or parameters.C2P_PROCESS_STORAGE_TANKS:
        building_refs = process_osm_building_refs(coords_transform, fg_elev, storage_tanks)
        logging.info('Number of reference buildings: %s', len(building_refs))
    # Power lines (major)
    powerlines: list[WayLine] = list()
    if parameters.C2P_PROCESS_POWERLINES:
        powerlines, aerialways = process_osm_power_aerialway([s.K_POWER], fg_elev, coords_transform, building_refs)

        # remove all those power lines, which are minor - after we have done the mapping in calc_and_map()
        for wayline in reversed(powerlines):
            wayline.calc_and_map()
            if wayline.type_ is WayLineType.power_minor:
                powerlines.remove(wayline)
        logging.info('Number of major power lines to process: %s', len(powerlines))
        for wayline in aerialways:
            wayline.calc_and_map()
    # wind turbines
    wind_turbines: list[WindTurbine] = list()
    if parameters.C2P_PROCESS_WIND_TURBINES:
        result = op.fetch_osm_nodes_isolated_key_values([s.KV_GENERATOR_SOURCE_WIND])
        wind_turbines = _process_osm_wind_turbines(result.nodes_dict, coords_transform, fg_elev, stg_entries)
        logging.info("Number of valid wind turbines found: {}".format(len(wind_turbines)))
    # chimneys
    chimneys: list[Chimney] = list()
    if parameters.C2P_PROCESS_CHIMNEYS:
        # start with chimneys tagged as node
        result = op.fetch_osm_nodes_isolated_key_values([s.KV_MAN_MADE_CHIMNEY])
        chimneys = _process_osm_chimneys_nodes(result.nodes_dict, coords_transform, fg_elev)
        # add chimneys tagged as way
        osm_way_result = op.fetch_osm_data_ways_key_values([s.KV_MAN_MADE_CHIMNEY])
        osm_nodes_dict = osm_way_result.nodes_dict
        osm_ways_dict = osm_way_result.ways_dict
        chimneys.extend(_process_osm_chimneys_ways(osm_nodes_dict, osm_ways_dict, coords_transform, fg_elev))
        logging.info("Number of valid chimneys found: {}".format(len(chimneys)))

    # communication masts
    communication_masts: list[CommunicationMast] = list()
    if parameters.C2P_PROCESS_COMMUNICATION_MASTS:
        # start with chimneys tagged as node
        result = op.fetch_osm_nodes_isolated_key_values([s.KV_MAN_MADE_MAST])
        communication_masts = _process_osm_communication_mast_nodes(result.nodes_dict, coords_transform, fg_elev)
        # add chimneys tagged as way
        osm_way_result = op.fetch_osm_data_ways_key_values([s.KV_MAN_MADE_MAST])
        osm_nodes_dict = osm_way_result.nodes_dict
        osm_ways_dict = osm_way_result.ways_dict
        communication_masts.extend(_process_osm_communication_mast_ways(osm_nodes_dict, osm_ways_dict, coords_transform, fg_elev))
        logging.info("Number of valid communication masts found: {}".format(len(communication_masts)))

    # free some memory
    del building_refs

    # -- initialize STGManager
    stg_manager = stg_io2.STGManager(parameters.get_output_path(), stg_io2.SceneryType.pylons, PYLONS_MAGIC,
                                     parameters.PREFIX)
    instanced_collector = stg_io2.ObjectInstancedListCollector()

    # Write to FlightGear

    if parameters.C2P_PROCESS_POWERLINES:
        write_instance_entries_pylons_for_line(powerlines, instanced_collector)
        write_cables(powerlines, coords_transform, stg_manager)

    if parameters.C2P_PROCESS_WIND_TURBINES:
        for turbine in wind_turbines:
            turbine.make_stg_entry(stg_manager)
    if parameters.C2P_PROCESS_STORAGE_TANKS:
        for tank in storage_tanks:
            tank.make_instanced_entry(instanced_collector)
    if parameters.C2P_PROCESS_CHIMNEYS:
        for chimney in chimneys:
            chimney.make_instanced_entry(instanced_collector)
    if parameters.C2P_PROCESS_COMMUNICATION_MASTS:
        for mast in communication_masts:
            mast.make_instanced_entry(instanced_collector)

    instanced_collector.register_and_write_lists(stg_manager, coords_transform.anchor)
    stg_manager.write(file_lock)

# ================ UNITTESTS =======================


class TestPylons(unittest.TestCase):
    def test_middle_angle(self):
        self.assertEqual(0, _calc_middle_angle(0, 0), "North North")
        self.assertEqual(45, _calc_middle_angle(0, 90), "North East")
        self.assertEqual(130, _calc_middle_angle(90, 170), "East Almost_South")
        self.assertEqual(90, _calc_middle_angle(135, 45), "South_East North_East")
        self.assertEqual(0, _calc_middle_angle(45, 315), "South_East North_East")
        self.assertEqual(260, _calc_middle_angle(170, 350), "Almost_South Almost_North")

    def test_wayline_calculate_and_map(self):
        # first test headings
        pylon1 = Pylon(t.OSMId(1))
        pylon1.x = -100
        pylon1.y = -100
        pylon2 = Pylon(t.OSMId(2))
        pylon2.x = 100
        pylon2.y = 100
        wayline1 = WayLine(t.OSMId(100))
        wayline1.type_ = WayLineType.power_line
        wayline1.shared_pylons.append(pylon1)
        wayline1.shared_pylons.append(pylon2)
        wayline1.calc_and_map()
        self.assertAlmostEqual(45., pylon1.heading, 2)
        self.assertAlmostEqual(45., pylon2.heading, 2)
        pylon3 = Pylon(t.OSMId(3))
        pylon3.x = 0
        pylon3.y = 100
        pylon4 = Pylon(t.OSMId(4))
        pylon4.x = -100
        pylon4.y = 200
        wayline1.shared_pylons.append(pylon3)
        wayline1.shared_pylons.append(pylon4)
        wayline1.calc_and_map()
        self.assertAlmostEqual(337.5, pylon2.heading, 2)
        self.assertAlmostEqual(292.5, pylon3.heading, 2)
        self.assertAlmostEqual(315., pylon4.heading, 2)
        pylon5 = Pylon(t.OSMId(5))
        pylon5.x = -100
        pylon5.y = 300
        wayline1.shared_pylons.append(pylon5)
        wayline1.calc_and_map()
        self.assertAlmostEqual(337.5, pylon4.heading, 2)
        self.assertAlmostEqual(0., pylon5.heading, 2)
        # then test other stuff
        self.assertEqual(4, len(wayline1.way_segments))

    def test_cable_vertex_calc_position(self):
        vertex = CableVertex(10, 5)
        vertex.calc_position(0, 0, 20, 0)
        self.assertAlmostEqual(25., vertex.elevation, 2)
        self.assertAlmostEqual(10., vertex.x, 2)
        self.assertAlmostEqual(0., vertex.y, 2)
        vertex.calc_position(0, 0, 20, 90)
        self.assertAlmostEqual(0., vertex.x, 2)
        self.assertAlmostEqual(-10., vertex.y, 2)
        vertex.calc_position(0, 0, 20, 210)
        self.assertAlmostEqual(-8.660, vertex.x, 2)
        self.assertAlmostEqual(5., vertex.y, 2)
        vertex.calc_position(20, 50, 20, 180)
        self.assertAlmostEqual(10., vertex.x, 2)
        self.assertAlmostEqual(50., vertex.y, 2)

    def test_catenary(self):
        #  Values taken from example 2 in http://www.mathdemos.org/mathdemos/catenary/catenary.html
        a, value = _optimize_catenary(170, 5000, 14, 0.001)
        print(a, value)
        self.assertAlmostEqual(1034/100, a/100, 2)
