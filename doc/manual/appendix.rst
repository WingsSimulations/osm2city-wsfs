.. _chapter-appendix-label:

########
Appendix
########


=====================
Developer Information
=====================

-------------
Documentation
-------------

You need to install Sphinx_. All documentation is written using reStructuredText_ and then made available on `Read the Docs`_.

Change into ``doc/manual`` and then run the following command to test on your local machine:

::

    $ sphinx-build -b html . build


.. _Sphinx: http://www.sphinx-doc.org
.. _reStructuredText: http://docutils.sourceforge.net/rst.html
.. _Read the Docs: https://readthedocs.org/


----------
Developing
----------

An unstructured list of stuff you might need to know as a developer:

* The code has evolved over time by contributions from persons, who are not necessarily professional Python developers. Whenever you touch or even only read a piece of code, please leave the place in a better state by adding comments with your understanding, refactoring etc.
* The level of unit testing is minimal and below what is achievable. There is no system testing. All system testing is done in a visual way - one of the reasons being that the scenery generation has randomising elements plus parametrisation, which means there is not deterministic right solution even from a regression point of view.
* Apart from testing the results in FlightGear by flying around with e.g. the UFO_, a few operations make use of a parameter ``DEBUG_PLOT_*``, which plots results to a pdf-file:

  * ``DEBUG_PLOT_RECTIFY``: Examples of rectified building floor plans
  * ``DEBUG_PLOT_GENBUILDINGS``: Result of generating buildings
  * ``DEBUG_PLOT_LANDUSE``: Different aspects of land-use
  * ``DEBUG_PLOT_ROADS``: Different plots for aspects of roads processing
  * ``DEBUG_PLOT_OFFSETS``: Showing offsets when placing rectangle (utility function)
* Use an editor, which supports `PEP 08`_. However the current main developer prefers a line length of 120 instead. You should be able to live with that.
* Use Python `type hints`_ as far as possible — and help improve the current situation. It might make the code a bit harder to read, but it gets so much easier to understand.
* Try to stick to the Python version as referenced in requirements.txt (cf. :ref:`chapter-python-label`).
* All code in utf-8. On Windows please make sure that line endings get correct in git (core.autocrlf)


-------------
Python vs C++
-------------

During winter 2021/2022 the land-use and trees functionality in osm2city was re-programmed in C++. These two modules take the longest time in processing and should therefore give an indication, whether C++ really would give a dramatic speed boost.

