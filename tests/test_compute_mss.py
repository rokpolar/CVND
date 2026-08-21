import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pandas as pd


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import compute_mss  # noqa: E402


class ComputeMssTests(unittest.TestCase):
    def test_zero_article_event_is_retained_with_zero_mss(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {
                "gdelt_bq": root / "gdelt.json",
                "events": root / "events.csv",
                "mss_results": root / "mss.csv",
                "mss_weight_meta": root / "weights.json",
                "mss_weight_provenance": root / "provenance.csv",
                "mss_rank_stability": root / "ranks.csv",
            }
            pd.DataFrame(
                [
                    {"event_id": "E001", "state": "Assam", "start_date": "2020-01-01", "income_group": "Low"},
                    {"event_id": "E002", "state": "Odisha", "start_date": "2020-02-01", "income_group": "Low"},
                ]
            ).to_csv(paths["events"], index=False)
            rows = [
                {
                    "event_id": "E001",
                    "state": "Assam",
                    "source_record_id": "2020-0001-IND",
                    "source_lang": "en",
                    "article_count": 2,
                    "first_article_date": "2020-01-01",
                    "last_article_date": "2020-01-02",
                    "coverage_days": 2,
                }
            ]
            paths["gdelt_bq"].write_text(json.dumps(rows), encoding="utf-8")

            with (
                patch.object(compute_mss, "data_path", side_effect=lambda key: paths[key]),
                redirect_stdout(io.StringIO()),
            ):
                compute_mss.main()

            result = pd.read_csv(paths["mss_results"]).set_index("event_id")
            self.assertEqual(result.loc["E001", "total_articles"], 2)
            self.assertEqual(result.loc["E002", "total_articles"], 0)
            self.assertEqual(result.loc["E002", "MSS"], 0.0)


if __name__ == "__main__":
    unittest.main()
