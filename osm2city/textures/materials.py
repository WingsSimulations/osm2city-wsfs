# SPDX-FileCopyrightText: (C) 2018 - 2026, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later
"""This module is about AC3D materials and OSM colours as well as OSM materials.

A material in AC3D is a kind of colour, and its definition can be found at https://www.inivis.com/resources.html.
MATERIAL (name) rgb %f %f %f  amb %f %f %f  emis %f %f %f  spec %f %f %f  shi %d  trans %f

Single line describing a material.  These are referenced by the "mat"
token of a surface.  The first "MATERIAL" in the file will be indexed as
zero.

Cf. https://wiki.openstreetmap.org/wiki/Key:material for use of materials in OSM.


In OSM "colour" instead of "color" is used in tagging - with a preference for British English spelling.
See https://wiki.openstreetmap.org/wiki/Key:colour.

osm2city only supports the following two keys (cf. method screen_osm_keys_for_colour_spelling(...)):
* building:colour
* roof:colour

"""
from enum import IntEnum, unique
import math
import unittest

from osm2city.static_types import osmstrings as s
from osm2city.static_types import types as t


def screen_tag_values_for_grey_spelling(original: str) -> str:
    """Handles variants for spelling for grey."""
    new_string = original.lower()
    if 'gray' in new_string:
        new_string = new_string.replace('gray', s.V_GREY)
    if '_grey' in new_string:  # e.g. light_grey
        new_string = new_string.replace('_grey', s.V_GREY)
    if ' grey' in new_string:  # e.g. light grey
        new_string = new_string.replace(' grey', s.V_GREY)
    return new_string


_OSM_VALID_COLOUR_KEYS = [s.K_BUILDING_COLOUR, s.K_ROOF_COLOUR]


_OSM_MATERIAL_KEY_MAPPING = [
    ('building:color', s.K_BUILDING_COLOUR),
    ('building:facade:color', s.K_BUILDING_COLOUR),
    ('building:facade:colour', s.K_BUILDING_COLOUR),
    ('wall:colour', s.K_BUILDING_COLOUR),
    ('wall:color', s.K_BUILDING_COLOUR),
    ('building:colour_1', s.K_BUILDING_COLOUR),
    ('roof:color', s.K_ROOF_COLOUR),
    ('building:roof:color', s.K_ROOF_COLOUR),
    ('building:roof:colour', s.K_ROOF_COLOUR),
    ('roof:colour_1', s.K_ROOF_COLOUR),
    ('building:facade:material', s.K_BUILDING_MATERIAL),
    ('building:roof:material', s.K_ROOF_MATERIAL)
]


def screen_osm_keys_for_colour_material_variants(tags: t.OSMTags) -> None:
    """Makes sure colour and material are spelled correctly in the key and reduced to known keys in osm2city.
    And for the correct ones it makes sure that the values are recognizable."""
    for wrong, correct in _OSM_MATERIAL_KEY_MAPPING:
        if wrong in tags:
            if correct not in tags:
                tags[correct] = tags[wrong]
            del (tags[wrong])
    for valid_key in _OSM_VALID_COLOUR_KEYS:
        if valid_key in tags:
            tags[valid_key] = screen_tag_values_for_grey_spelling(tags[valid_key])
            tags[valid_key] = _map_hex_colour_to_colour_name(tags[valid_key])


_COLOUR_NAME_TO_HEX_MAP: dict[str, str] = {
    # See https://www.w3.org/TR/css-color-3/#html4 16 basic colours.
    s.V_BLACK: '#000000',
    s.V_SILVER: '#C0C0C0',
    s.V_GREY: '#808080',
    s.V_WHITE: '#FFFFFF',
    s.V_MAROON: '#800000',
    s.V_RED: '#FF0000',
    s.V_PURPLE: '#800080',
    s.V_FUCHSIA: '#FF00FF',
    s.V_GREEN: '#008000',
    s.V_LIME: '#00FF00',
    s.V_OLIVE: '#808000',
    s.V_YELLOW: '#FFFF00',
    s.V_NAVY: '#000080',
    s.V_BLUE: '#0000FF',
    s.V_TEAL: '#008080',
    s.V_AQUA: '#00FFFF',
    # Additionally, named colours most used cf. https://taginfo.openstreetmap.org/keys/building%3Acolour#values,
    # and https://taginfo.openstreetmap.org/keys/roof%3Acolour#values
    # for colour card see https://www.w3.org/TR/css-color-3/#svg-color
    s.V_BROWN: '#A52A2A',
    s.V_BEIGE: '#F5F5DC',
    s.V_LIGHTGREY: '#D3D3D3',
    s.V_ORANGE: '#FFA500',
    s.V_LIGHTYELLOW: '#FFFFE0',
    s.V_SNOW: '#FFFAFA',
    s.V_FIREBRICK: '#B22222',
    s.V_PINK: '#FFC0CB',
    s.V_TAN: '#D2B48C',
    s.V_WHEAT: '#F5DEB3',
    s.V_LIGHTBLUE: '#ADD8E6',
    s.V_FLORALWHITE: '#FFFAF0',
    s.V_MOCCASIN: '#FFE4B5',
    s.V_GOLD: '#FFD700',
    s.V_SALMON: '#FA8072',
    s.V_DARKGREY: '#A9A9A9',
    s.V_DARKSALMON: '#E9967A',
    s.V_DIMGREY: '#696969',
    s.V_LIGHTSALMON: '#FFA07A',
    s.V_DARKRED: '#8B0000',
    s.V_INDIANRED: '#CD5C5C',
    s.V_ORANGERED: '#FF4500',
    s.V_DARKGREEN: '#006400'
}

