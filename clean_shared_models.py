# SPDX-FileCopyrightText: (C) 2024 - 2026, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later

import argparse
import logging
import sys

from osm2city import parameters
from osm2city.utils import utilities as u
from osm2city.utils import stg_io2

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="removes most types of shared objects from a scenery \
    based on a lon/lat defined area")
    parser.add_argument("-f", "--file", dest="filename",
                        help="Read parameters from FILE (e.g. params.ini)", metavar="FILE", required=True)
    parser.add_argument("-b", "--boundary", dest="boundary",
                        help="set the boundary as WEST_SOUTH_EAST_NORTH like *9.1_47.0_11_48.8 (. as decimal)",
                        required=True)

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    parameters.read_from_file(args.filename)

    try:
        boundary_floats = u.parse_boundary(args.boundary)
    except u.BoundaryError as be:
        logging.error(be.message)
        sys.exit(1)

    boundary_west = boundary_floats[0]
    boundary_south = boundary_floats[1]
    boundary_east = boundary_floats[2]
    boundary_north = boundary_floats[3]
    logging.info("Overall boundary {}, {}, {}, {}".format(boundary_west, boundary_south, boundary_east, boundary_north))

    stg_io2.clean_stg_entries_for_shared_models_in_boundary(boundary_west, boundary_south,
                                                            boundary_east, boundary_north)
