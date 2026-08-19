.. _chapter-preparation-label:

#####################
Preparation [Builder]
#####################

Before ``osm2city`` related programs can be run to generate FlightGear scenery objects, the following steps need to be done:

#. :ref:`Creating a Directory Structure <chapter-creating-directory-structure-label>`
#. :ref:`Getting OpenStreetMap Data <chapter-getting-data-label>`
#. :ref:`Setting Minimal Parameters <chapter-setting-parameters-label>`
#. :ref:`Generating elevation data <chapter-generating-elevation-data-label>`

It is recommended to start with generating scenery objects for a small area around a smaller airport outside of big cities, such that manual errors are found fast. Once you are acquainted with all process steps, you can experiment with larger and denser areas.


.. _chapter-creating-directory-structure-label:

==============================
Creating a Directory Structure
==============================

The following shows a directory structure, which one of the developers is using — feel free to use any other structure.

::

    HOME/
        flightgear/
            fgfs_terrasync/
                Airports/
                Models/
                Objects/
                Terrain/
                terrasync-cache.xml
        development
            osm2city/
            osm2city-data/
            ...
        fg_customscenery/
            params.py
            KBOS/
                Buildings/
                    w080n40/
                        w071n42/
                            3105315.btg
                            w080n40_w071n42_1794312city00000.ac
                            ...
                Pylons/
                    ...
                Roads/
                    ...
            LSME/
                Buildings/
                    ...


The directory ``flightgear`` contains folder ``fgfs_terrasync``. This is where you have your default FlightGear scenery. The FlightGear Wiki has extensive information about TerraSync_ and how to get data. You need this data in folder, as ``osm2city`` only enhances the scenery with e.g. additional buildings or power pylons.

.. _TerraSync: http://wiki.flightgear.org/TerraSync

The directory ``development`` contains the ``osm2city`` programs and data after installation as explained in :ref:`Installation <chapter-parameters-label>`.

In the example directory structure above the directory ``fg_customscenery`` hosts the input and output information — here two sceneries for airports KBOS and LSME (however there is no need to structure sceneries by airports). The output of ``osm2city`` scenery generation goes into e.g. ``fg_customscenery/KBOS``.

The directory structure in the output folders (e.g. ``fg_customscenery/KBOS``) is created by ``osm2city`` related programs, i.e. you do not need to create it manually.

The directory ``.../fg_customscenery`` will be called ``WORKING_DIRECTORY`` in the following. This is important because ``osm2city`` related programs will have assumptions about this.


.. _chapter-getting-data-label:

==========================
Getting OpenStreetMap Data
==========================

The OpenStreetMap Wiki has comprehensive information_ about how to get OSM data. An easy way to start is using Geofabrik's extracts (http://download.geofabrik.de/).

