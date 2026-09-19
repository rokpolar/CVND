"""The recorded source tree must distinguish staged and untracked changes."""
import subprocess
import sys
import tempfile
import unittest
import importlib.util
import json
from unittest.mock import patch
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from run_provenance import source_record

spec = importlib.util.spec_from_file_location('build_analysis_package',
    Path(__file__).resolve().parents[1] / 'scripts/build_analysis_package.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class ProvenanceTests(unittest.TestCase):
    def test_package_rejects_stale_analysis_before_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            primary, sensitivity = root / 'primary', root / 'sensitivity'
            for path, days in ((primary, 30), (sensitivity, 14)):
                path.mkdir()
                pd.DataFrame({'window_days': [days], 'analysis_eligible': [True]}).to_csv(
                    path / 'district_flood_articles.csv', index=False)
                pd.DataFrame({'model': ['model_2']}).to_csv(path / 'coverage_model_results.csv', index=False)
                (path / 'coverage_summary.json').write_text(json.dumps({'input_sha256': 'stale'}))
            with patch.multiple(package, ROOT=root, PRIMARY_DATA=primary, PRIMARY_OUTPUT=primary,
                                SENSITIVITY_DATA=sensitivity, SENSITIVITY_OUTPUT=sensitivity), \
                 patch.object(package, 'source_record', return_value={'source_tree_sha256': 'current'}):
                with self.assertRaisesRegex(ValueError, 'Stale analysis'):
                    package.main()
            self.assertFalse((primary / 'analysis_manifest.json').exists())

    def test_fractional_window_rejected_and_empty_results_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'input.csv'
            pd.DataFrame({'window_days': [30.5], 'analysis_eligible': [True]}).to_csv(path, index=False)
            with self.assertRaises(ValueError):
                package.input_record(path, 30)
            pd.DataFrame(columns=['model', 'term', 'se_type', 'p_value', 'n']).to_csv(path, index=False)
            rows = package.preferred_rows(path, '30-day primary')
            self.assertTrue(rows.empty)
            self.assertIn('effect_size', rows)
            package.write_figure(rows, Path(temp) / 'empty.png')

    def test_staged_and_untracked_sources_change_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def git(*args):
                subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)
            git('init')
            (root / 'src').mkdir()
            path = root / 'src/a.py'
            path.write_text('a = 1\n')
            git('add', '.')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'fixture')
            initial = source_record(root)
            path.write_text('a = 2\n')
            git('add', '.')
            staged = source_record(root)
            self.assertNotEqual(initial['source_tree_sha256'], staged['source_tree_sha256'])
            self.assertNotEqual(initial['source_diff_sha256'], staged['source_diff_sha256'])
            (root / 'src/b.py').write_text('b = 3\n')
            untracked = source_record(root)
            self.assertNotEqual(staged['source_tree_sha256'], untracked['source_tree_sha256'])
            self.assertIn('src/b.py', untracked['source_files_sha256'])
