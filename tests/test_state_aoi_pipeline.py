import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import compute_population  # noqa: E402
import merge_results  # noqa: E402


class StateAoiPipelineTests(unittest.TestCase):
    def test_population_uses_aoi_area_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {
                "flood_combined": root / "flood.csv",
                "events": root / "events.csv",
            }
            pd.DataFrame(
                [{
                    "event_id": "E001",
                    "combined_km2": 100.0,
                    "aoi_km2": 1000.0,
                    "flood_ratio": 0.1,
                    "combined_source": "S1",
                }]
            ).to_csv(paths["flood_combined"], index=False)
            pd.DataFrame(
                [{"event_id": "E001", "state": "Assam", "district": "Assam", "start_date": "2020-01-01"}]
            ).to_csv(paths["events"], index=False)

            with patch.object(compute_population, "data_path", side_effect=lambda key: paths[key]):
                result = compute_population.from_flood_combined(
                    {"Assam": 10_000}, {"Assam": 2_000}
                )

            self.assertEqual(result.loc[0, "aoi_km2"], 1000.0)
            self.assertEqual(result.loc[0, "population_exposed"], 500)
            self.assertNotIn("district_km2", result.columns)

            # exposure_rate and population_exposed must come from the SAME
            # flooded fraction. They were computed from different denominators
            # (aoi_km2 vs state_area_km2), so rate * population did not equal
            # the reported exposure -- by whatever the two areas differ by.
            rate = result.loc[0, "exposure_rate"]
            pop = 10_000
            self.assertAlmostEqual(rate * pop,
                                   result.loc[0, "population_exposed"], places=3)
            # and the mismatch between AOI and state area is surfaced, not hidden
            self.assertIn("AOI AREA DIFFERS", result.loc[0, "warnings"])

    def test_merge_results_emits_aoi_area(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scores = root / "scores"
            scores.mkdir()
            track = root / "track.csv"
            cloud = root / "cloud.csv"
            area = root / "area.csv"
            output = root / "combined.csv"
            pd.DataFrame(
                [{
                    "event_id": "E001",
                    "area_s1_km2": 25.0,
                    "area_s2_km2": None,
                    "s2_post_images": 0,
                }]
            ).to_csv(track, index=False)
            pd.DataFrame([{"event_id": "E001", "cloud_pct": 100.0}]).to_csv(cloud, index=False)
            pd.DataFrame([{"event_id": "E001", "aoi_km2": 500.0}]).to_csv(area, index=False)

            with (
                patch.object(merge_results, "SCORES_DIR", str(scores)),
                patch.object(merge_results, "TRACK_A_CSV", str(track)),
                patch.object(merge_results, "POST_CLOUD_CSV", str(cloud)),
                patch.object(merge_results, "AOI_AREA_CSV", str(area)),
                patch.object(merge_results, "OUT_CSV", str(output)),
            ):
                merge_results.main()

            result = pd.read_csv(output)
            self.assertEqual(result.loc[0, "aoi_km2"], 500.0)
            self.assertEqual(result.loc[0, "flood_ratio"], 0.05)
            self.assertNotIn("district_km2", result.columns)


if __name__ == "__main__":
    unittest.main()