It is highly recommend to limit the area covered as much as possible: it leads to faster processing and it is easier to experiment with smaller areas until you found suitable parameters. If you use Osmosis_ to cut the area with ``--bounding-box``, then you need to use ``completeWays=yes`` [#]_. E.g. on Windows it could look as follows:

::

    c:\> "C:\FlightGear\osmosis-latest\bin\osmosis.bat" --read-pbf file="C:\FlightGear\fg_customscenery\raw_data\switzerland-latest.osm.pbf"
         --bounding-box completeWays=yes top=46.7 left=9.75 bottom=46.4 right=10.0 --wx file="C:\FlightGear\fg_customscenery\projects\LSZS\lszs_wider.osm"


.. _information: http://wiki.openstreetmap.org/wiki/Downloading_data
.. _Osmosis: http://wiki.openstreetmap.org/wiki/Osmosis


.. _chapter-setting-parameters-label:

===================================
Setting a Minimal Set of Parameters
===================================

``osm2city`` has a large amount of parameters, by which the generation of scenery objects based on OSM data can be influenced. Chapter :ref:`Parameters <chapter-parameters-label>` has detailed information about the most important of these parameters[#]_. However to get started only a few parameters must be specified — actually it is generally recommended only to specify those parameters, which need to get a different value from the default values, so as to have a better understanding for which parameters you have taken an active decision.

Create a ``params.py`` file with your favorite text editor. In our example it would get stored in ``.../fg_customscenery`` and the minimal content could be as follows:

::

    PREFIX = "LSZS"
    PATH_TO_SCENERY = "/home/flightgear/fgfs_terrasync"
    PATH_TO_OUTPUT = "/home/fg_customscenery/LSZS"

    NO_ELEV = False
    DB_NAME = "swiss"



A few comments on the parameters:

PREFIX
    Needs to be the name of an existing folder in ``.../fg_customscenery/``. Do not use spaces in the name.

PATH_TO_SCENERY
    Full path to the scenery folder without trailing slash. This is where we will probe elevation and check for overlap with static objects. Most
    likely you'll want to use your TerraSync path here.

PATH_TO_OUTPUT
    The generated scenery files (.stg, .ac) will be written to this path — specified without trailing slash. If empty then the correct location in PATH_TO_SCENERY is used. Note that if you use TerraSync for PATH_TO_SCENERY, you MUST choose a different path here. Otherwise, TerraSync will overwrite the generated scenery. Unless you know what you are doing, there is no reason not to specify a dedicated path here. While not absolutely needed, it is good practice to name the output folder the same as ``PREFIX``. However, for WS3.0 you might often choose ``PATH_TO_OUTPUT`` to be the same as ``PATH_TO_SCENERY``.
NO_ELEV
    Set this to ``False``. The only reason to set this to ``True`` would be for builders to check generated scenery objects a bit faster not caring about the vertical position in the scenery.
DB_NAME
    The name of the database. See also connection settings for PostGIS: see :ref:`database parameters <chapter-parameters-database>`.


--------------------------
Advanced Parameter Setting
--------------------------
The parameter files are just regular Python files, the content of which is merged with the default parameters. This actually allows for some scripting, if you know very basic Python programming.

The parameter ``AREA`` has been added with the sole purpose of helping you reuse some parameters, while having some saved for special areas. This saves the trouble of having different parameter files for different areas.

The following is an example of how that can be used, where the only change between two generations is that I have to update ``AREA`` to be either "HAWAII" or "SCOTLAND". NB: "..." in the example below is just to tell that there would be other parameters - you must not have it in your file.

::

    AREA = 'HAWAII'
    ...
    OWBB_USE_EXTERNAL_LANDUSE_FOR_BUILDING_GENERATION = True
    OWBB_LANDUSE_CACHE = True
    ...

    if AREA == 'HAWAII':
        OWBB_GENERATE_BUILDINGS = True
        OWBB_USE_BTG_LANDUSE = True
        ...

    elif AREA == 'SCOTLAND':
        OWBB_USE_EXTERNAL_LANDUSE_FOR_BUILDING_GENERATION = False
        ...

The drawback of this advanced parameter setting is, that you might get difficult to interpret error messages, if you do something wrong. Python knowledge helps in that case.

If you want to use your own variables, then make sure you prefix them with "_" (underscore) - otherwise the process will abort immediately because an unknown parameter was found.

.. _chapter-generating-elevation-data-label:

=========================
Generating Elevation Data
=========================

``osm2city`` uses scenery elevation data from the FlightGear sceneries (TerraSync) for two reasons:

* No need to get additional data from elsewhere.
* The elevation of the generated scenery objects need to be aligned with the underlying scenery data (otherwise houses could hover over the ground or be invisible because below ground level).

This comes at the cost that elevation data must be read from scenery data using the utility program ``fgelev``, i.e. yet another sub-process and a bit of time consumption.

NB:

* The scenery data needed for your area might not have been downloaded yet by TerraSync, e.g. if you have not yet "visited" a specific tile. An easy way to download large areas of data is by using TerraMaster_. If you are exclusively using TerraMaster_ to download data, then make sure that you in TerraMaster also use button "Synchronise shared models".
* Make sure not to download osm2city data (buildings, roads, pylons). Otherwise, the new buildings etc. will be duplicated and other side effects could occur (e.g. elevation on top of existing buildings).

.. _TerraMaster: http://wiki.flightgear.org/TerraMaster

.. _chapter-elev-modes-label:


.. [#] Failing to do so might result in an exception, where the stack trace might contain something like ``KeyError: 1227981870``.
.. [#] Many parameters are self-explanatory by their name. Otherwise have a look at the comments in parameters.py
