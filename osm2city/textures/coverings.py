# SPDX-FileCopyrightText: (C) 2025-2026, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later

"""Coverings are a combination of textures and materials to be used in glTF."""
from dataclasses import dataclass
from enum import IntEnum
import logging
import random
import re

from osm2city import parameters
import osm2city.static_types.enumerations as enu
import osm2city.static_types.osmstrings as s
import osm2city.static_types.types as t
from osm2city.textures.materials import screen_tag_values_for_grey_spelling
import osm2city.utils.utilities as u


# ================================= COLOURS ===========================================


class RGBAColour:
    """A colour in RGBA format."""
    __slots__ = ('r', 'g', 'b', 'a')

    def __init__(self, r: float, g: float, b: float) -> None:
        self.r: float = r
        self.g: float = g
        self.b: float = b
        self.a: float = 1.  # do not use transparent colours in osm2city due to performance issues
        self._validate()

    def _validate(self) -> None:
        """Validate that all colour components are in the valid range [0.0, 1.0]."""
        assert 0.0 <= self.r <= 1.0, f'Colour component red must be between 0.0 and 1.0'
        assert 0.0 <= self.g <= 1.0, f'Colour component green must be between 0.0 and 1.0'
        assert 0.0 <= self.b <= 1.0, f'Colour component blue must be between 0.0 and 1.0'
        assert 0.0 <= self.a <= 1.0, f'Colour component alpha must be between 0.0 and 1.0'

    def as_list(self) -> list[float]:
        return [self.r, self.g, self.b, self.a]


_COLOUR_DEFAULT: RGBAColour = RGBAColour(1.0, 1.0, 1.0)  # white


# If possible, use HTML-named colours - see e.g. https://htmlcolorcodes.com/color-names/
COLOUR_LIGHT_GREY: RGBAColour = RGBAColour(211/255, 211/255, 211/255)
COLOUR_DIM_GREY: RGBAColour = RGBAColour(105/255, 105/255, 105/255)


# ================================= TEXTURES ==========================================

class CoveringTexture:
    """The physical file of a texture."""
    __slots__ = ('name', 'image_path', 'width', 'height')

    def __init__(self, name: str, image_path: str, width: int, height: int) -> None:
        self.name: str = name
        self.image_path: str = image_path
        self.width: int = width
        self.height: int = height

_tex_asphalt = CoveringTexture('tex_asphalt', 'Textures/Terrain/asphalt.png', 128, 128)

_tex_default_atlas = CoveringTexture('default_atlas', 'Textures/osm2city/atlas_facades.png', 256, 16348)

_tex_roads_atlas = CoveringTexture('roads_atlas', 'Textures/osm2city/roads.png', 1024, 512)


# ================================= MATERIALS =========================================


class CoveringMaterial:
    """A material to prepare for glTF export.

    metallic_factor (property metallicFactor in PbrMetallicRoughness)


    - 0.0 - 1.0 = Blended behaviour (usually avoided - use 0.0 or 1.0)

    - 0.0 = Non-metal (dielectric)**
        - Plastics, wood, concrete, fabric, skin, etc.
        - Base colour represents diffuse color
        - Reflections are typically white/colourless
        - Some light penetrates and scatters

    - 1.0 = Pure metal
        - Iron, gold, silver, copper, aluminium, etc.
        - Base colour represents reflection color
        - No diffuse scattering (all reflection)
        - Colored reflections based on base colour

    | Material | Typical Metallic Factor |
    | --- | --- |
    | Gold, Silver, Copper | 1.0 |
    | Steel, Iron, Aluminium | 1.0 |
    | Chrome, Brass | 1.0 |
    | Wood | 0.0 |
    | Plastic | 0.0 |
    | Concrete, Stone | 0.0 |
    | Fabric, Leather | 0.0 |
    | Glass | 0.0 |
    | Painted surfaces | 0.0 |
    | Dirty/oxidised metal | 0.0 - 0.2 |


    roughness_factor (property roughnessFactor in PbrMetallicRoughness)
    - 0.0 = Perfect mirror (completely smooth)
        - Sharp, clear reflections
        - Light reflects in a single direction
        - Think polished metal, glass, or water

    - 1.0 = Completely rough (maximally diffuse)
        - No clear reflections
        - Light scatters in all directions
        - Think chalk, concrete, or unfinished wood

    | Material | Typical Roughness Factor |
    | --- | --- |
    | Polished metal | 0.0 - 0.1 |
    | Glass | 0.0 - 0.05 |
    | Plastic (glossy) | 0.2 - 0.4 |
    | Wood (finished) | 0.4 - 0.7 |
    | Concrete | 0.8 - 1.0 |
    | Fabric | 0.9 - 1.0 |
    | Rubber | 0.7 - 0.9 |

    base_color: RGBA colour values (0.0-1.0), defaults to white (1.0, 1.0, 1.0, 1.0)
    """
    __slots__ = ('name', 'metallic_factor', 'roughness_factor', 'base_colour')

    def __init__(self, name: str, metallic_factor: float, roughness_factor: float,
                 base_color: RGBAColour = _COLOUR_DEFAULT) -> None:
        self.name: str = name
        self.metallic_factor: float = metallic_factor
        self.roughness_factor: float = roughness_factor
        self.base_colour: RGBAColour = base_color


# A cable for an aerialway, a powerline, etc.
# use high roughness and no metallic on purpose to get a rather dark cable
_mat_cable = CoveringMaterial('mat_cable', 0., 0.7,
                              COLOUR_DIM_GREY)

_mat_asphalt = CoveringMaterial('mat_asphalt', 0., 0.9,
                                COLOUR_LIGHT_GREY)

_mat_default_atlas = CoveringMaterial('mat_default_atlas', 0., 0.9,
                                      _COLOUR_DEFAULT)

_mat_roads_all = CoveringMaterial('mat_roads_all', 0., 0.9,
                                      COLOUR_DIM_GREY)

# ================================= COVERINGS =========================================

class RepeatType(IntEnum):
    """In which direction a covering can be repeated.

    It can be only in the horizontal direction or not.
    This is a design decision because the horizontal direction is the most common one
    for roofs and facades.
    """
    none = 0
    horizontal = 1


def create_kv_string(key: str, value: str) -> str:
    """To be used for required and provides key + values."""
    return '{}={}'.format(key, value)


def value_from_kv_string(kv_string: str, key: str) -> str | None:
    if key in kv_string:
        return kv_string[len(key) + 1:]  # there is also the '=' to separate the key and value
    return None


COMPAT_ROOF_FLAT = 'compat:roof-flat'
COMPAT_ROOF_PITCHED = 'compat:roof-pitched'
COMPAT_ROOF_LARGE = 'compat:roof-large'
ROOF_DEFAULT = 'roof:default'
ROOF_SPECIFIC = 'roof:specific'

