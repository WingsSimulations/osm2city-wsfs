# SPDX-FileCopyrightText: (C) 2015 - 2025, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later

"""Handles reading from apt.dat airport files and read/write to pickle file for minimised representation.
See https://developer.x-plane.com/?article=airport-data-apt-dat-file-format-specification for the specification.

Files in NavData/apt/ in scenery directories are used in addition to $FG_ROOT/Airports/apt.dat.gz,
see https://sourceforge.net/p/flightgear/flightgear/ci/516a5cf016a7d504b09aaac2e0e66c7e9efd42b2/.
"""

from abc import ABCMeta, abstractmethod
import gzip
import logging
import os
from osm2city import parameters
import time
from typing import Optional

from shapely.affinity import rotate
from shapely.geometry import box, CAP_STYLE, LineString, Point, Polygon

from osm2city.utils import utilities
import osm2city.utils.coordinates as co
import osm2city.utils.environment as env


class Boundary:
    def __init__(self, name: str) -> None:
        self.nodes_lists = list()  # a list of list of Nodes, where a Node is a tuple (lon, lat)
        self.name = name  # not used in osm2city, just for debugging

    def append_nodes_list(self, nodes_list) -> None:
        """Append new nodes list. There can be situations, where several closed polygons make up a pavement etc."""
        self.nodes_lists.append(nodes_list)

    def within_boundary(self, min_lon, min_lat, max_lon, max_lat):
        """If no node within - or there are no nodes - then return False.
        That is OK, because at least the runways will be checked."""
        if len(self.nodes_lists) == 0:
            return False
        for my_list in self.nodes_lists:
            for lon_lat in my_list:
                if (min_lon <= lon_lat[0] <= max_lon) and (min_lat <= lon_lat[1] <= max_lat):
                    return True
        return False

    def create_polygons(self, transformer: co.Transformation) -> Optional[list[Polygon]]:
        if self.not_empty:
            boundaries = list()
            for my_list in self.nodes_lists:
                if len(my_list) < 3:
                    continue
                my_boundary = Polygon([transformer.to_local(n) for n in my_list])
                if my_boundary.is_valid:
                    boundaries.append(my_boundary)
            return boundaries
        return None

    @property
    def not_empty(self) -> bool:
        if self.nodes_lists:
            return True
        return False


