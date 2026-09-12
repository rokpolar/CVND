#!/usr/bin/env python3
"""Build district urbanization covariates from Census of India 2011 data.

The verified source is the ORGI Primary Census Abstract workbook
2011-IndiaStateDist-0000.xlsx (catalog 42557). Its Data and Record Structure
sheets were inspected; it includes 640 districts with three residence rows.  The
builder accepts the published PCA SD layout (``State``, ``District``,
``Level``, ``Name``, ``TRU``, ``TOT_P``), a long
``Residence``/``Population - Persons`` layout, and a wide file with
total/urban/rural population columns.

No data are downloaded or fabricated.  A missing input, unsupported schema,
duplicate district, or conflicting population total fails with an actionable
error.  Name changes and spelling differences require the explicit crosswalk
columns ``registry_state,registry_district,census_state,census_district``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from cvnd_layout import data_path
from district_keys import COVARIATE_COLUMNS, normalize_name, normalize_state_name


CENSUS_YEAR = 2011
CENSUS_SOURCE_URL = "https://censusindia.gov.in/nada/index.php/catalog/42557"
CENSUS_LOCATION_CODE_URL = "https://censusindia.gov.in/nada/index.php/catalog/42648"
EXPECTED_SCHEMA = (
    "PCA SD State/District/Level/Name/TRU/TOT_P; or state and district names "
    "with Residence (Total/Rural/Urban) plus Population - Persons; or "
    "total_population/urban_population/rural_population"
)

# Census 2011's Location Code Directory assigns these codes to states/UTs.
# Telangana was carved out of Andhra Pradesh after this Census and therefore
# has no separate 2011 PCA state code; a Telangana event must use an explicit
# crosswalk if a later boundary source is supplied.
CENSUS_STATE_BY_CODE = {
    1: "Jammu and Kashmir", 2: "Himachal Pradesh", 3: "Punjab", 4: "Chandigarh",
    5: "Uttarakhand", 6: "Haryana", 7: "Delhi", 8: "Rajasthan",
    9: "Uttar Pradesh", 10: "Bihar", 11: "Sikkim", 12: "Arunachal Pradesh",
    13: "Nagaland", 14: "Manipur", 15: "Mizoram", 16: "Tripura",
    17: "Meghalaya", 18: "Assam", 19: "West Bengal", 20: "Jharkhand",
    21: "Odisha", 22: "Chhattisgarh", 23: "Madhya Pradesh", 24: "Gujarat",
    25: "Daman and Diu", 26: "Dadra and Nagar Haveli", 27: "Maharashtra",
    28: "Andhra Pradesh", 29: "Karnataka", 30: "Goa", 31: "Lakshadweep",
    32: "Kerala", 33: "Tamil Nadu", 34: "Puducherry",
    35: "Andaman and Nicobar Islands",
}


def _flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [
            " ".join(str(part).strip() for part in column if str(part).strip() and not str(part).startswith("Unnamed"))
            for column in out.columns
        ]
    out.columns = [str(column).replace("\n", " ").strip() for column in out.columns]
    return out


def _read_input(path: Path, sheet: str | int | None = None) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Census input is missing: {path}. Provide the official Census of India 2011 "
            f"district file with {EXPECTED_SCHEMA}. Source metadata: {CENSUS_SOURCE_URL}"
        )
    if path.suffix.lower() in {".csv", ".tsv"}:
        frame = pd.read_csv(path, sep="\t" if path.suffix.lower() == ".tsv" else ",", dtype=str)
        return _flatten_columns(frame)
    try:
        if sheet is not None:
            return _flatten_columns(pd.read_excel(path, sheet_name=sheet, dtype=str))
        workbook = pd.ExcelFile(path)
        candidates = []
        for name in workbook.sheet_names:
            candidate = _flatten_columns(pd.read_excel(path, sheet_name=name, dtype=str))
            if not candidate.empty:
                candidates.append(candidate)
        if not candidates:
            raise ValueError(f"{path} contains no non-empty worksheets")
        # Prefer the first sheet with a geography/population-looking header;
        # otherwise let schema validation explain what is missing.
        for candidate in candidates:
            keys = {normalize_name(column) for column in candidate.columns}
            if any("district" in key for key in keys) and any("population" in key for key in keys):
                return candidate
        return candidates[0]
    except ImportError as exc:
        raise RuntimeError("Reading Census Excel input requires pandas Excel support (openpyxl/xlrd)") from exc


def _find_column(frame: pd.DataFrame, aliases: Iterable[str], *, required: bool = True) -> str | None:
    columns = {column: normalize_name(column) for column in frame.columns}
    alias_keys = [normalize_name(alias) for alias in aliases]
    for alias in alias_keys:
        for column, key in columns.items():
            if key == alias:
                return column
    if required:
        expected = ", ".join(aliases)
        raise ValueError(f"Census input is missing a required column ({expected}); found: {list(frame.columns)}")
    return None


def _find_geography_columns(frame: pd.DataFrame) -> tuple[str, str, str | None]:
    state = _find_column(
        frame,
        ["state", "state name", "state/ut", "state / union territory", "state/ut name"],
    )
    district = _find_column(
        frame,
        ["district", "district name", "district name (in english)", "area name"],
    )
    code = _find_column(
        frame,
        ["census district code", "district code", "district_code", "district code (2011)", "location code"],
        required=False,
    )
    return state, district, code


def _filter_district_rows(frame: pd.DataFrame) -> pd.DataFrame:
    level = _find_column(frame, ["level", "geographic level", "area type", "location type"], required=False)
    if level is None:
        return frame
    values = frame[level].map(normalize_name)
    keep = values.str.contains("district", na=False)
    # Some files already contain only district rows and label the level as
    # "State/District".  Keep those rows when no explicit district rows exist.
    if not keep.any():
        raise ValueError("Census input contains no explicit DISTRICT-level rows")
    return frame.loc[keep].copy()


def _number(value: Any, *, field: str, row_number: int) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace(",", "")
    if not text or text.casefold() in {"na", "n/a", "null", "-", "—"}:
        return None
    parsed = pd.to_numeric(text, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Census column {field!r} has a non-numeric value at row {row_number}: {value!r}")
    result = float(parsed)
    if not math.isfinite(result) or not result.is_integer():
        raise ValueError(f"Census population must be a finite integer at row {row_number}: {value!r}")
    if result < 0:
        raise ValueError(f"Census column {field!r} has a negative value at row {row_number}: {value!r}")
    return result


def _code(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "na", "n/a", "null"}:
        return None
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return text


def _census_state_name(value: Any) -> str:
    """Resolve the numeric State field used by the official PCA SD file."""

    code = _code(value)
    if code is None:
        return ""
    try:
        number = int(code)
    except ValueError:
        return normalize_state_name(value)
    state = CENSUS_STATE_BY_CODE.get(number)
    if state is None:
        raise ValueError(
            f"Unsupported Census 2011 state code {code!r}; consult the official "
            f"Location Code Directory ({CENSUS_LOCATION_CODE_URL}) and add an explicit mapping"
        )
    return state


def _year(frame: pd.DataFrame) -> int:
    column = _find_column(frame, ["census_year", "census year", "year", "reference year"], required=False)
    if column is None:
        return CENSUS_YEAR
    values = pd.to_numeric(frame[column], errors="coerce")
    if not values.eq(CENSUS_YEAR).all():
        raise ValueError(f"Expected Census year {CENSUS_YEAR} in every row; found invalid/mixed years")
    return CENSUS_YEAR


def _population_wide_columns(frame: pd.DataFrame) -> tuple[str | None, str | None, str | None]:
    total = _find_column(frame, [
        "total_population", "total population", "population total", "population - total",
        "population total persons", "total population (persons)",
    ], required=False)
    urban = _find_column(frame, [
        "urban_population", "urban population", "urban population persons",
        "population urban", "urban - population", "urban total population",
    ], required=False)
    rural = _find_column(frame, [
        "rural_population", "rural population", "rural population persons",
        "population rural", "rural - population", "rural total population",
    ], required=False)
    return total, urban, rural


def _clean_display(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _check_total(total: float | None, urban: float | None, rural: float | None, *, key: str) -> float:
    if urban is None or rural is None:
        raise ValueError(f"Census district {key!r} must contain both urban and rural population")
    computed = urban + rural
    if total is None:
        return computed
    if total != computed:
        raise ValueError(
            f"Census district {key!r} total population ({total}) does not equal urban+rural ({computed})"
        )
    return total


def _base_record(state: str, district: str, code: str | None, total: float, urban: float, rural: float, year: int) -> dict[str, Any]:
    if total <= 0:
        raise ValueError(f"Census district {state}/{district} has non-positive total population")
    share = urban / total
    if not 0 <= share <= 1:
        raise ValueError(f"Census district {state}/{district} has urban_population_share={share}")
    return {
        "state": state,
        "district": district,
        "census_district_code": code,
        "total_population": int(total) if total.is_integer() else total,
        "urban_population": int(urban) if urban.is_integer() else urban,
        "rural_population": int(rural) if rural.is_integer() else rural,
        "urban_population_share": share,
        "census_year": year,
    }


def parse_census_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Parse an official Census table into one validated row per district."""

    frame = _filter_district_rows(_flatten_columns(frame))
    normalized_columns = {normalize_name(column): column for column in frame.columns}
    # The official PCA SD workbook is a code-and-level table.  State and
    # District are location codes; Name is the district display name, TRU is
    # Total/Rural/Urban, and TOT_P is population (persons).
    official_pca = all(
        required in normalized_columns
        for required in ("state", "district", "level", "name", "tru", "tot_p")
    )
    if official_pca:
        state_column = normalized_columns["state"]
        district_column = normalized_columns["name"]
        code_column = normalized_columns["district"]
    else:
        state_column, district_column, code_column = _find_geography_columns(frame)
    year = _year(frame)
    residence_column = normalized_columns.get("tru") if official_pca else _find_column(
        frame,
        ["residence", "total/rural/urban", "total rural urban", "tru", "urban/rural"],
        required=False,
    )
    person_column = normalized_columns.get("tot_p") if official_pca else _find_column(
        frame,
        ["population - persons", "population persons", "population (persons)", "persons population", "population"],
        required=False,
    )
    total_column, urban_column, rural_column = _population_wide_columns(frame)

    records: list[dict[str, Any]] = []
    if residence_column is not None and person_column is not None:
        grouped: dict[tuple[str, str, str | None], dict[str, Any]] = {}
        for row_number, (_, row) in enumerate(frame.iterrows(), start=2):
            state = _census_state_name(row[state_column]) if official_pca else normalize_state_name(row[state_column])
            district = _clean_display(row[district_column])
            if not state or not district or normalize_name(district) in {"india", "total", "state"}:
                continue
            residence = normalize_name(row[residence_column])
            if "urban" in residence and "rural" not in residence:
                kind = "urban"
            elif "rural" in residence:
                kind = "rural"
            elif "total" in residence:
                kind = "total"
            else:
                continue
            code = _code(row[code_column]) if code_column else None
            key = (normalize_name(state), normalize_name(district), code)
            value = _number(row[person_column], field=str(person_column), row_number=row_number)
            if value is None:
                raise ValueError(f"Census population is missing for {state}/{district} ({kind}) at row {row_number}")
            previous = grouped.setdefault(key, {"state": state, "district": district, "code": code})
            if kind in previous and previous[kind] != value:
                raise ValueError(f"Conflicting duplicate Census value for {state}/{district} ({kind})")
            previous[kind] = value
        for item in grouped.values():
            total = _check_total(item.get("total"), item.get("urban"), item.get("rural"), key=f"{item['state']}/{item['district']}")
            records.append(_base_record(item["state"], item["district"], item["code"], total, item["urban"], item["rural"], year))
    else:
        if total_column is None or urban_column is None or rural_column is None:
            raise ValueError(
                f"Unsupported Census schema. Need {EXPECTED_SCHEMA}; found columns: {list(frame.columns)}"
            )
        for row_number, (_, row) in enumerate(frame.iterrows(), start=2):
            state = normalize_state_name(row[state_column])
            district = _clean_display(row[district_column])
            if not state or not district or normalize_name(district) in {"india", "total", "state"}:
                continue
            total = _number(row[total_column], field=str(total_column), row_number=row_number)
            urban = _number(row[urban_column], field=str(urban_column), row_number=row_number)
            rural = _number(row[rural_column], field=str(rural_column), row_number=row_number)
            total = _check_total(total, urban, rural, key=f"{state}/{district}")
            code = _code(row[code_column]) if code_column else None
            records.append(_base_record(state, district, code, total, urban, rural, year))

    out = pd.DataFrame(records)
    if out.empty:
        raise ValueError("Census input yielded no district rows after schema/geography filtering")
    keys = out.apply(lambda row: (normalize_name(row["state"]), normalize_name(row["district"])), axis=1)
    if keys.duplicated().any():
        duplicates = out.loc[keys.duplicated(keep=False), ["state", "district"]].to_dict("records")
        raise ValueError(f"Census input contains duplicate district keys; use an explicit clean source: {duplicates}")
    out["source"] = "census_2011_official"
    out["match_status"] = "matched"
    return out[COVARIATE_COLUMNS]