# 'period' is not an official key in OSM, but other keys in OSM (e.g. 'historic', 'historic:era') are too specific
PERIOD_OLD = create_kv_string('period', 'old')
PERIOD_MODERN = create_kv_string('period', 'modern')

class CoveringType(IntEnum):
    """What this covering is used for."""
    roof = 0
    facade = 1
    other = 2


class CCovering:
    """A part of a texture atlas combined with a material.
    The C indicates that we are in cartesian land.

    Attributes:
        xy_coords: the lower-left x/y and upper right x/y coordinates of the texture in the atlas
            x and y are in pixels. x is in the left-to-right direction, y is in the bottom-to-top direction
            (i.e. != uv coordinates).
        width: how much the texture covers horizontally (in metres) - without repeating
        height: how much the texture covers vertically (in metres) - without stretching
        colour: the dominant colour - even if it is e.g. a glass facade.
                Use V_ from osmstring.py (e.g. V_RED)
    """
    __slots__ = ('name', 'texture', 'material', 'xy_coords', 'width', 'height', 'colour',
                 '_repeat_type', '_can_stretch_vertical')

    def __init__(self, name: str, texture: CoveringTexture, material: CoveringMaterial,
                 xy_coords: tuple[int, int, int, int], width: float, height: float, colour: str,
                 repeat_type: RepeatType = RepeatType.none, can_stretch_vertical: bool = False) -> None:
        self.name: str = name
        self.texture: CoveringTexture = texture
        self.material: CoveringMaterial = material
        self.xy_coords: tuple[int, int, int, int] = xy_coords  # lower left x, y, upper right x, y
        self.width: float = width
        self.height: float = height
        self.colour: str = colour

        self._repeat_type = repeat_type
        self._can_stretch_vertical = can_stretch_vertical

    @property
    def repeat_type(self) -> RepeatType:
        return self._repeat_type

    @property
    def h_can_repeat(self) -> bool:
        return self._repeat_type is RepeatType.horizontal

    @property
    def v_can_stretch(self) -> bool:
        return self._can_stretch_vertical

    def calc_absolute_texture_coordinates(self, x_local: float, y_local: float) -> tuple[float, float]:
        """Calculates the cartesian x/y coordinates as they would be in the real texture.

        Because the input coordinates are relative to the covering, not the original texture.

        Care must be taken in programming that texture coordinates only are used if there is a texture.
        """
        if self.texture is None or self.width == 0 or self.height == 0:
            return 0., 0.

        x_tex: float = self.xy_coords[0] + x_local * (self.xy_coords[2] - self.xy_coords[0])
        x_tex /= self.texture.width
        y_tex: float = self.xy_coords[1] + y_local * (self.xy_coords[3] - self.xy_coords[1])
        y_tex /= self.texture.height
        return x_tex, y_tex


COV_CABLE = CCovering('cov_cable', _tex_asphalt, _mat_cable,
                      (0, 0, 128, 128), 10., 10., s.V_DIMGREY,
                      repeat_type=RepeatType.horizontal, can_stretch_vertical=True)

COV_ASPHALT = CCovering('cov_asphalt', _tex_asphalt, _mat_asphalt,
                        (0, 0, 128, 128), 10., 10., s.V_LIGHTGREY,
                        repeat_type=RepeatType.horizontal, can_stretch_vertical=True)

_roof_width_px: int = 256
_roof_height_px: int = 128
_lower: int = 16348


class RoofPitchCompatibility(IntEnum):
    both = 0
    only_flat = 1
    only_pitched = 2


@dataclass
class RoofRequirements:
    """A temporary storage class for roof requirements from OSM"""
    roof_colour: str | None
    roof_material: str | None

    @property
    def complete(self) -> bool:
        return self.roof_colour is not None and self.roof_material is not None

    @property
    def empty(self) -> bool:
        return self.roof_colour is None and self.roof_material is None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RoofRequirements):
            return NotImplemented
        return (
            self.roof_colour == other.roof_colour and
            self.roof_material == other.roof_material
        )

    def __ne__(self, other: object) -> bool:
        result = self.__eq__(other)
        if result is NotImplemented:
            return NotImplemented
        return not result


class RCovering(CCovering):
    """A roof covering.
    All roof coverings can be repeated horizontally and stretched vertically.
    This is because it would be very hard to first test what the depth/height of a (pitched) roof is.
    E.g. for skeletons and because the roof orientation is not always obvious.
    Therefore, also for pitched roofs, some stretching might be required. And as a consequence, the
    height of a texture for a roof must be "considerable" (think a roof or dome of a church).

    There is no modelling of a relationship between roof coverings and facade coverings - e.g.
    such that a red facade does not get a red roof or the other way around. This is to simplify things.

    Attributes:
        roof_pitch_compatibility: whether this covering can be used with e.g. a pitched roof
        roof_material: the OSM material string (cf. https://wiki.openstreetmap.org/wiki/Key:roof:material)
                       NB: attribute 'material' is the glTF material
        match_roof_material: if True then this covering may only be used if there is a direct match
                             between the asked for roof material and this. I.e. this covering cannot
                             be used when there is no input roof material - because it is very specific
                             (e.g. grass, glass, a seldom colour)
    """
    __slots__ = ('roof_pitch_compatibility', 'roof_material', 'match_roof_material')

    def __init__(self, name: str, texture: CoveringTexture, material: CoveringMaterial,
                 xy_coords: tuple[int, int, int, int], width: float, height: float, colour: str,
                 roof_pitch_compatibility: RoofPitchCompatibility,
                 roof_material: str, match_roof_material: bool = False) -> None:
        super().__init__(name, texture, material, xy_coords, width, height, colour,
                         RepeatType.horizontal, True)
        self.roof_pitch_compatibility = roof_pitch_compatibility
        self.roof_material = roof_material
        self.match_roof_material: bool = match_roof_material


_lower -= _roof_height_px
COV_R_RED1 = RCovering('roof_red1', _tex_default_atlas, _mat_default_atlas,
                       (0, _lower, _roof_width_px, _lower + _roof_height_px), 32, 16,
                       s.V_RED, RoofPitchCompatibility.only_pitched, s.V_ROOF_TILES)

_lower -= _roof_height_px
COV_R_RED2 = RCovering('roof_red2', _tex_default_atlas, _mat_default_atlas,
                       (0, _lower, _roof_width_px, _lower + _roof_height_px), 32, 16,
                       s.V_RED, RoofPitchCompatibility.only_pitched, s.V_ROOF_TILES)

