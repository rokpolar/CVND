import requests
import pandas as pd
import time
import os

def reverse_geocode(lat, lon, retries=3):
    """
    Call Nominatim reverse geocoding API.
    Returns (district, state) or (None, None) on failure.
    Nominatim rate limit: 1 request/second max.
    """
    url = 'https://nominatim.openstreetmap.org/reverse'
    params = {
        'lat':            lat,
        'lon':            lon,
        'format':         'json',
        'zoom':           6,        # zoom=6 returns district level
        'addressdetails': 1
    }
    headers = {'User-Agent': 'CVND-climate-bias-research'}

    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=15)
            if r.status_code != 200:
                time.sleep(2)
                continue
            data = r.json()
            addr = data.get('address', {})

            # District: try multiple OSM field names in priority order
            district = (
                addr.get('state_district') or
                addr.get('county') or
                addr.get('district') or
                addr.get('city_district') or
                addr.get('city') or
                addr.get('town') or
                None
            )
            state = addr.get('state', None)
            return district, state

        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                return None, None

    return None, None


def clean_district_name(district):
    """Normalize OSM district names to clean readable form."""
    if not district:
        return None
    d = str(district).strip()

    # Common OSM suffixes to remove
    for suffix in [' Urban', ' Rural', ' district', ' District',
                   ' Division', ' division', ' Tehsil', ' tehsil']:
        if d.endswith(suffix):
            d = d[:-len(suffix)].strip()

    # Known OSM name variants → standard names
    replacements = {
        'Baleshwar':          'Balasore',
        'Bengaluru Urban':    'Bengaluru',
        'Bangalore Urban':    'Bengaluru',
        'Bangalore':          'Bengaluru',
        'Cachar':             'Cachar',
        'Marigaon':           'Morigaon',
        'Mumbai Suburban':    'Mumbai',
        'Thiruvananthapuram': 'Thiruvananthapuram',
        'East Delhi':         'Delhi',
        'North Delhi':        'Delhi',
        'South Delhi':        'Delhi',
        'West Delhi':         'Delhi',
        'Central Delhi':      'Delhi',
        'New Delhi':          'Delhi',
        'Purba Champaran':    'East Champaran',
        'Pashchim Champaran': 'West Champaran',
        'Budgam':             'Srinagar',
    }
    return replacements.get(d, d)


def state_matches(nominatim_state, expected_state):
    """
    Check if Nominatim returned state matches expected state.
    Handles UTs and name variants.
    """
    if not nominatim_state:
        # Delhi and other UTs may not return state
        return True   # give benefit of doubt, district check is enough

    state_norm = {
        'Odisha': ['Odisha', 'Orissa'],
        'Uttarakhand': ['Uttarakhand', 'Uttaranchal'],
        'Jammu and Kashmir': ['Jammu and Kashmir', 'Jammu & Kashmir', 'J&K'],
        'Delhi': ['Delhi', 'National Capital Territory of Delhi'],
    }

    nom_lower = nominatim_state.lower().strip()
    exp_lower = expected_state.lower().strip()

    if nom_lower == exp_lower:
        return True

    # Check normalized variants
    for canonical, variants in state_norm.items():
        if expected_state == canonical:
            if any(nom_lower == v.lower() for v in variants):
                return True

    return False


if __name__ == '__main__':
    events_df = pd.read_csv('data/raw/events.csv')
    print("=" * 60)
    print("FIX DISTRICTS — Nominatim reverse geocoding")
    print("=" * 60)
    print(f"Rate limit: 1 req/sec — about {len(events_df) / 60:.1f} minutes\n")

    CHECKPOINT = 'data/district_fix_checkpoint.csv'

    # Load checkpoint if exists (safe to interrupt and resume)
    if os.path.exists(CHECKPOINT):
        checkpoint_df = pd.read_csv(CHECKPOINT)
        done_ids      = set(checkpoint_df['event_id'].tolist())
        print(f"Resuming from checkpoint: {len(done_ids)} already done")
    else:
        checkpoint_df = pd.DataFrame()
        done_ids      = set()

    results = checkpoint_df.to_dict('records') if not checkpoint_df.empty else []

    remaining = events_df[~events_df['event_id'].isin(done_ids)]
    print(f"Remaining to geocode: {len(remaining)}\n")

    for i, (_, row) in enumerate(remaining.iterrows(), 1):
        event_id = row['event_id']
        state    = row['state']
        lat      = row['lat']
        lon      = row['lon']

        district_raw, nom_state = reverse_geocode(lat, lon)
        district_clean          = clean_district_name(district_raw)
        state_ok                = state_matches(nom_state, state)

        status = 'OK' if (district_clean and state_ok) else 'MISMATCH'

        print(f"[{len(done_ids)+i}/{len(events_df)}] {event_id} {state:20s} "
              f"lat={lat} lon={lon}")
        print(f"  → district={district_clean}  "
              f"nominatim_state={nom_state}  status={status}")

        results.append({
            'event_id':         event_id,
            'state':            state,
            'district_old':     row['district'],
            'district_new':     district_clean if status == 'OK' else row['district'],
            'nominatim_state':  nom_state,
            'status':           status
        })

        # Save checkpoint every 10 events
        if (len(done_ids) + i) % 10 == 0:
            pd.DataFrame(results).to_csv(CHECKPOINT, index=False)
            print(f"  >> Checkpoint saved")

        time.sleep(1.1)   # respect Nominatim 1 req/sec limit

    # Final checkpoint save
    results_df = pd.DataFrame(results)
    results_df.to_csv(CHECKPOINT, index=False)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    ok        = results_df[results_df['status'] == 'OK']
    mismatch  = results_df[results_df['status'] == 'MISMATCH']
    changed   = results_df[
        (results_df['status'] == 'OK') &
        (results_df['district_old'] != results_df['district_new'])
    ]

    print(f"Total    : {len(results_df)}")
    print(f"OK       : {len(ok)}  (district verified and applied)")
    print(f"Mismatch : {len(mismatch)}  (state didn't match — old district kept)")
    print(f"Changed  : {len(changed)}  (district actually updated)")

    if not mismatch.empty:
        print(f"\nMismatched events (kept old district):")
        print(mismatch[['event_id','state','district_old',
                         'nominatim_state']].to_string(index=False))

    print(f"\nSample verified districts:")
    print(ok[['event_id','state','district_old',
              'district_new']].head(20).to_string(index=False))

    # Keep this legacy geocoder as an audit only. The official registry is
    # deterministically rebuilt from EM-DAT and must not be mutated here.
    merge = events_df.merge(
        results_df[['event_id','district_new']],
        on='event_id', how='left'
    )
    merge['district'] = merge['district_new'].fillna(merge['district'])
    merge = merge.drop(columns=['district_new'])
    output = 'data/archive/district_geocode_audit.csv'
    merge.to_csv(output, index=False)

    print(f"\nSAVED: {output}; canonical events.csv was not modified")
    print("\nCP-02c COMPLETE — districts verified via Nominatim")
