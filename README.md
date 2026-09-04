# CVND (가제)

Satellite vision - media coverage for quantifying bias in climate disaster reporting
ICCJ 2026 in Bangaluru, India

Article-level GDELT collection and event relevance filtering are documented in
[`docs/gdelt_collection.md`](docs/gdelt_collection.md).

## Local satellite inference

Track B stores every downloaded HDF5 patch file under
`data/cache/sits_patches/`. Completed HDF5 files are scored locally with the
official SITS-Extreme-VAE model; input HDF5 files are retained after inference.
The official seed-42 checkpoint is checksum-verified and loaded directly from
`SITS-ExtremeEvents-main/checkpoints/ravaen/`. No model download is performed.

```bash
# Resume/download satellite H5 files.
venv/bin/python src/satellite.py --track B

# Score all completed H5 files on the local GPU (CPU fallback is automatic).
venv/bin/python src/run_sits_inference.py
```

The full pipeline runs local inference automatically after Track B:

```bash
SKIP_ARTICLES=1 bash scripts/run_pipeline.sh
```
