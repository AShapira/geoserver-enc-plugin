import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from tune_cache import plan,REGIONS,tile_range

class SeedPlanTests(unittest.TestCase):
    def test_plan_bounds_metatile_expansion_and_deduplicates(self):
        p=plan(REGIONS,11,13,['day','dusk','night'])
        self.assertLessEqual(p['maximum_generated_tiles'],2048)
        self.assertEqual(p['metatiles']*16,p['maximum_generated_tiles'])
        self.assertLessEqual(p['requested_tiles'],p['maximum_generated_tiles'])
        duplicated=plan({'one':REGIONS['new-york'],'two':REGIONS['new-york']},11,13,['day'])
        single=plan({'one':REGIONS['new-york']},11,13,['day'])
        self.assertEqual(single['requested_tiles'],duplicated['requested_tiles'])
    def test_invalid_world_extents_and_extreme_zooms_rejected(self):
        with self.assertRaises(ValueError):plan({'bad':[180,0,-180,1]},1,2,['day'])
        with self.assertRaises(ValueError):plan(REGIONS,0,23,['day'])
        self.assertEqual([0,0,1,1],tile_range([-1,-1,1,1],1))
