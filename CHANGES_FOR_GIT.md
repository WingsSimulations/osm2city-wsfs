# Changes made to osm2city for Wings Simulations FS 2027 Integration

This document logs modifications made to the upstream `osm2city` codebase for easy Git upstreaming and tracking.

## 1. `osm2city/utils/environment.py`
- **Added `DEFAULT_ENV_PARAMS` dictionary**:
  Provides default fallback values for Overpass API parameters (`O2C_OVERPASS_API`, `O2C_OVERPASS_MAX_RETRIES`, `O2C_OVERPASS_RETRY_DELAY`, `O2C_OVERPASS_RETRY_BACKOFF_FACTOR`, `O2C_OVERPASS_CONNECT_TIMEOUT`, `O2C_OVERPASS_READ_TIMEOUT`).
- **Updated `get_env_parameter()`**:
  Added an optional `default: Optional[str] = None` parameter so tools using osm2city programmatically don't hard-crash when environment variables are not globally defined in the OS environment.

## 2. Added `wsfs_autogen.py`
- Standalone CLI/bridge tool allowing WSFS27 to trigger building autogen for arbitrary geographic bounding boxes and tile coordinates, outputting building data / glTF directly to `cache/buildings/`.

## 3. Added `wsfs_osm2city_service.py`
- Multi-threaded standalone microservice daemon (`http://127.0.0.1:8765`) accepting tile bounding boxes and terrain elevation grids (`WSFSElevProber`), running osm2city's procedural building engine, and streaming 3D building meshes directly back to the simulator runtime.
