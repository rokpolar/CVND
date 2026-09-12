import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import satellite as sat


class SplitReductionTests(unittest.TestCase):
    def run_reduction(self, force, fail_whole=False):
        region=SimpleNamespace(intersection=lambda rect,error:rect)
        grid=SimpleNamespace(sub_rects=lambda meters:[3,1,2])
        calls=[]
        def reduce(image,reducer,geom,grid,spec):
            calls.append(geom)
            if geom is region:
                if fail_whole: raise RuntimeError('User memory limit exceeded')
                return {'value':99}
            return {'value':geom}
        with patch.dict(sat.os.environ,{'CVND_SPLIT_FIRST':'1' if force else ''}), \
             patch.object(sat,'ee',SimpleNamespace(ErrorMargin=lambda n:n)), \
             patch.object(sat,'grid_rectangle',lambda grid,rect:rect), \
             patch.object(sat,'_reduce_region',reduce):
            result=sat.reduce_grid(None,None,region,grid,SimpleNamespace(reduce_split_m=50000),
                                   lambda parts:[r['value'] for r in parts])
        return result,calls,region

    def test_default_success_uses_whole_region(self):
        result,calls,region=self.run_reduction(False)
        self.assertEqual(result,{'value':99})
        self.assertEqual(calls,[region])

    def test_force_split_skips_whole_and_preserves_grid_order(self):
        result,calls,region=self.run_reduction(True)
        self.assertEqual(result,[3,1,2])
        self.assertNotIn(region,calls)
        self.assertCountEqual(calls,[3,1,2])

    def test_limit_fallback_preserves_partition_order(self):
        result,calls,region=self.run_reduction(False,True)
        self.assertEqual(result,[3,1,2])
        self.assertEqual(calls[0],region)
        self.assertCountEqual(calls[1:],[3,1,2])

if __name__=='__main__': unittest.main()
