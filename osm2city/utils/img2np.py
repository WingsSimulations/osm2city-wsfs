# SPDX-FileCopyrightText: (C) 2015 - 2019, rick@vanosten.net, radi
# SPDX-License-Identifier: GPL-2.0-or-later

import numpy as np
from PIL import Image
from copy import copy


def img2RGBA(img):
    """convert PIL image to individual np arrays for R,G,B,A"""
    n = np.array(img)/255.
    height_px, width_px = n.shape[:2]
    if len(n.shape) == 2:
        n_channels = 1
    else:
        n_channels = n.shape[2]
    
    zero = np.zeros((height_px, width_px))
    
    if n_channels == 1:
        R = copy(n)
        G = copy(zero)
        B = copy(zero)
        A = copy(zero) + 1.
    elif n_channels >= 3:
        R = copy(n[:,:, 0])
        G = copy(n[:,:, 1])
        B = copy(n[:,:, 2])
        if n_channels == 4:
            A = copy(n[:,:, 3])
        else:
            A = copy(zero) + 1.
    else:
        raise NotImplementedError("can't handle number of channels")
    return R, G, B, A


def RGBA2img(R, G, B, A=None):
    channels = "RGB"
    if A: channels = "RGBA"
        
    height_px, width_px = R.shape
    n = np.zeros((height_px, width_px, len(channels)))
    n[:,:, 0] = R  #* random.uniform(0.5, 1.0)
    n[:,:, 1] = G
    n[:,:, 2] = B
    if A: n[:,:, 3] = A
    #channel_name = 'RGBA'
    #for i, channel in enumerate([R, G, B, A]):
    #    print "%s: %1.2f %1.2f" % (channel_name[i], channel.min(), channel.max())
    
    out = (n*255).astype('uint8')
    return Image.fromarray(out, channels)