for a_value in _COLOUR_NAME_TO_HEX_MAP.values():
    assert len(a_value) == 7, f"Hex value must be 7 characters long: {a_value!r}"
    assert a_value[0] == '#', f"Hex value must start with '#': {a_value!r}"
    assert a_value[1:].isalnum(), f"Hex value must contain only alphanumeric characters: {a_value!r}"
    assert a_value[1:].upper() == a_value[1:], f"Hex value must be uppercase due to later dependencies: {a_value!r}"


_COLOUR_HEX_TO_NAME_MAP: dict[str, str] = dict()
for o_key, o_value in _COLOUR_NAME_TO_HEX_MAP.items():
    assert o_value not in _COLOUR_HEX_TO_NAME_MAP, f"Duplicate value in colour original dict: {o_value!r}"
    _COLOUR_HEX_TO_NAME_MAP[o_value] = o_key


def _hex_to_rgb(hex_colour: str) -> tuple[int, int, int]:
    """Converts a hex colour value to a tuple of three integers in the range 0-255."""
    hex_colour = hex_colour.lstrip("#")
    return int(hex_colour[0:2], 16), int(hex_colour[2:4], 16), int(hex_colour[4:6], 16)


_COLOUR_NAME_TO_RGB_MAP: dict[str, tuple[int, int, int]] = {}
for o_key, o_value in _COLOUR_NAME_TO_HEX_MAP.items():
    _COLOUR_NAME_TO_RGB_MAP[o_key] = _hex_to_rgb(o_value)


def _colour_distance(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))


def _map_hex_colour_to_colour_name(value: str) -> str:
    value = value.strip().upper()
    if value.find("#") == 0 and len(value) == 7:
        found = _COLOUR_HEX_TO_NAME_MAP.get(value)
        if found:
            return found
        # now try to find a similar colour by using a simple RGB colour distance metric
        target_rgb: tuple[int, int, int] = _hex_to_rgb(value)
        minimum_dist: float = math.inf
        closest_colour_name: str | None = None
        for colour_name, rgb_tuple in _COLOUR_NAME_TO_RGB_MAP.items():
            dist = _colour_distance(rgb_tuple, target_rgb)
            if dist < minimum_dist:
                minimum_dist = dist
                closest_colour_name = colour_name
        if closest_colour_name:
            return closest_colour_name
    return value


def is_known_colour_name(colour_name: str) -> bool:
    return colour_name in _COLOUR_NAME_TO_HEX_MAP


def _map_osm_colour_value_to_hex(colour_value: str, default_colour: str) -> str:
    """Maps a colour value from OSM to a hex colour value.

    If the value cannot be interpreted or is not known, then a default colour passed as parameter is used.
    """
    if colour_value.lower() in _COLOUR_NAME_TO_HEX_MAP:
        return _COLOUR_NAME_TO_HEX_MAP[colour_value]

    if colour_value.upper() in _COLOUR_HEX_TO_NAME_MAP:
        return colour_value.upper()

    # nothing worked
    return _COLOUR_NAME_TO_HEX_MAP[default_colour].upper()


def _transform_hex_colour_into_rgb_values(hex_colour: str) -> list[int]:
    value = hex_colour.lstrip('#')
    return [int(value[i:i + 2], 16) for i in range(0, 6, 2)]


def map_osm_colour_value_to_int_rgb_values(colour_value: str, default_colour: str) -> list[int]:
    return _transform_hex_colour_into_rgb_values(_map_osm_colour_value_to_hex(colour_value, default_colour))


