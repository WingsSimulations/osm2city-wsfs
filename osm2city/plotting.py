# SPDX-FileCopyrightText: (C) 2024 - 2024, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later

from random import randint

import shapely.geometry as shg

import osm2city.static_types.osmstrings as s
import osm2city.static_types.types as t
import osm2city.utils.coordinates as co
import osm2city.utils.osmparser as op
import osm2city.utils.plot_utilities as pu
import osm2city.utils.utilities as u


LINEAR_NORMAL_STROKE_WIDTH = 4
LINEAR_BOLD_STROKE_WIDTH = 10


def _create_file_name(tile_index: int, process_name: str) -> str:
    return 'osm2city_plot_{}_{}_{}.svg'.format(process_name, tile_index, u.date_time_now())


def _create_svg_start(transform: co.Transformation) -> str:
    start = '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n<!-- Created by osm2city -->\n'
    start += '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
    bounds = pu.get_tile_bounds_local(transform)
    start += 'viewBox="{:.0f} {:.0f} {:.0f} {:.0f}"> \n'.format(bounds[0], bounds[1], bounds[2], bounds[3])
    return start


def _svg_style_for_line(colour: str, stroke_width: int = 3) -> str:
    return 'fill="none" stroke="{}" stroke-width="{}"'.format(colour, stroke_width)


def _svg_points_from_wkt_points(wkt_points: str) -> str:
    positions: list[str] = wkt_points.split(', ')
    points: list[str] = list()
    for position in positions:
        xy = position.split(' ')
        points.append('{:-.2f},{:-.2f}'.format(float(xy[0]), -1. * float(xy[1])))
    return ' '.join(points)


def _svg_points_from_wkt_line_string(line_string: shg.LineString) -> str:
    """
    Returns the points list from a WKT LineString converted to the SVG format.
    WKT representation of a LineString: 'LINESTRING (5713.183698669695 -5031.722835297676,
                                                     5713.479284156193 -5023.232030950962,
                                                     ...)'
    SVG equivalent:
    <polyline points="0,0 50,150 100,75 150,50 200,140 250,140"
              style="fill:none;stroke:green;stroke-width:3" />
    """
    wkt_string = line_string.wkt
    clipped = wkt_string[12:len(wkt_string) - 1]
    return _svg_points_from_wkt_points(clipped)


def _svg_points_from_wkt_polygon(polygon: shg.Polygon) -> list[str]:
    """
    Returns the points list from a WKT Polygon converted to the SVG format.
    WKT representation of a Polygon: POLYGON ((3587.648292944284 -3932.020173622564,
                                               3504.193146217626 -3917.8516418950358,
                                               ...),
                                               (...), ...)
    """
    ring_separator = '), ('
    wkt_string = polygon.wkt
    clipped = wkt_string[10:len(wkt_string) - 2]
    points_list: list[str] = list()
    if clipped.find(ring_separator) < 0:
        points_list.append(_svg_points_from_wkt_points(clipped))
    else:
        while True:
            position = clipped.find(ring_separator)
            if position < 0:
                break
            token = clipped[0:position]
            points_list.append(_svg_points_from_wkt_points(token))
            clipped = clipped[position + len(ring_separator)]
    return points_list


def _create_random_rgb_colour() -> str:
    return 'rgb({},{},{})'.format(randint(0, 255), randint(0, 255), randint(0, 255))


def _svg_polyline_from_points_and_styles(points: str, style_attributes: str) -> str:
    return '<polyline points="{}" {} />'.format(points, style_attributes)


def _svg_polygons_from_points(points: list[str]) -> list[str]:
    polygon_strings: list[str] = list()
    for index, point_string in enumerate(points):
        colour = 'white' if index > 0 else 'yellow'
        polygon_strings.append('<polygon points="{}" fill="{}" stroke-width="0" />'.format(point_string, colour))
    return polygon_strings