_lower -= _roof_height_px
COV_R_RED3 = RCovering('roof_red3', _tex_default_atlas, _mat_default_atlas,
                       (0, _lower, _roof_width_px, _lower + _roof_height_px), 32, 16,
                       s.V_RED, RoofPitchCompatibility.only_pitched, s.V_ROOF_TILES)

_lower -= _roof_height_px
COV_R_ORANGE = RCovering('roof_orange', _tex_default_atlas, _mat_default_atlas,
                         (0, _lower, _roof_width_px, _lower + _roof_height_px), 32, 16,
                         s.V_ORANGE, RoofPitchCompatibility.only_pitched, s.V_ROOF_TILES)

_lower -= _roof_height_px
COV_R_BLACK1 = RCovering('roof_black1', _tex_default_atlas, _mat_default_atlas,
                         (0, _lower, _roof_width_px, _lower + _roof_height_px), 32, 16,
                         s.V_BLACK, RoofPitchCompatibility.only_pitched, s.V_ROOF_TILES)

_lower -= _roof_height_px
COV_R_BLACK_SLATE = RCovering('roof_black_slate', _tex_default_atlas, _mat_default_atlas,
                              (0, _lower, _roof_width_px, _lower + _roof_height_px), 32, 16,
                              s.V_BLACK, RoofPitchCompatibility.only_pitched, s.V_SLATE)

_roof_height_px = 256
_lower -= _roof_height_px
COV_R_STONE_YELLOW = RCovering('roof_stone', _tex_default_atlas, _mat_default_atlas,
                               (0, _lower, _roof_width_px, _lower + _roof_height_px), 100, 100,
                               s.V_YELLOW, RoofPitchCompatibility.both, s.V_BRICK, True)

_lower -= _roof_height_px
COV_R_STONE_RED = RCovering('roof_stone_red', _tex_default_atlas, _mat_default_atlas,
                            (0, _lower, _roof_width_px, _lower + _roof_height_px), 100, 100,
                            s.V_RED, RoofPitchCompatibility.both, s.V_BRICK, True)

_lower -= _roof_height_px
COV_R_GEN_BLACK1 = RCovering('roof_gen_black1', _tex_default_atlas, _mat_default_atlas,
                             (0, _lower, _roof_width_px, _lower + _roof_height_px), 100, 100,
                             s.V_BLACK, RoofPitchCompatibility.both, s.V_METAL)

_lower -= _roof_height_px
COV_R_GEN_DARKGREY = RCovering('roof_gen_darkgrey', _tex_default_atlas, _mat_default_atlas,
                               (0, _lower, _roof_width_px, _lower + _roof_height_px), 100, 100,
                               s.V_DARKGREY, RoofPitchCompatibility.both, s.V_METAL)

_lower -= _roof_height_px
COV_R_GEN_GREY = RCovering('roof_gen_grey', _tex_default_atlas, _mat_default_atlas,
                           (0, _lower, _roof_width_px, _lower + _roof_height_px), 100, 100,
                           s.V_GREY, RoofPitchCompatibility.both, s.V_METAL)

_roof_height_px = 4*256
_lower -= _roof_height_px
COV_R_GEN_GREY_LARGE = RCovering('roof_gen_grey_large', _tex_default_atlas, _mat_default_atlas,
                                 (0, _lower, _roof_width_px, _lower + _roof_height_px), 100, 400,
                                 s.V_GREY, RoofPitchCompatibility.only_flat, s.V_METAL)

_roof_height_px = 256
_lower -= _roof_height_px
COV_R_GEN_LIGHTGREY = RCovering('roof_gen_lightgrey', _tex_default_atlas, _mat_default_atlas,
                                (0, _lower, _roof_width_px, _lower + _roof_height_px), 100, 100,
                                s.V_LIGHTGREY, RoofPitchCompatibility.both, s.V_METAL)

_lower -= _roof_height_px
COV_R_GEN_METAL = RCovering('roof_gen_metal', _tex_default_atlas, _mat_default_atlas,
                            (0, _lower, _roof_width_px, _lower + _roof_height_px), 100, 100,
                            s.V_LIGHTGREY, RoofPitchCompatibility.both, s.V_METAL)

_lower -= _roof_height_px
COV_R__GEN_BROWN1 = RCovering('roof_gen_brown1', _tex_default_atlas, _mat_default_atlas,
                              (0, _lower, _roof_width_px, _lower + _roof_height_px), 100, 100,
                              s.V_BROWN, RoofPitchCompatibility.both, s.V_METAL)


_lower -= _roof_height_px
COV_R_GEN_GRASS = RCovering('roof_gen_grass', _tex_default_atlas, _mat_default_atlas,
                            (0, _lower, _roof_width_px, _lower + _roof_height_px), 100, 100,
                            s.V_GREEN, RoofPitchCompatibility.both, s.V_GRASS, True)


_lower -= _roof_height_px
COV_R_GEN_COPPER = RCovering('roof_gen_copper', _tex_default_atlas, _mat_default_atlas,
                             (0, _lower, _roof_width_px, _lower + _roof_height_px), 100, 100,
                             s.V_COPPER, RoofPitchCompatibility.both, s.V_COPPER, True)


_lower -= _roof_height_px
COV_R_GEN_GLASS = RCovering('roof_gen_glass', _tex_default_atlas, _mat_default_atlas,
                            (0, _lower, _roof_width_px, _lower + _roof_height_px), 100, 100,
                            s.V_LIGHTBLUE, RoofPitchCompatibility.both, s.V_GLASS, True)


ROOF_COVERINGS = [COV_R_RED1, COV_R_RED2, COV_R_RED3, COV_R_ORANGE,
                  COV_R_BLACK1, COV_R_BLACK_SLATE, COV_R_STONE_YELLOW, COV_R_STONE_RED,
                  COV_R_GEN_BLACK1, COV_R_GEN_DARKGREY, COV_R_GEN_GREY, COV_R_GEN_GREY_LARGE,
                  COV_R_GEN_LIGHTGREY, COV_R_GEN_METAL, COV_R__GEN_BROWN1, COV_R_GEN_GRASS,
                  COV_R_GEN_COPPER, COV_R_GEN_GLASS]


