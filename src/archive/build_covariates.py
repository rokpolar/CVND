"""
LEGACY — state-level covariates table.

Wrote data/state_covariates.csv (now under data/archive/).
Unused by PSS / MSS / NegBin expected coverage.
"""
import pandas as pd
import os

covariates = [
    {
        "state": "Kerala",
        "gsdp_per_capita": 213000,
        "political_alignment": 0,  # 1 = aligned with BJP/NDA, 0 = opposition
        "press_language": "Malayalam",
        "distance_delhi_km": 2100,
        "population_density": 860,   # per km²
        "literacy_rate": 94.0
    },
    {
        "state": "Bihar",
        "gsdp_per_capita": 54000,
        "political_alignment": 1,
        "press_language": "Hindi",
        "distance_delhi_km": 1000,
        "population_density": 1102,
        "literacy_rate": 61.8
    },
    {
        "state": "Assam",
        "gsdp_per_capita": 95000,
        "political_alignment": 1,
        "press_language": "Assamese",
        "distance_delhi_km": 1700,
        "population_density": 397,
        "literacy_rate": 72.2
    },
    {
        "state": "Telangana",
        "gsdp_per_capita": 228000,
        "political_alignment": 0,
        "press_language": "Telugu",
        "distance_delhi_km": 1500,
        "population_density": 312,
        "literacy_rate": 72.8
    },
    {
        "state": "Maharashtra",
        "gsdp_per_capita": 198000,
        "political_alignment": 0,
        "press_language": "Marathi",
        "distance_delhi_km": 1400,
        "population_density": 365,
        "literacy_rate": 82.9
    },
    {
        "state": "Uttarakhand",
        "gsdp_per_capita": 170000,
        "political_alignment": 1,
        "press_language": "Hindi",
        "distance_delhi_km": 400,
        "population_density": 189,
        "literacy_rate": 78.8
    },
    {
        "state": "Uttar Pradesh",
        "gsdp_per_capita": 72000,
        "political_alignment": 1,
        "press_language": "Hindi",
        "distance_delhi_km": 500,
        "population_density": 828,
        "literacy_rate": 67.7
    },
    {
        "state": "Karnataka",
        "gsdp_per_capita": 289000,
        "political_alignment": 0,
        "press_language": "Kannada",
        "distance_delhi_km": 1750,
        "population_density": 319,
        "literacy_rate": 75.4
    },
    {
        "state": "Odisha",
        "gsdp_per_capita": 112000,
        "political_alignment": 0,
        "press_language": "Odia",
        "distance_delhi_km": 1500,
        "population_density": 269,
        "literacy_rate": 72.9
    },
    {
        "state": "Himachal Pradesh",
        "gsdp_per_capita": 187000,
        "political_alignment": 1,
        "press_language": "Hindi",
        "distance_delhi_km": 480,
        "population_density": 123,
        "literacy_rate": 82.8
    },
    {
        "state": "Delhi",
        "gsdp_per_capita": 390000,
        "political_alignment": 0,
        "press_language": "Hindi",
        "distance_delhi_km": 0,
        "population_density": 11320,
        "literacy_rate": 86.2
    },
    {
        "state": "Andhra Pradesh",
        "gsdp_per_capita": 147000,
        "political_alignment": 1,
        "press_language": "Telugu",
        "distance_delhi_km": 1650,
        "population_density": 308,
        "literacy_rate": 67.4
    },
    {
        "state": "Arunachal Pradesh",
        "gsdp_per_capita": 148000,
        "political_alignment": 1,
        "press_language": "English",
        "distance_delhi_km": 2300,
        "population_density": 17,
        "literacy_rate": 65.4
    },
    {
        "state": "Chhattisgarh",
        "gsdp_per_capita": 97000,
        "political_alignment": 1,
        "press_language": "Hindi",
        "distance_delhi_km": 1100,
        "population_density": 189,
        "literacy_rate": 70.3
    },
    {
        "state": "Goa",
        "gsdp_per_capita": 461000,
        "political_alignment": 1,
        "press_language": "Konkani",
        "distance_delhi_km": 1900,
        "population_density": 394,
        "literacy_rate": 88.7
    },
    {
        "state": "Gujarat",
        "gsdp_per_capita": 214000,
        "political_alignment": 1,
        "press_language": "Gujarati",
        "distance_delhi_km": 950,
        "population_density": 308,
        "literacy_rate": 78.0
    },
    {
        "state": "Haryana",
        "gsdp_per_capita": 211000,
        "political_alignment": 1,
        "press_language": "Hindi",
        "distance_delhi_km": 160,
        "population_density": 573,
        "literacy_rate": 75.6
    },
    {
        "state": "Jammu and Kashmir",
        "gsdp_per_capita": 101000,
        "political_alignment": 1,
        "press_language": "Urdu",
        "distance_delhi_km": 580,
        "population_density": 124,
        "literacy_rate": 67.2
    },
    {
        "state": "Jharkhand",
        "gsdp_per_capita": 72000,
        "political_alignment": 1,
        "press_language": "Hindi",
        "distance_delhi_km": 1200,
        "population_density": 414,
        "literacy_rate": 66.4
    },
    {
        "state": "Madhya Pradesh",
        "gsdp_per_capita": 89000,
        "political_alignment": 1,
        "press_language": "Hindi",
        "distance_delhi_km": 780,
        "population_density": 236,
        "literacy_rate": 69.3
    },
    {
        "state": "Manipur",
        "gsdp_per_capita": 71000,
        "political_alignment": 1,
        "press_language": "Meitei",
        "distance_delhi_km": 2500,
        "population_density": 115,
        "literacy_rate": 76.9
    },
    {
        "state": "Meghalaya",
        "gsdp_per_capita": 91000,
        "political_alignment": 0,
        "press_language": "English",
        "distance_delhi_km": 2000,
        "population_density": 132,
        "literacy_rate": 74.4
    },
    {
        "state": "Mizoram",
        "gsdp_per_capita": 130000,
        "political_alignment": 0,
        "press_language": "Mizo",
        "distance_delhi_km": 2600,
        "population_density": 52,
        "literacy_rate": 91.3
    },
    {
        "state": "Nagaland",
        "gsdp_per_capita": 78000,
        "political_alignment": 1,
        "press_language": "English",
        "distance_delhi_km": 2400,
        "population_density": 119,
        "literacy_rate": 79.6
    },
    {
        "state": "Punjab",
        "gsdp_per_capita": 162000,
        "political_alignment": 0,
        "press_language": "Punjabi",
        "distance_delhi_km": 450,
        "population_density": 550,
        "literacy_rate": 75.8
    },
    {
        "state": "Rajasthan",
        "gsdp_per_capita": 95000,
        "political_alignment": 1,
        "press_language": "Hindi",
        "distance_delhi_km": 500,
        "population_density": 201,
        "literacy_rate": 66.1
    },
    {
        "state": "Sikkim",
        "gsdp_per_capita": 295000,
        "political_alignment": 0,
        "press_language": "Nepali",
        "distance_delhi_km": 2100,
        "population_density": 86,
        "literacy_rate": 81.4
    },
    {
        "state": "Tamil Nadu",
        "gsdp_per_capita": 194000,
        "political_alignment": 0,
        "press_language": "Tamil",
        "distance_delhi_km": 2200,
        "population_density": 555,
        "literacy_rate": 80.1
    },
    {
        "state": "Tripura",
        "gsdp_per_capita": 95000,
        "political_alignment": 1,
        "press_language": "Bengali",
        "distance_delhi_km": 2500,
        "population_density": 350,
        "literacy_rate": 87.2
    },
    {
        "state": "West Bengal",
        "gsdp_per_capita": 114000,
        "political_alignment": 0,
        "press_language": "Bengali",
        "distance_delhi_km": 1500,
        "population_density": 1029,
        "literacy_rate": 76.3
    }
]

