# SPDX-FileCopyrightText: (C) 2023, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later

import enum
import logging
import os
import os.path as osp
import sys
from typing import Optional


DEFAULT_ENV_PARAMS = {
    'O2C_OVERPASS_API': 'https://overpass-api.de/api/interpreter',
    'O2C_OVERPASS_MAX_RETRIES': '3',
    'O2C_OVERPASS_RETRY_DELAY': '2.0',
    'O2C_OVERPASS_RETRY_BACKOFF_FACTOR': '1.5',
    'O2C_OVERPASS_CONNECT_TIMEOUT': '10',
    'O2C_OVERPASS_READ_TIMEOUT': '60',
}

def get_env_parameter(name: str, default: Optional[str] = None) -> str:
    """Reads the environment variable based on a name.
    If it is not set, use default dictionary or provided default, otherwise log error and exit.
    """
    my_env_param = os.getenv(name)
    if my_env_param is None:
        if default is not None:
            return default
        if name in DEFAULT_ENV_PARAMS:
            return DEFAULT_ENV_PARAMS[name]
        logging.error("%s must be set as an environment variable on operating system level", name)
        sys.exit(1)
    my_env_param = my_env_param.strip()
    logging.debug("{} is set to value '{}'".format(name, my_env_param))
    return my_env_param


@enum.unique
class OSType(enum.IntEnum):
    windows = 1
    linux = 2
    mac = 3
    other = 4


def get_os_type() -> OSType:
    if sys.platform.startswith("win"):
        return OSType.windows
    elif sys.platform.startswith("linux"):
        return OSType.linux
    elif sys.platform.startswith("darwin"):
        return OSType.mac
    else:
        return OSType.other


def is_linux_or_mac() -> bool:
    my_os_type = get_os_type()
    if my_os_type is OSType.linux or my_os_type is OSType.mac:
        return True
    return False


def get_fg_home() -> Optional[str]:
    """Constructs the path to FGHome.

    See also https://wiki.flightgear.org/$FG_HOME
    If the operating system cannot be determined, the function returns None.
    Otherwise, a platform-specific path.
    """
    home_dir = osp.expanduser("~")
    my_os_type = get_os_type()
    if my_os_type is OSType.windows:
        home = os.getenv("APPDATA", "APPDATA_NOT_FOUND") + os.sep + "flightgear.org" + os.sep
        return home.replace("\\", "/")
    elif my_os_type is OSType.linux:
        return home_dir + "/.fgfs/"
    elif my_os_type is OSType.mac:
        return home_dir + "/Library/Application Support/FlightGear/"
    else:
        return None
