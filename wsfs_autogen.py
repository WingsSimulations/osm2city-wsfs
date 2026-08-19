#!/usr/bin/env python3
# SPDX-FileCopyrightText: (C) 2026 Wings Simulations & osm2city contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""
wsfs_autogen.py - Wings Simulations FS 2027 Building Autogen Bridge using osm2city.

Usage:
    python wsfs_autogen.py --tile <tx> <ty> <zoom> [--output <dir>]
    python wsfs_autogen.py --bbox <min_lon> <min_lat> <max_lon> <max_lat> [--output <dir>]
"""

import argparse
import math
import os
import sys
from pathlib import Path

# Ensure local osm2city is in sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from osm2city import parameters
from osm2city.utils import calc_tile, coordinates


def num2deg(xtile: int, ytile: int, zoom: int) -> tuple[float, float]:
    """Convert tile numbers to NW corner lat/lon."""
    n = 1.0 << zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return lon_deg, lat_deg


def tile_to_bbox(tx: int, ty: int, zoom: int) -> tuple[float, float, float, float]:
    """Returns (min_lon, min_lat, max_lon, max_lat)."""
    nw_lon, nw_lat = num2deg(tx, ty, zoom)
    se_lon, se_lat = num2deg(tx + 1, ty + 1, zoom)
    return nw_lon, se_lat, se_lon, nw_lat


def generate_tile_buildings(min_lon: float, min_lat: float, max_lon: float, max_lat: float,
                            prefix: str, output_dir: str):
    """Configures osm2city parameters and executes building autogen for the given bounding box."""
    os.makedirs(output_dir, exist_ok=True)
    cache_dir = os.path.join(output_dir, "cache_osm2city")
    os.makedirs(cache_dir, exist_ok=True)

    parameters.PREFIX = prefix
    parameters.BOUNDARY_WEST = min_lon
    parameters.BOUNDARY_SOUTH = min_lat
    parameters.BOUNDARY_EAST = max_lon
    parameters.BOUNDARY_NORTH = max_lat
    parameters.PATH_TO_OUTPUT = output_dir
    parameters.CACHE_DIR_O2C = cache_dir
    parameters.NO_ELEV = True
    parameters.FLAG_BUILDINGS_MESH_SKIP = False
    parameters.CREATE_TREES = False

    print(f"[osm2city-WSFS] Generating buildings for {prefix}: [{min_lon:.4f}, {min_lat:.4f}] to [{max_lon:.4f}, {max_lat:.4f}]...")

    try:
        from osm2city import buildings
        buildings.process_buildings()
        print(f"[osm2city-WSFS] Finished building autogen for {prefix} successfully.")
    except Exception as e:
        print(f"[osm2city-WSFS] Exception generating buildings: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="WSFS27 osm2city Building Autogen Bridge")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tile", nargs=3, type=int, metavar=("TX", "TY", "ZOOM"),
                       help="Tile coordinate (e.g. 17565 10738 15)")
    group.add_argument("--bbox", nargs=4, type=float, metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
                       help="Bounding box in decimal degrees")

    parser.add_argument("--prefix", type=str, default="autogen",
                        help="Scenery prefix name (e.g. tile key or ICAO)")
    parser.add_argument("--output", type=str, default="cache/buildings",
                        help="Output directory for generated meshes and metadata")

    args = parser.parse_args()

    if args.tile:
        tx, ty, zoom = args.tile
        min_lon, min_lat, max_lon, max_lat = tile_to_bbox(tx, ty, zoom)
        prefix = args.prefix if args.prefix != "autogen" else f"{zoom}_{tx}_{ty}"
    else:
        min_lon, min_lat, max_lon, max_lat = args.bbox
        prefix = args.prefix

    generate_tile_buildings(min_lon, min_lat, max_lon, max_lat, prefix, args.output)


if __name__ == "__main__":
    main()
