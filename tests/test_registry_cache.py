import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import registry_cache  # noqa: E402
from district_keys import cache_stem  # noqa: E402


class RegistryBinaryArchiveTests(unittest.TestCase):
    def test_removed_h5_score_and_resume_checkpoint_are_archived(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            patches = root / "data/cache/district/sits_patches"
            scores = root / "data/cache/district/sits_scores"
            patches.mkdir(parents=True)
            scores.mkdir(parents=True)
            retained = cache_stem("E1::kept")
            removed = cache_stem("E2::removed")
            for path in (patches / f"{retained}.h5", patches / f"{removed}.h5",
                         patches / f"{removed}.h5.blocks.json",
                         scores / f"{removed}.npz"):
                path.write_bytes(b"cache")
            paths = {
                "district_sits_patches": patches,
                "district_sits_scores": scores,
            }
            archive = root / "data/archive/registry/old"
            registry = pd.DataFrame({"event_district_id": ["E1::kept"]})
            with patch.object(registry_cache, "ROOT", root), patch.object(
                    registry_cache, "data_path", lambda key: paths[key]):
                records = registry_cache.archive_removed_binary_caches(registry, archive)
            self.assertTrue((patches / f"{retained}.h5").exists())
            self.assertFalse((patches / f"{removed}.h5").exists())
            self.assertFalse((scores / f"{removed}.npz").exists())
            self.assertEqual(len(records), 3)
            self.assertTrue(all(Path(record["archive"]).exists() for record in records))


if __name__ == "__main__":
    unittest.main()