class Runway(metaclass=ABCMeta):
    @abstractmethod
    def within_boundary(self, min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> bool:
        pass

    @abstractmethod
    def create_blocked_area(self, coords_transform: co.Transformation) -> Polygon:
        pass


class LandRunway(Runway):
    def __init__(self, width: float, start: co.Vec2d, end: co.Vec2d) -> None:
        self.width = width
        self.start = start  # global coordinates
        self.end = end  # global coordinates

    def within_boundary(self, min_lon, min_lat, max_lon, max_lat):
        if (min_lon <= self.start.x <= max_lon) and (min_lat <= self.start.y <= max_lat):
            return True
        if (min_lon <= self.end.x <= max_lon) and (min_lat <= self.end.y <= max_lat):
            return True
        return False

    def create_blocked_area(self, coords_transform):
        line = LineString([coords_transform.to_local((self.start.x, self.start.y)),
                           coords_transform.to_local((self.end.x, self.end.y))])
        return line.buffer(self.width / 2.0, cap_style=CAP_STYLE.flat)


class WaterRunway(LandRunway):
    pass


class Helipad(Runway):
    def __init__(self, length: float, width: float, center: co.Vec2d, orientation: float) -> None:
        self.length = length
        self.width = width
        self.center = center  # global coordinates
        self.orientation = orientation

    def within_boundary(self, min_lon, min_lat, max_lon, max_lat):
        if (min_lon <= self.center.x <= max_lon) and (min_lat <= self.center.y <= max_lat):
            return True
        return False

    def create_blocked_area(self, coords_transform):
        my_point = Point(coords_transform.to_local((self.center.x, self.center.y)))
        my_box = box(my_point.x - self.length / 2, my_point.y - self.width / 2,
                     my_point.x + self.length / 2, my_point.y + self.width / 2)
        return rotate(my_box, self.orientation)


class Airport(object):
    def __init__(self, code: str, name: str, kind: int) -> None:
        self.code = code
        self.name = name
        self.kind = kind  # as per apt_dat definition: 1 = land airport, 16 = seaplane base, 17 = heliport
        self.runways = list()  # LandRunways, Helipads
        self.airport_boundary = None
        self.pavements = list()  # Pavement of type Boundary

    def append_runway(self, runway: Runway) -> None:
        self.runways.append(runway)

    def append_airport_boundary(self, airport_boundary: Boundary) -> None:
        self.airport_boundary = airport_boundary

    def append_pavement(self, pavement_boundary: Boundary) -> None:
        self.pavements.append(pavement_boundary)

    def within_boundary(self, min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> bool:
        for runway in self.runways:
            if runway.within_boundary(min_lon, min_lat, max_lon, max_lat):
                return True
        if self.airport_boundary is not None \
                and self.airport_boundary.within_boundary(min_lon, min_lat, max_lon, max_lat):
            return True
        return False

    def calculate_centre(self) -> tuple[float, float]:
        """There is no abstract lon/lat for the airport, therefore calculate it from other data"""
        total_lon = 0.
        total_lat = 0.
        counter = 0
        for runway in self.runways:
            if isinstance(runway, Helipad):
                total_lon += runway.center.x
                total_lat += runway.center.y
                counter += 1
            else:
                total_lon += runway.start.x + runway.end.x
                total_lat += runway.start.y + runway.end.y
                counter += 2
        if counter == 0:  # just to be sure and not getting a div by zero exception
            return 0, 0
        return total_lon / counter, total_lat / counter

    def create_blocked_areas(self, coords_transform: co.Transformation,
                             for_buildings: bool) -> list[Polygon]:
        blocked_areas = list()
        for runway in self.runways:
            blocked_areas.append(runway.create_blocked_area(coords_transform))
        if for_buildings:
            pavement_include_list = parameters.OVERLAP_CHECK_APT_PAVEMENT_BUILDINGS_INCLUDE
        else:
            pavement_include_list = parameters.OVERLAP_CHECK_APT_PAVEMENT_ROADS_INCLUDE

        if pavement_include_list is None:
            return blocked_areas  # no pavements are added to the blocked areas from runways.

        if len(pavement_include_list) == 0 or self.code in pavement_include_list:
            for pavement in self.pavements:
                pavement_polygons = pavement.create_polygons(coords_transform)
                if pavement_polygons:
                    for pb in pavement_polygons:
                        blocked_areas.append(pb)
        return utilities.merge_buffers(blocked_areas)

    def create_boundary_polygons(self, coords_transform: co.Transformation) -> Optional[list[Polygon]]:
        if self.airport_boundary is None:
            return None
        else:
            return self.airport_boundary.create_polygons(coords_transform)


def get_scenery_apt_dat_files() -> list[str]:
    """Return a list of paths to <apt>.dat files found in the scenery directories."""
    apt_dat_list = []

    if parameters.OVERLAP_CHECK_APT_DAT_SCENERY_LIST is not None:
        scenery_list = parameters.OVERLAP_CHECK_APT_DAT_SCENERY_LIST
    else:
        scenery_list = [parameters.PATH_TO_SCENERY]
        if parameters.PATH_TO_SCENERY_OPT is not None:
            scenery_list += parameters.PATH_TO_SCENERY_OPT

    for apt_dat_dir in [os.path.join(d, "NavData", "apt") for d in scenery_list]:
        if os.path.isdir(apt_dat_dir):
            for file in os.listdir(apt_dat_dir):
                if file.endswith(".dat") or file.endswith(".dat.gz"):
                    apt_dat_list.append(os.path.join(apt_dat_dir, file))

    return apt_dat_list


def _read_apt_dat_file(file, airports: dict[str, Airport], airport_lines: dict[str, list[str]],
                       min_lon: float, min_lat: float, max_lon: float, max_lat: float,
                       read_water_runways: bool = False) -> int:
    """Parse apt.dat files, extending the dict of airports from the input parameter."""
    total_airports = 0
    my_airport = None
    boundary = None
    current_boundary_nodes = list()
    in_boundary = False
    current_apt_lines = list()
    for line in file:
        current_apt_lines.append(line)
        parts = line.split()
        if not parts:
            continue
        if in_boundary:
            if parts[0] not in ['111', '112', '113', '114', '115', '116']:
                in_boundary = False
            else:
                current_boundary_nodes.append((float(parts[2]), float(parts[1])))
                if parts[0] in ['113', '114']:  # closed loop
                    boundary.append_nodes_list(current_boundary_nodes)
                    current_boundary_nodes = list()
        if parts[0] in ['1', '16', '17', '99']:
            # first actually append the previously read airport data to the collection if within bounds
            if (my_airport is not None) and (my_airport.within_boundary(min_lon, min_lat, max_lon, max_lat)):
                # will overwrite previous airport with same ICAO if present
                airports[my_airport.code] = my_airport
                if current_apt_lines:
                    current_apt_lines.pop()  # need to remove last line, because first line of next airport
                airport_lines[my_airport.code] = current_apt_lines
            # and then create a new empty airport
            if not parts[0] == '99':
                my_airport = Airport(parts[4], parts[5], int(parts[0]))
                current_apt_lines = [line]  # need to include the current line
                total_airports += 1
        elif parts[0] == '100':
            my_runway = LandRunway(float(parts[1]), co.Vec2d(float(parts[10]), float(parts[9])),
                                   co.Vec2d(float(parts[19]), float(parts[18])))
            my_airport.append_runway(my_runway)
        elif parts[0] == '101':
            if read_water_runways:
                my_runway = WaterRunway(float(parts[1]), co.Vec2d(float(parts[5]), float(parts[4])),
                                        co.Vec2d(float(parts[8]), float(parts[7])))
                my_airport.append_runway(my_runway)
        elif parts[0] == '102':
            my_helipad = Helipad(float(parts[5]), float(parts[6]), co.Vec2d(float(parts[3]), float(parts[2])),
                                 float(parts[4]))
            my_airport.append_runway(my_helipad)
        elif parts[0] == '110':  # Pavement
            name = 'no name'
            if len(parts) == 5:
                name = parts[4]
            boundary = Boundary(name)
            in_boundary = True
            my_airport.append_pavement(boundary)
        elif parts[0] == '130':  # Airport boundary header
            name = 'no name'
            if len(parts) > 0:
                name = ' '.join(parts[1:])
            boundary = Boundary(name)
            in_boundary = True
            my_airport.append_airport_boundary(boundary)

    return total_airports


def read_apt_dat_files(min_lon: float, min_lat: float,
                       max_lon: float, max_lat: float,
                       read_water_runways: bool = False) -> list[Airport]:
    """Returns: a list Airports read from the apt.dat files in FGData and in all the scenery directories."""
    start_time = time.time()
    airports: dict[str, Airport] = dict()
    airport_lines: dict[str, list[str]] = dict()
    total_airports = 0

    apt_dat_gz_file = os.path.join(env.get_env_parameter('FG_ROOT'), 'Airports', 'apt.dat.gz')
    logging.info('Reading apt.dat file %s', apt_dat_gz_file)
    with gzip.open(apt_dat_gz_file, 'rt', encoding="latin-1") as f:
        total_airports += _read_apt_dat_file(f, airports, airport_lines,
                                             min_lon, min_lat, max_lon, max_lat, read_water_runways)

    total_files = 1
    for path in get_scenery_apt_dat_files():
        logging.info('Reading apt.dat file %s', path)
        total_files += 1
        open_fun = gzip.open if path.endswith(".dat.gz") else open
        with open_fun(path, 'rt', encoding="latin-1") as f:
            total_airports += _read_apt_dat_file(f, airports, airport_lines,
                                                 min_lon, min_lat, max_lon, max_lat, read_water_runways)

    logging.info("Read %d airports from %d files, %d having runways/helipads within the boundary",
                 total_airports, total_files, len(airports))

    utilities.time_logging("Execution time", start_time)
    return list(airports.values())


def get_apt_dat_blocked_areas_from_airports(coords_transform: co.Transformation,
                                            min_lon: float, min_lat: float, max_lon: float, max_lat: float,
                                            airports: list[Airport], for_buildings: bool) -> tuple[list[Polygon],
                                                                                             list[Polygon]]:
    """Transforms runways/helipads - and depending on parameters also pavements - in airports to polygons.
    Returns 2 lists of polygons: blocked areas and airport boundaries.
    NB: depending on parameters the airport boundaries are also in the blocked_areas
    """
    blocked_areas: list[Polygon] = list()
    airport_boundaries: list[Polygon] = list()
    for airport in airports:
        if airport.within_boundary(min_lon, min_lat, max_lon, max_lat):
            boundary_polygons = airport.create_boundary_polygons(coords_transform)
            if boundary_polygons is not None:
                airport_boundaries.extend(boundary_polygons)

            blocked_areas.extend(airport.create_blocked_areas(coords_transform, for_buildings))
            if (for_buildings is False and parameters.OVERLAP_CHECK_APT_BOUNDARY_ROADS) or (
                for_buildings is True and parameters.OVERLAP_CHECK_APT_BOUNDARY_BUILDINGS):
                if boundary_polygons is not None:
                    blocked_areas.extend(boundary_polygons)
    return blocked_areas, airport_boundaries
