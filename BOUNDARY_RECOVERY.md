# District boundary recovery — 2026-09-13 KST

## Scope and interpretation

This recovery reconnects previously failed event-district identities. It does
not change event IDs, dates, district registry labels, flood thresholds, or
previously successful measurements. A successful match means the named district
has an explicitly selected reference polygon, **not** that its boundary equals
the boundary on the event date.

- Existing successful rows retain their GAUL reference geometry.
- 173 additional district names / 451 failed rows use pinned geoBoundaries
  gbOpen India ADM2, described by its publisher as representing 2021.
- Five further district names / seven failed rows have approved OSM district
  relation geometries. Their snapshot date is provenance, not a historical
  boundary year. Tamulpur has no verified published-area comparison and is lower
  confidence than the other four supplemental matches.
- Recalculation status is in `data/intermediate/boundary_recovery_summary.json`;
  do not infer completed measurements from the candidate counts above.

## Matching decisions and safeguards

`scripts/build_boundary_manifest.py` contains explicit state-scoped aliases.
There is no fuzzy nearest-name automatic match. Exact/spacing matches, Census
label aliases, and manually reviewed renames are distinguished in the manifest.
The manifests retain the selected feature ID, source, method, evidence and
limitations. Some spelling correspondences are analyst judgments against the
reference catalog, rather than independent official renaming certificates.

geoBoundaries district polygons were checked for validity, unique identity,
at least 90% overlap with their named state layer, and no >1% overlap relative
to the smaller neighboring polygon in that same ADM2 layer. This is an internal
consistency check, not validation against historical survey boundaries. The
ADM1 metadata says 2011 and is not contemporaneous with ADM2. Published ADM2
metadata says 736 units; the pinned downloaded GeoJSON actually has 735 features.
The file's SHA256, not that published count, is used for reproducibility.

OSM selections require an explicit relation ID, admin_level=5, matching state
and LGD district code. Four selected geometries are within 10% of published
district areas; area agreement alone does not establish positional accuracy.
Shamator was rejected (about 193 km2 in OSM vs 469 km2 on the district website).

`src/boundary_recovery.py` verifies raw file checksums and resolves the same
polygon for metadata, Track A and Track B. No fallback to a larger parent
district or state is permitted. Provenance fields include `aoi_source`,
`geometry_id`, `aoi_match_method`, `aoi_boundary_year`,
`aoi_historical_boundary_verified`, `aoi_match_evidence`, and `aoi_boundary_note`.

## Important aggregation restriction

This is a **mixed-reference-vintage dataset**. Existing GAUL parents can overlap
newer child districts, even though the newer ADM2 layer is internally consistent.
`data/intermediate/event_aoi_overlap_audit.csv` lists same-event overlaps >1% of
the smaller polygon. The initial complete planned-geometry audit found 422 pairs
across 101 events (419 mixed-source pairs).

**Do not sum these district flood areas into event totals.** A valid event total
needs a common non-overlapping geography or a union of pixel flood masks, not
addition of existing area numbers. Previously completed rows were deliberately
not remeasured in this matching task. Downstream statistical comparisons should
retain source/vintage flags or use harmonized boundaries.

## Remaining unresolved identities

- Itanagar Capital Region: no suitable district polygon in the reviewed layers.
- Jogbani: municipality; using Araria district would expand the requested area.
- Chengannur: town/taluk; using Alappuzha district would expand the area.
- Mumbai: city versus suburban district extent is ambiguous in the registry.
- Chumoukedima: conflicting published areas; supplemental polygon not verified.
- Shamator: supplemental polygon appears incomplete relative to official area.

All six remain explicitly unresolved, not zero flood area.

## Sources, licensing and reproducibility

- geoBoundaries metadata: https://www.geoboundaries.org/api/current/gbOpen/IND/ADM2/
- Pinned source revision: `9469f09`, India ADM2 SHA256:
  `8bef6929fd65432e7dc775e7c44473e84efff064ebddbfd6b834e6291546db40`.
- Original attribution: geoBoundaries / William & Mary geoLab; Pathways Data
  Pvt. Ltd. and lgdirectory.gov.in, as identified in the downloaded metadata.
  ADM2 license: Open Data Commons Open Database License 1.0.
- ADM1 validation layer: DataMeet India community / Election Commission of
  India; Creative Commons Attribution 2.5 India, per its metadata.
- Supplemental geometries: © OpenStreetMap contributors, ODbL 1.0:
  https://www.openstreetmap.org/copyright . Relation URLs, snapshot dates and
  response SHA256 hashes are retained in the supplemental manifest.
- Small, single-threaded, cached Nominatim lookup followed:
  https://operations.osmfoundation.org/policies/nominatim/ . The lookup script
  is a one-time research helper, not a public geocoding feature or periodic job.

Manifests and raw layers are under `data/raw/geoboundaries_2021/` and
`data/raw/osm_boundary_review/`. Recovery makes timestamped backups before
changing checkpoint/CSV/AOI files. Only one recovery writer may run at a time.
The three files are each atomically replaced, but they are not a single database
transaction: after an abrupt stop, verify their cross-file consistency before
resuming downstream analysis.

Tests: `venv/bin/python -m unittest tests.test_district_satellite tests.test_aoi_spacing tests.test_boundary_recovery`.

Recompute approved remaining failures: `venv/bin/python scripts/run_boundary_recovery.py --workers 8`.
Use `--supplemental-only` for the seven supplemental rows after the main batch.
Do not rebuild manifests from a partially completed checkpoint unless intending
to replace the approved decision set: builders audit the failures present then.
