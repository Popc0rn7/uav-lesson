"""Pillow-compatible uint8 bilinear resize with 22-bit fixed-point weights."""
import numpy as np


def resize_axis(array, size, axis):
    source = array.shape[axis]
    if source == size:
        return array
    scale = source/size
    support = max(1., scale)
    center = (np.arange(size)+.5)*scale
    left = np.maximum(0, (center-support+.5).astype(int))
    right = np.minimum(source, (center+support+.5).astype(int))
    count = right-left
    indices = left[:, None]+np.arange(int(count.max()))
    weights = np.maximum(0., 1-np.abs((indices-center[:, None]+.5)/support))
    weights *= indices < right[:, None]
    weights /= weights.sum(axis=1, keepdims=True)
    fixed = (weights*(1 << 22)+.5).astype(np.int64)
    indices = np.clip(indices, 0, source-1)
    shape = list(array.shape)
    shape[axis] = size
    result = np.empty(shape, np.uint8)
    if axis == 1:
        for row in range(0, array.shape[0], 8):
            selected = np.take(array[row:row+8], indices, axis=1).astype(np.int64)
            value = np.einsum('hwkc,wk->hwc', selected, fixed, optimize=True)
            result[row:row+8] = np.clip((value+(1 << 21)) >> 22, 0, 255)
    else:
        for row in range(0, size, 8):
            selected = np.take(array, indices[row:row+8], axis=0).astype(np.int64)
            value = np.einsum('hkwc,hk->hwc', selected, fixed[row:row+8], optimize=True)
            result[row:row+8] = np.clip((value+(1 << 21)) >> 22, 0, 255)
    return result


def resize_rgb(image, width, height):
    return resize_axis(resize_axis(image, width, 1), height, 0)
