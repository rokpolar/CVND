import pandas as pd
import numpy as np
import json
import re
import os
import warnings
warnings.filterwarnings('ignore')

# ── District/state centroid lookup ────────────────────────────────────────────
# (lon_min, lat_min, lon_max, lat_max) bboxes per state
# Used when EM-DAT lat/lon is missing or coarse
STATE_BBOX = {
    'Andhra Pradesh':    '77.0,12.5,84.8,19.9',
    'Arunachal Pradesh': '91.5,26.5,97.4,29.5',
    'Assam':             '89.7,24.1,96.0,27.9',
    'Bihar':             '83.3,24.3,88.3,27.5',
    'Chhattisgarh':      '80.2,17.8,84.4,24.1',
    'Delhi':             '76.8,28.4,77.6,28.9',
    'Goa':               '73.6,14.9,74.4,15.8',
    'Gujarat':           '68.2,20.1,74.5,24.7',
    'Haryana':           '74.5,27.7,77.6,30.9',
    'Himachal Pradesh':  '75.6,30.4,79.0,33.2',
    'Jharkhand':         '83.3,21.9,87.9,25.3',
    'Karnataka':         '74.1,11.6,78.6,18.5',
    'Kerala':            '74.8,8.3,77.6,12.8',
    'Madhya Pradesh':    '74.0,21.1,82.8,26.9',
    'Maharashtra':       '72.6,15.6,80.9,22.0',
    'Manipur':           '93.0,23.8,94.8,25.7',
    'Meghalaya':         '89.8,25.0,92.8,26.1',
    'Mizoram':           '92.3,21.9,93.5,24.5',
    'Nagaland':          '93.3,25.1,95.3,27.0',
    'Odisha':            '81.4,17.8,87.5,22.6',
    'Punjab':            '73.9,29.5,76.9,32.5',
    'Rajasthan':         '69.5,23.0,78.3,30.2',
    'Sikkim':            '88.0,27.1,88.9,28.1',
    'Tamil Nadu':        '76.2,8.1,80.3,13.6',
    'Telangana':         '77.2,15.9,81.3,19.9',
    'Tripura':           '91.2,22.9,92.3,24.5',
    'Uttar Pradesh':     '77.1,23.9,84.7,30.4',
    'Uttarakhand':       '78.0,28.7,81.0,31.5',
    'West Bengal':       '85.8,21.5,89.9,27.2',
    'Jammu and Kashmir': '73.7,32.3,80.4,36.6',
}

# Income group assignment per state (consistent with existing events.csv)
STATE_INCOME = {
    'Andhra Pradesh':    'Middle',
    'Arunachal Pradesh': 'Low',
    'Assam':             'Low',
    'Bihar':             'Low',
    'Chhattisgarh':      'Low',
    'Delhi':             'High',
    'Goa':               'High',
    'Gujarat':           'High',
    'Haryana':           'High',
    'Himachal Pradesh':  'Low',
    'Jharkhand':         'Low',
    'Karnataka':         'High',
    'Kerala':            'Middle',
    'Madhya Pradesh':    'Low',
    'Maharashtra':       'High',
    'Manipur':           'Low',
    'Meghalaya':         'Low',
    'Mizoram':           'Low',
    'Nagaland':          'Low',
    'Odisha':            'Low',
    'Punjab':            'Middle',
    'Rajasthan':         'Low',
    'Sikkim':            'Low',
    'Tamil Nadu':        'Middle',
    'Telangana':         'High',
    'Tripura':           'Low',
    'Uttar Pradesh':     'Low',
    'Uttarakhand':       'Low',
    'West Bengal':       'Middle',
    'Jammu and Kashmir': 'Low',
}

# Name normalization: EM-DAT variants → standard names
EMDAT_STATE_NORM = {
    'Orissa':                'Odisha',
    'Uttaranchal':           'Uttarakhand',
    'Pondicherry':           'Puducherry',
    'Jammu & Kashmir':       'Jammu and Kashmir',
    'Andaman & Nicobar':     'Andaman and Nicobar Islands',
    'Andaman and Nicobar':   'Andaman and Nicobar Islands',
    'Dadra & Nagar Haveli':  'Dadra and Nagar Haveli',
    'Daman & Diu':           'Daman and Diu',
    'J & K':                 'Jammu and Kashmir',
    'J&K':                   'Jammu and Kashmir',
    'HP':                    'Himachal Pradesh',
    'UP':                    'Uttar Pradesh',
    'MP':                    'Madhya Pradesh',
    'AP':                    'Andhra Pradesh',
    'WB':                    'West Bengal',
    'TN':                    'Tamil Nadu',
    'UK':                    'Uttarakhand',
}

