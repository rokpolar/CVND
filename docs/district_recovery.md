# Supplied district recovery

The event builder reads data/raw/district_recovery_mapping.csv. This is a
sanitized mapping derived from the supplied exhaustive recovery file. It stores
event identity, canonical district and source provenance. Recovery grades and
tier columns are not stored.

data/raw/district_recovery_aliases.csv supplies spelling repairs, compound
splits and non-district drops before ID generation. Boundary-crosswalk actions
are excluded because a current name does not establish Census 2011 boundary
equivalence.

Event ID, state, year and any provided date/source identifier must agree with
the official parent event. Missing identity values inherit the parent value.
District rows are deduplicated on the canonical event-district ID, while all
source evidence is retained in district_resolution_evidence.

The primary registry accepts only official government, state government, ISRO
or humanitarian source classes whose circularity risk is blank or `none`.
News-informed geography is excluded because article coverage is the outcome.
The primary registry currently contains 174 events and 1,553 named
event-district rows. The full 190-event, 1,623-row maximal recovery remains in
`data/intermediate/event_districts.news_sensitivity.csv`; it is never used by
the primary pipeline. `data/intermediate/event_registry_exclusions.csv` records
both unresolved and news-only excluded events. Flattened source class, evidence
type, circularity risk and source URL columns accompany the JSON provenance.
No district confidence field is written.

Rebuild with python src/build_emdat_events.py. Downstream article manifests
contain a registry fingerprint and must be regenerated. Existing article bodies
can be reused. AOI and Census matching remain separate validation steps.
