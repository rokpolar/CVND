# Copernicus local Track-B backend

This backend replaces Track-B Earth Engine extraction with direct Copernicus
Data Space downloads and local processing. Existing completed H5 and NPZ files
are reused. An interrupted GEE H5 is retained; the local result is written to a
separate `.cdse-local.h5` file rather than mixing pixels from two backends.

## Prerequisites

1. Create Copernicus Data Space S3 keys and install the project requirements.
2. Install ESA SNAP, including Sentinel-1 Toolbox, and point `SNAP_GPT` at its
   Graph Processing Tool executable.
3. Provide local GeoTIFF/VRT mosaics for JRC occurrence, SRTM elevation and ESA
   WorldCover 2021. They are static shared inputs and are reprojected into a
   geometry/block cache only once.

```bash
export CDSE_S3_ACCESS_KEY='...'
export CDSE_S3_SECRET_KEY='...'
export SNAP_GPT='/opt/snap/bin/gpt'
export CVND_JRC_OCCURRENCE_RASTER='/data/static/jrc_occurrence.tif'
export CVND_SRTM_RASTER='/data/static/srtm.vrt'
export CVND_WORLDCOVER_RASTER='/data/static/worldcover_2021.vrt'
export CVND_INDIA_BOUNDARY_VECTOR='/data/static/usdos_lsib_india.geojson'
venv/bin/pip install -r requirements.txt
venv/bin/python src/copernicus_local.py preflight
```

The S2 cache downloads only B02/B03/B04/B08 at 10 m, SCL at 20 m and required
metadata. S1 GRD SAFE products are complete downloads because SNAP needs their
manifest, annotation, calibration and noise files. Product IDs are globally
deduplicated under `data/cache/copernicus/products/`; event references live in
`scene_manifest.json`. SNAP outputs and static block caches are shared as well.

## Safe staged run

Catalogue planning is public and downloads nothing:

```bash
venv/bin/python src/copernicus_local.py plan E092::nadia
```

Before migrating the remainder, build a local candidate for a small completed
GEE example and compare the two H5 contracts:

```bash
venv/bin/python src/copernicus_local.py run --validation-copy EVENT::DISTRICT
venv/bin/python src/copernicus_local.py compare reference.h5 candidate.h5
```

Run the remaining Track B and overlap CUDA inference with completed H5 files:

```bash
SITS_BACKEND=cdse-local SATELLITE_TRACK=B SATELLITE_ROUTING=sits_primary \
SKIP_GEE=0 bash scripts/run_pipeline.sh
```

Despite the historical `SKIP_GEE` variable name, `SKIP_GEE=0` means “run the
satellite stage”; with `SITS_BACKEND=cdse-local` and `SATELLITE_TRACK=B`, neither
AOI resolution nor Track B initializes Earth Engine. Track A remains cached.

Raw products are never deleted automatically. `copernicus_local.py prune`
lists unreferenced candidates; deletion happens only with the explicit
`--execute` flag.
