.. _chapter-how-texturing-works-label:

###################
How Texturing Works
###################

===================================
Implementation 2024.1.x and Earlier
===================================


----------------
Texture Atlases
----------------

There are 2 atlases: one for roads and one for facades and roofs. Both of them have a `light map <http://wiki.flightgear.org/Howto:Lightmap>`_ and are in .png format.

........................
Roads and Railway Tracks
........................

The atlas for roads is a fixed file. Any change needs to be done directly in the file. The corresponding data object understanding the format is ``osm2city/textures/roads.py``.


.................
Facades and Roofs
.................

The atlases for facades and roofs are for FG versions <= 2020.x fixed in size and content, because code restructuring has necessitated a freeze plus compatibility between FG versions needs to be guaranteed. Theoretically the atlas is dynamically created based on:

* Image files in osm2city-data representing 1 facade or one roof. For facades there can be a corresponding light-map image, which shows which parts should shine at night (e.g. individual windows).
* Python files in osm2city-data describing the images (e.g. colour, time epoch, material, size, repeatability) based on class ``Texture`` in ``osm2city\textures\texture.py``.
* ``osm2city\prepare_textures.py`` reads the Python files and creates the atlas package structure according to ``osm2city\textures\atlas.py``
* The result is an atlas image for facades/roofs, an atlas image for the corresponding light-map as well as a Python data structure of the embedded textures (position, properties) saved as `serialized Python objects <https://docs.python.org/3/library/pickle.html>`_ in a ``*.pkl`` file.


------------------------
FGData Effects and Stuff
------------------------

``osm2city`` has dependencies in FGData for effects etc. to work. This means that changes in those parts might break osm2city — and osm2city might not work correctly if new features disregard those dependencies.

* fgdata/Textures/osm2city/ contains the texture atlas for road and facades including the respective light-maps.
* fgdata/Textures/ has ``buildings-*.png`` and the related ``*-lightmap.png``, which are used for list based shader buildings.
* fgdata/Shaders/road-ALS-ultra.frag: mapping with road texture, generates traffic and night lighting etc.
* fgdata/Shaders/urban-ALS.frag and urban.frag
* fgdata/Shaders/ has ``building-*.vert``
* fgdata/Effects/cityLM.eff: light-map for facades texture atlas (so there is no need for xml-files wrapping the ac-file containing the meshes)
* fgdata/Effects/road.eff: road and traffic effect incl. snow
* fgdata/Effects/urban.eff: incl. snow for osm-buildings


----------------------
Reference in STG-Files
----------------------
``fgdata/docs/README.scenery`` contains the specification for handling objects like buildings and roads in stg-files. For both roads/railways and buildings there is the possibility to set parts into a ROUGH LOD and a DETAILED LOD category, such that some objects appear from far away (e.g. skyscrapers and motorways), while e.g. family houses and residential ways only get visible from nearby.


========================================
Proposal Renewed Implementation > 2020.x
========================================

----------------------
Needed Texture Atlases
----------------------

......................................
Ideas, Constraints and Random Thoughts
......................................

* Older graphic cards might have difficulties with textures larger than 4k x 4k. On the other hand side the current texture atlas has been 16k x 256 for maybe 10 years without people complaining. Whoever runs osm2city might not have an old PC anyway. => Going with 8k (8192 pixels) per dimension max.
* Using a transparent texture and letting the underlying model's colours shine through is very bad for performance, unless a shader is used. I.e. using a few textures and then doing the variety by using colours in the ac-file materials is not a viable way.
* FG seems to support only one texture per ac-file - even though the `AC3D file format <https://www.inivis.com/ac3d/man/ac3dfileformat.html>`_ does support several textures (one texture per object, but there can be many objects).
* In cities and centres of towns the ground floor has often shops/bars - even though the next floors might be inhabited. And therefore the facade on the ground level has more glass, more "signs" / "colours", and more diverse lighting during night -> should be possible to texture map explicitly based on distance from centre etc.
* There are two options for compatibility between FG versions (as the texture atlases reside within FG and not within scenery folders a new scenery generated with the latest atlas might not work on an FG version referencing an older texture, which will lead to funny rendering):
    * Put new BUILDING_LIST buildings and new texture atlases into FG version specific scenery directories to avoid compatibility issues. Each FG version then knows which directory to reference.
    * Put the files into Terrasync/Models instead and make sure that as the atlas evolves only new stuff is added and each sub-texture has a "known FG minimal version" number.