def _crosswalk_map(path: Path | None) -> dict[tuple[str, str], tuple[str, str]]:
    if path is None or not path.exists():
        return {}
    table = pd.read_csv(path)
    registry_state = _find_column(table, ["registry_state", "source_state", "event_state"], required=True)
    registry_district = _find_column(table, ["registry_district", "source_district", "event_district"], required=True)
    census_state = _find_column(table, ["census_state", "target_state"], required=True)
    census_district = _find_column(table, ["census_district", "target_district"], required=True)
    evidence = _find_column(table, ["notes", "source", "evidence", "citation", "reference"], required=False)
    if evidence is None:
        raise ValueError(
            "District crosswalk must include a non-empty notes/source/evidence column "
            "for each explicit mapping"
        )
    result: dict[tuple[str, str], tuple[str, str]] = {}
    for _, row in table.iterrows():
        source_key = (normalize_name(row[registry_state]), normalize_name(row[registry_district]))
        target_key = (normalize_name(row[census_state]), normalize_name(row[census_district]))
        if not all(source_key) or not all(target_key):
            raise ValueError(f"Crosswalk contains a blank mapping row: {row.to_dict()}")
        if not normalize_name(row[evidence]):
            raise ValueError(f"Crosswalk mapping lacks evidence in {evidence!r}: {row.to_dict()}")
        previous = result.get(source_key)
        if previous is not None and previous != target_key:
            raise ValueError(f"Crosswalk maps one registry district to multiple Census districts: {source_key}")
        result[source_key] = target_key
    return result


