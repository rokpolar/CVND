import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pipeline_preflight  # noqa: E402
from flood_spec import SPEC_VERSION  # noqa: E402


class PreflightTests(unittest.TestCase):
    def test_stale_spec_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            aoi = root / "district_aoi.csv"
            extent = root / "flood_extent.csv"
            pd.DataFrame([{"event_district_id": "E1::a", "aoi_level": "district",
                           "aoi_match_status": "matched", "aoi_area_km2": 10.0,
                           "spec_version": SPEC_VERSION}]).to_csv(aoi, index=False)
            pd.DataFrame([{"event_district_id": "E1::a", "aoi_level": "district",
                           "aoi_match_status": "matched"}]).to_csv(extent, index=False)
            paths = {"district_aoi": aoi, "district_flood_extent": extent}
            with patch.object(pipeline_preflight, "data_path",
                              lambda key: paths.get(key, root / f"absent_{key}.csv")):
                rows = {r["artifact"]: r for r in pipeline_preflight.inspect_artifacts()}
                self.assertEqual(rows["district_aoi"]["status"], "present")
                self.assertEqual(rows["district_flood_extent"]["status"], "stale_spec")
                self.assertEqual(rows["district_flood_area"]["status"], "missing")
                self.assertEqual(pipeline_preflight.main(["--strict"]), 1)


if __name__ == "__main__":
    unittest.main()
