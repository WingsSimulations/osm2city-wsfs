# SPDX-FileCopyrightText: (C) 2025, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later

"""Different types for better type safety and to make stuff more explicit.

Different modules can still define their own types, but then they
shall not be used across module boundaries.
"""
from typing import NewType

OSMId = NewType('OSMId', int)

OSMTags = NewType('OSMTags', dict[str, str])