def project_to_events(covariates: pd.DataFrame, events: pd.DataFrame, crosswalk_path: Path | None = None) -> pd.DataFrame:
    """Project validated Census rows onto event_district registry rows."""

    required = {"state", "district"}
    missing = required - set(events.columns)
    if missing:
        raise ValueError(f"Events registry is missing required columns: {sorted(missing)}")
    crosswalk = _crosswalk_map(crosswalk_path)
    crosswalk_source = None
    if crosswalk_path is not None and crosswalk:
        digest = hashlib.sha256(crosswalk_path.read_bytes()).hexdigest()
        crosswalk_source = f"{crosswalk_path.name};sha256={digest}"
    lookup: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for _, row in covariates.iterrows():
        key = (normalize_name(row["state"]), normalize_name(row["district"]))
        lookup.setdefault(key, []).append(row.to_dict())

    rows: list[dict[str, Any]] = []
    seen_registry_keys: set[tuple[str, str]] = set()
    for _, event in events.iterrows():
        state = _clean_display(event.get("state"))
        district = _clean_display(event.get("district"))
        registry_key = (normalize_name(state), normalize_name(district))
        # The covariate table is a district lookup, not an event table.  A
        # district can occur in many event windows; emit it once so downstream
        # joins cannot mistake repeated event rows for ambiguous Census data.
        if registry_key in seen_registry_keys and registry_key != ("", ""):
            continue
        seen_registry_keys.add(registry_key)
        output = {column: None for column in COVARIATE_COLUMNS}
        output["state"] = state
        output["district"] = district
        if not state or not district or normalize_name(district) == "district_missing" or normalize_name(state) == "state_missing":
            output["match_status"] = "unresolved"
            rows.append(output)
            continue
        source_key = (normalize_name(state), normalize_name(district))
        target_key = crosswalk.get(source_key, source_key)
        matches = lookup.get(target_key, [])
        if len(matches) == 1:
            output.update(matches[0])
            output["state"] = state
            output["district"] = district
            output["match_status"] = "matched_crosswalk" if source_key in crosswalk else "matched"
            if source_key in crosswalk and crosswalk_source:
                output["source"] = f"{output['source']};crosswalk={crosswalk_source}"
        elif not matches:
            output["source"] = "census_2011_official"
            output["census_year"] = CENSUS_YEAR
            output["match_status"] = "unmatched"
        else:
            output["source"] = "census_2011_official"
            output["census_year"] = CENSUS_YEAR
            output["match_status"] = "ambiguous"
        rows.append(output)
    if not rows:
        return pd.DataFrame(columns=list(events.columns) + COVARIATE_COLUMNS)
    return pd.DataFrame(rows)