When most of the performance heavy code was ported, at test was done for comparison - because it began to appear that the speed improvements might not be so dramatic after all (in the beginning there were indications of a factor 5-10. The results are as follows:

===========  ========  ========  =============
Criteria     LSME      LSZH      Wäggitalersee
===========  ========  ========  =============
Python
Runtime      9 min     18 min    2 min
RAM core     0.63 G    1.2 G     0.13 G
RAM FGElev   1.5 G     1.5 G     1.5 G
C++
Runtime      2.5 min   11 min    0.5 min
RAM          0.22 G    0.4 G     0.1 G
===========  ========  ========  =============


Note that FGelev really takes a big toll - in C++ FGevlev would not be used, but instead directly loaded through SimGear. That would still have an impact at least on memory and also on runtime. Also osm2city made more processing (reading BTG files, 

The smaller than expected difference is most probably due to two things:

  * The really heavy calculations are for geometric operations. Shapely does a really good job in interfacing the native code in GEOS with Python.
  * What really matters to get time down for geometric operations is to devide into grids and reduce the loop sizes.
  * Processing trees (which is almost exclusively geometry operations took for LSZH almost the same time in Python and C++.
  
C++ clearly uses less resources (e.g. RAM) and still will be faster. But the difference is not that big to really give a large advantage for development (a bit more for generating the world scenery).


Python:

  * Good library support
  * More people know Python - also more "hobbyists"
  * Most of osm2city is done. Just do incremental improvements
  * Still areas around for speed improvements and reduction of resources
  * Found improvements / enhancements in C++ version can be ported relatively with low effort
  
C++:

  * Especially for smaller tiles the speed and resource usage is much better than Python. For tiles with lots of buildings etc. the difference seems to be smaller.
  * Can reuse code from SimGear - reduces development time and source of deviations
  * Might attract core developers more
  * Second time one builds something it gets better.
  * Stronger typing.
  * Disadvantages:
  
    * Still hundreds of hours to finalize land-use plus parametrization plus interface with Python
    * During transition phase it is quite difficult for others to use osm2city
    * Migrating building, pylons etc. code (probably not roads) will take many hundred hours if not thousands.
    

---------------
Protocol Buffer
---------------
``osm2city`` uses Google's `protocol buffer <https://developers.google.com/protocol-buffers>`_ to transfer data between modules of execution. This allows to have modules developed in a different language than Python for speed. Python's `pickle <https://docs.python.org/3/library/pickle.html>`_ is not language neutral.


.. _UFO: http://wiki.flightgear.org/UFO_from_the_%27White_Project%27_of_the_UNESCO
.. _PEP 08: https://www.python.org/dev/peps/pep-0008/
.. _type hints: https://docs.python.org/3/library/typing.html


==================
Status of osm2city
==================

-------
Overall
-------

osm2city is usable, documented, maintained and has enough features to make it an important part of the 3D experience in FlightGear.

However, not everything is just fine. E.g.

* Very few persons have contributed with code or other types of input
* The code base has many legacy elements - it has been refactored and partly restructured on the fly, but never been looked at with a fresh pair of eyes

--------------------------
Issues or Missing Features
--------------------------

Something like osm2city is never really complete. The GitLab organization for `osm2city <https://gitlab.com/osm2city>`_ includes a `list of work items <https://gitlab.com/groups/osm2city/-/work_items>`_ of varying details and a mix of feature requests and bugs.

Below are points that the main contributor of osm2city is aware of or believes to be important - some of which are also reflected in some sort in the work items.


..........
Versioning
..........

The textures used by osm2city and the meshes generated are directly related. Because the textures for osm2city have not been changed for maybe 10 years, this has not been a problem.

There cannot be done so much about this relationship. However (see below), there is a value in making a whole new set of textures (for buildings and roads/railways) to provide a much improved visual experience. Also, at some points there will things that should be done differently and therefore break existing meshes.

The challenge is that creating new world scenery is a lot of effort and cost - and so is storing and distributing (TerraSync) different versions. Making breaking changes should be tied to major changes in FlightGear - so the infrastructure, announcements etc. can be coordinated. The change from WS2 to WS3 is such a rare point - but even here for WS3 there are "tech previews".


.........
Buildings
.........

Interaction with WS3:

* The snow shader from WS2 for roofs is missing in WS3
* It is not yet clear/implemented how night lights would be done for glTF
* Different issues around elevation probing: `FGElev does not take airport elevation into account WS3.0 <https://gitlab.com/flightgear/flightgear/-/work_items/2919>`_


Textures for osm2city:

* How many different texture files may there be for roofs and facades? right now there is only one in ``fgdata/Textures/osm2city/``. More texture files results in more memory used and potentially more nodes in the scene graph. But it would also give much better results through variety of roofs, facade types (incl. more textures for special building types like warehouses). And it might make it possible to have regionalized textures (roofs might not need regionalization and neither generic modern buildings, but residential buildings might profit)
* It might be more ideal to distribute updates of osm2city textures through TerraSync than ``fgdata`` - because then updates can be made incrementally (as long as the "contract" between the texture file and osm2city is fixed)
* ORM for existing textures have not been created - and maybe SimGear needs to "know" that facades and roofs have ORM.

Once above could be settled, then it makes sense to get 2D artists working on textures. :ref:`chapter-how-texturing-works-label` has some examples - and ``covering.py`` has some ideas implemented.

......
Cables
......

* The current use of 3D faces has the advantage that aircraft can be damaged in cables. However, visually and computing/storage wise it would be better with a shader. The shader then also could make sure that only cables quite close by would be drawn.


..............
Roads/railways
..............

* More textures are needed for roads (e.g. 3-lines, 4-lines, grass, dirt)
* Snow shader from WS2 is missing in WS3
* The heuristics of WS3 roads and osm2city roads do not match. Also the visual appearance (shader) does not match for the same texture.
* The WS3 interface ``LINE_FEATURE_LIST``: there is a discussion on the mail list ca. June 2024 "WS3.0 linear features offset".

Due to the above points the idea of combining WS3 roads with embankments/bridges from osm2city will not give good results. Also, railway masts and lines from osm2city will not match the WS3 line feature. And therefore, roads/railways have not yet been ported to glTF.

...............
Parametrisation
...............

* Parametrisation overrides by regionalized files is not possible in C++ right now. I.e. everything is fixed.
* osm2city and osm2gear should use the same file format and features (e.g. distributions). that requires findings a suitable human readable format (e.g. YAML) and implement the parsing twice.


..............
Shared Objects
..............

* There should be more shared objects for highly visual elements - e.g. religious buildings for different religions
* Many shared objects should be checked for rotation, centre point, base elevation such that no individual compensations need to be made (see WorshipBuildings in building_lib.py)


............
WS3 Textures
............

* The ground textures for built-up areas show buildings, streets etc. This visually interferes with the buildings, roads, etc. placed on top by osm2city. See also :ref:`chapter-hide-urban-textures-label`.
* Textures for trees used by osm2city in urban areas are only available for very few regions in the world. It looks odd to have Western European style trees around houses in different climates.

.....
Piers
.....

* Piers can look weird with WS3, because the WS3 water near the coastline is not flat.
* Should use different materials for the surface (e.g. wood)
* Algorithm for placing boats is too primitive - and some shared objects for boats have wrong heading in the model


.........
Code Base
.........

* osm2city (Python), osm2gear (C++), Docker image etc. could live in one mono repo
* Ideally a mono-repo would live in `FlightGears GitLab structure <https://gitlab.com/flightgear>`_