# State capitals — used as district fallback when extraction fails
STATE_CAPITAL = {
    'Andhra Pradesh':    'Amaravati',
    'Arunachal Pradesh': 'Itanagar',
    'Assam':             'Guwahati',
    'Bihar':             'Patna',
    'Chhattisgarh':      'Raipur',
    'Delhi':             'Delhi',
    'Goa':               'Panaji',
    'Gujarat':           'Gandhinagar',
    'Haryana':           'Chandigarh',
    'Himachal Pradesh':  'Shimla',
    'Jharkhand':         'Ranchi',
    'Karnataka':         'Bengaluru',
    'Kerala':            'Thiruvananthapuram',
    'Madhya Pradesh':    'Bhopal',
    'Maharashtra':       'Mumbai',
    'Manipur':           'Imphal',
    'Meghalaya':         'Shillong',
    'Mizoram':           'Aizawl',
    'Nagaland':          'Kohima',
    'Odisha':            'Bhubaneswar',
    'Punjab':            'Chandigarh',
    'Rajasthan':         'Jaipur',
    'Sikkim':            'Gangtok',
    'Tamil Nadu':        'Chennai',
    'Telangana':         'Hyderabad',
    'Tripura':           'Agartala',
    'Uttar Pradesh':     'Lucknow',
    'Uttarakhand':       'Dehradun',
    'West Bengal':       'Kolkata',
    'Jammu and Kashmir': 'Srinagar',
}

# All known state/UT names — used to detect invalid district names
ALL_STATE_NAMES = set(STATE_BBOX.keys()) | set(EMDAT_STATE_NORM.keys()) | {
    'provinces', 'province', 'district', 'districts', 'region',
    'areas', 'area', 'zone', 'zones', 'state', 'states'
}

def is_valid_district(name, state):
    """Returns False if the district name is actually a state name or garbage."""
    if not name or len(name.strip()) < 2:
        return False
    name_lower = name.lower().strip()
    # Reject if it contains any state name
    for s in ALL_STATE_NAMES:
        if s.lower() in name_lower and s.lower() != state.lower():
            return False
    # Reject if it ends with 'province', 'provinces', 'a.' (garbled)
    bad_suffixes = ['province', 'provinces', 'a.', 'region', 'district']
    for suffix in bad_suffixes:
        if name_lower.endswith(suffix):
            return False
    # Reject if too long (likely a sentence fragment)
    if len(name) > 35:
        return False
    return True

def normalize_state(name):
    name = str(name).strip()
    return EMDAT_STATE_NORM.get(name, name)


def parse_admin_units(admin_str):
    """
    Extract state names from EM-DAT Admin Units JSON.
    Returns list of normalized state names.
    """
    if pd.isna(admin_str) or admin_str == '':
        return []
    try:
        units = json.loads(str(admin_str))
        states = []
        for u in units:
            if 'adm1_name' in u:
                s = normalize_state(u['adm1_name'])
                if s not in states:
                    states.append(s)
        return states
    except:
        return []


def parse_primary_district(admin_str):
    """
    Extract first adm2 district name from Admin Units JSON.
    Falls back to empty string.
    """
    if pd.isna(admin_str) or admin_str == '':
        return ''
    try:
        units = json.loads(str(admin_str))
        for u in units:
            if 'adm2_name' in u:
                return str(u['adm2_name']).strip()
        return ''
    except:
        return ''


def parse_states_from_location(location_str):
    """
    Fallback: extract state names from free-text Location field.
    Matches known state names as substrings.
    """
    if pd.isna(location_str):
        return []
    loc = str(location_str)
    found = []
    for state in STATE_BBOX.keys():
        if state.lower() in loc.lower():
            if state not in found:
                found.append(state)
    # Also check normalized variants
    for variant, standard in EMDAT_STATE_NORM.items():
        if variant.lower() in loc.lower() and standard not in found:
            found.append(standard)
    return found


def make_date(year, month, day, default_day=1):
    """Build date string from potentially NaN EM-DAT fields."""
    try:
        y = int(year)
        m = int(month) if not pd.isna(month) else 6
        d = int(day)   if not pd.isna(day)   else default_day
        m = max(1, min(12, m))
        d = max(1, min(31, d))
        return f'{y:04d}-{m:02d}-{d:02d}'
    except:
        return None


