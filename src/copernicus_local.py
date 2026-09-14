"""Copernicus Data Space -> local Track-B H5 backend.

The catalogue call is public OData.  Product bytes are downloaded once from
CDSE S3 and shared by every event/district.  All composites, masks, Otsu and
H5 tiling run locally.  Sentinel-1 is deliberately processed from GRD with
ESA SNAP; this module never substitutes a different RTC product silently.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
from datetime import datetime, timedelta
from urllib.parse import quote

import numpy as np
import requests

from cvnd_layout import data_path
from district_keys import analysis_key
from flood_spec import SPEC, SPEC_VERSION, otsu_from_histogram

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data/cache/copernicus"
CATALOGUE = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
S3_ENDPOINT = "https://eodata.dataspace.copernicus.eu"
S2_SUFFIXES = ("_B02_10m.jp2", "_B03_10m.jp2", "_B04_10m.jp2", "_B08_10m.jp2",
               "_SCL_20m.jp2", "/MTD_MSIL2A.xml", "/MTD_TL.xml")


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, default=str))
    os.replace(temporary, path)


def _sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def _feature_geometry(feature):
    from shapely.geometry import shape
    return shape(feature["geometry"])


class LocalAOIResolver:
    """Resolve the exact geometry already pinned by district_aoi.csv."""

    def __init__(self):
        self.aoi_rows = None
        self.by_gaul = None
        self.recovery = None
        self.osm = None

    def _load(self):
        if self.aoi_rows is not None:
            return
        import pandas as pd
        self.aoi_rows = pd.read_csv(data_path("district_aoi"), dtype=str,
                                    keep_default_na=False).set_index("event_district_id")
        gaul = json.loads((ROOT / "data/raw/geoboundaries_2021/existing_gaul_geometries.json").read_text())
        self.by_gaul = {str(f["properties"]["ADM2_CODE"]): f for f in gaul["features"]}
        recovery = json.loads((ROOT / "data/raw/geoboundaries_2021/ADM2.geojson").read_text())
        self.recovery = {str(f["properties"]["shapeID"]): f for f in recovery["features"]}
        from boundary_recovery import load_supplemental
        decisions, features = load_supplemental()
        self.osm = {"OSM:relation/" + str(v["relation_id"]): features[k]
                    for k, v in decisions.items()}

    def resolve(self, row):
        self._load()
        key = analysis_key(row)
        if key not in self.aoi_rows.index:
            raise ValueError(f"district AOI metadata missing: {key}")
        meta = self.aoi_rows.loc[key].to_dict()
        if meta.get("aoi_match_status") != "matched":
            raise ValueError(meta.get("aoi_error") or f"district AOI not matched: {key}")
        gid = str(meta["geometry_id"])
        # pandas string exports may retain a numeric GAUL code as ``70228.0``.
        # The pinned FeatureCollection stores the same identifier as an int.
        if gid.endswith(".0") and gid[:-2].isdigit():
            gid = gid[:-2]
        if gid.startswith("OSM:relation/"):
            feature = self.osm.get(gid)
            geometry = feature and feature.get("geojson")
            if geometry:
                from shapely.geometry import shape
                geom = shape(geometry)
            else:
                raise ValueError(f"pinned OSM geometry missing: {gid}")
        elif gid in self.recovery:
            geom = _feature_geometry(self.recovery[gid])
        else:
            feature = self.by_gaul.get(gid)
            if feature is None:
                raise ValueError(f"pinned GAUL geometry missing: {gid}")
            geom = _feature_geometry(feature)
        return {**meta, "geometry": geom, "geometry_id": gid}


def bbox_wkt(geom) -> str:
    xmin, ymin, xmax, ymax = geom.bounds
    return (f"POLYGON(({xmin} {ymin},{xmax} {ymin},{xmax} {ymax},"
            f"{xmin} {ymax},{xmin} {ymin}))")


def odata_filter(collection: str, product_type: str, start: str, end: str,
                 geom, cloud_max=None) -> str:
    parts = [f"Collection/Name eq '{collection}'",
             f"ContentDate/Start ge {start}T00:00:00.000Z",
             f"ContentDate/Start lt {end}T00:00:00.000Z",
             f"Attributes/OData.CSC.StringAttribute/any(a:a/Name eq 'productType' and a/OData.CSC.StringAttribute/Value eq '{product_type}')",
             "OData.CSC.Intersects(area=geography'SRID=4326;" + bbox_wkt(geom) + "')"]
    if cloud_max is not None:
        parts.append("Attributes/OData.CSC.DoubleAttribute/any(a:a/Name eq 'cloudCover' and a/OData.CSC.DoubleAttribute/Value lt " + str(float(cloud_max)) + ")")
    return " and ".join(parts)


class CDSEODataClient:
    def __init__(self, session=None):
        self.session = session or requests.Session()

    def search(self, collection, product_type, start, end, geom, cloud_max=None):
        query = {"$filter": odata_filter(collection, product_type, start, end, geom, cloud_max),
                 "$select": "Id,Name,S3Path,GeoFootprint,ContentDate,Checksum,Online",
                 "$orderby": "ContentDate/Start asc", "$top": "1000"}
        cache_file = CACHE / "catalog" / (_sha(query) + ".json")
        if cache_file.exists():
            return json.loads(cache_file.read_text())["value"]
        url, params, values = CATALOGUE, query, []
        while url:
            response = self.session.get(url, params=params, timeout=120)
            response.raise_for_status()
            payload = response.json()
            values.extend(payload.get("value", []))
            url, params = payload.get("@odata.nextLink"), None
        _atomic_json(cache_file, {"query": query, "value": values})
        return values


def wanted_s2_key(key: str) -> bool:
    normalized = "/" + key.replace("\\", "/").lstrip("/")
    return any(normalized.endswith(suffix) for suffix in S2_SUFFIXES)


class CDSES3Store:
    def __init__(self, client=None):
        if client is None:
            try:
                import boto3
                from boto3.s3.transfer import TransferConfig
            except ImportError as exc:
                raise RuntimeError("boto3 is required: pip install -r requirements.txt") from exc
            access = os.environ.get("CDSE_S3_ACCESS_KEY")
            secret = os.environ.get("CDSE_S3_SECRET_KEY")
            if not access or not secret:
                raise RuntimeError("set CDSE_S3_ACCESS_KEY and CDSE_S3_SECRET_KEY")
            client = boto3.client("s3", endpoint_url=S3_ENDPOINT,
                                  aws_access_key_id=access, aws_secret_access_key=secret,
                                  region_name="default")
            self.transfer_config = TransferConfig(max_concurrency=min(4, int(os.environ.get("CDSE_S3_CONNECTIONS", "4"))), use_threads=True)
        else:
            self.transfer_config = None
        self.client = client

    @staticmethod
    def prefix(product):
        return str(product["S3Path"]).removeprefix("/eodata/").lstrip("/")

    def keys(self, product, sensor):
        prefix, token, out = self.prefix(product), None, []
        while True:
            args = {"Bucket": "eodata", "Prefix": prefix}
            if token:
                args["ContinuationToken"] = token
            page = self.client.list_objects_v2(**args)
            keys = [x["Key"] for x in page.get("Contents", [])]
            out.extend(k for k in keys if sensor == "s1" or wanted_s2_key(k))
            if not page.get("IsTruncated"):
                break
            token = page["NextContinuationToken"]
        return out

    def download(self, product, sensor):
        target = CACHE / "products" / product["Name"]
        marker = target / ".complete.json"
        if marker.exists():
            return target
        keys = self.keys(product, sensor)
        if not keys:
            raise RuntimeError(f"no required assets in {product['Name']}")
        prefix = self.prefix(product).rstrip("/") + "/"
        for key in keys:
            relative = key[len(prefix):] if key.startswith(prefix) else Path(key).name
            destination = target / relative
            if destination.exists() and destination.stat().st_size:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".part")
            kwargs = {"Config": self.transfer_config} if self.transfer_config else {}
            self.client.download_file("eodata", key, str(temporary), **kwargs)
            os.replace(temporary, destination)
        _atomic_json(marker, {"id": product["Id"], "name": product["Name"],
                              "s3_path": product["S3Path"], "keys": keys})
        return target


def s2_harmonization_offset(product_name: str) -> int:
    match = __import__("re").search(r"_N(\d{4})_", product_name)
    return 1000 if match and int(match.group(1)) >= 400 else 0


def s2_valid_mask(bands, scl, excluded=SPEC.s2_scl_exclude):
    valid = np.ones(scl.shape, dtype=bool)
    for array in bands.values():
        valid &= np.isfinite(array) & (array > 0)
    valid &= ~np.isin(scl, excluded)
    return valid


def composite_s2(scenes, post=False):
    """Pure local S2 composite; scene dicts contain B2/B3/B4/B8/valid."""
    if not scenes:
        return None
    names = ("B2", "B3", "B4", "B8")
    stacks = {b: np.stack([s[b].astype(np.float32) for s in scenes]) for b in names}
    valid = np.stack([s["valid"] for s in scenes])
    for b in names:
        stacks[b][~valid] = np.nan
    if post and SPEC.post_composite == "max_water":
        ndwi = (stacks["B3"] - stacks["B8"]) / (stacks["B3"] + stacks["B8"] + 1e-6)
        safe = np.where(np.isfinite(ndwi), ndwi, -np.inf)
        index = np.argmax(safe, axis=0)
        any_valid = valid.any(axis=0)
        result = {b: np.take_along_axis(stacks[b], index[None], axis=0)[0] for b in names}
        result["valid"] = any_valid
    else:
        result = {b: np.nanmedian(stacks[b], axis=0) for b in names}
        result["valid"] = np.isfinite(result["B2"])
    return result


def composite_ndwi(scenes, post=False):
    """Match GEE ndwi_composites: composite per-scene NDWI values.

    In particular, median(NDWI(scene)) is not generally equal to NDWI of the
    median B3/B8 reflectances, so measurement references use this function
    instead of deriving NDWI from ``composite_s2``.
    """
    if not scenes:
        return None
    values = []
    for scene in scenes:
        ndwi = ((scene['B3'].astype(np.float32) - scene['B8']) /
                (scene['B3'].astype(np.float32) + scene['B8'] + 1e-6))
        values.append(np.where(scene['valid'], ndwi, np.nan))
    stack = np.stack(values)
    return np.nanmax(stack, axis=0) if post and SPEC.post_composite == 'max_water' \
        else np.nanmedian(stack, axis=0)


def _grid_for_geom(geom, spec=SPEC):
    from pyproj import Transformer
    from shapely.ops import transform
    from satellite import grid_from_utm_bounds, utm_epsg
    p = geom.representative_point()
    crs = f"EPSG:{utm_epsg(p.x, p.y)}"
    projected = transform(Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform, geom)
    return grid_from_utm_bounds(crs, *projected.bounds, spec), projected


def _transform(grid, row=0, col=0):
    from affine import Affine
    return Affine(*grid.transform(col, row))


def _read_mosaic(paths, grid, window, resampling="nearest", dtype="float32"):
    import rasterio
    from rasterio.warp import reproject, Resampling
    row, col, height, width = window
    out = np.full((height, width), np.nan, dtype=dtype)
    method = getattr(Resampling, resampling)
    for path in paths:
        with rasterio.open(path) as src:
            piece = np.full((height, width), np.nan, dtype=dtype)
            reproject(rasterio.band(src, 1), piece, src_transform=src.transform,
                      src_crs=src.crs, src_nodata=src.nodata,
                      dst_transform=_transform(grid, row, col), dst_crs=grid.crs,
                      dst_nodata=np.nan, resampling=method)
            take = ~np.isfinite(out) & np.isfinite(piece)
            out[take] = piece[take]
    return out


def _product_assets(directory: Path, token: str):
    return sorted(p for p in directory.rglob("*") if p.is_file() and token in p.name)


def _read_s2(product, directory, grid, window):
    arrays = {}
    offset = s2_harmonization_offset(product["Name"])
    for band in ("B02", "B03", "B04", "B08"):
        paths = _product_assets(directory, f"_{band}_10m.jp2")
        if not paths:
            raise RuntimeError(f"{product['Name']}: missing {band} 10m asset")
        # Earth Engine's default reprojection policy for these inputs is
        # nearest-neighbour; use the same policy for backend comparability.
        value = _read_mosaic(paths, grid, window, "nearest")
        if offset:
            value = np.where(value > 0, np.maximum(value - offset, 0), value)
        arrays[band.replace("0", "")] = value
    scl_paths = _product_assets(directory, "_SCL_20m.jp2")
    scl = _read_mosaic(scl_paths, grid, window, "nearest")
    arrays["valid"] = s2_valid_mask(arrays, scl)
    return arrays


def _scene_date(product):
    return datetime.fromisoformat(product["ContentDate"]["Start"].replace("Z", "+00:00")).replace(tzinfo=None)


def _month_end(year, month):
    return datetime(year + (month == 12), 1 if month == 12 else month + 1, 1)


class LocalTrackB:
    def __init__(self, spec=SPEC, catalogue=None, store=None):
        self.spec = spec
        self.catalogue = catalogue or CDSEODataClient()
        self.store = store
        self.aoi = LocalAOIResolver()

    def _search_s2(self, geom, start, end):
        return self.catalogue.search("SENTINEL-2", "S2MSI2A", start, end, geom,
                                     self.spec.s2_cloudy_pixel_pct_max)

    def plan(self, row):
        aoi = self.aoi.resolve(row)
        geom = aoi["geometry"]
        onset = datetime.strptime(str(row["start_date"]), "%Y-%m-%d")
        months_a, months_b = __import__("satellite").baseline_pool_months(onset, self.spec.sits_baseline_years)
        months = sorted(set(months_a + months_b))
        ranges = [(datetime(y, m, 1), min(_month_end(y, m), onset)) for y, m in months]
        s2 = {}
        for start, end in ranges + [(onset - timedelta(days=self.spec.pre_window_days), onset),
                                    (onset, onset + timedelta(days=self.spec.post_window_days))]:
            if end <= start:
                continue
            for product in self._search_s2(geom, start.date().isoformat(), end.date().isoformat()):
                s2[product["Id"]] = product
        s1 = {}
        for start, end in [(onset - timedelta(days=self.spec.pre_window_days), onset),
                           (onset, onset + timedelta(days=self.spec.post_window_days))]:
            for product in self.catalogue.search("SENTINEL-1", "IW_GRDH_1S",
                                                  start.date().isoformat(), end.date().isoformat(), geom):
                # GEE's S1_GRD query selects VV. Product names encode DV/SV
                # for dual/single VV; DH/SH products do not contain VV.
                if "_1SDV_" in product["Name"] or "_1SSV_" in product["Name"]:
                    s1[product["Id"]] = product
        plan = {"event_district_id": analysis_key(row), "spec_version": SPEC_VERSION,
                "geometry_id": aoi["geometry_id"], "s2": list(s2.values()), "s1": list(s1.values())}
        plan["plan_hash"] = _sha(plan)
        path = CACHE / "plans" / (quote(analysis_key(row), safe="") + ".json")
        _atomic_json(path, plan)
        return plan, aoi

    def download(self, plan, sensors=("s2", "s1")):
        store = self.store or CDSES3Store()
        result = {"s2": {}, "s1": {}}
        for sensor in sensors:
            for product in plan[sensor]:
                result[sensor][product["Id"]] = str(store.download(product, sensor))
        manifest_path = CACHE / "scene_manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"products": {}, "plans": {}}
        for sensor in ("s1", "s2"):
            for product in plan[sensor]:
                old = manifest["products"].get(product["Id"], {})
                manifest["products"][product["Id"]] = {"sensor": sensor, "name": product["Name"],
                    "s3_path": product["S3Path"], "local_path": result[sensor].get(product["Id"], old.get("local_path"))}
        manifest["plans"][plan["event_district_id"]] = {"plan_hash": plan["plan_hash"],
            "s1": [p["Id"] for p in plan["s1"]], "s2": [p["Id"] for p in plan["s2"]]}
        _atomic_json(manifest_path, manifest)
        return result

    def preflight(self):
        missing = []
        raster_paths = []
        for env in ("CDSE_S3_ACCESS_KEY", "CDSE_S3_SECRET_KEY", "CVND_JRC_OCCURRENCE_RASTER",
                    "CVND_SRTM_RASTER", "CVND_WORLDCOVER_RASTER",
                    "CVND_INDIA_BOUNDARY_VECTOR"):
            value = os.environ.get(env)
            if not value or ((env.endswith("_RASTER") or env.endswith("_VECTOR"))
                             and not Path(value).exists()):
                missing.append(env)
            elif env.endswith("_RASTER"):
                raster_paths.append((env, Path(value)))
        snap = os.environ.get("SNAP_GPT") or shutil.which("gpt")
        if not snap or not Path(snap).is_file() or not os.access(snap, os.X_OK):
            missing.append("SNAP_GPT")
        if missing:
            raise RuntimeError("local backend prerequisites missing: " + ", ".join(missing))
        import rasterio
        for env, path in raster_paths:
            try:
                with rasterio.open(path) as dataset:
                    if not dataset.crs or dataset.count < 1:
                        raise ValueError("missing CRS or band")
            except Exception as exc:
                raise RuntimeError(f"{env} is not a readable georeferenced raster: {path}: {exc}") from exc
        try:
            import geopandas as gpd
            boundary = gpd.read_file(os.environ['CVND_INDIA_BOUNDARY_VECTOR'])
            if boundary.empty or boundary.crs is None:
                raise ValueError('empty vector or missing CRS')
        except Exception as exc:
            raise RuntimeError('CVND_INDIA_BOUNDARY_VECTOR is not a readable georeferenced vector: '
                               f'{exc}') from exc
        return snap

    def _snap(self, product, directory, executable):
        output = CACHE / "processed_s1" / (product["Name"] + ".tif")
        if output.exists() and output.stat().st_size:
            return output
        manifest = next(iter(directory.rglob("manifest.safe")), None)
        if manifest is None:
            raise RuntimeError(f"{product['Name']}: manifest.safe missing")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".part.tif")
        subprocess.run([executable, str(ROOT / "config/snap_s1_grd.xml"),
                        f"-Pinput={manifest}", f"-Poutput={temporary}"], check=True)
        os.replace(temporary, output)
        return output

    def run(self, row, validation_copy=False):
        """Build one local H5. Existing complete H5 is never overwritten."""
        from satellite import (SITS_BLOCK_PATCHES, SITS_BANDS, SITS_OUTPUT_DIR, NDWI_NODATA,
                               NDWI_SCALE, S1_NODATA, S1_SCALE, TILE_SELECTION_RULE,
                               _append_h5, _create_h5,
                               _h5_identity_matches, _tiles_from_block, block_stats,
                               sits_h5_path)
        key = analysis_key(row)
        out = Path(sits_h5_path(key))
        if out.exists() and not Path(str(out) + ".blocks.json").exists() and validation_copy:
            out = out.with_name(out.stem + ".cdse-local.h5")
        if out.exists() and not Path(str(out) + ".blocks.json").exists():
            if _h5_identity_matches(out, row):
                import h5py
                with h5py.File(out) as h:
                    return {"status": "OK", "reason": "existing_h5", "path": str(out),
                            "complete": True, "kept_tiles": int(h["pre"].shape[0])}
            raise RuntimeError(f"refusing to overwrite completed H5 with different identity: {out}")
        if out.exists() and Path(str(out) + ".blocks.json").exists():
            import h5py
            with h5py.File(out) as existing:
                backend = str(existing["meta"].attrs.get("data_backend", "gee"))
            if backend != "cdse-local":
                # Preserve the interrupted GEE download byte-for-byte.  The
                # index will point at this backend-specific completed file.
                out = out.with_name(out.stem + ".cdse-local.h5")
        if out.exists() and not Path(str(out) + ".blocks.json").exists():
            if _h5_identity_matches(out, row):
                import h5py
                with h5py.File(out) as h:
                    return {"status":"OK", "reason":"existing_h5", "path":str(out),
                            "complete":True, "kept_tiles":int(h["pre"].shape[0])}
            raise RuntimeError(f"refusing to overwrite completed local H5 with different identity: {out}")
        snap = self.preflight()
        import geopandas as gpd
        india_frame = gpd.read_file(os.environ['CVND_INDIA_BOUNDARY_VECTOR']).to_crs('EPSG:4326')
        india_geometry = india_frame.geometry.union_all()
        plan, aoi = self.plan(row)
        if not plan["s2"]:
            return {"status": "SKIPPED_NO_IMAGERY", "reason": "no_s2_imagery", "path": None,
                    "complete": True, "kept_tiles": 0}
        # Optical feasibility is decided before downloading any large S1 SAFE
        # product. Districts without usable S2 therefore spend no S1 transfer.
        local = self.download(plan, sensors=("s2",))
        onset = datetime.strptime(str(row["start_date"]), "%Y-%m-%d")
        s2_dirs = {p["Id"]: Path(local["s2"][p["Id"]]) for p in plan["s2"]}
        grid, projected = _grid_for_geom(aoi["geometry"], self.spec)
        # Baseline QA is computed locally on a 100 m sampling grid.
        sample = type(grid)(grid.crs, grid.x0, grid.y0, 100, grid.patch_px,
                            max(1, math.ceil(grid.npx * grid.pixel_m / 100)),
                            max(1, math.ceil(grid.npy * grid.pixel_m / 100)))
        sample_window = (0, 0, sample.npy * sample.patch_px, sample.npx * sample.patch_px)
        products_by_month = {}
        for product in plan["s2"]:
            date = _scene_date(product)
            products_by_month.setdefault((date.year, date.month), []).append(product)
        scored = {}
        from shapely.geometry import mapping
        from shapely.ops import transform as shp_transform
        from pyproj import Transformer
        import rasterio.features
        geom_sample = shp_transform(Transformer.from_crs("EPSG:4326", sample.crs, always_xy=True).transform,
                                    aoi["geometry"])
        sample_inside = rasterio.features.rasterize([(mapping(geom_sample), 1)],
            out_shape=sample_window[2:], transform=_transform(sample), fill=0, dtype="uint8").astype(bool)
        for month, products in products_by_month.items():
            scenes = [_read_s2(p, s2_dirs[p["Id"]], sample, sample_window) for p in products]
            comp = composite_s2(scenes)
            if comp is None:
                continue
            clear = float(comp["valid"][sample_inside].mean()) if sample_inside.any() else 0.0
            ndwi = (comp["B3"] - comp["B8"]) / (comp["B3"] + comp["B8"] + 1e-6)
            scored[month] = (f"{month[0]:04d}-{month[1]:02d}", products, clear,
                             float(np.nanmean((ndwi > self.spec.ndwi_water_gt)[sample_inside])))
        from satellite import baseline_pool_months, choose_baseline
        pa, pb = baseline_pool_months(onset, self.spec.sits_baseline_years)
        baseline = choose_baseline([scored[m] for m in pa if m in scored],
                                   [scored[m] for m in pb if m in scored],
                                   self.spec.sits_n_pre, self.spec.sits_baseline_min_clear)
        if baseline is None:
            return {"status": "SKIPPED_NO_IMAGERY", "reason": "no_clear_baseline", "path": None,
                    "complete": True, "kept_tiles": 0}
        post_products = [p for p in plan["s2"] if onset <= _scene_date(p) < onset + timedelta(days=self.spec.post_window_days)]
        pre_products = [p for p in plan["s2"] if onset - timedelta(days=self.spec.pre_window_days) <= _scene_date(p) < onset]
        if not post_products or not pre_products:
            return {"status": "SKIPPED_NO_IMAGERY", "reason": "no_post_or_pre_imagery", "path": None,
                    "complete": True, "kept_tiles": 0}
        s1_local = self.download(plan, sensors=("s1",))
        local["s1"].update(s1_local["s1"])
        s1_tifs = {p["Id"]: self._snap(p, Path(local["s1"][p["Id"]]), snap) for p in plan["s1"]}
        s1pre = [p for p in plan["s1"] if _scene_date(p) < onset]
        s1post = [p for p in plan["s1"] if _scene_date(p) >= onset]
        from shapely.geometry import mapping
        from shapely.ops import transform as shp_transform
        from pyproj import Transformer
        geom_grid = shp_transform(Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True).transform,
                                  aoi["geometry"])
        india_grid = shp_transform(Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True).transform,
                                  india_geometry)
        import rasterio.features, h5py
        B, P = SITS_BLOCK_PATCHES, self.spec.sits_patch_px
        def s1comp(items, window, minimum=False):
            # One-pixel halo makes the local 3x3 focal median continuous at
            # block edges. Crop back to the frozen block after filtering.
            row,col,height,width=window
            top=min(1,row); left=min(1,col)
            bottom=min(1,grid.npy*grid.patch_px-(row+height))
            right=min(1,grid.npx*grid.patch_px-(col+width))
            expanded=(row-top,col-left,height+top+bottom,width+left+right)
            vals=[_read_mosaic([s1_tifs[p["Id"]]],grid,expanded,"nearest") for p in items]
            if not vals: return np.full((height,width),np.nan)
            from scipy.ndimage import median_filter
            stack=median_filter(np.stack(vals),size=(1,3,3))
            result=np.nanmin(stack,axis=0) if minimum else np.nanmedian(stack,axis=0)
            return result[top:top+height,left:left+width]
        # Accumulate the fixed-range 10 m post-S1 histogram across the exact
        # AOI before writing blocks. This yields one district threshold.
        hist=np.zeros(self.spec.otsu_buckets,dtype=np.int64)
        edges=np.linspace(self.spec.otsu_hist_min_db,self.spec.otsu_hist_max_db,
                          self.spec.otsu_buckets+1)
        for bi in range(0,grid.npy,B):
            for bj in range(0,grid.npx,B):
                win=grid.block(bi,bj,B)
                inside=rasterio.features.rasterize([(mapping(geom_grid),1)],out_shape=win[2:],
                    transform=_transform(grid,win[0],win[1]),fill=0,dtype="uint8").astype(bool)
                if inside.any() and s1post:
                    values=s1comp(s1post,win,True)
                    counts,_=np.histogram(values[inside & np.isfinite(values)],bins=edges)
                    hist += counts
        threshold,_=otsu_from_histogram(hist,(edges[:-1]+edges[1:])/2)
        fallback=threshold is None or not self.spec.otsu_lo_db <= threshold <= self.spec.otsu_hi_db
        if fallback: threshold=self.spec.otsu_fallback_db
        runtime = {"data_backend": "cdse-local", "cdse_plan_hash": plan["plan_hash"],
                   "tile_selection_rule": TILE_SELECTION_RULE,
                   "s2_product_ids": [p["Id"] for p in plan["s2"]],
                   "s1_product_ids": [p["Id"] for p in plan["s1"]],
                   "selected_baseline_months": [x[0] for x in baseline],
                   "snap_graph_sha256": hashlib.sha256((ROOT / "config/snap_s1_grd.xml").read_bytes()).hexdigest()}
        out.parent.mkdir(parents=True, exist_ok=True)
        blocks_file = Path(str(out) + ".blocks.json")
        done = set(json.loads(blocks_file.read_text())) if blocks_file.exists() else set()
        mode = "a" if out.exists() and blocks_file.exists() else "w"
        with h5py.File(out, mode) as h:
            if mode == "w":
                _create_h5(h, row, aoi, grid, self.spec, threshold, fallback, runtime_metadata=runtime)
                _atomic_json(blocks_file, [])
            else:
                from satellite import truncate_to_done
                truncate_to_done(h, done)
            block_index = -1
            for bi in range(0, grid.npy, B):
                for bj in range(0, grid.npx, B):
                    block_index += 1
                    if block_index in done:
                        continue
                    window = grid.block(bi, bj, B)
                    inside = rasterio.features.rasterize([(mapping(geom_grid), 1)], out_shape=window[2:],
                              transform=_transform(grid, window[0], window[1]), fill=0, dtype="uint8").astype(bool)
                    if not inside.any():
                        done.add(block_index); _atomic_json(blocks_file, sorted(done)); continue
                    baseline_arrays = []
                    for _, products, _, _ in baseline:
                        baseline_arrays.append(composite_s2([_read_s2(p, s2_dirs[p["Id"]], grid, window) for p in products]))
                    post_scenes = [_read_s2(p, s2_dirs[p["Id"]], grid, window) for p in post_products]
                    pre_scenes = [_read_s2(p, s2_dirs[p["Id"]], grid, window) for p in pre_products]
                    post = composite_s2(post_scenes, post=True)
                    pre30 = composite_s2(pre_scenes)
                    arrays = baseline_arrays + [post]
                    if any(x is None for x in arrays) or pre30 is None:
                        continue
                    sources = [Path(os.environ[x]) for x in ("CVND_JRC_OCCURRENCE_RASTER", "CVND_SRTM_RASTER", "CVND_WORLDCOVER_RASTER")]
                    static_sources = sources + [Path(os.environ["CVND_INDIA_BOUNDARY_VECTOR"])]
                    static_key = _sha({"schema":"static-block-v3", "geometry":aoi["geometry_id"], "grid":[grid.crs,grid.x0,grid.y0,grid.npx,grid.npy], "block":block_index,
                        "sources":[(str(p.resolve()),p.stat().st_size,p.stat().st_mtime_ns) for p in static_sources]})
                    static_file = CACHE / "static" / quote(str(aoi["geometry_id"]),safe="") / (static_key+".npz")
                    if static_file.exists():
                        with np.load(static_file) as cached:
                            jrc,lc,slope,country=cached["jrc"],cached["landcover"],cached["slope"],cached["country"]
                    else:
                        jrc = _read_mosaic([sources[0]], grid, window)
                        lc = _read_mosaic([sources[2]], grid, window)
                        row,col,height,width=window
                        top=min(1,row); left=min(1,col)
                        bottom=min(1,grid.npy*grid.patch_px-(row+height)); right=min(1,grid.npx*grid.patch_px-(col+width))
                        demwin=(row-top,col-left,height+top+bottom,width+left+right)
                        dem = _read_mosaic([sources[1]], grid, demwin, "bilinear")
                        gy,gx=np.gradient(dem,self.spec.sits_pixel_m)
                        slope_full=np.degrees(np.arctan(np.hypot(gx,gy)))
                        slope=slope_full[top:top+height,left:left+width]
                        country=rasterio.features.rasterize([(mapping(india_grid),1)],out_shape=window[2:],
                            transform=_transform(grid,window[0],window[1]),fill=0,dtype="uint8").astype(bool)
                        static_file.parent.mkdir(parents=True,exist_ok=True)
                        temporary=static_file.with_suffix(".part.npz")
                        np.savez_compressed(temporary,jrc=jrc,slope=slope,landcover=lc,country=country)
                        os.replace(temporary,static_file)
                    eligible = inside & country & (jrc < self.spec.jrc_permanent_occurrence_gte) & (slope < self.spec.slope_max_deg)
                    ndwi_pre = composite_ndwi(pre_scenes)
                    ndwi_post = composite_ndwi(post_scenes, post=True)
                    s1_pre, s1_post = s1comp(s1pre,window), s1comp(s1post,window,True)
                    valid_s1 = np.isfinite(s1_post) & inside
                    dtype = [(b, "f4") for b in SITS_BANDS] + [("valid", "u1")]
                    structured = []
                    for x in arrays:
                        arr = np.zeros(window[2:], dtype=dtype)
                        for b in SITS_BANDS: arr[b] = x[b]
                        arr["valid"] = x["valid"] & inside
                        structured.append(arr)
                    auxdtype = [("eligible","u1"),("inside","u1"),("area","f4"),("ndwi_pre","i2"),("ndwi_post","i2"),("s1_pre","i2"),("s1_post","i2"),("landcover","u1")]
                    aux = np.zeros(window[2:], dtype=auxdtype)
                    aux["eligible"], aux["inside"], aux["area"] = eligible, inside, self.spec.sits_pixel_m ** 2
                    aux["ndwi_pre"] = np.where(np.isfinite(ndwi_pre), np.clip(np.rint(ndwi_pre*NDWI_SCALE),-32767,32767), NDWI_NODATA)
                    aux["ndwi_post"] = np.where(np.isfinite(ndwi_post), np.clip(np.rint(ndwi_post*NDWI_SCALE),-32767,32767), NDWI_NODATA)
                    aux["s1_pre"] = np.where(np.isfinite(s1_pre), np.clip(np.rint(s1_pre*S1_SCALE),-32767,32767), S1_NODATA)
                    aux["s1_post"] = np.where(np.isfinite(s1_post), np.clip(np.rint(s1_post*S1_SCALE),-32767,32767), S1_NODATA)
                    aux["landcover"] = np.where(np.isfinite(lc), lc, 0).astype("u1")
                    tiles = _tiles_from_block(structured, aux, self.spec, bands=SITS_BANDS)
                    if tiles["rc"]:
                        coords = [[window[0]+r*P, window[1]+c*P, grid.x0+(window[1]+(c+.5)*P)*grid.pixel_m, grid.y0-(window[0]+(r+.5)*P)*grid.pixel_m] for r,c in tiles["rc"]]
                        _append_h5(h, {"pre":np.stack(tiles["pre"]),"post":np.stack(tiles["post"]),"coords":np.asarray(coords),"mask":np.stack(tiles["mask"]),"ndwi_ref":np.stack(tiles["ndwi_ref"]),"s1_ref":np.stack(tiles["s1_ref"]),"landcover":np.stack(tiles["landcover"]),"pixel_area_m2":np.asarray(tiles["pixel_area_m2"],dtype="f4"),"block_id":np.full(len(coords),block_index,dtype="i4")})
                    _append_h5(h, {"block_stats":np.asarray([[block_index]+block_stats(aux, threshold,self.spec)])})
                    h.flush(); done.add(block_index); _atomic_json(blocks_file, sorted(done))
        blocks_file.unlink(missing_ok=True)
        import h5py
        with h5py.File(out) as h: n=int(h["pre"].shape[0])
        return {"status":"OK", "reason":"ok" if n else "no_retained_tiles", "path":str(out), "complete":True, "kept_tiles":n}


def compare_h5(reference, candidate, atol_dn=1):
    """Compare two completed H5 contracts before a backend migration."""
    import h5py
    report = {"reference": str(reference), "candidate": str(candidate), "datasets": {}}
    with h5py.File(reference) as a, h5py.File(candidate) as b:
        for name in ("pre", "post", "mask", "ndwi_ref", "s1_ref", "landcover", "block_stats"):
            if name not in a or name not in b:
                report["datasets"][name] = {"match": False, "reason": "missing"}; continue
            if a[name].shape != b[name].shape:
                report["datasets"][name] = {"match": False, "shape": [a[name].shape,b[name].shape]}; continue
            av,bv=a[name][:],b[name][:]
            delta=np.abs(av.astype(float)-bv.astype(float))
            report["datasets"][name]={"match":bool(np.all(delta<=atol_dn)),"max_abs":float(np.nanmax(delta)) if delta.size else 0.0,"mean_abs":float(np.nanmean(delta)) if delta.size else 0.0}
    report["match"] = all(x["match"] for x in report["datasets"].values())
    return report


def prepare_sits_patch_local(row, spec=SPEC):
    return LocalTrackB(spec).run(row)


def prune_unreferenced(execute=False):
    manifests = list((CACHE / "plans").glob("*.json"))
    referenced = {p["Name"] for path in manifests for sensor in ("s1","s2")
                  for p in json.loads(path.read_text()).get(sensor, [])}
    candidates = [p for p in (CACHE / "products").glob("*") if p.name not in referenced]
    if execute:
        for path in candidates: shutil.rmtree(path)
    return [str(p) for p in candidates]


def main(argv=None):
    import argparse
    import pandas as pd
    parser = argparse.ArgumentParser(description="CDSE direct-download/local Track-B tools")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "download", "run"):
        item = sub.add_parser(name)
        item.add_argument("ids", nargs="+", help="event_district_id or event_id")
        if name == "run":
            item.add_argument("--validation-copy", action="store_true",
                              help="write .cdse-local.h5 beside an existing completed GEE H5")
    compare = sub.add_parser("compare")
    compare.add_argument("reference")
    compare.add_argument("candidate")
    prune = sub.add_parser("prune")
    prune.add_argument("--execute", action="store_true")
    sub.add_parser("preflight")
    args = parser.parse_args(argv)
    if args.command == "compare":
        print(json.dumps(compare_h5(args.reference, args.candidate), indent=2)); return
    if args.command == "prune":
        candidates = prune_unreferenced(args.execute)
        print(json.dumps({"execute": args.execute, "candidates": candidates}, indent=2)); return
    backend = LocalTrackB()
    if args.command == "preflight":
        print(f"SNAP GPT: {backend.preflight()}"); return
    events = pd.read_csv(data_path("event_districts"))
    keys = events.apply(analysis_key, axis=1)
    selected = events[keys.isin(args.ids) | events.event_id.astype(str).isin(args.ids)]
    if selected.empty:
        parser.error("no matching registry rows")
    for _, row in selected.iterrows():
        plan, _ = backend.plan(row)
        if args.command == "plan":
            print(f"{analysis_key(row)}: {len(plan['s2'])} S2, {len(plan['s1'])} S1")
        elif args.command == "download":
            backend.preflight()
            print(json.dumps(backend.download(plan), indent=2))
        else:
            print(json.dumps(backend.run(row, validation_copy=args.validation_copy), indent=2))


if __name__ == "__main__":
    main()
