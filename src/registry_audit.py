"""Read-only comparison of the stored cohort to the current registry derivation."""
import pandas as pd
from cvnd_layout import data_path
from district_articles import registry_fingerprint


def registry_drift():
    from build_emdat_events import load_official_workbook, build_state_events, build_event_districts
    from district_recovery import apply_registry_exclusions, recover_from_files
    base, _ = load_official_workbook(data_path('emdat_base'))
    _, states = build_state_events(base)
    generated = recover_from_files(build_event_districts(base, states), data_path('district_recovery_mapping'))
    generated, _ = apply_registry_exclusions(generated, data_path('district_registry_exclusions'))
    stored = pd.read_csv(data_path('event_districts'), dtype=str, keep_default_na=False)
    old, new = registry_fingerprint(stored), registry_fingerprint(generated)
    return {'status': 'current' if old == new else 'snapshot_differs_from_current_derivation',
            'stored_rows': len(stored), 'derived_rows': len(generated),
            'stored_registry_sha256': old, 'derived_registry_sha256': new,
            'added_keys': sorted(set(generated.event_district_id) - set(stored.event_district_id)),
            'removed_keys': sorted(set(stored.event_district_id) - set(generated.event_district_id))}
