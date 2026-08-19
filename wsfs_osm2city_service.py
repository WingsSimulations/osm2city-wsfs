#!/usr/bin/env python3
# SPDX-FileCopyrightText: (C) 2026 Wings Simulations
# SPDX-License-Identifier: GPL-2.0-or-later
"""
WSFS27 osm2city Microservice
----------------------------
Directly drives the official osm2city procedural building engine:
  - Takes raw OSM JSON and terrain elevation grids
  - Parses buildings with osm2city's rules and tag parsers
  - Analyzes roof shapes (gabled, hipped, mansard, pyramidal, flat, etc.)
  - Analyzes facade/roof textures, materials and UVs
  - Uses osm2city's GeometryCollector3D to write out real 3D meshes
  - Streams raw vertices (position, normal, UV, matId), indices, and AABBs to the C++ runtime.
"""

import sys
import os
import io
import json
import math
import time
import struct
import logging
import argparse
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

import numpy as np
import shapely.geometry as shg

# Locate the osm2city package bundled with the sim
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from osm2city import parameters, building_lib
import osm2city.static_types.enumerations as enu
from osm2city.utils import coordinates as co, osmparser as op, elev_probe as ep, gltf_io as gio, stg_io2
from osm2city.textures import coverings as cov

logging.basicConfig(level=logging.INFO, format="[osm2city-service] %(levelname)s: %(message)s")


class WSFSElevProber:
    """Terrain elevation prober based on the elevation grid sent from the engine."""
    def __init__(self, min_lon: float, min_lat: float, max_lon: float, max_lat: float,
                 elev_grid: list, grid_res: int):
        self.min_lon = min_lon
        self.min_lat = min_lat
        self.max_lon = max_lon
        self.max_lat = max_lat
        self.grid_res = grid_res

        if isinstance(elev_grid, list) and len(elev_grid) > 0 and isinstance(elev_grid[0], list):
            self.grid = np.array(elev_grid, dtype=np.float32)
        else:
            self.grid = np.array(elev_grid, dtype=np.float32).reshape((grid_res, grid_res))
        
        self.d_lon = max(1e-9, max_lon - min_lon)
        self.d_lat = max(1e-9, max_lat - min_lat)

    def probe_elev(self, lon_lat: tuple[float, float], is_global: bool = False) -> float:
        """Bilinear interpolation across the terrain elevation grid."""
        lon, lat = lon_lat[0], lon_lat[1]
        u = np.clip((lon - self.min_lon) / self.d_lon, 0.0, 1.0) * (self.grid_res - 1)
        v = np.clip((lat - self.min_lat) / self.d_lat, 0.0, 1.0) * (self.grid_res - 1)

        x0, y0 = int(math.floor(u)), int(math.floor(v))
        x1, y1 = min(x0 + 1, self.grid_res - 1), min(y0 + 1, self.grid_res - 1)
        fx, fy = u - x0, v - y0

        h00 = self.grid[y0, x0]
        h10 = self.grid[y0, x1]
        h01 = self.grid[y1, x0]
        h11 = self.grid[y1, x1]

        h0 = h00 * (1.0 - fx) + h10 * fx
        h1 = h01 * (1.0 - fx) + h11 * fx
        return float(h0 * (1.0 - fy) + h1 * fy)

    def probe_list_of_points(self, points: list) -> tuple[float, float]:
        elevs = [self.probe_elev(pt) for pt in points]
        if not elevs:
            return 0.0, 0.0
        min_e = min(elevs)
        max_e = max(elevs)
        return float(min_e), float(max_e - min_e)


def fetch_overpass_osm(min_lon: float, min_lat: float, max_lon: float, max_lat: float, timeout_sec: int = 12) -> dict | None:
    query = f"""[out:json][timeout:{timeout_sec}];
(
  way["building"]({min_lat},{min_lon},{max_lat},{max_lon});
  relation["building"]({min_lat},{min_lon},{max_lat},{max_lon});
  way["building:part"]({min_lat},{min_lon},{max_lat},{max_lon});
  relation["building:part"]({min_lat},{min_lon},{max_lat},{max_lon});
);
out body geom;
"""
    endpoints = [
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass-api.de/api/interpreter",
        "https://overpass.private.coffee/api/interpreter"
    ]
    for url in endpoints:
        try:
            data = query.encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "WSFS27-osm2city/2.0", "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logging.debug("Endpoint %s failed: %s", url, e)
            continue
    return None


