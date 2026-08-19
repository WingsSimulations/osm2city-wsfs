# SPDX-FileCopyrightText: (C) 2016 - 2026, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Diverse utility methods used throughout osm2city and not having a clear other home.
"""
from collections import defaultdict
import datetime
import logging
import math
import os
import random
import sys
import time
from typing import Any
import unittest

import numpy as np
from shapely import affinity
import shapely.geometry as shg
from shapely.geometry import Polygon
from shapely.ops import unary_union

import osm2city.static_types.types as t
import osm2city.utils.coordinates as co
import osm2city.utils.osmparser as op
from osm2city import parameters


def date_time_now() -> str:
    """Date and time as of now formatted as a string incl. seconds."""
    today = datetime.datetime.now()
    return today.strftime("%Y-%m-%d_%H%M%S")


def replace_with_os_separator(path: str) -> str:
    """Switches forward and backward slash depending on os."""
    my_string = path.replace("/", os.sep)
    my_string = my_string.replace("\\", os.sep)
    return my_string


def match_local_coords_with_global_nodes(local_list: list[tuple[float, float]], ref_list: list[t.OSMId],
                                         all_nodes: dict[t.OSMId, op.Node],
                                         coords_transform: co.Transformation, osm_id: t.OSMId,
                                         create_node: bool = False) -> list[t.OSMId]:
    """Given a set of coordinates in local space find matching Node objects in global space.
    Matching is using a bit of tolerance (cf. parameter), which should be enough to account for conversion precision
    resp. float precision.
    If a node cannot be matched: if parameter create_node is False, then a ValueError is thrown - else a new
    Node is created and added to the all_nodes dict.
    """
    matched_nodes = list()
    nodes_local = dict()  # key is osm_id from Node, value is tuple[float, float]
    for ref in ref_list:
        node = all_nodes[ref]
        nodes_local[node.osm_id] = coords_transform.to_local((node.lon, node.lat))

    for local in local_list:
        closest_distance = 999999
        found_key = -1
        for key, node_local in nodes_local.items():
            distance = co.calc_distance_local(local[0], local[1], node_local[0], node_local[1])
            if distance < closest_distance:
                closest_distance = distance
            if distance < parameters.TOLERANCE_MATCH_NODE:
                found_key = key
                break
        if found_key < 0:
            if create_node:
                lon, lat = coords_transform.to_global(local)
                new_node = op.Node(op.get_next_pseudo_osm_id(op.OSMFeatureType.building_relation), lat, lon)
                all_nodes[new_node.osm_id] = new_node
                matched_nodes.append(new_node.osm_id)
            else:
                raise ValueError('No match for parent with osm_id = %d. Closest: %f' % (osm_id, closest_distance))
        else:
            matched_nodes.append(found_key)

    return matched_nodes


class BoundaryError(Exception):
    """Indicates wrong values to define the boundary of the scenery."""
    def __init__(self, message: str) -> None:
        self.message = message


def parse_boundary(boundary_string: str) -> list[float] | None:
    """Parses the boundary argument provided as an underscore-delimited string into 4 floats for lon/lat.

    Raises BoundaryError if it cannot be parsed into 4 floats.
    Or raised BoundaryError if called function check_boundary raises it.
    """
    boundary_parts = boundary_string.replace("*", "").split("_")
    if len(boundary_parts) != 4:
        message = "Boundary must have four elements separated by '_': {} has only {} element(s) \
        -> aborting!".format(boundary_string, len(boundary_parts))
        raise BoundaryError(message)

    boundary_float_list = list()
    for i in range(len(boundary_parts)):
        try:
            boundary_float_list.append(float(boundary_parts[i]))
        except ValueError as my_value_error:
            message = "Boundary part {} cannot be parsed as float (decimal)".format(boundary_parts[i])
            raise BoundaryError(message) from my_value_error

    check_boundary(boundary_float_list[0], boundary_float_list[1], boundary_float_list[2], boundary_float_list[3])

    return boundary_float_list


def check_boundary(boundary_west: float, boundary_south: float,
                   boundary_east: float, boundary_north: float) -> None:
    """Check whether the boundary values actually make sense.

    Raise BoundaryError if there is a problem.
    """
    if boundary_west >= boundary_east:
        raise BoundaryError("Boundary West {} must be smaller than East {} -> aborting!".format(boundary_west,
                                                                                                boundary_east))
    if boundary_south >= boundary_north:
        raise BoundaryError("Boundary South {} must be smaller than North {} -> aborting!".format(boundary_south,
                                                                                                  boundary_north))
    # make sure that we are within safe latitude for calculations
    # in FG when tile span more than 1 deg it can get tricky -> http://wiki.flightgear.org/Tile_Index_Scheme
    # For most map projection the farther to the north the more tricky.
    if boundary_north > 83 or math.fabs(boundary_south) > 83:
        raise BoundaryError('Latitudes must be max 83.0 N / 83.0 S')

    # Due to workaround for FGElev cf. https://sourceforge.net/p/flightgear/codetickets/2657/
    # We need to be able to be sure that for each tile we can pre-calculate the L3 subtile.
    # Therefore, no boundaries > abs(76)
    if boundary_north > 76 or math.fabs(boundary_south) > 76:
        raise BoundaryError('For WS3.0 latitudes must be max 76.0 N / 76.0 S')


def bounds_from_list(bounds_list: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    """Finds the bounds (min_x, min_y, max_x, max_y) from a list of bounds.

    If the list of bounds is None or empty, then (0,0,0,0) is returned."""
    if not bounds_list:
        return 0, 0, 0, 0

    min_x = sys.float_info.max
    min_y = sys.float_info.max
    max_x = sys.float_info.min
    max_y = sys.float_info.min

    for bounds in bounds_list:
        min_x = min(min_x, bounds[0])
        min_y = min(min_y, bounds[1])
        max_x = max(max_x, bounds[2])
        max_y = max(max_y, bounds[3])

    return min_x, min_y, max_x, max_y


def random_value_from_ratio_dict_parameter(ratio_parameter: dict[Any, float]):
    target_ratio = random.random()
    return value_from_ratio_dict_parameter(target_ratio, ratio_parameter)


def value_from_ratio_dict_parameter(target_ratio: float, ratio_parameter: dict[Any, float]):
    """Finds the key value closet to and below the target ratio."""
    total_ratio = 0.
    return_value = None
    for key, ratio in ratio_parameter.items():
        if target_ratio <= total_ratio:
            return return_value
        return_value = key
        total_ratio += ratio
    return return_value


def time_logging(message: str, last_time: float) -> float:
    current_time = time.time()
    logging.info(message + ": %f", current_time - last_time)
    return current_time


def minimum_circumference_rectangle_for_polygon(hull: shg.Polygon) -> tuple[float, float, float]:
    """Constructs a minimum circumference rectangle around a polygon and returns its angle, length and width
    There is no check whether length is longer than width - or that length is closer to e.g. the x-axis.

    This is different from a bounding box, which just uses min/max along axis.
    See https://gis.stackexchange.com/questions/22895/finding-minimum-area-rectangle-for-given-points

    Circumference is used as opposed to typically area because often buildings tend to be less quadratic.

    The general idea is that at least one edge of the polygon will be aligned with an edge of the rectangle.
    Therefore Go through all edges of the polygon, rotate it down to normal axis, create a bounding box and
    save the dimensions incl. angle. Then compare with others obtained.

    Often the polygon is a convex hull for points. In osm2city it might be the convex hull of a building.

    A different algorithm also discussed in the article referenced above is using m matrix multiplication instead
    of trigonometrics.

    For an overview see also: David Eberly, 2015: Minimum-Area Rectangle Containing A Set of Points.
    www.geometrictools.com
    """
    min_angle = 0.
    min_length = 0.
    min_width = 0.
    min_circumference = 99999999.
    hull_coords = hull.exterior.coords[:]  # list of x,y tuples
    for index in range(len(hull_coords) - 1):
        angle = co.calc_angle_of_line_local(hull_coords[index][0], hull_coords[index][1],
                                            hull_coords[index + 1][0], hull_coords[index + 1][1])
        rotated_hull = affinity.rotate(hull, - angle, (0, 0))
        bounding_box = rotated_hull.bounds  # tuple x_min, y_min, x_max, y_max
        bb_length = math.fabs(bounding_box[2] - bounding_box[0])
        bb_width = math.fabs(bounding_box[3] - bounding_box[1])
        circumference = 2 * (bb_length + bb_width)
        if circumference < min_circumference:
            min_angle = angle
            if bb_length >= bb_width:
                min_length = bb_length
                min_width = bb_width
                min_angle += 90  # it happens to be such that the angle is against the y-axis
            else:
                min_length = bb_width
                min_width = bb_length
            min_circumference = circumference

    return min_angle, min_length, min_width


def fit_offsets_for_rectangle_with_hull(angle: float, hull: shg.Polygon, model_length: float, model_width: float,
                                        model_length_offset: float, model_width_offset: float,
                                        model_length_largest: bool,
                                        model_name: str, osm_id: t.OSMId) -> tuple[float, float]:
    """Makes sure that a rectangle (bounding box) on a convex hull fits as good as possible and returns centroid.

    This is necessary because the angle out of function minimum_circumference_rectangle_for_polygon(...) cannot be
    known whether it should have been +/- 180 degrees (depends on which point in hull gets started with at least
    if the hull was a rectangle to begin with).

    NB: length_largest could also be calculated on the fly, but is chosen to be consistent with caller in building_lib.
    """
    # if both the length and width offsets are null, then the centroid will always be the hull's centroid
    if model_length_offset == 0 and model_width_offset == 0:
        return hull.centroid.x, hull.centroid.y

    # need to correct the offsets based on whether the model has longer length or width
    my_length = model_length
    my_width = model_width
    my_length_offset = model_length_offset
    my_width_offset = model_width_offset
    if not model_length_largest:
        my_length = model_width
        my_width = model_length
        my_length_offset = model_width_offset
        my_width_offset = model_length_offset

    box = shg.box(-my_length/2, -my_width/2, my_length/2, my_width/2)
    box = affinity.rotate(box, angle)
    box = affinity.translate(box, hull.centroid.x, hull.centroid.y)

    # need to correct along x-axis and y-axis due to offsets in the ac-model
    correction_x = math.sin(angle) * my_length_offset
    correction_x += math.cos(angle) * my_width_offset
    correction_y = math.cos(angle) * my_length_offset
    correction_y += math.sin(angle) * my_width_offset

    box_minus = affinity.translate(box, -correction_x, -correction_y)
    difference_minus = box_minus.difference(hull)
    box_plus = affinity.translate(box, correction_x, correction_y)
    difference_plus = box_plus.difference(hull)

    new_x = hull.centroid.x - correction_x
    new_y = hull.centroid.y - correction_y
    if difference_minus.area > difference_plus.area:
        new_x = hull.centroid.x + correction_x
        new_y = hull.centroid.y + correction_y

    if parameters.DEBUG_PLOT_OFFSETS:
        plot_fit_offsets(hull, box_minus, box_plus, angle, model_length_largest,
                         new_x, new_y, model_name, osm_id)

    return new_x, new_y


def calc_lighting_params(min_h: float, max_h: float, min_v: float, max_v: float) -> tuple[float, float, float,
                                                                                          float, float]:
    """Calculate parameters for shader lights based on horizontal and vertical directed light.

    See extracts from Fahim Dalvi's e-mail Sep 1 2021 on flightgear-devel:

    Let us assume that I want a light to be like follows:
    * At lon=12.5, lat=56.125, elev=10.0
    * visible 30 degree below horizon up to 45 degrees over the horizon
    * visible from 70 degrees to 110 degrees on a compass
       => What values would I put for <normal-x>, <normal-y>, <normal-z>,
          <horizontal-angle> and <vertical-angle>

    (Visible from 70 degrees to 110 degrees on a compass” is interpreted as the light shines in the direction of 70
     to 110 degrees, so anyone in that cone will be able to see the light.)

    This is in spherical coordinates: https://motionscript.com/mastering-expressions/img/spherical-coords.gif.

    In this case, the -X is north (i.e. 0 degrees on the compass rose), +Y is east (90 degrees), and Z is the
    vertical axis. And the compass rose sits flush on the XY plane. What you want to do is get the vector that is at
    the centre of your light. In you case, that would be the line from the light to 7.5 degrees from the horizon
    vertically (centre of 45 and -30) and 90 degrees on the compass rose (centre of 70 and 110).
    Using the equations, we get:

    normal-x = 0.0
    normal-y = 0.99144
    normal-z = 0.13053
    horizontal-angle = 40 degrees (110-70)
    vertical-angle = 75 degrees (45 - (-30))
    """
    h = min_h + (max_h - min_h)/2
    v = -90 + min_v + (max_v - min_v)/2

    r = 1  # Unit length vector

    x = -1 * r * math.sin(math.radians(v)) * math.cos(math.radians(h))
    y = -1 * r * math.sin(math.radians(v)) * math.sin(math.radians(h))
    z = r * math.cos(math.radians(v))
    return x, y, z, max_h - min_h, max_v - min_v


def merge_buffers(original_list: list[Polygon]) -> list[Polygon]:
    """Attempts to merge as many polygon buffers with each other as possible to return a reduced list.
    The try/catch are needed due to maybe issues in Shapely with huge amounts of polys.
    See https://github.com/Toblerity/Shapely/issues/47. Seen problems with BTG-data, but then in the slow method
    actually no poly got discarded."""
    # first make sure that the polygons merged are actually good polygons
    cleaned_list = list()
    for poly in original_list:
        if poly is None or poly.is_empty or poly.is_valid is False:
            continue
        cleaned_list.append(poly)

    if len(cleaned_list) < 2:
        return cleaned_list

    multi_polygon = cleaned_list[0]
    try:
        multi_polygon = unary_union(cleaned_list)
    except ValueError:  # No Shapely geometry can be created from null value
        for other_poly in cleaned_list[1:]:  # let's do it slowly one at a time
            try:
                new_multi_polygon = unary_union(other_poly)
                multi_polygon = new_multi_polygon
            except ValueError:
                pass  # just forget about this one polygon
    if isinstance(multi_polygon, Polygon):
        return [multi_polygon]

    handled_list = list()
    if multi_polygon is not None:
        for polygon in multi_polygon.geoms:
            if isinstance(polygon, Polygon):
                handled_list.append(polygon)
            else:
                logging.debug("Unary union of transport buffers resulted in an object of type %s instead of Polygon",
                              type(polygon))
    return handled_list


# ================ PLOTTING FOR VISUAL TESTING =====

import osm2city.utils.plot_utilities as pu
from descartes import PolygonPatch
from matplotlib import patches as pat

from time import sleep


def plot_fit_offsets(hull: shg.Polygon, box_minus: shg.Polygon, box_plus: shg.Polygon,
                     angle: float,
                     model_length_largest: bool,
                     centroid_x: float, centroid_y: float,
                     model_name: str, osm_id: t.OSMId) -> None:
    pdf_pages = pu.create_pdf_pages('fit_offset_' + str(osm_id))

    my_figure = pu.create_a4_landscape_figure()
    title = 'osm_id={},\n model={},\n angle={},\n length_largest={}'.format(osm_id, model_name, angle,
                                                                            model_length_largest)
    my_figure.suptitle(title)

    ax = my_figure.add_subplot(111)

    patch = PolygonPatch(hull, facecolor='none', edgecolor="black")
    ax.add_patch(patch)
    patch = PolygonPatch(box_minus, facecolor='none', edgecolor="green")
    ax.add_patch(patch)
    patch = PolygonPatch(box_plus, facecolor='none', edgecolor="red")
    ax.add_patch(patch)
    ax.add_patch(pat.Circle((centroid_x, centroid_y), radius=0.4, linewidth=2,
                            color='blue', fill=False))
    bounds = bounds_from_list([box_minus.bounds, box_plus.bounds])
    pu.set_ax_limits_bounds(ax, bounds)

    pdf_pages.savefig(my_figure)

    pdf_pages.close()

    sleep(2)  # to make sure we have not several files in same second


class Stats(object):
    def __init__(self):
        self.objects = 0
        self.parse_errors = 0
        self.skipped_small = 0
        self.skipped_nearby = 0
        self.skipped_texture = 0
        self.skipped_no_elev = 0
        self.buildings_in_LOD = np.zeros(3)
        self.area_levels = np.array([1, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000])
        self.corners = np.zeros(10)
        self.area_above = np.zeros_like(self.area_levels)
        self.vertices = 0
        self.surfaces = 0
        self.roof_shapes = {}
        self.have_complex_roof = 0
        self.roof_errors = 0
        self.out = None
        self.LOD = np.zeros(3)
        self.nodes_simplified = 0
        self.nodes_roof_simplified = 0
        self.nodes_ground = 0
        self.random_buildings = 0
        self.textures_total = defaultdict(int)
        self.textures_used = None

    def count(self, b):
        """update stats (vertices, surfaces, area, corners) with given building's data
        """
        if b.roof_shape.name in self.roof_shapes:
            self.roof_shapes[b.roof_shape.name] += 1
        else:
            self.roof_shapes[b.roof_shape.name] = 1

        # -- stats on number of ground nodes.
        #    Complex buildings counted in corners[0]
        if b.pts_inner:
            self.corners[0] += 1
        else:
            self.corners[min(b.pts_outer_count, len(self.corners) - 1)] += 1

        # --stats on area
        for i in range(len(self.area_levels))[::-1]:
            if b.area >= self.area_levels[i]:
                self.area_above[i] += 1
                return i
        self.area_above[0] += 1

        return 0

    def count_LOD(self, lod):
        self.LOD[lod] += 1

    def count_texture(self, texture):
        self.textures_total[str(texture.filename)] += 1


# ================ UNITTESTS =======================

class TestUtilities(unittest.TestCase):
    def test_parse_boundary_empty_string(self):
        with self.assertRaises(BoundaryError):
            parse_boundary("")

    def test_parse_boundary_three_floats(self):
        with self.assertRaises(BoundaryError):
            parse_boundary("1.1_1.2_1.2")

    def test_parse_boundary_one_not_float(self):
        with self.assertRaises(BoundaryError):
            parse_boundary("1.1_1.2_1.2_a")

    def test_parse_boundary_pass(self):
        self.assertEqual(parse_boundary("1.1_-1.2_1.2_1.2"), [1.1, -1.2, 1.2, 1.2])

    def check_boundary_east_west_wrong(self):
        with self.assertRaises(BoundaryError):
            check_boundary(2, 1, 1, 2)

    def check_boundary_south_north_wrong(self):
        with self.assertRaises(BoundaryError):
            check_boundary(-2, 1, 1, -2)

    def check_boundary_pass(self):
        self.assertEqual(None, check_boundary(-2, -3, 1, -2))

    def test_value_from_ratio_dict_parameter(self):
        ratio_parameter = {1: 0.2, 2: 0.3, 3: 0.5}
        self.assertEqual(1, value_from_ratio_dict_parameter(0.1, ratio_parameter))
        self.assertEqual(1, value_from_ratio_dict_parameter(0.2, ratio_parameter))
        self.assertEqual(2, value_from_ratio_dict_parameter(0.3, ratio_parameter))
        self.assertEqual(2, value_from_ratio_dict_parameter(0.5, ratio_parameter))
        self.assertEqual(3, value_from_ratio_dict_parameter(1., ratio_parameter))