class RoofManager:
    __slots__ = ('_roof_coverings', '_coverings_by_colour', '_coverings_by_material',
                 '_coverings_flat', '_coverings_pitched',
                 '_missing_roof_colour_pitched_ratios', '_missing_roof_material_pitched_ratios')

    def __init__(self, roof_coverings: list[RCovering]) -> None:
        self._roof_coverings: list[RCovering] = list()
        self._coverings_by_colour: dict[str, list[RCovering]] = dict()  # key = colour string
        self._coverings_by_material: dict[str, list[RCovering]] = dict()  # key = roof-material string
        self._coverings_flat: list[RCovering] = list()
        self._coverings_pitched: list[RCovering] = list()
        self._process_coverings(roof_coverings)

        self._missing_roof_colour_pitched_ratios: dict[str, dict[str, float]] = dict()
        self._missing_roof_material_pitched_ratios: dict[str, dict[str, float]] = dict()
        self._process_missing_roof_pitched_ratios()

    def _process_coverings(self, coverings: list[RCovering]) -> None:
        for covering in coverings:
            assert isinstance(covering, RCovering), f"Expected RCovering, got {type(covering)}"
            self._roof_coverings.append(covering)
            if covering.colour not in self._coverings_by_colour:
                self._coverings_by_colour[covering.colour] = list()
            self._coverings_by_colour[covering.colour].append(covering)
            if covering.roof_material not in self._coverings_by_material:
                self._coverings_by_material[covering.roof_material] = list()
            self._coverings_by_material[covering.roof_material].append(covering)
            if covering.roof_pitch_compatibility in [RoofPitchCompatibility.only_pitched, RoofPitchCompatibility.both]:
                self._coverings_pitched.append(covering)
            if covering.roof_pitch_compatibility in [RoofPitchCompatibility.only_flat, RoofPitchCompatibility.both]:
                self._coverings_flat.append(covering)
        assert len(self._coverings_flat) > 0, "No flat roof coverings found"
        assert len(self._coverings_pitched) > 0, "No pitched roof coverings found"

    def _process_missing_roof_pitched_ratios(self) -> None:
        """For situations where there is a colour but not material - or the other way around
        - create a ratio for missing roof material/colour combinations based on what is in the
        parametrized value."""
        for key, ratio in parameters.BUILDING_ROOF_COLOUR_MATERIAL_PITCHED_RATIO.items():
            # I have the colour - not the material
            if key[0] not in self._missing_roof_material_pitched_ratios:
                self._missing_roof_material_pitched_ratios[key[0]] = dict()
            self._missing_roof_material_pitched_ratios[key[0]][key[1]] = ratio
            # I have the material - not the colour
            if key[1] not in self._missing_roof_colour_pitched_ratios:
                self._missing_roof_colour_pitched_ratios[key[1]] = dict()
            self._missing_roof_colour_pitched_ratios[key[1]][key[0]] = ratio

        for ratios in self._missing_roof_material_pitched_ratios.values():
            total_ratio = 0.0
            for ratio in ratios.values():
                total_ratio += ratio
            for key, ratio in ratios.items():
                ratios[key] = ratio / total_ratio

        for ratios in self._missing_roof_colour_pitched_ratios.values():
            total_ratio = 0.0
            for ratio in ratios.values():
                total_ratio += ratio
            for key, ratio in ratios.items():
                ratios[key] = ratio / total_ratio

    def _complete_pitched_roof_requirements(self, orig_requirements: RoofRequirements) -> RoofRequirements | None:
        """Complete the roof requirements with missing information"""
        if orig_requirements.empty:
            colour, mat = u.random_value_from_ratio_dict_parameter(parameters.BUILDING_ROOF_COLOUR_MATERIAL_PITCHED_RATIO)
            return RoofRequirements(colour, mat)
        elif orig_requirements.roof_material:
            ratios = self._missing_roof_colour_pitched_ratios.get(orig_requirements.roof_material)
            if ratios:
                random_colour = u.random_value_from_ratio_dict_parameter(ratios)
                return RoofRequirements(random_colour, orig_requirements.roof_material)
        elif orig_requirements.roof_colour:
            ratios = self._missing_roof_material_pitched_ratios.get(orig_requirements.roof_colour)
            if ratios:
                random_material = u.random_value_from_ratio_dict_parameter(ratios)
                return RoofRequirements(orig_requirements.roof_colour, random_material)
        return None

    def find_matching_roof(self, requirements: RoofRequirements, roof_shape: enu.RoofShape) -> RCovering:
        """Find a matching roof covering based on requirements and roof shape

        Args:
            requirements (RoofRequirements): The roof requirements
            roof_shape (enu.RoofShape): The roof shape

        Returns:
            RCovering: The matching roof covering
        """
        pitch_candidates: list[RCovering]
        if roof_shape is enu.RoofShape.flat:
            pitch_candidates = self._coverings_flat
        else:
            pitch_candidates = self._coverings_pitched
            if not requirements.complete:
                new_req = self._complete_pitched_roof_requirements(requirements)
                if new_req:
                    requirements = new_req

        candidates: list[RCovering] = list()
        # first try to satisfy both requirements
        if requirements.roof_material is not None and requirements.roof_colour is not None:
            for candidate in pitch_candidates:
                if candidate.roof_material == requirements.roof_material and candidate.colour == requirements.roof_colour:
                    candidates.append(candidate)
        if candidates:
            return random.choice(candidates)
        # then try to satisfy roof_material requirement
        if requirements.roof_material is not None:
            for candidate in pitch_candidates:
                if candidate.roof_material == requirements.roof_material:
                    candidates.append(candidate)
        if candidates:
            return random.choice(candidates)
        # then try to satisfy colour requirement
        if requirements.roof_colour is not None:
            for candidate in pitch_candidates:
                if candidate.colour == requirements.roof_colour:
                    candidates.append(candidate)
        if candidates:
            return random.choice(candidates)
        # we are desperate and just pick a random one from what we have
        # but not specific ones
        random_candidates: list[RCovering] = list()
        for candidate in pitch_candidates:
            if not candidate.match_roof_material:
                random_candidates.append(candidate)
        return random.choice(random_candidates)


class FCovering(CCovering):
    """
    Facade covering

    Attributes:
        h_cuts: list of horizontal cuts (0.0 - 1.0)
        v_cuts: list of vertical cuts (0.0 - 1.0)
        provides: what stuff this covering is representing
        requires (only for facades): requirements for the roof for this facade
    """
    __slots__ = ('h_cuts', 'v_cuts', 'provides', 'requires')

    def __init__(self, name: str, texture: CoveringTexture, material: CoveringMaterial,
                 xy_coords: tuple[int, int, int, int], width: float, height: float, colour: str,
                 h_cuts: list[float] | None, v_cuts: list[float] | None, provides: list[str], requires: list[str] | None,
                 repeat_type: RepeatType = RepeatType.none, can_stretch_vertical: bool = False) -> None:
        super().__init__(name, texture, material, xy_coords, width, height, colour,
                         repeat_type, can_stretch_vertical)
        self.h_cuts: list[float] | None = h_cuts
        self.v_cuts: list[float] | None = v_cuts

        self.provides: list[str] = provides
        assert self.provides is not None, 'provides may not be None'
        assert len(self.provides) > 0, 'provides may not be empty'
        self.requires: list[str] = requires if requires is not None else list()


