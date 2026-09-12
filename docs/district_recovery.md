# Supplied district recovery

The event builder reads data/raw/district_recovery_mapping.csv. This is a
sanitized mapping derived from the supplied exhaustive recovery file after
accepting every maximal candidate. It stores event identity, canonical district
and source provenance. Recovery grades and tier columns are not stored.

data/raw/district_recovery_aliases.csv supplies spelling repairs, compound
splits and non-district drops before ID generation. Boundary-crosswalk actions
are excluded because a current name does not establish Census 2011 boundary
equivalence.

Event ID, state, year and any provided date/source identifier must agree with
the official parent event. Missing identity values inherit the parent value.
District rows are deduplicated on the canonical event-district ID, while all
source evidence is retained in district_resolution_evidence.

The resulting registry contains 190 events and 1,630 named event-district rows.
The 14 events with no district candidate are omitted from both events.csv and
event_districts.csv: E006, E007, E011, E018, E043, E062, E063, E083, E102,
E105, E123, E147, E149 and E155. No district confidence field is written.

Rebuild with python src/build_emdat_events.py. Downstream article manifests
contain a registry fingerprint and must be regenerated. Existing article bodies
can be reused. AOI and Census matching remain separate validation steps.
