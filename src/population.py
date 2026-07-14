import ee
import pandas as pd
import os
import warnings
import json
warnings.filterwarnings('ignore')

from gee_config import initialize_gee

initialize_gee()


def load_checkpoint(path):
    with open(path, 'r') as f:
        return json.load(f)

def get_worldpop_year(event_year):
    """
    Returns the closest available WorldPop year for India.
    WorldPop GP/100m/pop covers 2000-2020. For post-2020 events, use 2020.
    """
    available_years = list(range(2000, 2021))
    if event_year in available_years:
        return event_year
    elif event_year > 2020:
        return 2020   # most recent available
    else:
        return 2000   # oldest available

def compute_population_exposure(row, flood_df):
    event_id = row['event_id']
    state    = row['state']

    # Get flood extent for this event
    flood_row = flood_df[flood_df['event_id'] == event_id]
    if flood_row.empty:
        print(f"  [{event_id}] SKIP: no flood extent data")
        return {
            'event_id': event_id, 'state': state,
            'affected_area_km2': None,
            'population_exposed': None,
            'worldpop_year_used': None,
            'status': 'SKIPPED_NO_FLOOD_DATA'
        }

    area_km2 = flood_row.iloc[0]['affected_area_km2']
    if pd.isna(area_km2):
        print(f"  [{event_id}] SKIP: flood area is null")
        return {
            'event_id': event_id, 'state': state,
            'affected_area_km2': None,
            'population_exposed': None,
            'worldpop_year_used': None,
            'status': 'SKIPPED_NULL_AREA'
        }

    print(f"\n[{event_id}] {state} / {row['district']} "
          f"(flood area: {area_km2} km²)")

    try:
        bbox   = [float(x) for x in row['bbox'].split(',')]
        region = ee.Geometry.Rectangle(bbox)

        # Year-matched WorldPop (fixes Bug 2)
        event_year    = int(row['start_date'][:4])
        worldpop_year = get_worldpop_year(event_year)
        print(f"    Event year: {event_year} → WorldPop year: {worldpop_year}")

        worldpop = (ee.ImageCollection('WorldPop/GP/100m/pop')
                    .filter(ee.Filter.eq('country', 'IND'))
                    .filter(ee.Filter.eq('year', worldpop_year))
                    .first())

        # Reconstruct flood mask from Sentinel-1 to apply over WorldPop
        pre_start  = ee.Date(row['start_date']).advance(-30, 'day')
        pre_end    = ee.Date(row['start_date'])
        post_start = ee.Date(row['start_date'])
        post_end   = ee.Date(row['start_date']).advance(7, 'day')

        s1 = (ee.ImageCollection('COPERNICUS/S1_GRD')
              .filter(ee.Filter.eq('instrumentMode', 'IW'))
              .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
              .filter(ee.Filter.eq('orbitProperties_pass', 'DESCENDING'))
              .filterBounds(region))

        pre_img  = s1.filterDate(pre_start, pre_end).select('VV').median()
        post_img = s1.filterDate(post_start, post_end).select('VV').median()

        # Use same threshold as satellite.py result
        otsu_thresh = flood_row.iloc[0]['otsu_threshold_db']
        if pd.isna(otsu_thresh):
            otsu_thresh = 3.0
        print(f"    Using threshold: {otsu_thresh} dB")

        flood_mask = pre_img.subtract(post_img).gt(otsu_thresh)

        # Mask WorldPop with flood extent, sum exposed population
        pop_stats = (worldpop
                     .updateMask(flood_mask)
                     .reduceRegion(
                         reducer=ee.Reducer.sum(),
                         geometry=region,
                         scale=100,
                         maxPixels=1e9,
                         bestEffort=True
                     ))

        population = pop_stats.getInfo().get('population', 0) or 0
        population = round(population)

        print(f"    Population exposed: {population:,}")

        if population == 0:
            print(f"    WARN: 0 population exposed — "
                  f"may indicate flood mask / WorldPop mismatch")

        return {
            'event_id': event_id,
            'state': state,
            'affected_area_km2': area_km2,
            'population_exposed': population,
            'worldpop_year_used': worldpop_year,
            'status': 'OK'
        }

    except Exception as e:
        print(f"    ERROR: {e}")
        return {
            'event_id': event_id, 'state': state,
            'affected_area_km2': area_km2,
            'population_exposed': None,
            'worldpop_year_used': None,
            'status': f'ERROR: {e}'
        }


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 55)
    print("CP-06: WORLDPOP POPULATION OVERLAY (168 events)")
    print("=" * 55)

    CHECKPOINT = 'data/population_checkpoint.json'

    events   = pd.read_csv('data/events.csv')
    flood_df = pd.read_csv('data/flood_extent.csv')

    # Load checkpoint
    completed = load_checkpoint(CHECKPOINT) if os.path.exists(CHECKPOINT) else {}

    # Seed from existing severity_raw.csv if checkpoint empty
    if not completed and os.path.exists('data/severity_raw.csv'):
        existing = pd.read_csv('data/severity_raw.csv')
        for _, r in existing.iterrows():
            completed[r['event_id']] = r.to_dict()
        print(f"Seeded {len(completed)} events from existing severity_raw.csv")

    done_ids  = set(completed.keys())
    remaining = events[~events['event_id'].isin(done_ids)]

    print(f"Total   : {len(events)}")
    print(f"Done    : {len(done_ids)}")
    print(f"Remaining: {len(remaining)}\n")

    for i, (_, row) in enumerate(remaining.iterrows(), 1):
        result = compute_population_exposure(row, flood_df)
        completed[row['event_id']] = result

        # Save checkpoint after every event
        with open(CHECKPOINT, 'w') as f:
            import json
            json.dump(completed, f)

        if (len(done_ids) + i) % 10 == 0:
            pd.DataFrame(list(completed.values())).to_csv(
                'data/severity_raw.csv', index=False)
            print(f"  >> Checkpoint: {len(done_ids)+i}/{len(events)} done")

    # Final save
    df = pd.DataFrame(list(completed.values()))
    df = df.sort_values('event_id').reset_index(drop=True)

    print("\n" + "=" * 55)
    print("RESULTS SUMMARY")
    print("=" * 55)
    print(df[['event_id', 'state', 'affected_area_km2',
              'population_exposed', 'worldpop_year_used',
              'status']].to_string(index=False))

    ok      = df[df['status'] == 'OK']
    skipped = df[df['status'].str.startswith('SKIPPED', na=False)]
    errors  = df[df['status'].str.startswith('ERROR', na=False)]

    print(f"\nProcessed : {len(df)}")
    print(f"OK        : {len(ok)}")
    print(f"Skipped   : {len(skipped)}")
    print(f"Errors    : {len(errors)}")

    df.to_csv('data/severity_raw.csv', index=False)
    print(f"\nSAVED: data/severity_raw.csv")
    print("\nCP-06 COMPLETE — ready for CP-07") 