# SPDX-FileCopyrightText: (C) 2023 - 2025, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later

import logging
import math
import subprocess
from typing import Optional, Any

from osm2city import parameters
import osm2city.utils.coordinates as co
import osm2city.utils.environment as env


FG_ELEV_NO_ELEV = -9999  # Used to indicate that FGElev did not return a reliable result

# Found hole of minimum diameter 1.31072m at lon = 5.42631deg lat = 52.4969deg
# 1: -1000
FG_ELEV_HOLE = '-1000'  # default set in flightgear/utils/fgelev/fgelev.cxx line 306


class FGElev:
    """Probes elevation and ground solidness via fgelev."""
    __slots__ = ('fg_pipes', 'record', 'coords_transform')

    def __init__(self, coords_transform: Optional[co.Transformation]) -> None:
        """Open pipe to fgelev."""
        self.fg_pipes: dict[str, Any] = dict()  # contains the process pipes to the spawned fgelev instances
        self.record = 0
        self.coords_transform = coords_transform

    def _open_fg_elev(self, tile_lon: int, tile_lat: int, tile_key: str) -> None:
        logging.info("Spawning fgelev")
        scenery_path = create_scenery_path()
        fgelev_args = [env.get_env_parameter('O2C_PATH_TO_FG_ELEV'), '--fg-scenery', scenery_path,
                       '--tile-lon', str(tile_lon), '--tile-lat', str(tile_lat)]

        logging.info('fg_elev parameters used: %s', str(fgelev_args))
        fg_elev_pipe = subprocess.Popen(fgelev_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        bufsize=1, universal_newlines=True)
        self.fg_pipes[tile_key] = fg_elev_pipe

    def close(self) -> None:
        for fg_elev_pipe in self.fg_pipes.values():
            try:
                if fg_elev_pipe is not None:
                    fg_elev_pipe.kill()
            except:
                logging.warning('Unable to close FGElev process. You might have to kill it manually at the very end.')

    def _really_probe(self, lon_lat: tuple[float, float]) -> tuple[float, bool]:
        """Does the actual probing. The position is always a global lon/lat."""
        tile_lon = math.floor(lon_lat[0])
        tile_lat = math.floor(lon_lat[1])
        tile_key = f'{tile_lon:03d}_{tile_lat:03d}'
        if tile_key not in self.fg_pipes:
            self._open_fg_elev(tile_lon, tile_lat, tile_key)
        fg_elev_pipe = self.fg_pipes[tile_key]

        if math.isnan(lon_lat[0]) or math.isnan(lon_lat[1]):
            logging.error("NaN encountered while probing elevation")
            return FG_ELEV_NO_ELEV, True

        query: str = '%i %1.10f %1.10f\r\n' % (self.record, lon_lat[0], lon_lat[1])
        try:
            fg_elev_pipe.stdin.write(query)
        except IOError as reason:
            if reason.errno == 32:
                raise RuntimeError('fgelev - Broken pipe. Most probably no scenery available. Cannot continue.')
            logging.error("IOError while writing query '%s': %s", query.strip(), reason)

        empty_lines = 0
        line = ""
        try:
            while line == "" and empty_lines < 20:
                empty_lines += 1
                line = fg_elev_pipe.stdout.readline().strip()
                if line.startswith('Now checking') or line.startswith('osg::Registry::addImageProcessor') or \
                        line.startswith('Loaded plug-in'):  # New in FG Git version end of Dec 2018
                    line = ""
            parts = line.split()
            is_solid = True
            # in some situations we do not get the value of elevation
            if len(parts) < 2:
                elev = FG_ELEV_NO_ELEV
            else:
                if parts[1] == FG_ELEV_HOLE:
                    elev = FG_ELEV_NO_ELEV
                else:
                    elev = float(parts[1])
        except IndexError as reason:
            self.close()
            if empty_lines > 1:
                logging.fatal("Skipped %i lines" % empty_lines)
            logging.fatal("%i %g %g" % (self.record, lon_lat[0], lon_lat[1]))
            logging.fatal("fgelev returned <%s>, resulting in %s. Did fgelev start OK (Record : %i)?",
                          line, reason, self.record)
            raise RuntimeError("fgelev errors are fatal.")
        return elev, is_solid

    def probe_elev(self, lon_lat: tuple[float, float], is_global: bool = False) -> float:
        elev_is_solid_tuple = self.probe(lon_lat, is_global)
        return elev_is_solid_tuple[0]

    def probe(self, lon_lat: tuple[float, float], is_global: bool = False) -> tuple[float, bool]:
        """Return elevation and ground solidness at (x,y).
        Elevation is in meters as float. Solid is True, in water is False
        """
        if parameters.NO_ELEV:
            return 0, True

        if not is_global:
            lon_lat = self.coords_transform.to_global(lon_lat)

        self.record += 1
        return self._really_probe(lon_lat)

    def probe_list_of_points(self, points: list[tuple[float, float]]) -> tuple[float, float]:
        """Get the elevation of the lowest node of a list of points.
        If a node is in water or at -9999, then return -9999
        Second returned value is the difference between the highest and the lowest point.
        """
        elev_water_ok = True
        min_ground_elev = 9999
        max_ground_elev = -999
        for point in points:
            elev_is_solid_tuple = self.probe(point)
            if elev_is_solid_tuple[0] == FG_ELEV_NO_ELEV:
                logging.debug("-9999")
                elev_water_ok = False
                break
            elif not elev_is_solid_tuple[1]:
                logging.debug("in water")
                elev_water_ok = False
                break
            if min_ground_elev > elev_is_solid_tuple[0]:
                min_ground_elev = elev_is_solid_tuple[0]
            if max_ground_elev < elev_is_solid_tuple[0]:
                max_ground_elev = elev_is_solid_tuple[0]
        if not elev_water_ok:
            return FG_ELEV_NO_ELEV, 0
        return min_ground_elev, max_ground_elev - min_ground_elev


def create_scenery_path() -> str:
    scenery_path = parameters.PATH_TO_SCENERY
    if parameters.PATH_TO_AIRPORTS is not None:
        scenery_path = f'{parameters.PATH_TO_SCENERY}:{parameters.PATH_TO_AIRPORTS}'
    return scenery_path
