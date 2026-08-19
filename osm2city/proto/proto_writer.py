# SPDX-FileCopyrightText: (C) 2025, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later
import logging

from shapely import wkb, Polygon

def write_blocked_areas_to_protobuf(proto_filename: str,
                                    blocked_apt_areas: list[Polygon], airport_boundaries: list[Polygon],
                                    stg_static_polys: list[Polygon], stg_shared_polys: list[Polygon],
                                    platform_polys:  list[Polygon]) -> None:
    import osm2city.proto.blocked_areas_pb2 as opb

    blocked_areas = opb.BlockedAreas()

    geoms = 0
    for area in blocked_apt_areas:
        well_known_bin = blocked_areas.blocked_apt_areas.add()
        well_known_bin.wkb = wkb.dumps(area)
        geoms += 1
    for area in airport_boundaries:
        well_known_bin = blocked_areas.airport_boundaries.add()
        well_known_bin.wkb = wkb.dumps(area)
        geoms += 1
    for area in stg_static_polys:
        well_known_bin = blocked_areas.stg_static_polys.add()
        well_known_bin.wkb = wkb.dumps(area)
        geoms += 1
    for area in stg_shared_polys:
        well_known_bin = blocked_areas.stg_shared_polys.add()
        well_known_bin.wkb = wkb.dumps(area)
        geoms += 1
    for area in platform_polys:
        well_known_bin = blocked_areas.platform_polys.add()
        well_known_bin.wkb = wkb.dumps(area)
        geoms += 1

    # Write the new address book back to disk.
    with open(proto_filename, "wb") as f:
        f.write(blocked_areas.SerializeToString())

    logging.info('Written %i blocked areas to protobuf file %s',
                 geoms, proto_filename)
    logging.info('%i blocked airport areas', len(blocked_apt_areas))
    logging.info('%i airport boundaries', len(airport_boundaries))
    logging.info('%i polys for static stg objects', len(stg_static_polys))
    logging.info('%i polys for shared stg objects', len(stg_shared_polys))
    logging.info('%i polys for platforms', len(platform_polys))
