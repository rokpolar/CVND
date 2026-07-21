import pandas as pd
import os

events = [
    {
        "event_id": "E01",
        "state": "Kerala",
        "district": "Ernakulam",
        "disaster_type": "flood",
        "start_date": "2018-08-08",
        "end_date": "2018-08-23",
        "lat": 10.6,
        "lon": 76.2,
        "bbox": "74.8,8.4,77.6,12.8",
        "income_group": "Middle"
    },
    {
        "event_id": "E02",
        "state": "Bihar",
        "district": "Muzaffarpur",
        "disaster_type": "flood",
        "start_date": "2019-07-10",
        "end_date": "2019-07-30",
        "lat": 26.2,
        "lon": 85.8,
        "bbox": "84.0,25.0,87.5,27.5",
        "income_group": "Low"
    },
    {
        "event_id": "E03",
        "state": "Assam",
        "district": "Morigaon",
        "disaster_type": "flood",
        "start_date": "2020-05-25",
        "end_date": "2020-06-10",
        "lat": 26.3,
        "lon": 92.3,
        "bbox": "90.5,25.5,93.0,27.5",
        "income_group": "Low"
    },
    {
        "event_id": "E04",
        "state": "Telangana",
        "district": "Hyderabad",
        "disaster_type": "flood",
        "start_date": "2020-10-13",
        "end_date": "2020-10-17",
        "lat": 17.4,
        "lon": 78.5,
        "bbox": "78.0,17.0,79.2,17.8",
        "income_group": "High"
    },
    {
        "event_id": "E05",
        "state": "Maharashtra",
        "district": "Raigad",
        "disaster_type": "flood",
        "start_date": "2021-07-22",
        "end_date": "2021-07-26",
        "lat": 18.5,
        "lon": 73.3,
        "bbox": "72.8,17.8,74.0,19.0",
        "income_group": "High"
    },
    {
        "event_id": "E06",
        "state": "Uttarakhand",
        "district": "Chamoli",
        "disaster_type": "flood",
        "start_date": "2021-02-07",
        "end_date": "2021-02-09",
        "lat": 30.4,
        "lon": 79.5,
        "bbox": "79.0,30.0,80.5,31.0",
        "income_group": "Low"
    },
    {
        "event_id": "E07",
        "state": "Uttar Pradesh",
        "district": "Bahraich",
        "disaster_type": "flood",
        "start_date": "2021-08-10",
        "end_date": "2021-08-28",
        "lat": 27.6,
        "lon": 81.6,
        "bbox": "80.5,26.5,83.0,28.5",
        "income_group": "Low"
    },
    {
        "event_id": "E08",
        "state": "Assam",
        "district": "Silchar",
        "disaster_type": "flood",
        "start_date": "2022-06-15",
        "end_date": "2022-07-05",
        "lat": 24.8,
        "lon": 92.8,
        "bbox": "92.0,24.0,93.5,25.5",
        "income_group": "Low"
    },
    {
        "event_id": "E09",
        "state": "Karnataka",
        "district": "Bengaluru",
        "disaster_type": "flood",
        "start_date": "2022-09-05",
        "end_date": "2022-09-07",
        "lat": 12.9,
        "lon": 77.6,
        "bbox": "77.3,12.7,78.0,13.3",
        "income_group": "High"
    },
    {
        "event_id": "E10",
        "state": "Odisha",
        "district": "Balasore",
        "disaster_type": "flood",
        "start_date": "2022-09-16",
        "end_date": "2022-09-22",
        "lat": 21.5,
        "lon": 86.9,
        "bbox": "85.5,20.5,87.5,22.0",
        "income_group": "Low"
    },
    {
        "event_id": "E11",
        "state": "Himachal Pradesh",
        "district": "Mandi",
        "disaster_type": "flood",
        "start_date": "2023-07-08",
        "end_date": "2023-07-16",
        "lat": 31.7,
        "lon": 76.9,
        "bbox": "76.0,31.0,77.8,32.5",
        "income_group": "Low"
    },
    {
        "event_id": "E12",
        "state": "Delhi",
        "district": "Delhi",
        "disaster_type": "flood",
        "start_date": "2023-07-10",
        "end_date": "2023-07-14",
        "lat": 28.7,
        "lon": 77.1,
        "bbox": "76.8,28.4,77.6,28.9",
        "income_group": "High"
    },
]

df = pd.DataFrame(events)

# Validation checks before saving
print("Running validation checks...")
print("-" * 50)

errors = []

# Check 1: No duplicate event IDs
dupes = df[df.duplicated('event_id')]
if not dupes.empty:
    errors.append(f"Duplicate event IDs: {dupes['event_id'].tolist()}")
else:
    print("  OK  No duplicate event IDs")

# Check 2: Dates are valid and end >= start
df['start_date'] = pd.to_datetime(df['start_date'])
df['end_date'] = pd.to_datetime(df['end_date'])
bad_dates = df[df['end_date'] < df['start_date']]
if not bad_dates.empty:
    errors.append(f"end_date before start_date: {bad_dates['event_id'].tolist()}")
else:
    print("  OK  All end_dates >= start_dates")

# Check 3: BBox has exactly 4 values and is within India bounds
def validate_bbox(bbox_str):
    try:
        parts = [float(x) for x in bbox_str.split(',')]
        if len(parts) != 4:
            return False
        lon_min, lat_min, lon_max, lat_max = parts
        # India rough bounds: lon 68-98, lat 6-38
        if not (68 <= lon_min <= 98 and 68 <= lon_max <= 98):
            return False
        if not (6 <= lat_min <= 38 and 6 <= lat_max <= 38):
            return False
        if lon_min >= lon_max or lat_min >= lat_max:
            return False
        return True
    except:
        return False

bad_bbox = df[~df['bbox'].apply(validate_bbox)]
if not bad_bbox.empty:
    errors.append(f"Invalid bbox: {bad_bbox['event_id'].tolist()}")
else:
    print("  OK  All bounding boxes valid and within India bounds")

# Check 4: income_group only valid values
valid_income = {'High', 'Middle', 'Low'}
bad_income = df[~df['income_group'].isin(valid_income)]
if not bad_income.empty:
    errors.append(f"Invalid income_group: {bad_income[['event_id','income_group']].values.tolist()}")
else:
    print("  OK  All income_group values valid")

# Check 5: Income group distribution
income_counts = df['income_group'].value_counts()
print(f"  OK  Income distribution: {income_counts.to_dict()}")

# Check 6: Date range of dataset
print(f"  OK  Date range: {df['start_date'].min().date()} to {df['end_date'].max().date()}")

print("-" * 50)

if errors:
    print("VALIDATION FAILED:")
    for e in errors:
        print(f"  ERROR: {e}")
else:
    # Convert dates back to string for clean CSV storage
    df['start_date'] = df['start_date'].dt.strftime('%Y-%m-%d')
    df['end_date'] = df['end_date'].dt.strftime('%Y-%m-%d')
    os.makedirs('data', exist_ok=True)
    df.to_csv('data/events.csv', index=False)
    print(f"SAVED: data/events.csv ({len(df)} events)")
    print()
    print(df[['event_id','state','district','start_date','end_date','income_group']].to_string(index=False))
    print()
    print("CP-02 COMPLETE — ready for CP-03")