def build_district_covariates(
    input_path: Path,
    output_path: Path | None = None,
    *,
    events_path: Path | None = None,
    crosswalk_path: Path | None = None,
    sheet: str | int | None = None,
    recovery_path: Path | None = None,
) -> pd.DataFrame:
    frame = _read_input(Path(input_path), sheet)
    covariates = parse_census_table(frame)
    digest = hashlib.sha256(Path(input_path).read_bytes()).hexdigest()
    covariates['source'] = f"census_2011_official;file={Path(input_path).name};sha256={digest};catalog={CENSUS_SOURCE_URL}"
    if events_path is not None:
        events = pd.read_csv(events_path)
        result = project_to_events(covariates, events, crosswalk_path)
        if recovery_path is not None:
            result = apply_census_recovery(result, events, covariates, recovery_path)
    else:
        result = covariates
    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(output_path, index=False)
    return result


def apply_census_recovery(result, events, census, path):
    """Fill unmatched regions only, from cited names or official 2011 retabulations.

    Explicit event IDs scope a recovery to reviewed registry entries. New events
    are not silently assigned a historical boundary. No parent-area proxy or
    estimated population is accepted. The district lookup remains many-to-one.
    """
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    if payload.get('schema_version') != 1:
        raise ValueError('Unsupported Census recovery schema')
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    out = result.copy()
    key = lambda row: (normalize_name(row['state']), normalize_name(row['district']))
    census_lookup = {key(row): row for row in census.to_dict('records')}
    event_groups = {}
    for row in events.to_dict('records'):
        event_groups.setdefault(key(row), []).append(row)
    seen = set()
    for record in payload['records']:
        k = key(record)
        if k in seen:
            raise ValueError(f'Duplicate Census recovery: {k}')
        seen.add(k)
        source = payload['sources'][record['source_id']]
        if not source.get('url', '').startswith('https://') or not record.get('notes'):
            raise ValueError(f'Census recovery requires source and notes: {k}')
        if record.get('census_year') != 2011:
            raise ValueError(f'Recovery must use 2011 Census: {k}')
        if not record.get('event_ids'):
            raise ValueError(f'Recovery requires reviewed event IDs: {k}')
        if record['method'] == 'census_name_link':
            target = (normalize_name(record['census_state']), normalize_name(record['census_district']))
            if target not in census_lookup:
                raise ValueError(f'Unknown Census recovery target: {target}')
            values = dict(census_lookup[target])
        elif record['method'] == 'official_retabulation':
            nums = {f: _number(record.get(f), field=f, row_number=0)
                    for f in ['total_population', 'urban_population', 'rural_population']}
            if any(v is None for v in nums.values()):
                raise ValueError(f'Missing recovery population: {k}')
            total = _check_total(nums['total_population'], nums['urban_population'], nums['rural_population'], key=str(k))
            geography_id = record.get('geography_id', ':'.join(k))
            values = _base_record(record['state'], record['district'], f'retabulated:{geography_id}', total,
                                  nums['urban_population'], nums['rural_population'], 2011)
        else:
            raise ValueError(f'Unsupported recovery method: {record["method"]}')
        reviewed = set(record['event_ids'])
        rows = event_groups.get(k, [])
        if not rows or any(str(row['event_id']) not in reviewed for row in rows):
            continue
        dates = pd.to_datetime([row.get('start_date') for row in rows], errors='coerce')
        if dates.isna().any():
            continue
        if record.get('valid_from') and (dates < pd.Timestamp(record['valid_from'])).any():
            continue
        if record.get('valid_until') and (dates >= pd.Timestamp(record['valid_until'])).any():
            continue
        mask = out.apply(key, axis=1).map(lambda value: value == k) & out['match_status'].eq('unmatched')
        population_source = values.get('source', source['url'])
        values.update(state=record['state'], district=record['district'],
                      match_status='matched_crosswalk',
                      source=f'census_2011_recovery;method={record["method"]};url={source["url"]};'
                             f'table={source.get("table", "district demography")};'
                             f'notes={record["notes"]};population_source={population_source};'
                             f'file={Path(path).name};sha256={digest}')
        for column in COVARIATE_COLUMNS:
            out.loc[mask, column] = values.get(column)
    return out


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=data_path("census_district_input"))
    parser.add_argument("--output", type=Path, default=data_path("district_covariates"))
    parser.add_argument(
        "--events",
        type=Path,
        default=data_path("event_districts"),
        help="event_districts.csv registry to project onto",
    )
    parser.add_argument("--no-events", action="store_true", help="Write a standalone Census district lookup")
    parser.add_argument("--crosswalk", type=Path, default=data_path("district_crosswalk"))
    parser.add_argument("--sheet", help="Optional Excel sheet name")
    parser.add_argument('--recovery', type=Path, default=data_path('district_crosswalk').with_name('district_census_recovery.json'))
    parser.add_argument('--no-recovery', action='store_true', help='Use the original Census/name crosswalk only')
    parser.add_argument('--unmatched-output', type=Path, help='Optional unresolved-region audit CSV')
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = build_district_covariates(
            args.input,
            args.output,
            events_path=None if args.no_events else args.events,
            crosswalk_path=args.crosswalk if args.crosswalk.exists() else None,
            sheet=args.sheet,
            recovery_path=None if args.no_recovery else args.recovery,
        )
        print(f"Wrote district covariates: {args.output} ({len(result)} rows)")
        if "match_status" in result:
            print(result["match_status"].value_counts(dropna=False).to_string())
        if args.unmatched_output and not args.no_events:
            registry = pd.read_csv(args.events)
            unresolved = result.loc[~result.match_status.isin(['matched', 'matched_crosswalk']),
                                    ['state', 'district', 'match_status']].copy()
            counts = registry.groupby(['state', 'district']).agg(
                event_count=('event_id', 'nunique'),
                event_ids=('event_id', lambda values: '|'.join(sorted(set(values)))))
            unresolved = unresolved.merge(counts, on=['state', 'district'], how='left', validate='one_to_one')
            unresolved['reason'] = 'Requires verified 2011 total and urban/rural population for the district boundary; no parent proxy applied'
            args.unmatched_output.parent.mkdir(parents=True, exist_ok=True)
            unresolved.to_csv(args.unmatched_output, index=False)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
