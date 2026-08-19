# SPDX-FileCopyrightText: (C) 2014 - 2025, rick@vanosten.net, radi, portree_kid
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Manage I/O for .stg files. There are two classes, STGManager and STGFile.

STGManager is the main interface for writing OBJECT_STATIC (_SHARED will
follow) to .stg files. It knows about the scenery path, tile indices etc. You
only need to provide the actual ac_file_name, position, elevation, hdg.
See __main__ for usage.

STG_file represents an .stg file. Usually you don't deal with them directly.

Coordinate precision is often quite important - especially when different objects
are combined. E.g. cables and pylons.

According to https://wiki.openstreetmap.org/wiki/Precision_of_coordinates ca. 0.1m
needs a coordinate precision of 6 digits. On the other hand, more digits means
more space on disk.
"""
import enum
from dataclasses import dataclass
import gzip
import logging
import multiprocessing.synchronize as mps
import os
from pathlib import Path
import time

from shapely import affinity
import shapely.geometry as shg

from osm2city import parameters
import osm2city.static_types.shared_models as sm
from osm2city.static_types import types as t
from osm2city.utils import calc_tile
from osm2city.utils.coordinates import Transformation, Vec2d, calc_horizon_elev_local, normal_degrees


OBJECT_SHARED = 'OBJECT_SHARED'
OBJECT_STATIC = 'OBJECT_STATIC'
OBJECT_SIGN = 'OBJECT_SIGN'


@enum.unique
class LOD(enum.IntEnum):
    rough = 0
    detail = 1


@enum.unique
class STGVerbType(enum.IntEnum):  # must be the same as actual string in lowercase in FGFS
    object_shared = 1
    object_static = 2
    object_building_mesh_rough = 3
    object_building_mesh_detailed = 4
    object_road_rough = 5
    object_road_detailed = 6
    object_railway_rough = 7
    object_railway_detailed = 8
    building_list = 10


@enum.unique
class SceneryType(enum.IntEnum):
    buildings = 1
    roads = 2
    pylons = 3
    details = 4
    trees = 5
    # other types
    objects = 11
    terrain = 12


def scenery_directory_name(scenery_type: SceneryType) -> str:
    """Return a capitalized version to be used in directory naming"""
    return scenery_type.name.title()


def parse_for_scenery_type(type_argument: str) -> SceneryType:
    """Parses a command line argument to determine which osm2city procedure to run.
    Returns KeyError if mapping cannot be done"""
    return SceneryType.__members__[type_argument.lower()]


@dataclass
class ObjectInstancedListEntry:
    """Stores the details of entries in STF OBJECT_INSTANCED list.
    Cf. details in chapter in fgdata/docs/README.scenery."""

    osm_id: t.OSMId | None = None
    x: float = 0.
    y: float = 0.
    z: float = 0.
    has_orientation: bool = False
    hdg: float = 0.
    pitch: float = 0.
    roll: float = 0.
    has_scale: bool = False
    scale: float = 0.

    def __init__(self, osm_id: t.OSMId | None = None):
        self.osm_id = osm_id  # only used for debugging reference

    def add_position(self, x: float, y: float, z: float) -> None:
        self.x = x
        self.y = y
        self.z = z

    def add_position_local_coordinates(self, x: float, y: float, z: float) -> None:
        """Uses local coordinates on flat space as input and transforms to coordinate system used in lists"""
        elev = z - calc_horizon_elev_local(x, y)
        self.x = -y
        self.y = x
        self.z = elev

    def add_orientation(self, hdg: float, pitch: float = 0., roll: float = 0.) -> None:
        self.has_orientation = True
        self.hdg = normal_degrees(hdg)
        self.pitch = pitch
        self.roll = roll

    def add_orientation_local_coordinates(self, hdg: float) -> None:
        self.add_orientation(_stg_angle(hdg - 90.))

    def add_scale(self, scale: float):
        self.has_scale = True
        self.scale = scale

    def format_list_entry(self) -> str:
        line = f'{self.x:.2f} {self.y:.2f} {self.z:.2f}'
        if self.has_orientation:
            line += f' {self.hdg:.1f} {self.pitch:.1f} {self.roll:.1f}'
        if self.has_scale:
            line += f' {self.scale:.4f}'
        return line


class STGFile(object):
    """represents an .stg file.
       takes care of writing/reading/uninstalling OBJECT_* lines
    """
    
    def __init__(self, lon_lat: Vec2d, path_to_scenery: str, scenery_type: SceneryType,
                 magic: str, prefix: str) -> None:
        """Read all lines from stg to memory.
           Store our/other lines in two separate lists."""
        scenery_name = scenery_directory_name(scenery_type)
        self.path_to_stg = calc_tile.construct_path_to_files(path_to_scenery, scenery_name, (lon_lat.lon, lon_lat.lat))
        tile_index = calc_tile.calc_tile_index((lon_lat.lon, lon_lat.lat))
        self.file_name = os.path.join(self.path_to_stg, calc_tile.construct_stg_file_name_from_tile_index(tile_index))
        self.other_list = list()
        self.our_list = list()
        self.prefix = prefix
        self.our_magic_start = _make_delimiter_string(magic, prefix, True)
        self.our_magic_end = _make_delimiter_string(magic, prefix, False)
        self.osm_ids: list[t.OSMId] = list()  # optional osm_ids for objects in file (e.g. for shared objects to prevent duplicates)

    def _read(self) -> None:
        """read others and ours from file"""
        try:
            stg = open(self.file_name, 'r')
            lines = stg.readlines()
            stg.close()
        except IOError as ioe:
            logging.debug("Error reading %s as it might not exist yet: %s", self.file_name, ioe)
            return

        self.other_list = []
        # if our magic is not present, then use the whole file content
        if lines.count(self.our_magic_start) == 0:
            self.other_list = lines
            return
        # otherwise handle the possibility for several sections
        while lines.count(self.our_magic_start) > 0:
            try:
                ours_start = lines.index(self.our_magic_start)
            except ValueError:
                self.other_list = lines
                break

            try:
                ours_end = lines.index(self.our_magic_end)
            except ValueError:
                ours_end = len(lines)

            self.other_list = self.other_list + lines[:ours_start]
            lines = lines[ours_end + 1:]

    def add_object(self, stg_verb: str, ac_file_name: str, lon_lat, elev: float, hdg: float, roll: float,
                   radius: float | None, osm_id: t.OSMId | None = None) -> str:
        """Add OBJECT_XXXXX line to our_list. Returns the path to stg.

        If there is an osm_id, we check against already registered ones and only add if it did not exist yet.
        """
        write_object = True
        if osm_id:
            if osm_id not in self.osm_ids:
                self.osm_ids.append(osm_id)
            else:
                write_object = False
        if write_object:
            line = '{} {} {:.6f} {:.6f} {:.2f} {:.1f} 0.0 {:.1f}'.format(stg_verb.upper(), ac_file_name,
                                                                         lon_lat.lon, lon_lat.lat, elev, hdg, roll)
            if radius is not None:
                line += ' ' + str(radius) + '\n'
            else:
                line += '\n'
            self.our_list.append(line)
            logging.debug(self.file_name + ':' + line)
        # Make sure the path exists. Needs to be done already now, because e.g. ac-files might be written to the path
        _make_path_to_stg(self.path_to_stg)
        return self.path_to_stg

    def add_line(self, line: str) -> str:
        self.our_list.append(line + '\n')
        _make_path_to_stg(self.path_to_stg)
        return self.path_to_stg

    def write(self) -> None:
        """write stg-objects from other procedures (e.g. maritime.py) and our procedure (e.g. pylons.py) to file.
        Other stuff is read if the file already exists.
        Our stuff was added through the add_object(...) method.
        """
        # Read the current content if it already exists
        self._read()
        # Write the content
        stg = open(self.file_name, 'w')
        logging.info("Writing %d other lines" % len(self.other_list))
        for line in self.other_list:
            stg.write(line)

        if self.our_list:
            logging.info("Writing %d lines" % len(self.our_list))
            stg.write(self.our_magic_start)
            stg.write("# do not edit below this line\n")
            stg.write("# Last Written %s\n#\n" % time.strftime("%c"))
            for line in self.our_list:
                logging.debug(line.strip())
                stg.write(line)
            stg.write(self.our_magic_end)

        stg.close()


def _make_path_to_stg(path_to_stg: str) -> None:
    try:
        os.makedirs(path_to_stg)
    except OSError as e:
        if e.errno != 17:
            logging.exception('Unable to create path to output %s', path_to_stg)
            raise e


class STGManager(object):
    """manages STG objects. Knows about scenery path.
       prefix separates different writers to work around two PREFIX areas interleaving 
    """
    def __init__(self, path_to_scenery: str, scenery_type: SceneryType, magic: str, prefix: str = None) -> None:
        self.stg_dict = dict()  # key: tile index, value: STGFile
        self.path_to_scenery = path_to_scenery
        self.magic = magic
        self.prefix = prefix
        self.scenery_type = scenery_type

    def _find_create_stg_file(self, lon_lat: Vec2d) -> STGFile:
        """Finds an STGFile for a given coordinate. If not yet registered, then new one created."""
        tile_index = calc_tile.calc_tile_index((lon_lat.lon, lon_lat.lat))
        try:
            return self.stg_dict[tile_index]
        except KeyError:
            the_stg_file = STGFile(lon_lat, self.path_to_scenery, self.scenery_type, self.magic, self.prefix)
            self.stg_dict[tile_index] = the_stg_file
        return the_stg_file

    def add_object_static(self, ac_file_name: str, lon_lat: Vec2d, radius: float,
                          stg_verb_type: STGVerbType = STGVerbType.object_static, hdg: float = 0., roll: float = 0.) -> str:
        """Adds OBJECT_STATIC line. Returns path to stg."""
        the_stg_file = self._find_create_stg_file(lon_lat)
        return the_stg_file.add_object(stg_verb_type.name.upper(), ac_file_name, lon_lat, 0., hdg, roll, radius)

    def add_object_shared(self, ac_file_name: str, lon_lat: Vec2d, elev: float, hdg: float, roll: float = 0.,
                          osm_id: t.OSMId | None = None) -> None:
        """Adds OBJECT_SHARED line.

        The optional osm_id is used to make sure that shared objects do not get added twice
        - e.g. because they are referenced in 2 lines as end pylons.
        """
        the_stg_file = self._find_create_stg_file(lon_lat)
        the_stg_file.add_object(OBJECT_SHARED, ac_file_name, lon_lat, elev, hdg, roll, None, osm_id)

    def add_building_list(self, building_list_name: str, material_name: str, lon_lat: Vec2d, elev: float) -> str:
        """Adds a BUILDING_LIST line"""
        the_stg_file = self._find_create_stg_file(lon_lat)
        line = 'BUILDING_LIST {} {} {:.6f} {:.6f} {:.2f}'.format(building_list_name, material_name,
                                                                 lon_lat.lon, lon_lat.lat, elev)
        return the_stg_file.add_line(line)

    def add_light_list(self, light_list_name: str, lon_lat: Vec2d, elev: float) -> str:
        """Adds a LIGHT_LIST line"""
        the_stg_file = self._find_create_stg_file(lon_lat)
        line = 'LIGHT_LIST {} {:.6f} {:.6f} {:.2f}'.format(light_list_name, lon_lat.lon, lon_lat.lat, elev)
        return the_stg_file.add_line(line)

    def add_line_feature_list(self, line_feature_list_name: str, material_name: str, lon_lat: Vec2d) -> str:
        """Adds a LINE_FEATURE_LIST line"""
        the_stg_file = self._find_create_stg_file(lon_lat)
        line = 'LINE_FEATURE_LIST {} {}'.format(line_feature_list_name, material_name)
        return the_stg_file.add_line(line)

    def add_instanced_list(self, model: str, instance_list_name: str, lon_lat: Vec2d, elev: float) -> str:
        the_stg_file = self._find_create_stg_file(lon_lat)
        line = 'OBJECT_INSTANCED {} {} default {:.6f} {:.6f} {:.2f}'.format(model, instance_list_name,
                                                                            lon_lat.lon, lon_lat.lat, elev)
        return the_stg_file.add_line(line)

    def write(self, file_lock: mps.Lock | None = None):
        """Writes all new scenery objects, including the already existing back to stg-files.
        The file_lock object makes sure that only the current process is reading and writing stg-files
        to avoid conflicts.
        """
        if file_lock is not None:
            file_lock.acquire()
        for key, the_stg in self.stg_dict.items():
            the_stg.write()
        if file_lock is not None:
            file_lock.release()


class STGEntry(object):
    def __init__(self, type_string: str, obj_filename: str, stg_path: str,
                 lon: float, lat: float, elev: float, hdg: float) -> None:
        self.verb_type = STGVerbType.object_shared
        self._translate_verb_type(type_string)
        self.obj_filename = obj_filename
        self.stg_path = stg_path  # the path of the stg_file without file name and trailing path-separator
        self.lon = lon
        self.lat = lat
        self.elev = elev
        self.hdg = hdg
        self.convex_hull = None  # a Polygon object set by parse_stg_entries_for_convex_hull(...) in local coordinates

    def _translate_verb_type(self, type_string: str) -> None:
        """Translates from a string in FGFS to an enumeration.
        If nothing is found, then the default in __init__ is used."""
        for verb in STGVerbType:
            if verb.name == type_string.lower():
                self.verb_type = verb
                return

    def overwrite_filename(self, new_name: str) -> None:
        if self.verb_type is STGVerbType.object_static:
            self.obj_filename = new_name
        else:
            slash_index = self.obj_filename.rfind("/")
            backslash_index = self.obj_filename.rfind("\\")
            chosen_index = max([slash_index, backslash_index])
            self.obj_filename = self.obj_filename[:chosen_index + 1] + new_name

    def get_obj_path_and_name(self, scenery_path: str | None = None) -> str:
        """Parameter scenery_path is most probably parameters.SCENERY_PATH.
        It can be useful to try a different path for shared_objects, which might be from Terrasync."""
        if self.verb_type is STGVerbType.object_shared:
            if scenery_path is not None:
                return os.path.join(scenery_path, self.obj_filename)

            p = os.path.abspath(self.stg_path + os.sep + '..' + os.sep + '..' + os.sep + '..')
            return os.path.abspath(os.path.join(p, self.obj_filename))
        else:
            return os.path.join(self.stg_path, self.obj_filename)


def read_stg_entries(stg_path_and_name: str, our_magic: str = "",
                     ignore_bad_lines: bool = False) -> list[STGEntry]:
    """Reads an stg-file and extracts STGEntry objects outside of marked areas for our_magic.
    TODO: In the future, take care of multiple scenery paths here.
    TODO: should be able to take a list of our_magic"""
    entries = []  # list of STGEntry objects

    our_magic_start = _make_delimiter_string(our_magic, None, True)
    our_magic_end = _make_delimiter_string(our_magic, None, False)
    ours = False
    try:
        with open(stg_path_and_name, 'r') as my_file:
            path, stg_name = os.path.split(stg_path_and_name)
            for line in my_file:
                if len(our_magic) > 0:
                    if line.startswith(our_magic_start):
                        ours = True
                        continue
                    if line.startswith(our_magic_end):
                        ours = False
                        continue
                    if ours:
                        continue

                if line.startswith('#') or line.lstrip() == "":
                    continue
                if line.startswith(OBJECT_SIGN):
                    continue
                if parameters.OVERLAP_CHECK_CONSIDER_SHARED is False and line.startswith(OBJECT_SHARED):
                    continue
                try:
                    splitted = line.split()
                    type_ = splitted[0]
                    obj_filename = splitted[1]
                    lon = float(splitted[2])
                    lat = float(splitted[3])
                    elev = float(splitted[4])
                    hdg = float(splitted[5])
                    entry = STGEntry(type_, obj_filename, path, lon, lat, elev, hdg)
                    entries.append(entry)                
                except ValueError as reason:
                    if not ignore_bad_lines:
                        logging.warning("stg_io:read: Damaged file %s", reason)
                        logging.warning("Damaged line: %s", line.strip())
                        return []
                    else:
                        logging.warning("Damaged line: %s", line.strip())
                except IndexError as reason:
                    if not ignore_bad_lines:
                        logging.warning("stg_io:read: Ignoring unreadable file %s", reason)
                        logging.warning("Offending line: %s", line.strip())
                        return []
                    else:
                        logging.warning("Damaged line: %s", line.strip())
    except IOError as reason:
        logging.warning("stg_io:read: Ignoring unreadable file %s", reason)
        return []
    return entries


def read_stg_entries_in_boundary(transform: Transformation, for_roads: bool) -> list[STGEntry]:
    """Returns a list of all STGEntries within the boundary according to parameters.
    Adds all tiles bordering the chosen tile in order to make sure that objects crossing tile borders but
    maybe located outside also are taken into account.
    It uses the PATH_TO_SCENERY and PATH_TO_SCENERY_OPT (which are static), not PATH_TO_OUTPUT.
    """
    bucket_span = calc_tile.bucket_span(parameters.BOUNDARY_NORTH - (
            parameters.BOUNDARY_NORTH - parameters.BOUNDARY_SOUTH) / 2)
    boundary_west = parameters.BOUNDARY_WEST - bucket_span
    boundary_east = parameters.BOUNDARY_EAST + bucket_span
    boundary_north = parameters.BOUNDARY_NORTH + 1. / 8.
    boundary_south = parameters.BOUNDARY_SOUTH - 1. / 8.
    stg_entries: list[STGEntry] = list()
    stg_files = calc_tile.get_stg_files_in_boundary(boundary_west, boundary_south,
                                                    boundary_east, boundary_north,
                                                    parameters.PATH_TO_SCENERY,
                                                    scenery_directory_name(SceneryType.objects))

    if parameters.PATH_TO_SCENERY_OPT:
        for my_path in parameters.PATH_TO_SCENERY_OPT:
            stg_files_opt = calc_tile.get_stg_files_in_boundary(boundary_west, boundary_south,
                                                                boundary_east, boundary_north,
                                                                my_path,
                                                                scenery_directory_name(SceneryType.objects))
            stg_files.extend(stg_files_opt)

    for filename in stg_files:
        stg_entries.extend(read_stg_entries(filename))

    # exclude entries in skip list
    for entry in reversed(stg_entries):
        if entry.obj_filename in parameters.SKIP_LIST_OVERLAP:
            stg_entries.remove(entry)

    # the border of the original tile in local coordinates
    south_west = transform.to_local((parameters.BOUNDARY_WEST, parameters.BOUNDARY_SOUTH))
    north_east = transform.to_local((parameters.BOUNDARY_EAST, parameters.BOUNDARY_NORTH))
    tile_box = shg.box(south_west[0], south_west[1], north_east[0], north_east[1])

    _parse_stg_entries_for_convex_hull(stg_entries, transform, tile_box)

    # after having all original stg-entries, lets check for exclude areas
    if for_roads:
        areas = parameters.OVERLAP_CHECK_EXCLUDE_AREAS_ROADS
    else:
        areas = parameters.OVERLAP_CHECK_EXCLUDE_AREAS_BUILDINGS
    exclude_area_entries = _create_pseudo_stg_entries_for_exclude_areas(areas, transform)
    # remove all static entries within the exclude areas - as they might have problems in their geometry
    count_removed = 0
    for entry in reversed(stg_entries):
        if entry.verb_type is not STGVerbType.object_static:
            continue
        x, y = transform.to_local((entry.lon, entry.lat))
        for fake_entry in exclude_area_entries:
            if fake_entry.convex_hull.contains(shg.Point(x, y)):
                stg_entries.remove(entry)
                count_removed += 1
                break
    # finally add the fake exclude areas to the list of entries
    logging.info('Removed %i static object entries due to OVERLAP_CHECK_EXCLUDE_AREAS', count_removed)
    stg_entries.extend(exclude_area_entries)
    return stg_entries


def _create_pseudo_stg_entries_for_exclude_areas(areas: list[list[tuple[float, float]]] | None,
                                                 transform: Transformation) -> list[STGEntry]:
    """Create a list of faked STGEntries for exclude areas.

    We cannot control the data quality of the user provided input, so no recovery on error -> fail fast.
    """
    if areas is None or len(areas) == 0:
        return list()
    faked_entries = list()
    for i, list_of_tuples in enumerate(areas):
        my_coordinates = list()
        for lon_lat in list_of_tuples:
            x, y = transform.to_local((lon_lat[0], lon_lat[1]))
            my_coordinates.append((x, y))
        if len(my_coordinates) >= 3:
            my_polygon = shg.Polygon(my_coordinates)
            if my_polygon.is_valid and not my_polygon.is_empty:
                lon, lat = transform.to_global((my_polygon.centroid.x, my_polygon.centroid.y))
                my_entry = STGEntry(STGVerbType.object_static.name, 'exclude area', 'fake', lon, lat, 0, 0)
                my_entry.convex_hull = my_polygon
                faked_entries.append(my_entry)
            else:
                raise ValueError('Resulting exclude area polygon is not valid or empty: Entry: %i', i + 1)
        else:
            raise ValueError('There must be at least 3 coordinate tuples per exclude area polygon. Entry: %i', i + 1)
    logging.info('Added %i fake static STGEntries for OVERLAP_CHECK_EXCLUDE_AREAS', len(faked_entries))
    return faked_entries


def _parse_stg_entries_for_convex_hull(stg_entries: list[STGEntry], my_coord_transformation: Transformation,
                                       tile_box: shg.Polygon) -> None:
    """
    Parses the ac-file content for a set of STGEntry objects and sets their boundary attribute
    to be the convex hull of all points in the ac-file in the specified local coordinate system.
    If there is a problem creating the convex hull, then the stg_entry will be removed.
    """
    ac_filename = ""
    alternative_models_path = parameters.PATH_TO_SCENERY
    if parameters.SHARED_MODELS_PATH:
        alternative_models_path = parameters.SHARED_MODELS_PATH
    for entry in reversed(stg_entries):
        if entry.verb_type in [STGVerbType.object_static, STGVerbType.object_shared]:
            try:
                ac_filename = entry.obj_filename
                if ac_filename.endswith(".xml"):
                    entry.overwrite_filename(_extract_ac_from_xml(entry.get_obj_path_and_name(),
                                                                  entry.get_obj_path_and_name(
                                                                      alternative_models_path)))
                boundary_polygon = _extract_object_boundary(entry.get_obj_path_and_name(),
                                                            entry.get_obj_path_and_name(alternative_models_path))
                rotated_polygon = affinity.rotate(boundary_polygon, entry.hdg - 90, (0, 0))
                x_y_point = my_coord_transformation.to_local((entry.lon, entry.lat))
                translated_polygon = affinity.translate(rotated_polygon, x_y_point[0], x_y_point[1])
                if entry.verb_type is STGVerbType.object_static and parameters.OVERLAP_CHECK_CH_BUFFER_STATIC > 0.01:
                    entry.convex_hull = translated_polygon.buffer(
                        parameters.OVERLAP_CHECK_CH_BUFFER_STATIC, shg.CAP_STYLE.square)
                elif entry.verb_type is STGVerbType.object_shared and parameters.OVERLAP_CHECK_CH_BUFFER_SHARED > 0.01:
                    entry.convex_hull = translated_polygon.buffer(
                        parameters.OVERLAP_CHECK_CH_BUFFER_SHARED, shg.CAP_STYLE.square)
                else:
                    entry.convex_hull = translated_polygon
            except IndexError as reason:
                logging.debug("Ignoring corrupted stg_entry of type %s and file name %s: %s",
                              entry.verb_type.name, entry.obj_filename, reason)
            except IOError as reason:
                logging.debug("Ignoring unreadable stg_entry of type %s and file name %s: %s",
                              entry.verb_type.name, entry.obj_filename, reason)
            except ValueError:
                # Happens e.g. for waterfalls, where the xml-file only references a <particlesystem>
                logging.debug("AC-filename could be wrong in xml-file %s - or just no ac-file referenced", ac_filename)

            # Now check, whether we are interested
            if entry.convex_hull is None or entry.convex_hull.is_valid is False or entry.convex_hull.is_empty:
                logging.debug("Ignoring stg_entry of type %s and file name %s: convex hull invalid",
                              entry.verb_type.name, entry.obj_filename)
                stg_entries.remove(entry)
            elif entry.convex_hull.within(tile_box) is False and entry.convex_hull.disjoint(tile_box):
                stg_entries.remove(entry)
            elif entry.convex_hull.area > parameters.OVERLAP_CHECK_CONVEX_HULL_STG_MAX_AREA:
                # happens e.g. for Models/Maritime/Misc/phare due to light stuff
                logging.debug("Ignoring stg_entry of type %s and file name %s: convex hull too large",
                              entry.verb_type.name, entry.obj_filename)
                stg_entries.remove(entry)


def _extract_object_boundary(ac_filename: str, alternative_ac_filename: str = None) -> shg.Polygon:
    """Reads an ac-file and constructs a convex hull as a proxy to the real boundary.
    No attempt is made to follow rotations and translations.
    Returns a tuple (x_min, y_min, x_max, y_max) in meters.
    An alternative path is tried, if the first path is not successful"""
    numvert = 0
    points = list()
    try:
        checked_filename = ac_filename
        if not os.path.isfile(checked_filename) and alternative_ac_filename is not None:
            checked_filename = alternative_ac_filename
        with open(checked_filename, 'r') as my_file:
            for my_line in my_file:
                if 0 == my_line.find("numvert"):
                    numvert = int(my_line.split()[1])
                elif numvert > 0:
                    vertex_values = my_line.split()
                    # Minus factor in y-axis due to the ac3d coordinate-system.
                    # Switch of y_min and y_max for the same reason
                    points.append((float(vertex_values[0]), -1 * float(vertex_values[2])))
                    numvert -= 1
    except (IndexError, IOError) as e:
        raise e

    hull_polygon = shg.MultiPoint(points).convex_hull
    return hull_polygon


def _parse_ac_file_name(xml_string: str) -> str:
    """Finds the corresponding ac-file in a xml-file"""
    try:
        x1 = xml_string.index("<path>")
        x2 = xml_string.index("</path>", x1)
    except ValueError as e:
        raise e
    ac_file_name = (xml_string[x1+6:x2]).strip()
    return ac_file_name


def _extract_ac_from_xml(xml_filename: str, alternative_xml_filename: str = None) -> str:
    """Reads the *.ac filename out of an xml-file"""
    checked_filename = xml_filename
    if not os.path.isfile(checked_filename) and alternative_xml_filename is not None:
        checked_filename = alternative_xml_filename
    with open(checked_filename, 'r') as f:
        xml_data = f.read()
        ac_filename = _parse_ac_file_name(xml_data)
        return ac_filename


def convex_hulls_from_stg_entries(stg_entries: list[STGEntry], verb_type: STGVerbType) -> list[shg.Polygon]:
    """Merge the convex hull of objects in stg-files into the blocked areas list of polygons."""
    my_polys = list()

    for stg_entry in stg_entries:
        if stg_entry.verb_type is verb_type:
            my_polys.append(stg_entry.convex_hull)
    return my_polys


def _make_delimiter_string(our_magic: str | None, prefix: str | None, is_start: bool) -> str:
    if our_magic is None:
        magic = ""
    else:
        magic = our_magic
    delimiter = '# '
    if not is_start:
        delimiter += 'END '
    if prefix is None:
        return delimiter + magic + '\n'
    else:
        return delimiter + magic + '_' + prefix + '\n'


def _stg_angle(angle_normal: float) -> float:
    """Returns the input angle in degrees to an angle for the stg-file in degrees.
    stg-files use angles counter-clockwise starting with 0 in North."""
    if 0 == angle_normal:
        return 0
    elif angle_normal > 360:
        angle_normal -= 360
    return 360 - angle_normal


class ObjectInstancedListCollector:
    """Class to collect all entries for OBJECT_INSTANCED lists across models"""
    model_lists: dict[str, list[ObjectInstancedListEntry]]

    def __init__(self):
        self.model_lists = dict()

    def add_entry(self, model: str, entry: ObjectInstancedListEntry) -> None:
        assert '/' in model, f'Model name "{model}" must have "/" as path separator'
        assert '\\' not in model, f'Model name "{model}" must not have "\\" as path separator'
        assert model.count('.') == 1, f'Model name "{model}" must have exactly one "."'

        if model not in self.model_lists:
            self.model_lists[model] = list()
        self.model_lists[model].append(entry)

    def register_and_write_lists(self, stg_mgr: STGManager, lon_lat: Vec2d) -> None:
        for model, instanced_list in self.model_lists.items():
            model_name = model.replace('/', '_')
            index = model_name.find('.')
            model_name = model_name[:index]
            file_name = f'{stg_mgr.prefix}_{model_name}.txt.gz'
            path_to_stg = stg_mgr.add_instanced_list(model, file_name, lon_lat, 0.)
            with gzip.open(os.path.join(path_to_stg, file_name), 'wt') as instance_file:
                for entry in instanced_list:
                    instance_file.write(entry.format_list_entry())
                    instance_file.write('\n')


def clean_stg_entries_for_shared_models_in_boundary(boundary_west: float, boundary_south: float,
                                                    boundary_east: float, boundary_north: float) -> None:
    """Within the boundary removes SHARED_OBJECT entries in stg-files for models, which osm2city controls.
    It uses the PATH_TO_SCENERY and PATH_TO_SCENERY_OPT, not PATH_TO_OUTPUT.
    It takes only stg-files in 'Objects' into account.
    """
    stg_files = calc_tile.get_stg_files_in_boundary(boundary_west, boundary_south,
                                                    boundary_east, boundary_north,
                                                    parameters.PATH_TO_SCENERY,
                                                    scenery_directory_name(SceneryType.objects))

    if parameters.PATH_TO_SCENERY_OPT:
        for my_path in parameters.PATH_TO_SCENERY_OPT:
            stg_files_opt = calc_tile.get_stg_files_in_boundary(boundary_west, boundary_south,
                                                                boundary_east, boundary_north,
                                                                my_path,
                                                                scenery_directory_name(SceneryType.objects))
            stg_files.extend(stg_files_opt)
    logging.info('Found %i stg-files to clean', len(stg_files))

    used_shared_models = _get_all_shared_models_used()
    logging.info('Found %i shared models handled by osm2city', len(used_shared_models))

    for filename in stg_files:
        path = Path(filename)
        if path.is_file():
            try:
                kept_lines: list[str] = list()
                original_total_lines = 0
                with open(filename, 'r') as my_file:
                    for line in my_file:
                        original_total_lines += 1
                        if line:
                            keep_line = True
                            if line.startswith(OBJECT_SHARED):
                                for model in used_shared_models:
                                    if model in line:
                                        keep_line = False
                                        break
                            if keep_line:
                                kept_lines.append(line)
                with open(filename, 'w') as my_file:
                    for entry in kept_lines:
                        my_file.write(entry)
                logging.info('Removed %i shared models out of original %i entries in %s',
                             original_total_lines - len(kept_lines), original_total_lines, filename)
            except IOError as reason:
                logging.warning("Problem in file %s - ignoring: %s", reason)


def _get_all_shared_models_used() -> list[str]:
    shared_models: list[str] = list()
    for attr in dir(sm):
        attr_value = getattr(sm, attr)
        if isinstance(attr_value, str):  # we do not want e.g. function objects
            if attr.startswith('__'):  # Python built-in stuff
                continue
            elif attr_value.endswith('/'):  # directory entries
                continue
            shared_models.append(attr_value)
    return shared_models