`The WikiPedia list of the largest buildings <https://en.wikipedia.org/wiki/List_of_largest_buildings>`_ has buildings with up to 2000 m in one direction. 1000 m in one direction is still unusual, but down to 500 m it gets more common - and therefore osm2city should be able to handle it consistently. See also the `List of tallest buildings <https://en.wikipedia.org/wiki/List_of_tallest_buildings>`_

.....................................
High Office Buildings and Skyscrapers
.....................................

For all but very high buildings we can manage vertical scale within texture. Therefore it makes sense to have the texture for high and very high buildings separate. That texture can in general also be used for office buildings. Horizontal scale is not known - and therefore these skyscraper textures should be x-repeatable. Skyscrapers should have the possibility for a special ground floor (often ca. 2 times floor height) handling and special handling of the top (often also 2-3 times floor height).
NB: this is not for apartment buildings, as they typically have lower floor height and have a facade with clear entries/staircase dividing the building.

Proposal:

* 1 special atlas file (8k x 256 pixels)
* 20 cm per pixel
* Normal floors: 4 metres / floor height => 20 pixels
* Ground floor: 6 metres height => 30 pixels
* Top floor: x metres => 26 pixels, which can be stretched (allowing some variations between buildings). Often no top floor for buildings with relatively few floors
* Use 10 floors per texture, which should fit most commercial buildings / industry offices etc.
* Resulting in 10*20 pixels plus 30 pixels plus 26 pixels = 256 pixels per texture => 32 different textures in 8k
* Use a width of 256 pixels, i.e. ca. 50 metres should allow to repeat in x-direction without looking wrong

Special handling in osm2city:

* The facade needs to be split into 2 parts in vertical direction, such that the ground floor and the stuff in the middle vs. the top floor can be handled accordingly (if the middle has more than 10 floors, then more parts are needed).
* Do not have roofs in texture -> separate mesh


...............................................
Long Offices, Retail, Warehouse, etc. Buildings
...............................................

Textures for buildings, which are large especially in the horizontal dimension. E.g. industry, office buildings, ware-houses, hospitals, retail/malls, airport terminals, parking-houses, etc. The commonality with all these textures is that they can be repeated in x-direction and should represent a whole facade (ground level, other levels)

Proposal:

* 2 special atlas files (512 x 8 k pixels): one for "modern" and one for "old/brick and mortar"
* 20 cm per pixel (typically, can be overridden e.g. in vertical direction for modern warehouses)
* Normal floors: determined by texture, often 4 metres / floor => 20 pixels
* Ground floors: determined by texture
* Given that most of these buildings would be 5 floors (20 m) or less - i.e. 100 pixels, there could be up to 80 distinct textures.

Special handling in osm2city:

* If facade turns out not to be high enough, then need to split vertically
* Do not have roofs in texture -> separate mesh


........
The Rest
........

Contains textures for a variety of objects:

* (European) city buildings / apartment buildings / smaller buildings (like family houses)
* special stuff modelled in code by osm2city (e.g. water towers, greenhouses, chimneys).

Proposal:

* 1 special atlas file with dimensions to the limit of the possible of most graphics cards ca. 2016 onwards (8k x 8k)
* Most often 10 cm per pixel, but can be defined individually
* On per texture level it can be specified, whether it is x-repeatable and where horizontal cuts can be done.
* On per texture level it can be specified, which levels can be cut (vertical cuts)
* The atlas is split into "sectors" with distinct size and with specific building types (e.g. city buildings)
* Each "sector" is split into "pods" with distinct size
* Each pod contains one or a set of textures. All these textures have the same geometry, type etc., but can be different in the looks (colour etc.).
* The sectors and pods have fixed positions and IDs in the atlas
* A pod corresponds to a file in the filesystem with a distinct name corresponding to the ID scheme. osm2city combines the single files into an atlas making sure that the atlas is always fixed in terms of where a given pod lives.
* In the beginning some pods might be empty - but they will already be allocated in the atlas scheme. That way over time more and more textures can be added to the atlas and osm2city will check which textures are available already. This necessitates like today that the atlases (also for skyscrapers / large buildings) are written as serialized Python objects by osm2city (texture) maintainers in a osm2city place for those who generate sceneries - and that the osm2city (texture maintainers) push the corresponding atlas images to TerraySync.

Special handling in osm2city:

* n/a

NB: details has its own texture atlas for stuff like cars, pylons and cabins for aerialways, platform roofs etc.


..............................
Roofs for Large Flat Buildings
..............................

Contains textures for the roofs of large buildings with flat roofs, because the textures for skyscrapers / large buildings do not have space for roof textures.

Proposal:

