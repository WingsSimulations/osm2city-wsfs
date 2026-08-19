#!/bin/bash

PROG=gimp2tex.sh
USAGE="$PROG base_texture.png [..]"
DESC="For texture and lightmap, scale to pow2 and remove alpha channel"
HELP="<Zero or more lines of Help>"
AUTHOR="Thomas Albrecht"

[ "$1" == "" ] || [ "$1" == "-h" ] || [ "$1" == "--help" ] && \
    echo -e "Usage: $USAGE\n$DESC\n$HELP" && exit 1

set -u
scale=2048
noalpha="-background black -flatten +matte"
for f in $*; do
# Here follows your own code
    case=`echo $f | cut -d. -f1`
    convert ${case}.png    -scale ${scale}x${scale}\! $noalpha ${case}_pow2.png
    convert ${case}_LM.png -scale ${scale}x${scale}\! $noalpha ${case}_pow2_LM.png
done
