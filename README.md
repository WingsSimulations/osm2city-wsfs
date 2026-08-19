# osm2city-wsfs

**osm2city-wsfs** is the [Wings Simulations](https://wingssimulations.de/) fork of **osm2city**, customized for real-time procedural building generation, terrain integration, and streaming 3D building meshes in **Wings Flight Simulator (WSFS 2027)**.

---

## Authors & Attribution

### Original Authors & Upstream Project
- **osm2city upstream**: [https://gitlab.com/osm2city/osm2city](https://gitlab.com/osm2city/osm2city)
- **Original Copyright**: (C) 2013 - 2026 Rick van Osten (`rick@vanosten.net`), radi, portree_kid, and contributors.
- **License**: GNU General Public License v2.0 or later (GPL-2.0-or-later).

### Wings Simulations Modifications
- **Fork Maintainer**: [Wings Simulations](https://wingssimulations.de/) (`WingsSimulations` on GitHub)
- **Modifications Copyright**: (C) 2026 Wings Simulations
- **License**: GNU General Public License v2.0 or later (GPL-2.0-or-later).

---

## Features Added in this Fork

1. **WSFS 2027 Microservice Daemon (`wsfs_osm2city_service.py`)**:
   - High-performance multi-threaded HTTP microservice (`/generate_tile` and `/health` endpoints).
   - Bilinear interpolation elevation probing across raw terrain matrices (`WSFSElevProber`).
   - Generates and extracts raw 3D vertices, calculated normals, texture UV coordinates, face indices, and collision AABBs.
   - Coordinates are normalized to 1:1 metric scale and aligned with the engine coordinate frame.

2. **Standalone Autogen Bridge (`wsfs_autogen.py`)**:
   - Command-line tool to run procedural building autogen for arbitrary tile bounds and geographic bounding boxes.

3. **Runtime Fallbacks (`osm2city/utils/environment.py`)**:
   - Safe default fallback parameters for Overpass API connections and timeouts without requiring global OS environment variables.

---

## License

This project is licensed under the **GNU General Public License v2.0 or later (GPL-2.0-or-later)**. See the [LICENSE](LICENSE) file for details.

When using or redistributing this software, proper credit must be given to **Wings Simulations** and the **original osm2city contributors**.
