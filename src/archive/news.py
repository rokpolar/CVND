"""
LEGACY / OPTIONAL — GDELT Doc API collector.

Primary MSS reads data/gdelt_bq.json via src/compute_mss.py.
This script does not feed the current scoring path.
"""
import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import os
import json
import warnings
warnings.filterwarnings('ignore')

# ── Synonym map (all 30 states) ───────────────────────────────────────────────
SYNONYMS = {
    'Andhra Pradesh':    ['Andhra Pradesh', 'Amaravati', 'Vijayawada', 'Visakhapatnam'],
    'Arunachal Pradesh': ['Arunachal Pradesh', 'Itanagar'],
    'Assam':             ['Assam', 'Guwahati', 'Silchar', 'Dibrugarh', 'Barak Valley'],
    'Bihar':             ['Bihar', 'Patna', 'Muzaffarpur', 'North Bihar'],
    'Chhattisgarh':      ['Chhattisgarh', 'Raipur', 'Bilaspur'],
    'Delhi':             ['Delhi', 'New Delhi', 'Yamuna flood'],
    'Goa':               ['Goa', 'Panaji', 'Margao'],
    'Gujarat':           ['Gujarat', 'Ahmedabad', 'Surat', 'Gandhinagar'],
    'Haryana':           ['Haryana', 'Chandigarh', 'Gurugram', 'Faridabad'],
    'Himachal Pradesh':  ['Himachal Pradesh', 'Shimla', 'Mandi', 'Himachal'],
    'Jammu and Kashmir': ['Jammu Kashmir', 'Srinagar', 'Jammu', 'J&K'],
    'Jharkhand':         ['Jharkhand', 'Ranchi', 'Dhanbad'],
    'Karnataka':         ['Karnataka', 'Bengaluru', 'Bangalore', 'Mangaluru'],
    'Kerala':            ['Kerala', 'Kochi', 'Thiruvananthapuram', 'Ernakulam'],
    'Madhya Pradesh':    ['Madhya Pradesh', 'Bhopal', 'Indore', 'MP flood'],
    'Maharashtra':       ['Maharashtra', 'Mumbai', 'Pune', 'Raigad', 'Konkan'],
    'Manipur':           ['Manipur', 'Imphal'],
    'Meghalaya':         ['Meghalaya', 'Shillong'],
    'Mizoram':           ['Mizoram', 'Aizawl'],
    'Nagaland':          ['Nagaland', 'Kohima', 'Dimapur'],
    'Odisha':            ['Odisha', 'Bhubaneswar', 'Balasore', 'Orissa'],
    'Punjab':            ['Punjab', 'Chandigarh', 'Ludhiana', 'Amritsar'],
    'Rajasthan':         ['Rajasthan', 'Jaipur', 'Jodhpur'],
    'Sikkim':            ['Sikkim', 'Gangtok'],
    'Tamil Nadu':        ['Tamil Nadu', 'Chennai', 'Madurai', 'Tamilnadu'],
    'Telangana':         ['Telangana', 'Hyderabad', 'Warangal'],
    'Tripura':           ['Tripura', 'Agartala'],
    'Uttar Pradesh':     ['Uttar Pradesh', 'Lucknow', 'Bahraich', 'UP flood'],
    'Uttarakhand':       ['Uttarakhand', 'Dehradun', 'Chamoli', 'Uttaranchal'],
    'West Bengal':       ['West Bengal', 'Kolkata', 'Howrah', 'WB flood'],
}

CHECKPOINT_PATH = 'data/raw_gdelt_checkpoint.json'
OUTPUT_PATH     = 'data/raw_gdelt.csv'


def build_queries(state):
    terms = SYNONYMS.get(state, [state])
    return [f'flood "{t}"' for t in terms]


