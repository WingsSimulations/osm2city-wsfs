# SPDX-FileCopyrightText: (C) 2025, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later

import logging

import shapely.geometry as shg

from osm2city import parameters
import osm2city.static_types.osmstrings as s
import osm2city.static_types.types as t
import osm2city.utils.coordinates as co
from osm2city.utils import osmparser as op


class Greenhouse:
    def __init__(self, way: op.Way, nodes_dict: dict[t.OSMId, op.Node], transformer: co.Transformation) -> None:
        self.way = way
        line_string = way.line_string_from_osm_way(nodes_dict, transformer)
        self.line_ring = shg.LinearRing(line_string)
        if not self.line_ring.is_ccw:
            self.line_ring = shg.LinearRing(self.line_ring.coords[::-1])
        self._convert_glasshouse()

    def _convert_glasshouse(self) -> None:
        """Convert a glasshouse to a greenhouse with glass materials.

        Glasshouse is deprecated in OSM: https://wiki.openstreetmap.org/wiki/Tag:building%3Dglasshouse
        """
        if s.K_BUILDING in self.way.tags and self.way.tags[s.K_BUILDING] == s.V_GLASSHOUSE:
            self.way.tags[s.K_BUILDING] = s.V_GREENHOUSE
            if not s.K_BUILDING_MATERIAL in self.way.tags:
                self.way.tags[s.K_BUILDING_MATERIAL] = s.V_GLASS
            if not s.K_ROOF_MATERIAL in self.way.tags:
                self.way.tags[s.K_ROOF_MATERIAL] = s.V_GLASS

    def write_to_gltf(self) -> None:
        """Writes a platform mapped as an area"""
        elevations: list[float] = list()
        # o = obj.next_node_index()
        # # top ring of nodes
        # for p in self.line_ring.coords:
        #     asl = fg_elev.probe_elev((p[0], p[1]))
        #     horizon_elev = co.calc_horizon_elev_local(p[0], p[1])
        #     elevations.append(asl - horizon_elev)
        #     obj.node(-p[1], asl - horizon_elev + PLATFORM_HEIGHT, -p[0])
        # # bottom ring of nodes
        # for index, p in enumerate(self.line_ring.coords):
        #     obj.node(-p[1], elevations[index] - PLATFORM_HEIGHT, -p[0])
        #
        # face_refs: list[tuple[int, float, float]] = list()
        # ring_length = len(self.line_ring.coords)  # there are +1 nodes, because the ring is closed
        #
        # # Top Face
        # for n in range(ring_length):
        #     face_refs.append((n + o, 1.0/(n+1), 1.0/(n+1)))  # use a bit random coordinates
        # obj.face(face_refs)
        #
        # # Build Sides
        # for n in range(ring_length - 1):
        #     face_refs = list()
        #     face_refs.append((n + o + 1, 0., 1.))  # top right
        #     face_refs.append((n + o, 0., 0.))  # top left
        #     face_refs.append((n + o + ring_length, 1., 0.))  # bottom left
        #     face_refs.append((n + o + ring_length + 1, 1., 1.))  # bottom right
        #     obj.face(face_refs)



def _process_osm_greenhouse(my_coord_transformator: co.Transformation) -> list[Greenhouse]:
    osm_way_result = op.fetch_osm_data_ways_key_values([s.KV_GREENHOUSE, s.KV_GLASSHOUSE])
    osm_nodes_dict = osm_way_result.nodes_dict
    osm_ways_dict = osm_way_result.ways_dict

    my_greenhouses: list[Greenhouse] = list()
    clipping_border = shg.Polygon(parameters.get_clipping_border())
    for key, way in osm_ways_dict.items():

        first_node = osm_nodes_dict[way.refs[0]]
        if not clipping_border.contains(shg.Point(first_node.lon, first_node.lat)):
            continue
        try:
            greenhouse = Greenhouse(way, osm_nodes_dict, my_coord_transformator)
            my_greenhouses.append(greenhouse)
        except ValueError as e:
            logging.debug(e)
    logging.info("number of greenhouses: %i", len(my_greenhouses))
    return my_greenhouses
