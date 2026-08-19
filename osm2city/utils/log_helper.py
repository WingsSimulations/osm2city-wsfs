# SPDX-FileCopyrightText: (C) 2018 - 2019, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later
import logging


def log_level_info_or_lower():
    return logging.getLogger().level <= logging.INFO


def log_level_debug_or_lower():
    return logging.getLogger().level <= logging.DEBUG
