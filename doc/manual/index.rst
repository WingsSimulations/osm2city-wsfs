
Welcome to osm2city's documentation!
====================================

--------------
About osm2city
--------------

``osm2city`` can generate 3D scenery on top of `World Scenery 2.0 (WS2) <https://wiki.flightgear.org/FlightGear_World_Scenery_2.0>`_ and `World Scenery 3.0 (WS3) <https://wiki.flightgear.org/World_Scenery_3.0>`_ for `FlightGear <https://www.flightgear.org/>`_. The focus of development has since ca. 2024 only been an WS3 and therefore some features are only available for WS3.

Elements of generated scenery are e.g.:

* Different kinds of buildings
* Roads, railways incl. bridges and embankments
* Aerialways, electrical power lines, pylons of different kinds, chimneys, oil and gas tanks, railway overhead lines
* Transportation platforms and piers
* Trees in urban areas
* Maritime seamarks, lights

Scenery can be generated for the whole world and adapted to the whole world by a large set of parameters .

The basis of this scenery generation are:

* Elevation data: taken from the underlying FlightGear scenery
* Topology data: taken from `OpenStreetMap (OSM) <https://www.openstreetmap.org>`_
* Parameters: to adapt the generation to the whole world (e.g. the distribution of roof types, materials, colours)
* Heuristics: established over the years by the developers of ``osm2city``.
* Interfaces in FlightGear: e.g. for placing shared objects from the `FG scenery website <https://scenery.flightgear.org/models>`_, using shaders for lights, specifying buildings drawn with a shader instead of 3D meshes, etc.

Given that the quality of OSM data in the world depending on the region can be quite low, ``osm2city`` can generate missing buildings (the most visible scenery feature) based on heuristics.


--------------------
Scenery distribution
--------------------

The main distribution channel of ``osm2city`` scenery is the FlightGear built-in `TerraSync <https://wiki.flightgear.org/TerraSync>`_. It covers the whole world.

Proof of Concept sceneries can be downloaded and installed locally by the users.

The scenery in TerraSync is often somewhat dated in terms of data freshness (especially OSM) and features / bug fixes from ``osm2city``. The root cause of this is that it needs thousands for compute hours and hundreds of GB of data to re-generate the whole world.


------------------
This Documentation
------------------

Before you generate your own sceneries, you might want to get familiar with the output of ``osm2city`` by first deploying some of the downloadable osm2city sceneries and have a look at chapter :ref:`Using Generated Scenery <chapter-using-label>`. See amongst others `Areas populated with osm2city scenery <http://wiki.flightgear.org/Areas_populated_with_osm2city_scenery>`_ or look for announcements in the Sceneries_ part of the FlightGear Forums.

.. _Sceneries: http://forum.flightgear.org/viewforum.php?f=5

``User`` in the context of this guide means the end user in FlightGear using osm2city generated sceneries. ``Builder`` means a person using osm2city to generate a scenery.

**Contents:**

.. toctree::
   :maxdepth: 2
   
   using
   installation
   preparation
   generation
   parameters
   how_it_works
   appendix


**Indices and tables:**

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
