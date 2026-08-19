# SPDX-FileCopyrightText: (C) 2025, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later

"""A custom unittest runner, where unittest classes are added manually.

This is because the unittests are within modules, such that module internal methods (_do_something())
do not have to be made public.
"""

import unittest

import build_tiles

from osm2city import linear, linear_transportation, parameters, pylons, roofs
from osm2city.static_types import osmstrings
from osm2city.textures import materials
from osm2city.utils import calc_tile, coordinates, gltf_io, osmparser, utilities


def _create_test_suite_for_root():
    """All modules with unit tests in the package root."""
    suite = unittest.TestSuite()

    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(build_tiles.TestProcedures))

    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(linear.TestLinear))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(linear_transportation.TestLinearTransportation))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(parameters.TestParameters))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(pylons.TestPylons))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(roofs.TestRoofs))

    return suite


def _create_test_suite_for_utils():
    """All modules with unit tests in the utils folder."""
    suite = unittest.TestSuite()

    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(calc_tile.TestCalcTile))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(coordinates.TestCoordinates))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(gltf_io.TestGeometryCollector3D))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(osmparser.TestOSMParser))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(utilities.TestUtilities))

    return suite


def _create_test_suite_for_textures():
    """All modules with unit tests in the utils folder."""
    suite = unittest.TestSuite()

    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(materials.TestMaterials))

    return suite


def _create_test_suite_for_static_types():
    """All modules with unit tests in the utils folder."""
    suite = unittest.TestSuite()

    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(osmstrings.TestOSMStrings))

    return suite


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(_create_test_suite_for_root())
    runner.run(_create_test_suite_for_utils())
    runner.run(_create_test_suite_for_textures())
    runner.run(_create_test_suite_for_static_types())