* 1 special atlas file (8192 x 256 pixels)
* 10 cm per pixel such that some lines (connections) and dirt can be modelled (but can be made stretchable as an attribute of the individual textures)
* Repeatable in x-direction
* 8 materials:
    * Concrete
    * Gravel
    * Solar panels
    * ?
    * 4 different coloured and sized sheets

Additionally, in the future it might be possible to handle these roofs with shaders:

* to show some structure like pipes, air conditioning, etc.
* to show obstruction lights instead of using the the current xml-file to show ``Models/Effects/pos_lamp_red_light_2st.xml`` on the top of high buildings.
* if the concept of "roof" is a bit abused, then this mesh could also include surfaces for signs/logos to be displayed in some variety during day and night instead of backing these into the facade textures (incl. light-map) of large buildings.


..........
Roof Tiles
..........

`Roof tiles <https://en.wikipedia.org/wiki/Roof_tiles>`_ come in different forms, colours etc. and are quite visible from above.

File ``osm2city-data/tex.src/roof_red3.png`` uses 8 pixels in width per tile and allows distinctive forms plus some dirt. Such a tile has a visible width of around 20 cm, so ca. 3 cm per pixel.

There are buildings with roof tiles, which are very long, but it is quite uncommon, that buildings with tiles are long along the gable. 20 metres might be pretty much the maximum (e.g. the abbey of St. Gallen), because many large roofs of churches are not made of tiles (e.g. copper, lead). Most of the time 10+ metres is enough (including considering steep roofs on large buildings. Therefore it should be enough to have only a few roof textures for up to 20 metres and the rest for up to 10 metres.

Proposed texture file:

* 1 pixel per 3 cm
* Repeatable in x-direction, fixed in y direction (if needed more than the max, then just stretch - should be very rare)
* Width: 256 pixel (ca. 8 metres, ca. 30 smaller tiles) -> allows to have some dirt and variation, but still small
* Height: 8192 pixels (8k):
    * 4 textures with 825 pixels (24+ m) plus 6 pixels = 3324 (e.g. one black and 3 different red)
    * 12 textures with 400 pixels (12 m) plus 6 pixels for gutter = 4872
* Leaves still e.g. 4 pixels per texture at the bottom to visualize a gutter


......................................
Other Roof Materials for Sloping Roofs
......................................

``osm2city-data/tex.src/roofs_default.py`` has the following materials:

* roof_tiles
* slate
* stone
* metal
* grass
* copper
* glass

Other material are e.g.:

* straw, seagrass
* laminated glass
* wood shakes and shingles
* asphalt, PVC, asbestos

See also `OSM roof:material <https://wiki.openstreetmap.org/wiki/Key:roof:material>`_ and `OSM tag info for roof:material <https://taginfo.openstreetmap.org/keys/?key=roof%3Amaterial#values>`_

``osm2city-data/tex.src/roof_gen_grey.png`` is an example of a metallic looking texture with ca. 1 cm per pixel. The same effect should be achievable with ca. 2 cm per pixel. For stone, wood, grass, straw the same might be needed.

Proposed texture file:

* 1 pixel per 3 cm
* repeatable in x-direction, fixed in y direction (if needed more than the max, then just stretch - should work for metal)
* Width: 256 pixel (ca. 5 metres) -> allows to have some dirt and variation for natural materials, but still small
* Height: 8192 pixels (8k)
    * 17 x 348 (ca. 7 metres):
        * 1 Grass
        * 2 Straw / seagrass
        * 3 wooden shingles
        * 1 glass
        * 1 waved PVC / plastic
        * 3 asbestos / eternit tiles / waved
        * 3 stone
        * 1 waved metal
        * 2 asphalt / rubber / tar paper
    * 4 x 512 pixels (ca. 10 metres):
        * 4 variations of metal (colour, size of plates)

-----------------------------------
Resulting Number of Meshes per Tile
-----------------------------------

Old scheme (assuming 4x4 km dimensions):
* Detailed: 3-5 * 3-5 = 9 - 25 meshes
* Rough: (ditto) -> 9 - 25 meshes
* Total: 18 - 50 meshes per tile

New scheme (assuming 4x4 km dimensions):
Assumption: the facade texture determines, whether BUILDING_ROUGH or BUILDING_DETAILED stg-verb is used.
Because roof textures can be used on large and small buildings, potentially the total of roof meshes is 2 times the
number of roof textures - e.g. 2*3=6

* BUILDING_ROUGH:
    * 1 mesh skyscrapers per tile
    * 2 meshes large buildings per tile (assuming we have 2 special textures)
    * up to 3 roof meshes
* BUILDING_DETAILED:
    * ca. 2 meshes other
    * up to 3 roof meshes

Total: 10-12 meshes