df = pd.DataFrame(covariates)

print("Running validation checks...")
print("-" * 50)

errors = []

# Check 1: All states from events.csv are covered
events_df = pd.read_csv('data/events.csv')
event_states = set(events_df['state'].unique())
covariate_states = set(df['state'].unique())
missing = event_states - covariate_states
if missing:
    errors.append(f"States in events.csv missing from covariates: {missing}")
else:
    print(f"  OK  All {len(event_states)} event states have covariate entries")

# Check 2: No duplicate states
dupes = df[df.duplicated('state')]
if not dupes.empty:
    errors.append(f"Duplicate states: {dupes['state'].tolist()}")
else:
    print("  OK  No duplicate states")

# Check 3: GSDP values are plausible (INR per capita, should be > 0)
bad_gsdp = df[df['gsdp_per_capita'] <= 0]
if not bad_gsdp.empty:
    errors.append(f"Invalid GSDP: {bad_gsdp['state'].tolist()}")
else:
    print(f"  OK  GSDP range: ₹{df['gsdp_per_capita'].min():,} (Bihar) "
          f"to ₹{df['gsdp_per_capita'].max():,} (Delhi)")

# Check 4: political_alignment is binary
bad_align = df[~df['political_alignment'].isin([0, 1])]
if not bad_align.empty:
    errors.append(f"political_alignment not 0/1: {bad_align['state'].tolist()}")
else:
    aligned = df[df['political_alignment']==1]['state'].tolist()
    opposition = df[df['political_alignment']==0]['state'].tolist()
    print(f"  OK  Aligned (1): {aligned}")
    print(f"  OK  Opposition (0): {opposition}")

# Check 5: Distance from Delhi
bad_dist = df[df['distance_delhi_km'] < 0]
if not bad_dist.empty:
    errors.append(f"Negative distance: {bad_dist['state'].tolist()}")
else:
    print(f"  OK  Distance range: {df['distance_delhi_km'].min()} km "
          f"to {df['distance_delhi_km'].max()} km")

# Check 6: Literacy rate in valid range
bad_lit = df[(df['literacy_rate'] < 0) | (df['literacy_rate'] > 100)]
if not bad_lit.empty:
    errors.append(f"Invalid literacy rate: {bad_lit['state'].tolist()}")
else:
    print(f"  OK  Literacy range: {df['literacy_rate'].min()}% "
          f"to {df['literacy_rate'].max()}%")

# Check 7: press_language — show unique values for awareness
langs = df['press_language'].unique().tolist()
print(f"  OK  Languages represented: {langs}")

# Check 8: Add a binary English-press flag (used later in regression)
df['press_lang_english'] = df['press_language'].apply(
    lambda x: 1 if 'English' in x else 0
)
english_states = df[df['press_lang_english']==1]['state'].tolist()
print(f"  OK  English press flag (1): {english_states if english_states else 'None — all regional language press'}")

print("-" * 50)

if errors:
    print("VALIDATION FAILED:")
    for e in errors:
        print(f"  ERROR: {e}")
else:
    os.makedirs('data', exist_ok=True)
    df.to_csv('data/state_covariates.csv', index=False)
    print(f"SAVED: data/state_covariates.csv ({len(df)} states)")
    print()
    print(df[['state', 'gsdp_per_capita', 'political_alignment',
              'press_language', 'distance_delhi_km',
              'population_density', 'literacy_rate']].to_string(index=False))
    print()
    print("CP-03 COMPLETE — ready for CP-04")