def assign_district(state, admin_str, location_str):
    """
    Best-effort district extraction with validation.
    Falls back to state capital if extracted name is invalid.
    """
    # Try Admin Units JSON first (most reliable)
    d = parse_primary_district(admin_str)
    if d and is_valid_district(d, state):
        return d

    # Try Location text — first token that looks like a district
    if not pd.isna(location_str):
        loc = str(location_str)
        tokens = [t.strip() for t in re.split(r'[,;()]', loc)]
        for t in tokens:
            t = t.strip()
            if t and is_valid_district(t, state):
                return t[:35]

    # Final fallback: state capital
    return STATE_CAPITAL.get(state, state)


# ── Main parser ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 60)
    print("BUILD EVENTS CSV FROM EM-DAT")
    print("=" * 60)

    EMDAT_PATH   = 'data/emdat_raw.xlsx'
    EXISTING_CSV = 'data/events_base12.csv'
    OUTPUT_CSV   = 'data/events.csv'

    if not os.path.exists(EMDAT_PATH):
        print(f"ERROR: {EMDAT_PATH} not found.")
        print("Download from emdat.be and save as data/emdat_raw.xlsx")
        exit(1)

    raw = pd.read_excel(EMDAT_PATH, header=0)
    print(f"\nEM-DAT raw: {raw.shape[0]} records, {raw.shape[1]} columns")

    # ── Step 1: Filter to flood events with Sentinel-1 coverage ──────────────
    raw = raw[raw['Disaster Type'].str.lower() == 'flood'].copy()
    raw = raw[raw['Start Year'] >= 2015].copy()
    raw = raw[raw['Start Year'] <= 2026].copy()
    print(f"After filter (flood, 2015-2024): {len(raw)} records")

    # ── Step 2: Explode multi-state records into one row per state ────────────
    exploded_rows = []
    skipped       = 0

    for _, row in raw.iterrows():
        disno      = str(row['DisNo.'])
        start_date = make_date(row['Start Year'], row['Start Month'], row['Start Day'], default_day=1)
        end_date   = make_date(row['End Year'],   row['End Month'],   row['End Day'],   default_day=28)

        if start_date is None or end_date is None:
            skipped += 1
            continue

        # Ensure end >= start
        if end_date < start_date:
            end_date = start_date

        # Extract states: Admin Units JSON first, fallback to Location text
        states = parse_admin_units(row.get('Admin Units', ''))
        if not states:
            states = parse_states_from_location(row.get('Location', ''))

        if not states:
            skipped += 1
            continue

        for state in states:
            if state not in STATE_BBOX:
                continue   # skip UTs / states outside our bbox table

            district = assign_district(state, row.get('Admin Units', ''), row.get('Location', ''))
            bbox     = STATE_BBOX[state]
            income   = STATE_INCOME.get(state, 'Low')

            exploded_rows.append({
                'emdat_disno':    disno,
                'state':          state,
                'district':       district,
                'disaster_type':  'flood',
                'start_date':     start_date,
                'end_date':       end_date,
                'bbox':           bbox,
                'income_group':   income,
                'total_deaths':   row.get('Total Deaths', np.nan),
                'total_affected': row.get('Total Affected', np.nan),
            })

    emdat_df = pd.DataFrame(exploded_rows)
    print(f"\nAfter state explosion: {len(emdat_df)} state-level records")
    print(f"Skipped (bad dates / no state): {skipped}")

    # ── Step 3: Deduplicate — same state + overlapping dates = one event ──────
    emdat_df['start_dt'] = pd.to_datetime(emdat_df['start_date'])
    emdat_df['end_dt']   = pd.to_datetime(emdat_df['end_date'])
    emdat_df = emdat_df.sort_values(['state', 'start_dt'])

    deduped = []
    for state, grp in emdat_df.groupby('state'):
        grp = grp.reset_index(drop=True)
        merged = [grp.iloc[0].to_dict()]
        for i in range(1, len(grp)):
            cur  = grp.iloc[i]
            prev = merged[-1]
            # Overlap: current start within 30 days of previous end
            if (cur['start_dt'] - prev['end_dt']).days <= 30:
                # Extend the window, keep worst-case damage stats
                prev['end_date'] = max(prev['end_date'], cur['end_date'])
                prev['end_dt']   = max(prev['end_dt'],   cur['end_dt'])
                prev['total_deaths']   = max(
                    prev.get('total_deaths', 0) or 0,
                    cur.get('total_deaths', 0) or 0)
                prev['total_affected'] = max(
                    prev.get('total_affected', 0) or 0,
                    cur.get('total_affected', 0) or 0)
                merged[-1] = prev
            else:
                merged.append(cur.to_dict())
        deduped.extend(merged)

    deduped_df = pd.DataFrame(deduped)
    print(f"After deduplication (30-day merge window): {len(deduped_df)} events")

    # ── Step 4: Load existing 12 events, merge, assign event IDs ─────────────
    existing = pd.read_csv(EXISTING_CSV)
    existing_keys = set(
        zip(existing['state'], existing['start_date'])
    )
    print(f"\nExisting events: {len(existing)}")

    # Flag which EM-DAT rows overlap with existing events
    # Match: same state AND start date within 14 days
    existing['start_dt'] = pd.to_datetime(existing['start_date'])

    new_rows = []
    duplicates_of_existing = 0

    for _, row in deduped_df.iterrows():
        state     = row['state']
        start_dt  = row['start_dt']
        # Check if this state+date already exists in the 12 events
        match = existing[
            (existing['state'] == state) &
            (abs(existing['start_dt'] - start_dt).dt.days <= 14)
        ]
        if not match.empty:
            duplicates_of_existing += 1
            continue
        new_rows.append(row)

    new_df = pd.DataFrame(new_rows)
    print(f"EM-DAT events overlapping existing 12: {duplicates_of_existing} (skipped)")
    print(f"New events to add: {len(new_df)}")

    # ── Step 5: Assign event IDs and build final merged CSV ───────────────────
    # Keep existing IDs (E01-E12), new ones start from E13
    next_id = 13
    new_event_ids = []
    for _ in range(len(new_df)):
        new_event_ids.append(f'E{next_id:02d}')
        next_id += 1

    new_df = new_df.copy()
    new_df['event_id'] = new_event_ids

    # Build lat/lon from bbox center for new events
    def bbox_center_lat(bbox):
        parts = [float(x) for x in bbox.split(',')]
        return round((parts[1] + parts[3]) / 2, 2)

    def bbox_center_lon(bbox):
        parts = [float(x) for x in bbox.split(',')]
        return round((parts[0] + parts[2]) / 2, 2)

    new_df['lat'] = new_df['bbox'].apply(bbox_center_lat)
    new_df['lon'] = new_df['bbox'].apply(bbox_center_lon)

    # Final columns matching existing events.csv schema
    final_cols = ['event_id', 'state', 'district', 'disaster_type',
                  'start_date', 'end_date', 'lat', 'lon', 'bbox', 'income_group']

    existing_clean = existing[final_cols].copy()
    new_clean      = new_df[final_cols].copy()
    merged         = pd.concat([existing_clean, new_clean], ignore_index=True)

    # ── Step 6: Validation ────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("VALIDATION")
    print("=" * 60)

    errors = []

    # No duplicate event IDs
    dupes = merged[merged.duplicated('event_id')]
    if not dupes.empty:
        errors.append(f"Duplicate event IDs: {dupes['event_id'].tolist()}")
    else:
        print(f"  OK  No duplicate event IDs")

    # Date sanity
    merged['start_dt'] = pd.to_datetime(merged['start_date'])
    merged['end_dt']   = pd.to_datetime(merged['end_date'])
    bad_dates = merged[merged['end_dt'] < merged['start_dt']]
    if not bad_dates.empty:
        errors.append(f"end < start: {bad_dates['event_id'].tolist()}")
    else:
        print(f"  OK  All dates valid")

    # Income group distribution
    ic = merged['income_group'].value_counts()
    print(f"  OK  Income distribution: {ic.to_dict()}")

    # State distribution
    sc = merged['state'].value_counts()
    print(f"  OK  States covered: {len(sc)}")
    print(f"      Events per state (top 10):")
    for state, cnt in sc.head(10).items():
        print(f"        {state}: {cnt}")

    # Year distribution
    merged['year'] = merged['start_dt'].dt.year
    yc = merged['year'].value_counts().sort_index()
    print(f"  OK  Year distribution: {yc.to_dict()}")

    print(f"\n  TOTAL EVENTS: {len(merged)}")

    if errors:
        print("\nVALIDATION ERRORS:")
        for e in errors:
            print(f"  ERROR: {e}")
        print("Fix before proceeding.")
    else:
        merged = merged.drop(columns=['start_dt', 'end_dt', 'year'], errors='ignore')
        merged.to_csv(OUTPUT_CSV, index=False)
        print(f"\nSAVED: {OUTPUT_CSV} ({len(merged)} events)")

        # Preview new events
        print(f"\nNew events added (E13 onwards) — first 15:")
        print(merged[merged['event_id'] >= 'E13'].head(15)[
            ['event_id', 'state', 'district', 'start_date', 'income_group']
        ].to_string(index=False))

        print("\nCP-02b COMPLETE — events.csv expanded, ready for CP-08")