# osm2city-data/tex.src/gb/residential/sandstone3_16x03m.png
COV_F_1001 = FCovering('facade_1001', _tex_default_atlas, _mat_default_atlas,
                       (0, 8548, 256, 8596), 15.50, 2.60, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:residential', PERIOD_OLD, PERIOD_MODERN, COMPAT_ROOF_PITCHED, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/gb/residential/sandstone6_16x11m.png
COV_F_1002 = FCovering('facade_1002', _tex_default_atlas, _mat_default_atlas,
                       (0, 8316, 256, 8548), 16.20, 11.30, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:residential', PERIOD_OLD, PERIOD_MODERN, COMPAT_ROOF_PITCHED, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/gb/residential/plaster3_10x03m.png
COV_F_1003 = FCovering('facade_1003', _tex_default_atlas, _mat_default_atlas,
                       (0, 8235, 256, 8316), 9.90, 3.30, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:residential', PERIOD_OLD, PERIOD_MODERN, COMPAT_ROOF_PITCHED, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/gb/residential/plaster2_09x05m.png
COV_F_1004 = FCovering('facade_1004', _tex_default_atlas, _mat_default_atlas,
                       (0, 8080, 256, 8235), 9.40, 4.90, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:residential', PERIOD_OLD, PERIOD_MODERN, COMPAT_ROOF_PITCHED, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/gb/residential/sandstone2_13x03m.png
COV_F_1005 = FCovering('facade_1005', _tex_default_atlas, _mat_default_atlas,
                       (0, 8019, 256, 8080), 13.40, 2.60, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:residential', PERIOD_OLD, PERIOD_MODERN, COMPAT_ROOF_PITCHED, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/gb/residential/sandstone4_09x05m.png
COV_F_1006 = FCovering('facade_1006', _tex_default_atlas, _mat_default_atlas,
                       (0, 7845, 255, 8019), 9.00, 4.90, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:residential', PERIOD_OLD, PERIOD_MODERN, COMPAT_ROOF_PITCHED, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/gb/residential/sandstone1_13x06m.png
COV_F_1007 = FCovering('facade_1007', _tex_default_atlas, _mat_default_atlas,
                       (0, 7716, 255, 7845), 13.40, 5.80, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:residential', PERIOD_OLD, PERIOD_MODERN, COMPAT_ROOF_PITCHED, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/gb/residential/plaster1_07x03m.png
COV_F_1008 = FCovering('facade_1008', _tex_default_atlas, _mat_default_atlas,
                       (0, 7655, 256, 7716), 7.10, 3.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:residential', PERIOD_OLD, PERIOD_MODERN, COMPAT_ROOF_PITCHED, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/us/commercial/45storyglassmodern.jpg
COV_F_1009 = FCovering('facade_1009', _tex_default_atlas, _mat_default_atlas,
                       (0, 11520, 128, 11776), 40.00, 80.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/41storyconcrglasswhitemodern2.jpg
COV_F_1010 = FCovering('facade_1010', _tex_default_atlas, _mat_default_atlas,
                       (128, 11520, 192, 11776), 46.20, 184.80, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/40storymodern.jpg
COV_F_1011 = FCovering('facade_1011', _tex_default_atlas, _mat_default_atlas,
                       (0, 7185, 256, 7655), 35.00, 64.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/us/commercial/36storyconcrglassmodern.jpg
COV_F_1012 = FCovering('facade_1012', _tex_default_atlas, _mat_default_atlas,
                       (192, 11520, 256, 11776), 29.70, 118.80, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/35storyconcrmodernwhite.jpg
COV_F_1013 = FCovering('facade_1013', _tex_default_atlas, _mat_default_atlas,
                       (0, 11264, 64, 11520), 25.00, 100.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/30storyconcrbrown4.jpg
COV_F_1014 = FCovering('facade_1014', _tex_default_atlas, _mat_default_atlas,
                       (64, 11264, 192, 11520), 48.00, 96.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/27storyConcrBrownGlass.jpg
COV_F_1015 = FCovering('facade_1015', _tex_default_atlas, _mat_default_atlas,
                       (192, 11264, 256, 11520), 22.27, 89.10, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/25storyBrownWide1.jpg
COV_F_1016 = FCovering('facade_1016', _tex_default_atlas, _mat_default_atlas,
                       (0, 11008, 256, 11264), 66.00, 66.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/20storybrownconcrmodern.jpg
COV_F_1017 = FCovering('facade_1017', _tex_default_atlas, _mat_default_atlas,
                       (0, 6860, 256, 7185), 44.00, 56.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/us/commercial/20storygreycncrglassmodern.jpg
COV_F_1018 = FCovering('facade_1018', _tex_default_atlas, _mat_default_atlas,
                       (0, 10752, 128, 11008), 27.00, 54.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/19storyretromodern.jpg
COV_F_1019 = FCovering('facade_1019', _tex_default_atlas, _mat_default_atlas,
                       (0, 10240, 128, 10752), 25.00, 100.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/18storyoffice.jpg
COV_F_1020 = FCovering('facade_1020', _tex_default_atlas, _mat_default_atlas,
                       (128, 10752, 256, 11008), 28.00, 56.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/15storyltbrownconcroffice3.jpg
COV_F_1021 = FCovering('facade_1021', _tex_default_atlas, _mat_default_atlas,
                       (128, 10496, 256, 10752), 29.00, 58.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/10storymodernconcrete.jpg
COV_F_1022 = FCovering('facade_1022', _tex_default_atlas, _mat_default_atlas,
                       (128, 10240, 256, 10496), 20.00, 40.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/US-dcofficeconcrwhite8st.jpg
COV_F_1023 = FCovering('facade_1023', _tex_default_atlas, _mat_default_atlas,
                       (0, 6604, 256, 6860), 30.00, 30.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/us/commercial/US-dchotelDC2_8st.jpg
COV_F_1024 = FCovering('facade_1024', _tex_default_atlas, _mat_default_atlas,
                       (0, 9984, 128, 10240), 15.00, 30.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/US-dcofficeconcrwhite6-7st.jpg
COV_F_1025 = FCovering('facade_1025', _tex_default_atlas, _mat_default_atlas,
                       (0, 9876, 256, 9984), 54.76, 23.10, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/7storymodernsq.jpg
COV_F_1026 = FCovering('facade_1026', _tex_default_atlas, _mat_default_atlas,
                       (128, 10112, 256, 10240), 21.00, 21.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/US-dcdupontconcr5st.jpg
COV_F_1027 = FCovering('facade_1027', _tex_default_atlas, _mat_default_atlas,
                       (128, 9984, 192, 10112), 7.50, 15.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/5storywhite.jpg
COV_F_1028 = FCovering('facade_1028', _tex_default_atlas, _mat_default_atlas,
                       (0, 9748, 128, 9876), 15.00, 15.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/US-dcgovtconcrtan4st.jpg
COV_F_1029 = FCovering('facade_1029', _tex_default_atlas, _mat_default_atlas,
                       (128, 9812, 256, 9876), 33.00, 16.50, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/3storystorefronttown.jpg
COV_F_1030 = FCovering('facade_1030', _tex_default_atlas, _mat_default_atlas,
                       (0, 9620, 128, 9748), 9.00, 9.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/salmon_3_story_0_scale.jpg
COV_F_1031 = FCovering('facade_1031', _tex_default_atlas, _mat_default_atlas,
                       (128, 9684, 256, 9812), 8.00, 8.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/2stFancyconcrete1.jpg
COV_F_1032 = FCovering('facade_1032', _tex_default_atlas, _mat_default_atlas,
                       (0, 9492, 256, 9620), 14.00, 7.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/US-dcwhiteconcr2st.jpg
COV_F_1033 = FCovering('facade_1033', _tex_default_atlas, _mat_default_atlas,
                       (0, 9364, 256, 9492), 16.00, 8.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/US-dctbrickcomm2st.jpg
COV_F_1034 = FCovering('facade_1034', _tex_default_atlas, _mat_default_atlas,
                       (0, 9300, 256, 9364), 21.00, 5.25, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/USUAE-4stCommercial.jpg
COV_F_1035 = FCovering('facade_1035', _tex_default_atlas, _mat_default_atlas,
                       (0, 9172, 256, 9300), 20.00, 10.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/US-OfficeComm-2st.jpg
COV_F_1036 = FCovering('facade_1036', _tex_default_atlas, _mat_default_atlas,
                       (0, 9108, 256, 9172), 15.00, 3.75, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/US-1stCommWarehousewhite1.jpg
COV_F_1037 = FCovering('facade_1037', _tex_default_atlas, _mat_default_atlas,
                       (0, 9044, 256, 9108), 15.00, 3.75, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/US-1stCommBrick2.jpg
COV_F_1038 = FCovering('facade_1038', _tex_default_atlas, _mat_default_atlas,
                       (0, 8980, 256, 9044), 15.00, 3.75, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/commercial/US-1stCommStFront3.jpg
COV_F_1039 = FCovering('facade_1039', _tex_default_atlas, _mat_default_atlas,
                       (128, 9620, 256, 9684), 10.00, 5.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/residential/tiles/USUAE-8stTile_rep.jpg
COV_F_1040 = FCovering('facade_1040', _tex_default_atlas, _mat_default_atlas,
                       (0, 8724, 128, 8980), 15.00, 30.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/residential/6storybrickbrown1.jpg
COV_F_1041 = FCovering('facade_1041', _tex_default_atlas, _mat_default_atlas,
                       (128, 8852, 256, 8980), 21.00, 21.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/residential/5storyCondo_concrglasswhite.jpg
COV_F_1042 = FCovering('facade_1042', _tex_default_atlas, _mat_default_atlas,
                       (192, 9984, 256, 10112), 14.00, 28.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/residential/US-CityCondo_brick_4st.jpg
COV_F_1043 = FCovering('facade_1043', _tex_default_atlas, _mat_default_atlas,
                       (128, 8724, 256, 8852), 16.00, 16.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/us/residential/US-CityCondo2st.jpg
COV_F_1044 = FCovering('facade_1044', _tex_default_atlas, _mat_default_atlas,
                       (0, 8596, 128, 8724), 11.00, 11.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/de/industrial/facade_industrial_red_white_24x18m.jpg
# also used for hangar in _find_aeroway_facade
COV_F_1045 = FCovering('facade_1045', _tex_default_atlas, _mat_default_atlas,
                       (0, 6406, 256, 6604), 23.80, 18.50, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:industrial', PERIOD_OLD, COMPAT_ROOF_FLAT, COMPAT_ROOF_PITCHED],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/residential/DSCF9495_pow2.png
COV_F_1046 = FCovering('facade_1046', _tex_default_atlas, _mat_default_atlas,
                       (0, 6150, 256, 6406), 14.00, 19.40, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:residential', PERIOD_OLD, COMPAT_ROOF_FLAT, COMPAT_ROOF_PITCHED],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/residential/LZ_old_bright_bc2.png
COV_F_1047 = FCovering('facade_1047', _tex_default_atlas, _mat_default_atlas,
                       (0, 5894, 256, 6150), 17.90, 14.80, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:residential', PERIOD_OLD, COMPAT_ROOF_FLAT, COMPAT_ROOF_PITCHED],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/commercial/facade_modern_21x42m.jpg
COV_F_1048 = FCovering('facade_1048', _tex_default_atlas, _mat_default_atlas,
                       (0, 5372, 256, 5894), 43.00, 88.00, s.V_WHITE,
                       None, None,
                       [PERIOD_MODERN, COMPAT_ROOF_FLAT, 'facade:facade:shape:commercial', 'facade:facade:shape:urban'],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/industrial/facade_industrial_white_26x14m.jpg
COV_F_1049 = FCovering('facade_1049', _tex_default_atlas, _mat_default_atlas,
                       (0, 5238, 256, 5372), 25.70, 13.50, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:industrial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/commercial/facade_modern_commercial_35x20m.jpg
# also used for terminal in_find_aeroway_facade
COV_F_1050 = FCovering('facade_1050', _tex_default_atlas, _mat_default_atlas,
                       (0, 5088, 256, 5238), 34.60, 20.40, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/residential/facade_modern36x36_12.png
COV_F_1051 = FCovering('facade_1051', _tex_default_atlas, _mat_default_atlas,
                       (0, 4832, 256, 5088), 36.00, 36.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:residential', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/residential/facade_modern_residential_26x34m.jpg
COV_F_1052 = FCovering('facade_1052', _tex_default_atlas, _mat_default_atlas,
                       (0, 4503, 256, 4832), 26.30, 33.90, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:residential', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/residential/DSCF9503_noroofsec_pow2.png
COV_F_1053 = FCovering('facade_1053', _tex_default_atlas, _mat_default_atlas,
                       (0, 4247, 256, 4503), 12.85, 17.66, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:residential', PERIOD_OLD, COMPAT_ROOF_FLAT, COMPAT_ROOF_PITCHED],
                       ['roof:colour:black'],
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/residential/DSCF9710.png
COV_F_1054 = FCovering('facade_1054', _tex_default_atlas, _mat_default_atlas,
                       (0, 4119, 256, 4247), 29.90, 19.80, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:residential', PERIOD_OLD, COMPAT_ROOF_FLAT, COMPAT_ROOF_PITCHED],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/residential/DSCF9678_pow2.png
COV_F_1055 = FCovering('facade_1055', _tex_default_atlas, _mat_default_atlas,
                       (0, 3863, 256, 4119), 10.40, 15.50, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:residential', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/residential/facade_modern_residential_25x15m.jpg
COV_F_1056 = FCovering('facade_1056', _tex_default_atlas, _mat_default_atlas,
                       (0, 3712, 256, 3863), 25.00, 14.80, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:residential', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       ['roof:colour:black'],
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/commercial/facade_modern_commercial_red_gray_20x14m.jpg
# also used for "other" _find_aeroway_facade
COV_F_1057 = FCovering('facade_1057', _tex_default_atlas, _mat_default_atlas,
                       (0, 3532, 256, 3712), 20.00, 14.10, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       ['roof:colour:black'],
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/commercial/facade_modern_commercial_green_red_27x39m.jpg
COV_F_1058 = FCovering('facade_1058', _tex_default_atlas, _mat_default_atlas,
                       (0, 3168, 256, 3532), 27.30, 38.90, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       ['roof:colour:black'],
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/residential/DSCF9726_noroofsec_pow2.png
COV_F_1059 = FCovering('facade_1059', _tex_default_atlas, _mat_default_atlas,
                       (0, 3040, 256, 3168), 15.10, 9.60, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:residential', PERIOD_OLD, COMPAT_ROOF_FLAT, COMPAT_ROOF_PITCHED],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/residential/wohnheime_petersburger.png
COV_F_1060 = FCovering('facade_1060', _tex_default_atlas, _mat_default_atlas,
                       (0, 2784, 256, 3040), 15.60, 15.60, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:residential', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.none)

# osm2city-data/tex.src/de/commercial/facade_modern_black_46x60m.jpg
COV_F_1061 = FCovering('facade_1061', _tex_default_atlas, _mat_default_atlas,
                       (0, 2447, 256, 2784), 45.90, 60.50, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       ['roof:colour:black'],
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/commercial/facade_modern_commercial_46x170m.jpg
COV_F_1062 = FCovering('facade_1062', _tex_default_atlas, _mat_default_atlas,
                       (0, 1551, 256, 2447), 46.00, 170.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:commercial', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       ['roof:colour:black'],
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/industrial/transformer_07x03m.png
COV_F_1063 = FCovering('facade_1063', _tex_default_atlas, _mat_default_atlas,
                       (0, 1446, 256, 1551), 7.50, 3.30, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:power:substation', 'facade:facade:shape:industrial', PERIOD_OLD, PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/industrial/old_factory_30x07m.png
COV_F_1064 = FCovering('facade_1064', _tex_default_atlas, _mat_default_atlas,
                       (0, 1382, 256, 1446), 30.00, 6.60, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:industrial', PERIOD_OLD, PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/residential/wbs70_36x36m.png
COV_F_1065 = FCovering('facade_1065', _tex_default_atlas, _mat_default_atlas,
                       (0, 1145, 256, 1382), 33.60, 33.20, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:residential', PERIOD_MODERN, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/residential/cream_high_08x13m.png
COV_F_1066 = FCovering('facade_1066', _tex_default_atlas, _mat_default_atlas,
                       (0, 968, 256, 1145), 13.00, 8.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:residential', PERIOD_OLD, COMPAT_ROOF_PITCHED],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/residential/red_6x12m.png
COV_F_1067 = FCovering('facade_1067', _tex_default_atlas, _mat_default_atlas,
                       (0, 849, 256, 968), 12.00, 6.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:residential', PERIOD_OLD, PERIOD_MODERN, COMPAT_ROOF_PITCHED, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/residential/cream2_08x05m.png
COV_F_1068 = FCovering('facade_1068', _tex_default_atlas, _mat_default_atlas,
                       (0, 685, 255, 849), 8.10, 5.20, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:residential', PERIOD_OLD, PERIOD_MODERN, COMPAT_ROOF_PITCHED, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/residential/CIMG8177_18x14m.png
COV_F_1069 = FCovering('facade_1069', _tex_default_atlas, _mat_default_atlas,
                       (0, 458, 256, 685), 17.70, 13.70, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:residential', PERIOD_OLD, PERIOD_MODERN, COMPAT_ROOF_PITCHED, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/residential/cream3_10x06m.png
COV_F_1070 = FCovering('facade_1070', _tex_default_atlas, _mat_default_atlas,
                       (0, 288, 256, 458), 9.70, 6.40, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:residential', PERIOD_OLD, PERIOD_MODERN, COMPAT_ROOF_PITCHED, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

# osm2city-data/tex.src/de/residential/coloured_6x12m.png
COV_F_1071 = FCovering('facade_1071', _tex_default_atlas, _mat_default_atlas,
                       (0, 162, 256, 288), 12.00, 6.00, s.V_WHITE,
                       None, None,
                       ['facade:facade:shape:urban', 'facade:facade:shape:residential', PERIOD_OLD, PERIOD_MODERN, COMPAT_ROOF_PITCHED, COMPAT_ROOF_FLAT],
                       None,
                       repeat_type=RepeatType.horizontal)

FACADE_COVERINGS = [COV_F_1001,COV_F_1002,COV_F_1003,COV_F_1004,COV_F_1005,
                    COV_F_1006,COV_F_1007,COV_F_1008,COV_F_1009,COV_F_1010,
                    COV_F_1011,COV_F_1012,COV_F_1013,COV_F_1014,COV_F_1015,
                    COV_F_1016,COV_F_1017,COV_F_1018,COV_F_1019,COV_F_1020,
                    COV_F_1021,COV_F_1022,COV_F_1023,COV_F_1024,COV_F_1025,
                    COV_F_1026,COV_F_1027,COV_F_1028,COV_F_1029,COV_F_1030,
                    COV_F_1031,COV_F_1032,COV_F_1033,COV_F_1034,COV_F_1035,
                    COV_F_1036,COV_F_1037,COV_F_1038,COV_F_1039,COV_F_1040,
                    COV_F_1041,COV_F_1042,COV_F_1043,COV_F_1044,COV_F_1045,
                    COV_F_1046,COV_F_1047,COV_F_1048,COV_F_1049,COV_F_1050,
                    COV_F_1051,COV_F_1052,COV_F_1053,COV_F_1054,COV_F_1055,
                    COV_F_1056,COV_F_1057,COV_F_1058,COV_F_1059,COV_F_1060,
                    COV_F_1061,COV_F_1062,COV_F_1063,COV_F_1064,COV_F_1065,
                    COV_F_1066,COV_F_1067,COV_F_1068,COV_F_1069,COV_F_1070,
                    COV_F_1071
                   ]


class FacadeManager:
    __slots__ = ('_coverings', '_available_materials', '_material_key')

    def __init__(self, coverings: list[FCovering], material_key: str) -> None:
        self._material_key = material_key
        self._available_materials: set[str] = set()  # values of *:material tags
        self._coverings: set[FCovering] = set()
        for covering in coverings:
            self._append(covering)

    def has_material_available(self, material_value: str) -> bool:
        return material_value in self._available_materials

    def _append(self, covering: FCovering) -> None:
        new_provides: list[str] = list()
        my_available_materials: list[str] = list()
        for item in covering.provides:
            screened_item = screen_tag_values_for_grey_spelling(item)
            new_provides.append(screened_item)
            material_value = value_from_kv_string(screened_item, self._material_key)
            if material_value:
                my_available_materials.append(material_value)

        covering.provides = new_provides
        self._available_materials.update(my_available_materials)

        new_requires: list[str] = list()
        for item in covering.requires:
            new_requires.append(screen_tag_values_for_grey_spelling(item))
        covering.requires = new_requires

        self._coverings.add(covering)

    def _find_candidates(self, requires: list[str], excludes: list[str]) -> list[FCovering]:
        candidates: list[FCovering] = list()

        can_use = True
        for candidate in self._coverings:
            for ex in excludes:
                # check if we maybe have a tag that doesn't match a requires
                ex_material_key = 'XXX'
                ex_colour_key = 'XXX'
                ex_material = ''
                ex_colour = ''
                if re.match('^.*material=.*', ex):
                    ex_material_key = re.match('(^.*:material=)[^:]*', ex).group(1)
                    ex_material = re.match('^.*material=([^:]*)', ex).group(1)
                elif re.match('^.*:colour=.*', ex):
                    ex_colour_key = re.match('(^.*:colour=)[^:]*', ex).group(1)
                    ex_colour = re.match('^.*:colour=([^:]*)', ex).group(1)
                for req in candidate.requires:
                    if req.startswith(ex_colour_key) and ex_colour != re.match('^.*:colour=(.*)', req).group(1):
                        can_use = False
                    if req.startswith(ex_material_key) and ex_material != re.match('^.*:material=(.*)',
                                                                                       req).group(1):
                        can_use = False

            if set(requires).issubset(candidate.provides):
                # Check for "specific" texture in order they do not pollute everything
                if ('facade:specific' in candidate.provides) or (ROOF_SPECIFIC in candidate.provides):
                    can_use = False
                    req_material = None
                    req_colour = None
                    for req in requires:
                        if re.match('^.*material=.*', req):
                            req_material = re.match('^.*material=(.*)', req).group(0)
                        elif re.match('^.*:colour=.*', req):
                            req_colour = re.match('^.*:colour=(.*)', req).group(0)

                    prov_materials = []
                    prov_colours = []
                    for prov in candidate.provides:
                        if re.match('^.*:material=.*', prov):
                            prov_material = re.match('^.*:material=(.*)', prov).group(0)
                            prov_materials.append(prov_material)
                        elif re.match('^.*:colour=.*', prov):
                            prov_colour = re.match('^.*:colour=(.*)', prov).group(0)
                            prov_colours.append(prov_colour)

                    # req_material and colour
                    can_material = False
                    if req_material is not None:
                        for prov_material in prov_materials:
                            logging.debug('Provides: %s; requires: %s', prov_material, requires)
                            if prov_material in requires:
                                can_material = True
                                break
                    else:
                        can_material = True

                    can_colour = False
                    if req_colour is not None:
                        for prov_colour in prov_colours:
                            if prov_colour in requires:
                                can_colour = True
                                break
                    else:
                        can_colour = True

                    if can_material and can_colour:
                        can_use = True

                if can_use:
                    candidates.append(candidate)
            else:
                logging.debug("  unmet requires %s req %s prov %s",
                              str(candidate.name), str(requires), str(candidate.provides))
        return candidates

    def _ranked_random_candidate(self, candidates: list[FCovering], tags: t.OSMTags) -> FCovering:
        ranked_list: list[tuple[int, FCovering]] = list()
        for candidate in candidates:
            match: int = 0
            if self._material_key in tags:
                val = tags[self._material_key]
                new_key = create_kv_string(self._material_key, val)
                if new_key in candidate.provides:
                    match += 1
            ranked_list.append((match, candidate))
        ranked_list.sort(key=lambda tup: tup[0], reverse=True)
        max_val = ranked_list[0][0]
        if max_val > 0:
            pass  # just for debugging
        ranked_candidates = [candidate[1] for candidate in ranked_list if candidate[0] >= max_val]
        return ranked_candidates[random.randint(0, len(ranked_candidates) - 1)]

    def find_matching_facade(self, requires: list[str], tags: t.OSMTags, height: float, width: float,
                             ) -> FCovering | None:
        if s.K_AEROWAY in tags:
            return self._find_aeroway_facade(tags)

        exclusions = []
        # if 'roof:colour' in tags: FIXME why would we need this at all?
        # exclusions.append("%s:%s" % ('roof:colour', tags['roof:colour']))
        candidates = self._find_facade_candidates(requires, exclusions, height, width)
        if not candidates:
            # Break down requirements to something that matches
            for simple_req in requires:
                candidates = self._find_facade_candidates([simple_req], exclusions, height, width)
                if candidates:
                    break
            if not candidates:
                # Now we're really desperate - just find something!
                candidates = self._find_facade_candidates([COMPAT_ROOF_FLAT], exclusions, height, width)
            if not candidates:
                logging.debug("WARNING: no matching facade texture for %1.f m x %1.1f m <%s>",
                              height, width, str(requires))
                return None
        return self._ranked_random_candidate(candidates, tags)

    def _find_facade_candidates(self, requires: list[str], excludes: list[str], height: float, width: float)\
            -> list[FCovering]:
        candidates = self._find_candidates(requires, excludes)
        # -- check height and width requirements
        new_candidates: list[FCovering] = list()
        for candidate in candidates:
            if height > candidate.height:
                logging.debug("height %.2f (outside bounds : %s",
                              height, str(candidate.name))
                continue
            if candidate.repeat_type is RepeatType.none and width > candidate.width:
                logging.debug("width %.2f outside bounds : %s",
                              width, str(candidate.name))
                continue

            new_candidates.append(candidate)
        return new_candidates

    @staticmethod
    def _find_aeroway_facade(tags: t.OSMTags) -> FCovering:
        """A little hack to get facades that match an airport a bit."""
        if s.V_HANGAR in tags:
            return COV_F_1045
        elif s.V_TERMINAL in tags:
            return COV_F_1050
        else:
            if random.randint(0, 1) == 0:
                return COV_F_1050
        return COV_F_1057
