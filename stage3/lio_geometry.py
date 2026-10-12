"""Quaternion/frame transforms for LIO → course ENU → PX4 NED/FRD."""
import math
import numpy as np


def multiply(a,b):
    x,y,z,w=a;X,Y,Z,W=b
    return np.array([w*X+x*W+y*Z-z*Y,w*Y-x*Z+y*W+z*X,w*Z+x*Y-y*X+z*W,w*W-x*X-y*Y-z*Z])


def matrix(q):
    x,y,z,w=q
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                     [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                     [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])


def enu_flu_to_ned_frd(q):
    x,y,z,w=q;h=math.sqrt(.5)
    return [h*(w+z),h*(x+y),h*(x-y),h*(w-z)]  # PX4 w,x,y,z


def course_alignment(q):
    """Set initial heading to +Y while preserving the LIO gravity direction."""
    x,y,z,w=q
    yaw=math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))
    angle=math.pi/2-yaw
    return np.array([0.,0.,math.sin(angle/2),math.cos(angle/2)])