# amb has to be 1 1 1 no matter the colour when textures are involved
_MATERIAL_FORMAT = ('MATERIAL "{0}" rgb {1:05.3f} {2:05.3f} {3:05.3f} amb {4:05.3f} {5:05.3f} {6:05.3f} '
                    'emis 0 0 0 spec 0.0 0.0 0.0 shi {7} trans 0')


def _create_material(name: str, red: float, green: float, blue: float, shi: int,
                     ambient_as_colour: bool) -> str:
    """Creates a material line in AC3D format.
    See also https://wiki.flightgear.org/AC_files:_Basic_changes_to_textures_and_colors#Textures.

    A fabric like cloth might have a shi like 32, whereas polished steel might have > 100.
    If something does not get a texture, then ambient should be like the colour.
    """
    if ambient_as_colour:
        return _MATERIAL_FORMAT.format(name, red, green, blue, red, green, blue, shi)
    return _MATERIAL_FORMAT.format(name, red, green, blue, 1., 1., 1., shi)

@unique
class Material(IntEnum):
    """Defines all available materials with the value being the index in a list.

    The list is defined in the method 'create_materials_list' below and needs to be in sync.
    """
    unlit = 0
    lit = 1
    cable = 2
    facade = 3  # and roofs


def create_materials_list() -> list[str]:
    materials_list = list()
    materials_list.append(_create_material(Material.unlit.name, 0., 0., 0., 0, False))
    materials_list.append(_create_material(Material.lit.name, 1., 1., 1., 0, False))
    materials_list.append(_create_material(Material.cable.name, .3, .3, .3, 100, True))
    materials_list.append(_create_material(Material.facade.name, 1., 1., 1., 0, False))
    return materials_list


# ================ UNITTESTS =======================

class TestMaterials(unittest.TestCase):

    def test_screen_osm_keys_for_colour_material_variants(self):
        my_tags = t.OSMTags({'foo': '1', 'building:color': 'red', 'building:colour': 'blue', 'building:roof:material': 'stone'})
        screen_osm_keys_for_colour_material_variants(my_tags)
        self.assertEqual(3, len(my_tags), '# of element reduced to 3')
        self.assertEqual('blue', my_tags[s.K_BUILDING_COLOUR], 'original key/value preserved')
        self.assertEqual('stone', my_tags[s.K_ROOF_MATERIAL], 'original key replaced and value preserved')

    def test_map_osm_colour_value_to_hex(self):
        self.assertEqual(_map_osm_colour_value_to_hex('lightgrey', s.V_YELLOW),
                         _COLOUR_NAME_TO_HEX_MAP[s.V_LIGHTGREY], 'Direct name mapping')
        self.assertEqual(_map_osm_colour_value_to_hex(_COLOUR_NAME_TO_HEX_MAP[s.V_LIGHTGREY],  s.V_YELLOW),
                         _COLOUR_NAME_TO_HEX_MAP[s.V_LIGHTGREY], 'Valid hex with #')
        self.assertEqual(_map_osm_colour_value_to_hex('',  s.V_YELLOW), _COLOUR_NAME_TO_HEX_MAP[s.V_YELLOW], 'Empty')
        self.assertEqual(_map_osm_colour_value_to_hex('x',  s.V_YELLOW), _COLOUR_NAME_TO_HEX_MAP[s.V_YELLOW], 'Not valid')

    def test_transform_hex_colour_int_rgb_values(self):
        self.assertEqual(0, _transform_hex_colour_into_rgb_values('#000000')[0], 'black')
        self.assertEqual(255, _transform_hex_colour_into_rgb_values('ffffff')[0], 'white without #')

    def test_map_hex_colour_to_colour_name(self):
        self.assertEqual(_map_hex_colour_to_colour_name(_COLOUR_NAME_TO_HEX_MAP[s.V_LIGHTGREY]), s.V_LIGHTGREY, 'Good mapping')
        self.assertEqual(_map_hex_colour_to_colour_name('#000001'), '#000001', 'Not know value')
        self.assertEqual(_map_hex_colour_to_colour_name(s.V_LIGHTGREY), s.V_LIGHTGREY, 'Not a hex')

    def test_screen_tag_values_for_grey_spelling(self):
        self.assertEqual(screen_tag_values_for_grey_spelling('grey'), s.V_GREY,  'No change')
        self.assertEqual(screen_tag_values_for_grey_spelling('gray'), s.V_GREY,  'Gray to grey')
        self.assertEqual(screen_tag_values_for_grey_spelling('light_gray'), s.V_LIGHTGREY,  'light_gray to lightgrey')
        self.assertEqual(screen_tag_values_for_grey_spelling('light grey'), s.V_LIGHTGREY,  'light grey to lightgrey')
