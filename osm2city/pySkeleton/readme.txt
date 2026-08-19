#================================================================================
# pySkeleton: version 1.0
# Author: Olivier Teboul
# contact: olivier.teboul@ecp.fr
#================================================================================

This is a prototype software that implements weighted straight skeleton algorithm.
It allows to draw, load and save a polygon, with or without holes, and compute its the straight skeleton.

To start the software, just launch pySkeleton.py !!

To draw a polygon, just click point in a clock-wise order. To close the polygon, press "Enter"
To close a loop, press z.
To draw a hole in the polygon, click the point in counter clock-wise order.

The rest is pretty straightforward since the commands are given by the gui. 

Comments:
1. The search of events is not optimized by a heap yet. therefore the computation could be faster.
2. There is a known bug: if two or more split events occurs at the same time and place, the computation will fail.
3. The 3D roof button can be used only we Google Sketchup. It produces a 3D model of a roof.
4. The face command is currently using graphviz in order to represent the straight skeleton as a tree. This option can be disable in the code. Alternatively, 
you can download this nice library at graphviz.org.

Feel free to contact me if you want to submit an improved version of the code, or if you have any comments.

PLEASE: if you use this software or the underlying librairies for scientific purposes, I kindly ask you to explicitely refer to Olivier Teboul's implementation of
(weighted straight skeletons).