.. _chapter-installation-label:

######################
Installation [Builder]
######################

The following specifies software and data requirements as part of the installation. Please be aware that different steps in scenery generation (e.g. generating elevation data, generating scenery objects) might require a lot of memory and are CPU intensive. Either use decent hardware or experiment with the size of the sceneries. However it is more probable that your computer gets at limits when flying around in FlightGear with sceneries using ``osm2city`` than when generating the sceneries.

============
The Easy Way
============

Safe yourself some trouble and use the `Docker container for osm2city <https://gitlab.com/osm2city/container-image-for-o2c>`_, which has everything installed with compatible versions.

Alternatively: Read on below and maybe supplement with the recipe in the Docker container's Dockerfile.

==============
Pre-requisites
==============


.. _chapter-python-label:

------
Python
------

``osm2city`` is written in Python and needs Python for execution. Python is available on all major desktop operating systems — including but not limited to Windows, Linux and Mac OS X. See http://www.python.org.

The minimal Python version is mentioned in file ``pyproject.toml`` (e.g. ``requires-python = ">=3.12"``).

--
uv
--

``uv`` is used as the Python package and project manager. Install ``uv`` using the `installation guide <https://docs.astral.sh/uv/getting-started/installation/>`_ for your operating system.


.................
Protobuf Compiler
.................

Only relevant if you are actively developing osm2city: osm2city uses the `proto3 <https://developers.google.com/protocol-buffers/docs/proto3>`_ version of the protocol buffers language. Install a recent protobuf compiler: either a `release package <https://github.com/protocolbuffers/protobuf/releases>`_ or alternatively a package from your linux distro.


.. _chapter-osm2city-install:

========================
Installation of osm2city
========================

There is no installer package - neither on Windows nor Linux. ``osm2city`` consists mainly of a set of Python programs and the related data in ``osm2city-data``. You need both.

--------
Download
--------

Download the necessary files either using `Git <https://www.git-scm.com/>`_ or as a zip-package from https://gitlab.com/osm2city/osm2city and https://gitlab.com/osm2city/osm2city-data.


------------------------------------
Setup the Virtual Python Environment
------------------------------------

You need a local environment, which has all dependencies installed. Open a shell and change into the ``osm2city`` directory (it will amongst others contain a folder ``osm2city``, a folder ``doc``). Execute:

::

    ~/develop_vcs/osm2city$ uv sync


--------------------------
Compiling the protobuffers
--------------------------
Only relevant if you are actively developing osm2city:

#. Execute ``~/develop_vcs/osm2city$ protoc --proto_path=../osm2gear --python_out=osm2city/proto ../osm2gear/buildings.proto`` (adapt the path to your setup)
#. Execute ``~/develop_vcs/osm2city$ protoc --proto_path=../osm2gear --python_out=osm2city/proto ../osm2gear/blocked_areas.proto`` (adapt the path to your setup)



.. _chapter-set-pythonpath-label:

------------------
Setting PYTHONPATH
------------------
You can read more about this at https://docs.python.org/3.12/using/cmdline.html#envvar-PYTHONPATH.

On Linux you would typically add something like the following to your ``.bashrc`` file:

::

    PYTHONPATH=$HOME/develop_vcs/python3/osm2city
    export PYTHONPATH



--------------------------------------
Installation of SimGear and FlightGear
--------------------------------------
Compiling and running ``osm2gear`` has only been done on a recent Ubuntu version on x86/64-bit.

As basis the following is built on Linux using `download_and_compile <https://wiki.flightgear.org/Scripted_Compilation_on_Linux_Debian/Ubuntu>`_ on Linux:

::

    ~/bin/flightgear/dnc-managed$ ../fgmeta/download_and_compile.sh -j 4 FGDATA SIMGEAR FGFS OSG

This is needed, as the CMakeLists.txt expects it to be present - and you need to update the path.

For generating osm2city scenery for WS3.0 you need to be on FlightGear ``Next`` and a version after end of November 2024.
.. due to https://sourceforge.net/p/flightgear/codetickets/2901/


.. _chapter-set-fgroot-label:

----------------------------------------------
Setting Operating System Environment Variables
----------------------------------------------
The environment variable ``$FG_ROOT`` must be set in your operating system or at least your current session, such that ``fgelev`` can work optimally. How you set environment variables is depending on your operating system and not described here. I.e. this is NOT something you set as a parameter in ``params.ini``!

You might have to restart Windows to be able to read the environment variable that you set through the control panel. In Linux you might have to create a new console session.

`$FG_ROOT`_ is typically a path ending with directories ``data`` or ``fgdata`` (e.g. on Linux it could be ``/home/pingu/bin/fgfs_git/next/install/flightgear/fgdata``; on Windows it might be ``C:\flightGear\2017.3.1\data``).

BTW: you have to set the name of the variable in your operating system to ``FG_ROOT`` (not ``$FG_ROOT``).

.. _$FG_ROOT: http://wiki.flightgear.org/$FG_ROOT

Apart from ``FG_ROOT`` you also need to set the following environment variables:

* ``FG_INSTALL`` - e.g. /home/pingu/bin/flightgear/dnc-managed/install (this makes the critical assumption that FLightGear has been installed as specified above)
* ``O2C_PATH_TO_FG_ELEV`` - e.g. /home/pingu/bin/flightgear/dnc-managed/install/flightgear/bin/fgelev
* ``O2C_OVERPASS_API`` - https://overpass-api.de/api/interpreter
* ``O2C_OVERPASS_MAX_RETRIES`` - e.g. 3 (integer)
* ``O2C_OVERPASS_RETRY_DELAY`` - e.g. 10 (float - seconds)
* ``O2C_OVERPASS_BACKOFF_FACTOR`` - e.g. 1.2 (float - each time a retry is needed, the delay is multiplied again by this number)
* ``O2C_OVERPASS_CONNECT_TIMEOUT`` - e.g. 10 (integer - seconds)
* ``O2C_OVERPASS_READ_TIMEOUT`` - e.g. 120 (integer - seconds)
* ``O2C_PATH_TO_O2G`` - e.g. /home/pingu/develop_vcs/osm2gear/cmake-build-debug/osm2gear
* ``O2C_PATH_TO_DATA`` - e.g. /home/pingu/develop_vcs/osm2city-data
* ``LD_LIBRARY_PATH`` - e.g. /home/pingu/bin/flightgear/dnc-managed/install/simgear/lib:/home/pingu/bin/flightgear/dnc-managed/install/openscenegraph/lib:/home/pingu/bin/flightgear/dnc-managed/install/openrti/lib:/home/pingu/bin/flightgear/dnc-managed/install/plib/lib:$LD_LIBRARY_PATH

Choose one of the public `Overpass API <https://wiki.openstreetmap.org/wiki/Overpass_API#Public_Overpass_API_instances>`_ instances. Alternatively you can `install <https://wiki.openstreetmap.org/wiki/Overpass_API/Installation>`_ you own instance og Overpass API locally

.. _chapter-helpers-install:

===========
Other Tools
===========

----
JOSM
----

``JOSM`` is an offline editor for OSM-data. It is not required for pre- or post-processing of ``osm2city``, but it might be handy for debugging and detailed investigations.

Information about JOSM including installation instructions can be found at https://josm.openstreetmap.de/.
