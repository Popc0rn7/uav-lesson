"""平坦走廊：从雷达帧拟合地面，不依赖姿态或仿真真值。"""
import numpy as np


def estimate_height(points, sensor_z=.135):
    points=np.asarray(points,dtype=float)
    mask=np.isfinite(points).all(axis=1)&(points[:,2]<-.2)&(np.linalg.norm(points,axis=1)<8.)
    points=points[mask]
    if len(points)<100:return None
    rng=np.random.default_rng(7)
    sample=points[rng.choice(len(points),min(1200,len(points)),replace=False)]
    best=None;count=0
    for _ in range(48):
        a,b,c=sample[rng.choice(len(sample),3,replace=False)]
        normal=np.cross(b-a,c-a);norm=np.linalg.norm(normal)
        if norm<1e-6:continue
        normal/=norm
        if normal[2]<0:normal=-normal
        distance=-normal@a
        if normal[2]<.75 or not .2<distance<5:continue
        inliers=np.abs(sample@normal+distance)<.025
        if inliers.sum()>count:best=(normal,distance);count=int(inliers.sum())
    if best is None or count<.45*len(sample):return None
    normal,distance=best
    selected=points[np.abs(points@normal+distance)<.025]
    centre=selected.mean(axis=0)
    _,_,vectors=np.linalg.svd(selected-centre,full_matrices=False)
    normal=vectors[-1]
    if normal[2]<0:normal=-normal
    distance=-normal@centre
    rms=float(np.sqrt(np.mean((selected@normal+distance)**2)))
    height=float(distance-sensor_z*normal[2])
    if normal[2]<.75 or rms>.025 or not .1<height<4.5:return None
    return dict(height_m=height,rms_m=rms,inliers=len(selected),fraction=count/len(sample))
