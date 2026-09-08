# Archived non-primary utilities

State-level analysis scripts were removed. The supported analysis path is the
district pipeline in the repository root and `src/`.

| Script | Role |
| --- | --- |
| `build_events.py` | Validate the parent registry generated from official `EM-DAT-BASE.xlsx` |
| `fix_districts.py` | Legacy district geocode audit; never overwrites canonical events |
| `test_gee.py` | GEE connectivity smoke test |

To re-run an archived script from repo root:

```bash
python src/archive/<script>.py
```

`build_events.py` no longer contains an embedded event list. Different
official `DisNo.` records are never merged and manual event seeds are not used.
