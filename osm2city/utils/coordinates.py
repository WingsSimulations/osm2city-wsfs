# SPDX-FileCopyrightText: (C) 2013 - 2026, rick@vanosten.net, radi, portree_kid
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Transform global (aka geodetic) coordinates to a local cartesian, in meters.
A flat earth approximation (https://williams.best.vwh.net/avform.htm) seems good
enough if distances are up to a few km.

Created on Sat Jun 7 22:38:59 2014
@author: albrecht

# https://williams.best.vwh.net/avform.htm
# Local, flat earth approximation
# If you stay in the vicinity of a given fixed point (lat0,lon0), it may be a 
# good enough approximation to consider the earth as "flat", and use a North,
# East, Down rectangular coordinate system with origin at the fixed point. If
# we call the changes in latitude and longitude dlat=lat-lat0, dlon=lon-lon0 
# (Here treating North and East as positive!), then
#
#       distance_North=R1*dlat
#       distance_East=R2*cos(lat0)*dlon
#
# R1 and R2 are called the meridional radius of curvature and the radius of 
# curvature in the prime vertical, respectively.
#
#      R1=a(1-e^2)/(1-e^2*(sin(lat0))^2)^(3/2)
#      R2=a/sqrt(1-e^2*(sin(lat0))^2)
#
# a is the equatorial radius of the earth (=6378.137000km for WGS84), and
# e^2=f*(2-f) with the flattening f=1/298.257223563 for WGS84.
#
# In the spherical model used elsewhere in the Formulary, R1=R2=R, the earth's
# radius. (using R=1 we get distances in radians, using R=60*180/pi distances are in nm.)
#
# In the flat earth approximation, distances and bearings are given by the
# usual plane trigonometry formulae, i.e:
#
#    distance = sqrt(distance_North^2 + distance_East^2)
#    bearing to (lat,lon) = mod(atan2(distance_East, distance_North), 2*pi)
#                        (= mod(atan2(cos(lat0)*dlon, dlat), 2*pi) in the spherical case)
#
# These approximations fail in the vicinity of either pole and at large 
# distances. The fractional errors are of order (distance/R)^2.

"""

from math import asin, atan2, sin, cos, sqrt, radians, degrees, pi, fabs
import logging
import unittest

import numpy as np

import pyproj
from pyproj.enums import TransformDirection


class Vec2d(object):
    """A simple 2d vector class. Supports basic arithmetics."""

    def __init__(self, x, y=None):
        if y is None:
            if len(x) != 2:
                raise ValueError('Need exactly two values to create Vec2d from list.')
            y = x[1]  # -- Yes, we need to process y first.
            x = x[0]
        self.x = x
        self.y = y

    @property
    def lon(self):
        return self.x

    @lon.setter
    def lon(self, value):
        self.x = value

    @property
    def lat(self):
        return self.y

    @lat.setter
    def lat(self, value):
        self.y = value

    def __getitem__(self, key):
        return (self.x, self.y)[key]

    def __fixtype(self, other):
        if isinstance(other, type(self)):
            return other
        return Vec2d(other, other)

    def __add__(self, other):
        other = self.__fixtype(other)
        return Vec2d(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        other = self.__fixtype(other)
        return Vec2d(self.x - other.x, self.y - other.y)

    def __mul__(self, other):
        other = self.__fixtype(other)
        return Vec2d(self.x * other.x, self.y * other.y)

    def __floordiv__(self, other):
        other = self.__fixtype(other)
        return Vec2d(self.x // other.x, self.y // other.y)

    def __str__(self):
        return "%1.7f %1.7f" % (self.x, self.y)

    def __neg__(self):
        return Vec2d(-self.x, -self.y)

    def __abs__(self):
        return Vec2d(abs(self.x), abs(self.y))

    def sign(self):
        return Vec2d(np.sign((self.x, self.y)))

    def __lt__(self, other):
        return Vec2d(self.x < other.x, self.y < other.y)

    def list(self):
        print("deprecated call to Vec2d.list(). Iterate instead.")
        return self.x, self.y

    def as_array(self):
        """return as numpy array"""
        return np.array((self.x, self.y))

    def __iter__(self):
        yield (self.x)
        yield (self.y)

    def swap(self):
        return Vec2d(self.y, self.x)

    def int(self):
        return Vec2d(int(self.x), int(self.y))

    def distance_to(self, other):
        d = self - other
        return (d.x ** 2 + d.y ** 2) ** 0.5

    def magnitude(self):
        return (self.x ** 2 + self.y ** 2) ** 0.5

    def normalize(self):
        mag = self.magnitude()
        self.x /= mag
        self.y /= mag

    def rot90ccw(self):
        return Vec2d(-self.y, self.x)

    def atan2(self):
        return atan2(self.y, self.x)


NAUTICAL_MILES_METERS = 1852

# from WGS84. See simgear/math/SGGeodesy.cxx
EQURAD = 6378137.0
FLATTENING = 298.257223563
SQUASH = 0.9966471893352525192801545

E2 = fabs(1 - SQUASH * SQUASH)
RA2 = 1 / (EQURAD * EQURAD)
E4 = E2 * E2


class Transformation(object):
    """Global <-> local coordinate system transformation, using flat earth approximation

    See also:
    https://wiki.flightgear.org/Geographic_Coordinate_Systems

    PROJ supports a number of projections (cf. https://proj.org/en/9.4/operations/projections/index.html), e.g.:
    "aeqd": Azimuthal Equidistant
    "tmerc": Transverse Mercator
    "merc": Mercator
    "stere": Stereographic
    "lcc": Lambert Conformal Conic
    "utm": Universal Transverse Mercator (UTM)
    "cass": Cassini-Soldner
    "laea": Lambert Azimuthal Equal Area
    "moll": Mollweide
    "robin": Robinson
    "sinu": Sinusoidal
    "cea": Cylindrical Equal Area
    "gnom": Gnomonic
    "eqc": Equidistant Cylindrical (Plate Carrée)
    "omerc": Oblique Mercator

    Tests have been made at Lelystad station in the Netherlands. The station is in the South-East corner of a
    tile and therefore a good candidate to test alignment with WS3.0 roads/railways etc.
    * UTM projection has been tested with very bad results, but maybe using +k_0=0.9996 would have given better
      results.
    * laea has given better results than aeqd. Still, there is an offset relative to rails/roads of ca. 1 m in
      North/South direction and 1 m in East/West direction.
    """
    def __init__(self, boundary_west: float, boundary_south: float,
                 boundary_east: float, boundary_north: float, tile_index: int,
                 use_approximation: bool = False):
        cmin = Vec2d(boundary_west, boundary_south)
        cmax = Vec2d(boundary_east, boundary_north)
        self.tile_index = tile_index  # for convenience but not used in transformation
        mid_point = (cmin + cmax) * 0.5
        self._lon = mid_point.lon
        self._lat = mid_point.lat
        self._trans_proj = None
        self._proj_mid_x = 0.
        self._proj_mid_y = 0.
        self._approximation = use_approximation
        if self._approximation:
            self._set_approximation_fields()
        else:
            crs_wgs = pyproj.Proj('epsg:4326')  # assuming you're using WGS84 geographic
            local_projection = pyproj.Proj("+proj=laea +lon_0={0} +lat_0={1} +ellps=WGS84 +units=m".format(self._lon,
                                                                                                           self._lat))
            self._trans_proj = pyproj.Transformer.from_proj(crs_wgs, local_projection, always_xy=True)
            self._proj_mid_x, self._proj_mid_y = self._trans_proj.transform(self._lon, self._lat, radians=False)
            logging.info(local_projection.definition)

    @classmethod
    def create_zero_zero_transformation(cls):
        return Transformation(0., 0., 0.125, 0.125, 2954880)

    @property
    def anchor(self) -> Vec2d:
        return Vec2d(self._lon, self._lat)

    @property
    def anchor_local(self) -> Vec2d:
        x, y = self.to_local((self._lon, self._lat))
        return Vec2d(x, y)

    @property
    def cos_lat_factor(self) -> float:
        return self._coslat

    def _set_approximation_fields(self):
        """compute radii for local origin"""
        f = 1. / FLATTENING
        e2 = f * (2.-f)

        self._coslat = cos(radians(self._lat))
        sinlat = sin(radians(self._lat))
        self._R1 = EQURAD * (1.-e2)/(1.-e2*(sinlat**2))**(3./2.)
        self._R2 = EQURAD / sqrt(1-e2*sinlat**2)

    def to_local(self, coord_tuple: tuple[float, float]) -> tuple[float, float]:
        """transform global -> local coordinates"""
        (lon, lat) = coord_tuple
        if self._approximation:
            y = self._R1 * radians(lat - self._lat)
            x = self._R2 * radians(lon - self._lon) * self._coslat
        else:
            x, y = self._trans_proj.transform(lon, lat, radians=False)
            x -= self._proj_mid_x
            y -= self._proj_mid_y
        return x, y

    def to_global(self, coord_tuple: tuple[float, float]) -> tuple[float, float]:
        """transform local -> global coordinates"""
        (x, y) = coord_tuple
        if self._approximation:
            lat = degrees(y / self._R1) + self._lat
            lon = degrees(x / (self._R2 * self._coslat)) + self._lon
        else:
            lon, lat = self._trans_proj.transform(x + self._proj_mid_x, y + self._proj_mid_y,
                                                  radians=False, direction=TransformDirection.INVERSE)
        return lon, lat

    def __str__(self):
        return "(%f %f)" % (self._lon, self._lat)


class Vec3d(object):
    """A simple 3d object"""
    __slots__ = ('x', 'y', 'z')

    def __init__(self, x: float, y: float, z: float) -> None:
        self.x = x  # or lon
        self.y = y  # or lat
        self.z = z  # or height

    @staticmethod
    def dot(first: 'Vec3d', other: 'Vec3d') -> float:
        return first.x * other.x + first.y * other.y + first.z * other.z

    @staticmethod
    def cross(first: 'Vec3d', other: 'Vec3d') -> 'Vec3d':
        # (a1, a2, a3) X (b1, b2, b3) = (a2*b3-a3*b2, a3*b1-a1*b3, a1*b2-a2*b1)
        x = first.y * other.z - first.z * other.y
        y = first.z * other.x - first.x * other.z
        z = first.x * other.y - first.y * other.x
        return Vec3d(x, y, z)

    def multiply(self, multiplier: float) -> None:
        self.x *= multiplier
        self.y *= multiplier
        self.z *= multiplier

    def add(self, other: 'Vec3d') -> None:
        self.x += other.x
        self.y += other.y
        self.z += other.z

    def subtract(self, other: 'Vec3d') -> None:
        self.x -= other.x
        self.y -= other.y
        self.z -= other.z

    def to_local(self, transformer: Transformation) -> None:
        """Translates to local coordinate system."""
        self.x, self.y = transformer.to_local((self.x, self.y))
        # nothing to do for z

    def __copy__(self) -> 'Vec3d':
        return Vec3d(self.x, self.y, self.z)


def cart_to_geod(center: Vec3d) -> tuple[float, float, float]:
    """Converts a cartesian point to geodetic coordinates. Returns lon, lat in radians and elevation in meters
    See SGGeodesy::SGCartToGeod in simgear/math/SGGeodesy.cxx

    Description in simgear/math/SGGeod.hxx:
    Factory to convert position from a cartesian position assumed to be in wgs84 measured in meters
    Note that this conversion is relatively expensive to compute
    """
    xx_p_yy = center.x * center.x + center.y * center.y
    if xx_p_yy + center.z * center.z < 25.:
        return 0.0, 0.0, -EQURAD

    sqrt_xx_p_yy = sqrt(xx_p_yy)
    p = xx_p_yy * RA2
    q = center.z * center.z * (1 - E2) * RA2
    r = 1 / 6.0 * (p + q - E4)
    s = E4 * p * q / (4 * r * r * r)
    if -2.0 <= s <= 0.0:
        s = 0.0

    t = pow(1 + s + sqrt(s * (2 + s)), 1 / 3.0)
    u = r * (1 + t + 1 / t)
    v = sqrt(u * u + E4 * q)
    w = E2 * (u + v - q) / (2 * v)
    k = sqrt(u + v + w * w) - w
    d = k * sqrt_xx_p_yy / (k + E2)
    lon_rad = 2 * atan2(center.y, center.x + sqrt_xx_p_yy)
    sqrt_dd_p_zz = sqrt(d * d + center.z * center.z)
    lat_rad = 2 * atan2(center.z, d + sqrt_dd_p_zz)
    elev = (k + E2 - 1) * sqrt_dd_p_zz / k
    return lon_rad, lat_rad, elev


def cartesian_to_gltf_in_fgfs(x_cart: float, y_cart: float, z_cart: float) -> tuple[float, float, float]:
    """Convert cartesian coordinates (East, North, Up) to glTF so it fits the FlightGears coordinate system.

    If only cartesian to glTF would be done, then additional rotation and roll would be needed in stg-entries.

    Input cartesian system:
    x_cart: East-West (positive = East)
    y_cart: North-South (positive = North)
    z_cart: Elevation (positive = up)
    """
    x_gltf = -y_cart
    y_gltf = x_cart
    z_gltf = z_cart

    return x_gltf, y_gltf, z_gltf


def cartesian_to_uv(x_cart: float, y_cart: float) -> tuple[float, float]:
    """Convert cartesian texture coordinates (right, up) to glTF uv coordinates (down, right).

    Input cartesian system:
    x_cart: Left-Right (positive = Right)
    y_cart: Button-Up (positive = Up)

    Output UV coordinate system:
    U-axis: Points right (horizontal, positive = rightward)
    V-axis: Points down (vertical, positive = downward)

    I.e. This means the origin (0,0) is in the bottom-left corner of the texture, and coordinates go from (0,0) to (1,1)
    with (1,1) being in the bottom-right corner.

    Therefore, there is only a slight conversion needed.
    """
    u = x_cart
    v = 1. - y_cart
    return u, v


def calc_angle_of_line_local(x1: float, y1: float, x2: float, y2: float) -> float:
    """Returns the angle in degrees of a line relative to North.
    Based on local coordinates (x,y) of two points.
    """
    angle = atan2(x2 - x1, y2 - y1)
    degree = degrees(angle)
    return normal_degrees(degree)


def calc_point_angle_away(x: float, y: float, added_distance: float, angle: float) -> tuple[float, float]:
    new_x = x + added_distance * sin(radians(angle))
    new_y = y + added_distance * cos(radians(angle))
    return new_x, new_y


def calc_point_on_line_local(x1: float, y1: float, x2: float, y2: float, factor: float) -> tuple[float, float]:
    """Returns the x,y coordinates of a point along the line defined by the input coordinates factor away from first.
    """
    angle = calc_angle_of_line_local(x1, y1, x2, y2)
    length = calc_distance_local(x1, y1, x2, y2) * factor

    x_diff = sin(radians(angle)) * length
    y_diff = cos(radians(angle)) * length
    return x1 + x_diff, y1 + y_diff


def calc_angle_of_corner_local(prev_point_x: float, prev_point_y: float,
                               corner_point_x: float, corner_point_y,
                               next_point_x: float, next_point_y) -> float:
    """The angle seen from the corner looking at the prev_point and then the next point - normalized between 0-180"""
    first_angle = calc_angle_of_line_local(corner_point_x, corner_point_y, prev_point_x, prev_point_y)
    second_angle = calc_angle_of_line_local(corner_point_x, corner_point_y, next_point_x, next_point_y)
    final_angle = fabs(first_angle - second_angle)
    if final_angle > 180:
        final_angle = 360 - final_angle
    return final_angle


def calc_delta_bearing(bearing1: float, bearing2: float) -> float:
    """Calculates the difference between two bearings. If positive with clock, if negative against the clock sense.

    I.e. from bearing1 to bearing2 you need to turn delta with or against the clock."""
    if bearing1 == 360.:
        bearing1 = 0.
    if bearing2 == 360.:
        bearing2 = 0.
    delta = bearing2 - bearing1

    if delta > 180:
        delta = delta - 360
    elif delta < -180:
        delta = 360 + delta

    return delta


def calc_distance_local(x1, y1, x2, y2):
    """Returns the distance between two points based on local coordinates (x,y)."""
    return sqrt(pow(x1 - x2, 2) + pow(y1 - y2, 2))


def calc_distance_global(lon1, lat1, lon2, lat2):
    lon1_r = radians(lon1)
    lat1_r = radians(lat1)
    lon2_r = radians(lon2)
    lat2_r = radians(lat2)
    distance_radians = calc_distance_global_radians(lon1_r, lat1_r, lon2_r, lat2_r)
    return distance_radians * ((180 * 60) / pi) * NAUTICAL_MILES_METERS


def calc_distance_global_radians(lon1_r, lat1_r, lon2_r, lat2_r):
    return 2*asin(sqrt(pow(sin((lat1_r-lat2_r)/2), 2) + cos(lat1_r)*cos(lat2_r)*pow(sin((lon1_r-lon2_r)/2), 2)))


def calc_angle_of_line_global(lon1: float, lat1: float, lon2: float, lat2: float,
                              transformation: Transformation) -> float:
    x1, y1 = transformation.to_local((lon1, lat1))
    x2, y2 = transformation.to_local((lon2, lat2))
    return calc_angle_of_line_local(x1, y1, x2, y2)


def disjoint_bounds(bounds_1: tuple[float, float, float, float], bounds_2: tuple[float, float, float, float]) -> bool:
    """Returns True if the two input bounds are disjoint. False otherwise.
    Bounds are Shapely (minx, miny, maxx, maxy) tuples (float values) that bounds the object -> geom.bounds.
    """
    try:
        x_overlap = bounds_1[0] <= bounds_2[0] <= bounds_1[2] or bounds_1[0] <= bounds_2[2] <= bounds_1[2] or \
            bounds_2[0] <= bounds_1[0] <= bounds_2[2] or bounds_2[0] <= bounds_1[2] <= bounds_2[2]
        y_overlap = bounds_1[1] <= bounds_2[1] <= bounds_1[3] or bounds_1[1] <= bounds_2[3] <= bounds_1[3] or \
            bounds_2[1] <= bounds_1[1] <= bounds_2[3] or bounds_2[1] <= bounds_1[3] <= bounds_2[3]
        if x_overlap and y_overlap:
            return False
        return True
    except IndexError:
        logging.exception('Something wrong with the tuples in input')
        logging.warning('bounds_1 has %i values, bounds_2 has %i values', len(bounds_1), len(bounds_2))
        return True


def calc_horizon_elev_local(point_x: float, point_y: float) -> float:
    """Calculates how much a given point a distance away is elevated over the round world.
    The world is flat in an ac-mesh. Therefore, a correction elevation needs to be calculated,
    such that the mesh looks draped over the round Earth.
    """
    horizontal_dist_square = point_x ** 2 + point_y ** 2
    shorter = sqrt(EQURAD**2 - horizontal_dist_square)
    return EQURAD - shorter


def normal_degrees(degree: float) -> float:
    """Makes sure that degrees are between 0 and 360."""
    if degree < 0:
        return degree + 360
    elif degree >= 360:
        return degree - 360
    return degree


def calc_angle_of_longest_edge(pts: list[tuple[float, float]]) -> float:
    """For a set of points find the longest edge and then calculate the angle relative to North"""
    longest_edge_length = 0
    angle = 0.
    for i in range(len(pts) - 1):
        my_edge_length = ((pts[i + 1][0] - pts[i][0]) ** 2 +
                          (pts[i + 1][1] - pts[i][1]) ** 2) ** 0.5
        if my_edge_length > longest_edge_length:
            longest_edge_length = my_edge_length
            angle = calc_angle_of_line_local(pts[i][0], pts[i][1],
                                             pts[i + 1][0], pts[i + 1][1])
    return angle


# ================ UNITTESTS =======================


class TestCoordinates(unittest.TestCase):
    def test_calc_angle_of_line_local(self):
        self.assertEqual(0, calc_angle_of_line_local(0, 0, 0, 1), "North")
        self.assertEqual(90, calc_angle_of_line_local(0, 0, 1, 0), "East")
        self.assertEqual(180, calc_angle_of_line_local(0, 1, 0, 0), "South")
        self.assertEqual(270, calc_angle_of_line_local(1, 0, 0, 0), "West")
        self.assertEqual(45, calc_angle_of_line_local(0, 0, 1, 1), "North East")
        self.assertEqual(315, calc_angle_of_line_local(1, 0, 0, 1), "North West")
        self.assertEqual(225, calc_angle_of_line_local(1, 1, 0, 0), "South West")

    def test_calc_angle_of_line_global(self):
        tf = Transformation.create_zero_zero_transformation()
        # need to be a bit more cautious here, because the angle can be slightly less than 360 degrees
        self.assertLess(abs(calc_delta_bearing(0., calc_angle_of_line_global(1, 46, 1, 47, tf))), 1.)
        self.assertAlmostEqual(90., calc_angle_of_line_global(1, -46, 2, -46, tf), delta=0.5)  # "East"
        self.assertAlmostEqual(180., calc_angle_of_line_global(-1, -33, -1, -34, tf), delta=0.5)  # "South"
        self.assertAlmostEqual(270., calc_angle_of_line_global(-29, 0, -29.2, 0, tf), delta=0.5)  # "West"
        self.assertAlmostEqual(45., calc_angle_of_line_global(0, 0, 1, 1, tf), delta=0.5)  # "North East"
        self.assertAlmostEqual(315., calc_angle_of_line_global(1, 0, 0, 1, tf), delta=0.5)  # "North West"
        self.assertAlmostEqual(225., calc_angle_of_line_global(1, 1, 0, 0, tf), delta=0.5)  # "South West"

    def test_calc_distance_local(self):
        self.assertEqual(5, calc_distance_local(0, -1, -4, 2))

    def test_calc_distance_global(self):
        self.assertAlmostEqual(NAUTICAL_MILES_METERS * 60., calc_distance_global(1, 46, 1, 47), delta=10)
        self.assertAlmostEqual(NAUTICAL_MILES_METERS * 60., calc_distance_global(1, -33, 1, -34), delta=10)
        self.assertAlmostEqual(NAUTICAL_MILES_METERS * 60., calc_distance_global(1, 0, 2, 0), delta=10)
        self.assertAlmostEqual(NAUTICAL_MILES_METERS * 60. * sqrt(2), calc_distance_global(1, 0, 2, 1), delta=10)

    def test_disjoint_bounds(self):
        bounds_1 = (0, 0, 10, 10)
        bounds_2 = (2, 2, 8, 8)
        self.assertFalse(disjoint_bounds(bounds_1, bounds_2), 'Within 1-2')
        self.assertFalse(disjoint_bounds(bounds_2, bounds_1), 'Within 2-1')

        bounds_2 = (10, 10, 20, 20)
        self.assertFalse(disjoint_bounds(bounds_1, bounds_2), 'Touch 1-2')
        self.assertFalse(disjoint_bounds(bounds_2, bounds_1), 'Touch 2-1')

        bounds_2 = (0, 20, 20, 30)
        self.assertTrue(disjoint_bounds(bounds_1, bounds_2), 'Disjoint 1-2')
        self.assertTrue(disjoint_bounds(bounds_2, bounds_1), 'Disjoint 2-1')

    def test_calc_angle_of_corner_local(self):
        self.assertAlmostEqual(180., calc_angle_of_corner_local(-1., 0., 0., 0., 1., 0.), 2)
        self.assertAlmostEqual(180., calc_angle_of_corner_local(1, 0, 0, 0, -1, 0), 2)

        self.assertAlmostEqual(90., calc_angle_of_corner_local(1, 0, 0, 0, 0, 1), 2)
        self.assertAlmostEqual(90., calc_angle_of_corner_local(0, 1, 0, 0, 1, 0), 2)

        self.assertAlmostEqual(90., calc_angle_of_corner_local(1, 0, 0, 0, 0, -1), 2)
        self.assertAlmostEqual(90., calc_angle_of_corner_local(0, -1, 0, 0, 1, 0), 2)

        self.assertAlmostEqual(45., calc_angle_of_corner_local(1, 0, 0, 0, 1, 1), 2)
        self.assertAlmostEqual(45., calc_angle_of_corner_local(1, 1, 0, 0, 1, 0), 2)

        self.assertAlmostEqual(135., calc_angle_of_corner_local(-1, 0, 0, 0, 1, 1), 2)
        self.assertAlmostEqual(135., calc_angle_of_corner_local(1, 1, 0, 0, -1, 0), 2)

        self.assertAlmostEqual(45., calc_angle_of_corner_local(-1, 1, 0, 0, 0, 1), 2)
        self.assertAlmostEqual(45., calc_angle_of_corner_local(-1, 1, 0, 0, -1, 0), 2)

    def test_calc_delta_bearing(self):
        bearing1 = 0.
        bearing2 = 0.
        self.assertEqual(0., calc_delta_bearing(bearing1, bearing2), 'No difference 0')

        bearing1 = 0.
        bearing2 = 360.
        self.assertEqual(0., calc_delta_bearing(bearing1, bearing2), 'No difference 0/360')

        bearing1 = 360.
        bearing2 = 0.
        self.assertEqual(0., calc_delta_bearing(bearing1, bearing2), 'No difference 360/0')

        bearing1 = 20
        bearing2 = 200
        self.assertEqual(180., fabs(calc_delta_bearing(bearing1, bearing2)), '180 degrees')

        bearing1 = 10
        bearing2 = 20
        self.assertEqual(10., calc_delta_bearing(bearing1, bearing2), '10 with clock')

        bearing1 = 20
        bearing2 = 10
        self.assertEqual(-10., calc_delta_bearing(bearing1, bearing2), '10 against clock')

        bearing1 = 350
        bearing2 = 10
        self.assertEqual(20., calc_delta_bearing(bearing1, bearing2), 'Through 0: 20 with clock')

        bearing1 = 10
        bearing2 = 350
        self.assertEqual(-20., calc_delta_bearing(bearing1, bearing2), 'Through 0: 20 against clock')

    def test_calc_point_on_line_local(self):
        # straight up
        x, y = calc_point_on_line_local(0, 1, 0, 2, 0.5)
        self.assertAlmostEqual(0., x)
        self.assertAlmostEqual(1.5, y)
        x, y = calc_point_on_line_local(0, 1, 0, 2, 2.0)
        self.assertAlmostEqual(0., x)
        self.assertAlmostEqual(3., y)
        # straight down
        x, y = calc_point_on_line_local(1, -1, 1, -2, 0.5)
        self.assertAlmostEqual(1., x)
        self.assertAlmostEqual(-1.5, y)
        # straight right
        x, y = calc_point_on_line_local(1, -1, 2, -1, 0.5)
        self.assertAlmostEqual(1.5, x)
        self.assertAlmostEqual(-1., y)
        # straight left
        x, y = calc_point_on_line_local(-1, 1, -2, 1, 0.5)
        self.assertAlmostEqual(-1.5, x)
        self.assertAlmostEqual(1., y)
        # 45 degrees
        x, y = calc_point_on_line_local(1, 1, 2, 2, 2.)
        self.assertAlmostEqual(3., x)
        self.assertAlmostEqual(3., y)
        # straight right with negative value
        x, y = calc_point_on_line_local(1, -1, 2, -1, -1)
        self.assertAlmostEqual(0., x)
        self.assertAlmostEqual(-1., y)

    def test_calc_horizon_elev_local(self):
        elev_1 = calc_horizon_elev_local(2000, 2000)
        elev_2 = calc_horizon_elev_local(1000, 1000)
        self.assertGreater(elev_1, elev_2)
