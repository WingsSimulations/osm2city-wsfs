# SPDX-FileCopyrightText: (C) 2015 - 2020, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later
"""Road texture coordinates in osm2city-data/tex/roads.png"""
TRACK = (0/8., 1/8.)  # railway
ROAD_1 = (1/8., 2/8.)  # no stripes in middle of road
ROAD_2 = (2/8., 3/8.)  # with strips in middle of road
BRIDGE_1 = (3/8., 4/8.)
EMBANKMENT_1 = (4/8., 5/8.)
ROAD_3 = (5/8., 6/8.)  # motorway like (but no hard shoulder)
EMBANKMENT_2 = (6/8., 7/8.)
TRAMWAY = (7/8., 8/8.)

BOTTOM = (4/8.-0.05, 4/8.)

# texture length in meters
# 2 lanes * 4m per lane = 128 px wide. 512px long = 32 m
#                Autobahnen      Andere Straßen
# Schmalstrich   0,15 m          0,12 m
# Breitstrich    0,30 m          0,25 m
# Leitlinie Schmalstrich, 3m innerorts, 6m BAB. Verhältnis Strich:Lücke = 1:2
LENGTH = 32.
