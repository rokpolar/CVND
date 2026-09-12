import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import satellite


class Value:
    def __init__(self, value): self.value = value
    def getInfo(self): return self.value


class Collection:
    def __init__(self, features): self.features = features
    def filter(self, criterion):
        field, value = criterion
        return Collection([f for f in self.features if f['properties'].get(field) == value])
    def size(self): return Value(len(self.features))
    def getInfo(self): return {'features': self.features}


class FakeGaul:
    class Filter:
        @staticmethod
        def eq(field, value): return field, value
    def __init__(self, names):
        self.features = [{'properties': {'ADM0_NAME': 'India', 'ADM1_NAME': state,
                          'ADM2_NAME': name, 'ADM2_CODE': code}}
                         for state, name, code in names]
    def FeatureCollection(self, asset): return Collection(self.features)


class SpacingTests(unittest.TestCase):
    def resolve(self, names, district='Barabanki'):
        row = {'state': 'Uttar Pradesh', 'district': district, 'event_district_id': 'E1::b'}
        with patch.object(satellite, 'ee', FakeGaul(names)):
            return satellite._feature_collection_for_aoi(row)

    def test_unique_spacing_uses_exact_code(self):
        result = self.resolve([('Uttar Pradesh', 'Bara Banki', 17896)])
        self.assertEqual(result.getInfo()['features'][0]['properties']['ADM2_CODE'], 17896)

    def test_compact_name_collision_rejected(self):
        with self.assertRaises(ValueError):
            self.resolve([('Uttar Pradesh', 'Bara Banki', 1), ('Uttar Pradesh', 'Barab Anki', 2)])

    def test_other_state_not_matched(self):
        with self.assertRaises(ValueError):
            self.resolve([('Assam', 'Bara Banki', 1)])

    def test_typo_not_fuzzy_matched(self):
        with self.assertRaises(ValueError):
            self.resolve([('Uttar Pradesh', 'Bara Banki', 1)], 'Barabank')

    def test_diacritics_not_stripped(self):
        with self.assertRaises(ValueError):
            self.resolve([('Uttar Pradesh', 'São José', 1)], 'Sao Jose')


if __name__ == '__main__':
    unittest.main()