def query_gdelt_window(query, start_dt, end_dt, max_records=250):
    """Single GDELT API call for one weekly window."""
    params = {
        'query':         query,
        'mode':          'artlist',
        'maxrecords':    max_records,
        'startdatetime': start_dt.strftime('%Y%m%d%H%M%S'),
        'enddatetime':   end_dt.strftime('%Y%m%d%H%M%S'),
        'format':        'json',
        'sort':          'datedesc'
    }
    try:
        resp = requests.get(
            'https://api.gdeltproject.org/api/v2/doc/doc',
            params=params, timeout=30
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get('articles', [])
    except Exception as e:
        return []


def collect_articles_paginated(state, start_date, end_date):
    """Weekly pagination + synonym queries. Returns deduplicated articles."""
    queries      = build_queries(state)
    all_urls     = set()
    all_articles = []

    event_end_ext = end_date + timedelta(days=14)
    window_start  = start_date - timedelta(days=3)

    while window_start < event_end_ext:
        window_end = min(window_start + timedelta(days=7), event_end_ext)
        for query in queries:
            articles = query_gdelt_window(query, window_start, window_end)
            for a in articles:
                url = a.get('url', '')
                if url and url not in all_urls:
                    all_urls.add(url)
                    all_articles.append(a)
            time.sleep(0.3)
        window_start = window_end

    return all_articles


def compute_mss_inputs(articles, event_start):
    """Compute raw MSS input metrics from article list."""
    if not articles:
        return {
            'article_count': 0, 'coverage_days': 0,
            'time_to_first_report': 14, 'avg_tone': 0.0
        }

    pub_dates = []
    for a in articles:
        try:
            pub_dates.append(datetime.strptime(a['seendate'][:8], '%Y%m%d'))
        except:
            pass

    tones = []
    for a in articles:
        t = a.get('tone', {})
        score = t.get('score') if isinstance(t, dict) else (t if isinstance(t, (int, float)) else None)
        if score is not None:
            tones.append(score)

    if pub_dates:
        time_to_first = max(0, (min(pub_dates) - event_start).days)
        coverage_days = (max(pub_dates) - min(pub_dates)).days + 1
    else:
        time_to_first = 14
        coverage_days = 0

    return {
        'article_count':        len(articles),
        'coverage_days':        coverage_days,
        'time_to_first_report': time_to_first,
        'avg_tone':             round(sum(tones) / len(tones), 2) if tones else 0.0
    }


def load_checkpoint():
    """Load previously completed event IDs from checkpoint file."""
    if os.path.exists(CHECKPOINT_PATH):
        with open(CHECKPOINT_PATH, 'r') as f:
            return json.load(f)
    return {}


def save_checkpoint(completed):
    """Save completed results to checkpoint file."""
    with open(CHECKPOINT_PATH, 'w') as f:
        json.dump(completed, f)


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 60)

    events     = pd.read_csv('data/events.csv')
    total      = len(events)
    print(f"GDELT NEWS COLLECTION ({total} events) — OPTIONAL / LEGACY")
    print("=" * 60)
    print("Primary MSS reads gdelt_bq.json, not this script's output")
    print("Checkpointing enabled — safe to interrupt and resume\n")

    completed  = load_checkpoint()   # dict: event_id -> result dict
    results    = list(completed.values())
    done_ids   = set(completed.keys())

    remaining  = events[~events['event_id'].isin(done_ids)]
    print(f"Total events : {total}")
    print(f"Already done : {len(done_ids)}")
    print(f"Remaining    : {len(remaining)}\n")

    for i, (_, row) in enumerate(remaining.iterrows(), 1):
        event_id   = row['event_id']
        state      = row['state']
        district   = row['district']
        start_date = datetime.strptime(row['start_date'], '%Y-%m-%d')
        end_date   = datetime.strptime(row['end_date'],   '%Y-%m-%d')

        print(f"[{len(done_ids)+i}/{total}] {event_id} — {state} / {district} "
              f"({row['start_date']})")

        articles   = collect_articles_paginated(state, start_date, end_date)
        mss_inputs = compute_mss_inputs(articles, start_date)

        print(f"  articles={mss_inputs['article_count']:>4}  "
              f"coverage_days={mss_inputs['coverage_days']:>3}  "
              f"time_to_first={mss_inputs['time_to_first_report']:>2}d  "
              f"tone={mss_inputs['avg_tone']:>6.2f}")

        result = {
            'event_id':             event_id,
            'state':                state,
            'article_count':        mss_inputs['article_count'],
            'coverage_days':        mss_inputs['coverage_days'],
            'time_to_first_report': mss_inputs['time_to_first_report'],
            'avg_tone':             mss_inputs['avg_tone']
        }

        completed[event_id] = result
        results_so_far = list(completed.values())

        # Save checkpoint after every event
        save_checkpoint(completed)

        # Also write partial CSV after every 10 events
        if (len(done_ids) + i) % 10 == 0:
            pd.DataFrame(results_so_far).to_csv(OUTPUT_PATH, index=False)
            print(f"  >> Checkpoint saved ({len(completed)}/{total} complete)")

    # Final save
    df = pd.DataFrame(list(completed.values()))
    df = df.sort_values('event_id').reset_index(drop=True)
    df.to_csv(OUTPUT_PATH, index=False)

    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    print(f"Total processed: {len(df)}")
    print(f"Article range  : {df['article_count'].min()} – {df['article_count'].max()}")
    print(f"Mean articles  : {df['article_count'].mean():.1f}")

    print("\nTop 5 by article count:")
    print(df.nlargest(5, 'article_count')[
        ['event_id', 'state', 'article_count', 'coverage_days']
    ].to_string(index=False))

    print("\nBottom 5 by article count:")
    print(df.nsmallest(5, 'article_count')[
        ['event_id', 'state', 'article_count', 'coverage_days']
    ].to_string(index=False))

    zero = df[df['article_count'] == 0]
    if not zero.empty:
        print(f"\nWARN: {len(zero)} events with 0 articles — "
              f"will get MSS=0 in CP-09")
        print(zero[['event_id', 'state']].to_string(index=False))

    print(f"\nSAVED: {OUTPUT_PATH}")
    print("\nCP-08 COMPLETE — ready for CP-09")