def generate_tile_mesh(payload: dict) -> dict:
    """Runs osm2city directly to produce raw meshes and returns raw vertex attributes."""
    bounds = payload.get("bounds", [0, 0, 0, 0]) # [min_lon, min_lat, max_lon, max_lat]
    min_lon, min_lat, max_lon, max_lat = bounds[0], bounds[1], bounds[2], bounds[3]
    origin_lat = (min_lat + max_lat) * 0.5
    cos_lat = max(0.01, math.cos(math.radians(origin_lat)))

    grid_res = payload.get("grid_res", 8)
    elev_grid = payload.get("elevation_grid", [])

    if elev_grid:
        prober = WSFSElevProber(min_lon, min_lat, max_lon, max_lat, elev_grid, grid_res)
    else:
        prober = WSFSElevProber(min_lon, min_lat, max_lon, max_lat, [0.0] * (grid_res * grid_res), grid_res)

    osm_data = payload.get("osm_json")
    if not osm_data or not isinstance(osm_data, dict) or "elements" not in osm_data:
        osm_data = fetch_overpass_osm(min_lon, min_lat, max_lon, max_lat)

    if not osm_data or "elements" not in osm_data or not osm_data["elements"]:
        return {
            "success": True,
            "vertex_count": 0,
            "index_count": 0,
            "vertices": [],
            "indices": [],
            "aabbs": []
        }

    # Setup osm2city transformation
    coords_transform = co.Transformation(min_lon, min_lat, max_lon, max_lat, 0, True)
    facade_manager = cov.FacadeManager(cov.FACADE_COVERINGS, "brick")
    roof_manager = cov.RoofManager(cov.ROOF_COVERINGS)
    instanced_collector = stg_io2.ObjectInstancedListCollector()

    default_zone = building_lib.Zone(1, shg.Polygon([(-5000, -5000), (5000, -5000), (5000, 5000), (-5000, 5000)]),
                                     enu.BuildingZoneType.residential, enu.SettlementType.dense)

    the_buildings = []
    aabbs_out = []

    for el in osm_data["elements"]:
        if not isinstance(el, dict):
            continue
        tags = el.get("tags", {})
        if not (tags.get("building") or tags.get("building:part")):
            continue

        # Extract footprint coordinates
        geom = el.get("geometry", [])
        if not geom and "members" in el:
            for mem in el["members"]:
                if mem.get("role") in ("outer", "") and "geometry" in mem:
                    geom = mem["geometry"]
                    break

        if len(geom) < 3:
            continue

        coords_local = []
        for pt in geom:
            lon, lat = pt.get("lon", 0.0), pt.get("lat", 0.0)
            lx, ly = coords_transform.to_local((lon, lat))
            coords_local.append((lx, ly))

        if len(coords_local) < 3:
            continue

        # Ensure ring is closed
        if coords_local[0] != coords_local[-1]:
            coords_local.append(coords_local[0])

        try:
            ring = shg.LinearRing(coords_local)
            if not ring.is_valid or ring.length < 1.0:
                continue
            b = building_lib.Building(el.get("id", len(the_buildings) + 1), tags, ring, None)
            b.zone = default_zone
            the_buildings.append(b)
        except Exception:
            continue

    if not the_buildings:
        return {
            "success": True,
            "vertex_count": 0,
            "index_count": 0,
            "vertices": [],
            "indices": [],
            "aabbs": []
        }

    # Run osm2city procedural analysis
    try:
        the_buildings = building_lib.analyse(the_buildings, prober, instanced_collector, facade_manager, roof_manager)
    except Exception as e:
        logging.warning("osm2city analyse exception: %s", e)

    # Geometry collection
    geom_collector = gio.GeometryCollector3D(False, False)
    for b in the_buildings:
        try:
            b.set_ground_elev()
            b.compute_roof_height()
            b.write_facades(geom_collector)
            b.write_roof(roof_manager, geom_collector)

            # Compute AABB for aircraft collision in Simulator Coordinates (X=East, Y=Up, Z=-North)
            pts = np.array(b.pts_outer)
            min_x, max_x = float(pts[:, 0].min()), float(pts[:, 0].max())
            min_z, max_z = float(-pts[:, 1].max()), float(-pts[:, 1].min())
            base_e = float(b.ground_elev)
            top_e = float(base_e + (b.building_height if hasattr(b, "building_height") else 10.0) + (b.roof_height if hasattr(b, "roof_height") else 0.0))
            aabbs_out.append([min_x / cos_lat, base_e, min_z / cos_lat, max_x / cos_lat, top_e, max_z / cos_lat])
        except Exception:
            pass

    geom_collector.process()

    verts_out = []
    indices_out = []
    vert_map = {}

    # Extract geometry directly from osm2city faces in true Simulator Coordinates
    for fid, c_face in geom_collector._c_faces.items():
        if len(c_face.vertices) < 3:
            continue
        cov_name = c_face.covering.name.lower()
        if "roof" in cov_name:
            mat_id = 3.0
        elif "glass" in cov_name or "office" in cov_name or "modern" in cov_name:
            mat_id = 2.0
        else:
            mat_id = 1.0

        v_pts = []
        for v in c_face.vertices:
            # Simulator coordinate mapping:
            # X = East (c_vertex.x / cos_lat)
            # Y = Elev (c_vertex.elev)
            # Z = -North (-c_vertex.y / cos_lat)
            vx = float(v.x) / cos_lat
            vy = float(v.elev)
            vz = float(-v.y) / cos_lat
            v_pts.append(np.array([vx, vy, vz]))

        # Calculate geometric face normal in simulator space
        e1 = v_pts[1] - v_pts[0]
        e2 = v_pts[2] - v_pts[0]
        fn = np.cross(e1, e2)
        norm_len = np.linalg.norm(fn)
        if norm_len > 1e-6:
            fn /= norm_len
        else:
            fn = np.array([0.0, 1.0, 0.0])

        face_indices = []
        for idx, v in enumerate(c_face.vertices):
            vx, vy, vz = v_pts[idx]
            # Use raw un-stretched texture coordinates directly from osm2city
            u = float(v.ct_map.x)
            v_coord = float(v.ct_map.y)

            vert_key = (round(vx, 3), round(vy, 3), round(vz, 3),
                        round(fn[0], 3), round(fn[1], 3), round(fn[2], 3),
                        round(u, 4), round(v_coord, 4), mat_id)
            if vert_key not in vert_map:
                vert_idx = len(verts_out) // 9
                vert_map[vert_key] = vert_idx
                verts_out.extend([vx, vy, vz, float(fn[0]), float(fn[1]), float(fn[2]), u, v_coord, mat_id])
            face_indices.append(vert_map[vert_key])

        # Triangulate face
        for i in range(1, len(face_indices) - 1):
            indices_out.extend([face_indices[0], face_indices[i], face_indices[i+1]])

    return {
        "success": True,
        "vertex_count": len(verts_out) // 9,
        "index_count": len(indices_out),
        "vertices": verts_out,
        "indices": indices_out,
        "aabbs": aabbs_out
    }


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class OSM2CityRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "service": "wsfs_osm2city_raw"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/generate_tile":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                payload = json.loads(body.decode("utf-8"))

                result = generate_tile_mesh(payload)
                resp_bytes = json.dumps(result).encode("utf-8")

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)
            except Exception as e:
                logging.exception("Error processing /generate_tile request")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def run_service(port: int = 8765):
    server = ThreadedHTTPServer(("127.0.0.1", port), OSM2CityRequestHandler)
    logging.info("WSFS27 osm2city microservice active on http://127.0.0.1:%d", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        logging.info("osm2city microservice stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WSFS27 osm2city Microservice")
    parser.add_argument("--port", type=int, default=8765, help="HTTP server port (default: 8765)")
    args = parser.parse_args()
    run_service(args.port)