def _write_svg_file(object_lines: list[str], process_name: str,
                    tile_index: int, transform: co.Transformation) -> None:

    file_name = _create_file_name(tile_index, process_name)
    with open(file_name, 'w') as f:
        f.write(_create_svg_start(transform))
        for object_line in object_lines:
            f.write('{}\n'.format(object_line))
        f.write('</svg>\n')


def _draw_linear_objects_by_type(ways_list: list[op.Way],
                                 transform: co.Transformation, nodes_dict: dict[t.OSMId, op.Node],
                                 tile_index: int) -> None:
    random_rail_poly_lines: list[str] = list()
    random_roads_poly_lines: list[str] = list()
    type_poly_lines: list[str] = list()
    for way in ways_list:
        line_string = way.line_string_from_osm_way(nodes_dict, transform)
        if line_string:
            points = _svg_points_from_wkt_line_string(line_string)
            stroke_width = LINEAR_NORMAL_STROKE_WIDTH
            if s.is_bridge(way.tags):
                stroke_width = LINEAR_BOLD_STROKE_WIDTH

            # all lines as random colours to se where start / stop
            style_attributes = _svg_style_for_line(_create_random_rgb_colour(), stroke_width)
            if s.is_railway(way.tags):
                random_rail_poly_lines.append(_svg_polyline_from_points_and_styles(points, style_attributes))
            else:
                random_roads_poly_lines.append(_svg_polyline_from_points_and_styles(points, style_attributes))

            # type
            if s.is_railway(way.tags):
                if s.is_bridge(way.tags):
                    colour = 'purple'
                else:
                    colour = 'fuchsia'
            else:
                if s.is_bridge(way.tags):
                    colour = 'navy'
                else:
                    colour = 'blue'
            style_attributes = _svg_style_for_line(colour, stroke_width)
            type_poly_lines.append(_svg_polyline_from_points_and_styles(points, style_attributes))

    _write_svg_file(random_rail_poly_lines, 'railways_random', tile_index, transform)
    _write_svg_file(random_roads_poly_lines, 'roads_random', tile_index, transform)
    _write_svg_file(type_poly_lines, 'line_type', tile_index, transform)


def _draw_blocked_areas_with_linear_objects(ways_list: list[op.Way], blocked_areas: list[shg.Polygon],
                                            transform: co.Transformation, nodes_dict: dict[t.OSMId, op.Node],
                                            tile_index: int) -> None:
    object_lines: list[str] = list()
    # draw the blocked areas
    for blocked_area in blocked_areas:
        points = _svg_points_from_wkt_polygon(blocked_area)
        object_lines.extend(_svg_polygons_from_points(points))

    # draw the linear objects on top, so we could see if one crosses a blocked area
    for way in ways_list:
        line_string = way.line_string_from_osm_way(nodes_dict, transform)
        if line_string:
            points = _svg_points_from_wkt_line_string(line_string)
            stroke_width = LINEAR_NORMAL_STROKE_WIDTH
            if s.is_bridge(way.tags):
                stroke_width = LINEAR_BOLD_STROKE_WIDTH
            if s.is_railway(way.tags):
                if s.is_bridge(way.tags):
                    colour = 'purple'
                else:
                    colour = 'fuchsia'
            else:
                if s.is_bridge(way.tags):
                    colour = 'navy'
                else:
                    colour = 'blue'
            style_attributes = _svg_style_for_line(colour, stroke_width)
            object_lines.append(_svg_polyline_from_points_and_styles(points, style_attributes))

    _write_svg_file(object_lines, 'blocked_areas', tile_index, transform)


def draw_roads(ways_list: list[op.Way], blocked_areas: list[shg.Polygon],
               transform: co.Transformation, nodes_dict: dict[t.OSMId, op.Node],
               tile_index: int) -> None:
    _draw_linear_objects_by_type(ways_list, transform, nodes_dict, tile_index)
    _draw_blocked_areas_with_linear_objects(ways_list, blocked_areas, transform, nodes_dict, tile_index)
