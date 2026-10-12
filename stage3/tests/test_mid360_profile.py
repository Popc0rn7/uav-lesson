"""Protect the physical MID-360 FoV boundary and nominal scan budget."""
import math
import shutil
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import generate_gazebo_corridor as generator


class Mid360Profile(unittest.TestCase):
    def test_official_fov_and_pattern_raster(self):
        # Generate fixtures privately: tests must not rewrite an active world's
        # models or depend on untracked output left by a previous Docker run.
        source=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'stage3';target.mkdir()
            shutil.copy2(source/'corridor_layout.json',target/'corridor_layout.json')
            for name in ('mid360s','x500_experiment'):
                model=target.parent/'stage2/models'/name;model.mkdir(parents=True)
                shutil.copy2(source.parent/'stage2/models'/name/'model.sdf',model/'model.sdf')
            for temporal in (False,True):
                with self.subTest(temporal=temporal), patch.object(generator,'ROOT',target), patch('sys.argv',['generator']+(['--temporal-scan'] if temporal else [])):
                    generator.main()
                    self.check_profile(target/'models/mid360/model.sdf',temporal)

    def check_profile(self,path,temporal):
        sensor=E.parse(path).find('.//sensor')
        ray=sensor.find('ray')
        self.assertAlmostEqual(float(ray.find('scan/vertical/min_angle').text),math.radians(-7))
        self.assertAlmostEqual(float(ray.find('scan/vertical/max_angle').text),math.radians(52))
        h=ray.find('scan/horizontal')
        width=int(h.find('samples').text)
        self.assertAlmostEqual(float(h.find('max_angle').text)-float(h.find('min_angle').text),2*math.pi*(1-1/width))
        self.assertEqual((width,int(ray.find('scan/vertical/samples').text),int(sensor.find('update_rate').text)),(1800,64,60) if temporal else (900,148,30))
        # The raster is a lookup backend; emitted sample budget is applied by
        # the SUPER-derived non-repeating angular mask in the C++ prefilter.


if __name__=='__main__':unittest.main()
