import pandas as pd
import json
import os

print("=" * 55)
print("PROCESSING BIGQUERY MULTILINGUAL GDELT DATA")
print("=" * 55)

# ── Load BigQuery result ──────────────────────────────────────────────────────
with open('data/archive/gdelt_bigquery_lang.json', 'r') as f:
    data = json.load(f)

df = pd.DataFrame(data)
df['article_count'] = df['article_count'].astype(int)
df['avg_tone'] = df['avg_tone'].astype(float)

print(f"\nLoaded {len(df)} language-event rows")
print(f"Events: {df['event_id'].nunique()}")
print(f"Languages found: {sorted(df['source_lang'].unique())}")

# ── Language classification ───────────────────────────────────────────────────
# Indic languages present in the data
INDIC_LANGS = {
    'hin': 'Hindi',
    'mal': 'Malayalam',
    'tam': 'Tamil',
    'tel': 'Telugu',
    'kan': 'Kannada',
    'ben': 'Bengali',
    'mar': 'Marathi',
    'guj': 'Gujarati',
    'pan': 'Punjabi',
    'urd': 'Urdu',
    'nep': 'Nepali',
    'ori': 'Odia',
    'asm': 'Assamese',
    'sin': 'Sinhala',
}

def classify_lang(code):
    if code == 'en':
        return 'english'
    elif code in INDIC_LANGS:
        return 'indic'
    else:
        return 'international'

df['lang_class'] = df['source_lang'].apply(classify_lang)

# ── Aggregate per event ───────────────────────────────────────────────────────
# Total articles
total = df.groupby('event_id').agg(
    total_article_count=('article_count', 'sum'),
    state=('state', 'first')
).reset_index()

# By language class
by_class = df.groupby(['event_id', 'lang_class'])['article_count'].sum().unstack(fill_value=0).reset_index()
by_class.columns.name = None

# Ensure all columns exist
for col in ['english', 'indic', 'international']:
    if col not in by_class.columns:
        by_class[col] = 0

# Indic language breakdown
indic_df = df[df['lang_class'] == 'indic'].copy()
indic_pivot = indic_df.pivot_table(
    index='event_id',
    columns='source_lang',
    values='article_count',
    aggfunc='sum',
    fill_value=0
).reset_index()

# Weighted avg tone across all languages
tone = df.groupby('event_id').apply(
    lambda x: (x['article_count'] * x['avg_tone']).sum() / x['article_count'].sum()
).reset_index()
tone.columns = ['event_id', 'weighted_avg_tone']

# Merge everything
result = total.merge(by_class[['event_id', 'english', 'indic', 'international']], on='event_id')
result = result.merge(tone, on='event_id')

# Add key Indic language columns individually
for lang_code, lang_name in [('hin','hindi'), ('tam','tamil'), ('mal','malayalam'),
                               ('tel','telugu'), ('kan','kannada'), ('ben','bengali'),
                               ('mar','marathi'), ('guj','gujarati'), ('pan','punjabi'),
                               ('urd','urdu')]:
    if lang_code in indic_pivot.columns:
        result[f'count_{lang_name}'] = indic_pivot.set_index('event_id').reindex(
            result['event_id'])[lang_code].fillna(0).astype(int).values
    else:
        result[f'count_{lang_name}'] = 0

# Compute derived metrics
result['indic_share']   = (result['indic'] / result['total_article_count']).round(4)
result['english_share'] = (result['english'] / result['total_article_count']).round(4)
result['lang_diversity'] = df.groupby('event_id')['source_lang'].nunique().reindex(
    result['event_id']).values

print("\n" + "=" * 55)
print("SUMMARY PER EVENT")
print("=" * 55)
print(result[['event_id', 'state', 'total_article_count',
              'english', 'indic', 'international',
              'indic_share', 'lang_diversity',
              'weighted_avg_tone']].to_string(index=False))

# ── Key finding: Indic coverage gap ──────────────────────────────────────────
print("\n" + "=" * 55)
print("INDIC LANGUAGE COVERAGE GAP (key finding)")
print("=" * 55)
print(f"\n{'Event':<6} {'State':<20} {'Total':>8} {'Indic':>8} {'IndShare':>10} {'LangDiv':>8}")
print("-" * 62)
for _, row in result.sort_values('indic_share').iterrows():
    print(f"{row['event_id']:<6} {row['state']:<20} "
          f"{row['total_article_count']:>8,} "
          f"{row['indic']:>8,} "
          f"{row['indic_share']:>10.1%} "
          f"{row['lang_diversity']:>8}")

print("\nNote: Low indic_share for a state that speaks non-English languages")
print("is a direct measure of GDELT's language monitoring gap for that region.")

# ── Save ──────────────────────────────────────────────────────────────────────
os.makedirs('data', exist_ok=True)
result.to_csv('data/gdelt_multilingual.csv', index=False)
print(f"\nSAVED: data/gdelt_multilingual.csv")

# ── Now update raw_gdelt.csv with BigQuery ground-truth counts for E01-E12 ───
print("\n" + "=" * 55)
print("UPDATING raw_gdelt.csv WITH BIGQUERY GROUND TRUTH (E01-E12)")
print("=" * 55)

gdelt = pd.read_csv('data/raw_gdelt.csv')
print(f"Current raw_gdelt.csv: {len(gdelt)} events")

# For E01-E12, replace article_count and avg_tone with BigQuery values
bq_map = result.set_index('event_id')[['total_article_count', 'weighted_avg_tone']]

updated = 0
for eid in ['E01','E02','E03','E04','E05','E06','E07','E08','E09','E10','E11','E12']:
    if eid in bq_map.index:
        old_count = gdelt.loc[gdelt['event_id']==eid, 'article_count'].values[0]
        new_count = bq_map.loc[eid, 'total_article_count']
        new_tone  = round(bq_map.loc[eid, 'weighted_avg_tone'], 4)
        gdelt.loc[gdelt['event_id']==eid, 'article_count'] = new_count
        gdelt.loc[gdelt['event_id']==eid, 'avg_tone']      = new_tone
        print(f"  {eid}: article_count {old_count} → {new_count}, tone → {new_tone}")
        updated += 1

gdelt.to_csv('data/raw_gdelt.csv', index=False)
print(f"\nUpdated {updated} events in raw_gdelt.csv")
print("Remaining 156 events retain API-derived counts")
print("\nPROCESSING COMPLETE — ready for CP-09")