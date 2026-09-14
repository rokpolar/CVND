import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import copernicus_local as local


def test_odata_filter_is_direct_product_query():
    query = local.odata_filter("SENTINEL-2", "S2MSI2A", "2020-01-01", "2020-02-01",
                               box(70, 20, 71, 21), 80)
    assert "Collection/Name eq 'SENTINEL-2'" in query
    assert "productType" in query and "S2MSI2A" in query
    assert "cloudCover" in query
    assert "Intersects" in query


def test_odata_pagination_and_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(local, "CACHE", tmp_path)
    class Response:
        def __init__(self, payload): self.payload = payload
        def raise_for_status(self): pass
        def json(self): return self.payload
    class Session:
        def __init__(self): self.calls = 0
        def get(self, *args, **kwargs):
            self.calls += 1
            return Response({"value":[{"Id":str(self.calls)}],
                             **({"@odata.nextLink":"next"} if self.calls == 1 else {})})
    session=Session(); client=local.CDSEODataClient(session)
    result=client.search("SENTINEL-1","IW_GRDH_1S","2020-01-01","2020-01-02",box(1,1,2,2))
    assert [x["Id"] for x in result] == ["1","2"]
    assert session.calls == 2
    assert client.search("SENTINEL-1","IW_GRDH_1S","2020-01-01","2020-01-02",box(1,1,2,2)) == result
    assert session.calls == 2


def test_s2_asset_selection_is_minimal():
    assert local.wanted_s2_key("A/GRANULE/X/IMG_DATA/R10m/X_B02_10m.jp2")
    assert local.wanted_s2_key("A/GRANULE/X/IMG_DATA/R20m/X_SCL_20m.jp2")
    assert local.wanted_s2_key("A/MTD_MSIL2A.xml")
    assert not local.wanted_s2_key("A/IMG_DATA/R20m/X_B11_20m.jp2")


def test_harmonization_and_cloud_mask():
    assert local.s2_harmonization_offset("S2A_X_N0400_X") == 1000
    assert local.s2_harmonization_offset("S2A_X_N0300_X") == 0
    bands={x:np.ones((2,2)) for x in ("B2","B3","B4","B8")}
    bands["B2"][0,0]=0
    valid=local.s2_valid_mask(bands,np.array([[4,8],[4,4]]))
    assert valid.tolist() == [[False,False],[True,True]]


def test_post_composite_uses_wettest_observation():
    def scene(green,nir):
        return {"B2":np.array([[1.]]),"B3":np.array([[green]]),"B4":np.array([[2.]]),
                "B8":np.array([[nir]]),"valid":np.array([[True]])}
    result=local.composite_s2([scene(2,8),scene(8,2)],post=True)
    assert result["B3"][0,0] == 8
    assert result["B8"][0,0] == 2


def test_s3_store_deduplicates_completed_product(tmp_path, monkeypatch):
    monkeypatch.setattr(local,"CACHE",tmp_path)
    product={"Id":"p","Name":"SAFE","S3Path":"/eodata/A/SAFE"}
    target=tmp_path/"products"/"SAFE"; target.mkdir(parents=True)
    (target/".complete.json").write_text("{}")
    class Client:
        def list_objects_v2(self,**kwargs): raise AssertionError("must not list")
    assert local.CDSES3Store(Client()).download(product,"s2") == target


def test_prune_is_dry_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(local,"CACHE",tmp_path)
    product=tmp_path/"products"/"unused"; product.mkdir(parents=True)
    assert local.prune_unreferenced() == [str(product)]
    assert product.exists()


def test_local_aoi_resolves_numeric_gaul_export():
    import pandas as pd
    rows=pd.read_csv(local.data_path("district_aoi"),dtype=str,keep_default_na=False)
    row=rows[(rows.geometry_id.str.endswith(".0")) & (rows.aoi_match_status=="matched")].iloc[0]
    resolved=local.LocalAOIResolver().resolve(row)
    assert not resolved["geometry"].is_empty
    assert not resolved["geometry_id"].endswith(".0")


class CopernicusLocalTests(unittest.TestCase):
    def test_filter(self):
        test_odata_filter_is_direct_product_query()

    def test_assets(self):
        test_s2_asset_selection_is_minimal()

    def test_harmonization(self):
        test_harmonization_and_cloud_mask()

    def test_composite(self):
        test_post_composite_uses_wettest_observation()

    def test_ndwi_is_composited_before_median(self):
        def scene(green, nir):
            shape=(1,1)
            return {"B2":np.ones(shape),"B3":np.array([[green]],float),
                    "B4":np.ones(shape),"B8":np.array([[nir]],float),
                    "valid":np.ones(shape,bool)}
        scenes=[scene(1,9),scene(4,6),scene(9,1)]
        expected=np.median([(1-9)/(1+9),(4-6)/(4+6),(9-1)/(9+1)])
        self.assertAlmostEqual(float(local.composite_ndwi(scenes)[0,0]),expected,places=6)

    def test_aoi(self):
        test_local_aoi_resolves_numeric_gaul_export()

    def test_pagination(self):
        class Response:
            def __init__(self, payload): self.payload = payload
            def raise_for_status(self): pass
            def json(self): return self.payload
        class Session:
            def __init__(self): self.calls = 0
            def get(self, *args, **kwargs):
                self.calls += 1
                return Response({"value":[{"Id":str(self.calls)}],
                    **({"@odata.nextLink":"next"} if self.calls == 1 else {})})
        with tempfile.TemporaryDirectory() as directory, patch.object(local,"CACHE",Path(directory)):
            session=Session(); client=local.CDSEODataClient(session)
            args=("SENTINEL-1","IW_GRDH_1S","2020-01-01","2020-01-02",box(1,1,2,2))
            result=client.search(*args)
            self.assertEqual([x["Id"] for x in result],["1","2"])
            self.assertEqual(client.search(*args),result)
            self.assertEqual(session.calls,2)

    def test_completed_product_is_reused(self):
        product={"Id":"p","Name":"SAFE","S3Path":"/eodata/A/SAFE"}
        class Client:
            def list_objects_v2(self,**kwargs): raise AssertionError("must not list")
        with tempfile.TemporaryDirectory() as directory, patch.object(local,"CACHE",Path(directory)):
            target=Path(directory)/"products"/"SAFE"; target.mkdir(parents=True)
            (target/".complete.json").write_text("{}")
            self.assertEqual(local.CDSES3Store(Client()).download(product,"s2"),target)

    def test_prune_default_does_not_delete(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(local,"CACHE",Path(directory)):
            product=Path(directory)/"products"/"unused"; product.mkdir(parents=True)
            self.assertEqual(local.prune_unreferenced(),[str(product)])
            self.assertTrue(product.exists())


if __name__ == "__main__":
    unittest.main()
