# SPDX-FileCopyrightText: (C) 2023 - 2025, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later
import logging
import os

from shapely import wkb, Polygon

import osm2city.buildings as b
import osm2city.building_lib as bl
import osm2city.roofs as r
import osm2city.static_types.enumerations as e
import osm2city.static_types.types as t
import osm2city.utils.coordinates as co
import osm2city.utils.osmparser as op


def read_building_stuff_from_protobuf(coords_transform: co.Transformation,
                                      proto_filename: str, keep_file: bool) -> tuple[list[bl.Building], list[Polygon]]:
    buildings = list()

    import osm2city.proto.buildings_pb2 as opb
    proto_buildings = opb.Buildings()

    num_proto_buildings = 0
    num_building_parents = 0
    with (open(proto_filename, 'rb') as proto_file):
        proto_buildings.ParseFromString(proto_file.read())

        # nodes dict
        nodes_dict: dict[t.OSMId, op.Node] = dict()
        for proto_node in proto_buildings.nodes:
            nodes_dict[proto_node.osm_id] = op.Node(proto_node.osm_id, proto_node.lat, proto_node.lon)

        # zones
        zones_dict: dict[t.OSMId, bl.Zone] = dict()
        for proto_zone in proto_buildings.zones:
            my_geometry = wkb.loads(proto_zone.geometry.wkb)
            bz_type = None
            for type_ in e.BuildingZoneType:
                if type_.value == proto_zone.building_zone_type:
                    bz_type = type_
            if bz_type is None:
                raise ValueError('Programming error: no mapping found for BuildingZoneType %i',
                                 proto_zone.building_zone_type)
            s_type = None
            for type_ in e.SettlementType:
                if type_.value == proto_zone.settlement_type:
                    s_type = type_
            if s_type is None:
                raise ValueError('Programming error: no mapping found for SettlementType %i',
                                 proto_zone.settlement_type)
            zones_dict[proto_zone.osm_id] = bl.Zone(proto_zone.osm_id, my_geometry, bz_type, s_type)

        # buildings
        buildings_map: dict[t.OSMId, bl.Building] = dict()  # only used for building parent: key = osm_id, value = building
        for proto_building in proto_buildings.buildings:
            num_proto_buildings += 1
            tags = t.OSMTags(dict())
            for key in proto_building.tags:
                foo = proto_building.tags[key]
                tags[key] = foo
            outer_way = op.Way(proto_building.osm_id)
            for ref in proto_building.outer_refs.refs:
                outer_way.add_ref(ref)
            inner_rings = list()
            for ring in proto_building.inner_refs.vecs:
                inner_way = op.Way(op.get_next_pseudo_osm_id(op.OSMFeatureType.generic_way))
                if len(ring.refs) < 4:
                    logging.warning('Skipping inner ring in building %i due to not enough refs', proto_building.osm_id)
                    continue
                for ref in ring.refs:
                    inner_way.add_ref(ref)
                inner_rings.append(inner_way)
            a_building = b.make_building_from_way(nodes_dict, tags, outer_way, coords_transform, inner_rings)
            if a_building:
                a_building.zone = zones_dict[proto_building.zone_id]
                a_building.has_neighbours = proto_building.has_neighbours

                if proto_building.HasField('roof_hint'):
                    roof_hint = r.RoofHint()
                    roof_hint.ridge_orientation = proto_building.roof_hint.ridge_orientation
                    if proto_building.roof_hint.HasField('inner_node_lon') and \
                            proto_building.roof_hint.HasField('inner_node_lat'):

                        roof_hint.inner_node = coords_transform.to_local((proto_building.roof_hint.inner_node_lon,
                                                proto_building.roof_hint.inner_node_lat))
                    roof_hint.node_before_inner_is_shared = proto_building.roof_hint.node_before_inner_is_shared
                    a_building.roof_hint = roof_hint

                buildings.append(a_building)
                buildings_map[a_building.osm_id] = a_building

        # building parents
        tags = t.OSMTags(dict())
        for proto_parent in proto_buildings.parents:
            num_building_parents += 1
            for key in proto_parent.tags:
                foo = proto_parent.tags[key]
                tags[key] = foo
            parent_type: e.BuildingParentType | None = None
            for type_ in e.BuildingParentType:
                if type_.value == proto_parent.parent_type:
                    parent_type = type_
            if parent_type is None:
                raise ValueError('Programming error: no mapping found for BuildingParentType %i',
                                 proto_zone.parent_type)
            building_parent = bl.BuildingParent(proto_parent.osm_id, parent_type)
            building_parent.add_tags(tags)
            for child in proto_parent.children:
                if child in buildings_map:
                    building_parent.add_child(buildings_map[child])

        # lit areas
        lit_areas: list[Polygon] = list()
        total_transferred = 0
        for proto_lit_area in proto_buildings.lit_areas:
            total_transferred += 1
            my_geometry = wkb.loads(proto_lit_area.geometry.wkb)
            if isinstance(my_geometry, Polygon):
                lit_areas.append(my_geometry)

    logging.info('Created %i buildings from reading %i buildings in protobuf file %s',
                 len(buildings), num_proto_buildings, proto_filename)
    logging.info('Related %i building parents from protobuf file', num_building_parents)
    logging.info('Related %i zones from protobuf file', len(zones_dict))
    logging.info('%i lit areas polygons from protobuf file (%i total)', len(lit_areas), total_transferred)

    if not keep_file:
        try:
            os.remove(proto_filename)
        except (FileNotFoundError, OSError) as error:
            logging.warning(error)  # not so much to do - but the program can continue nevertheless
    return buildings, lit_areas
