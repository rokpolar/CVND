"""
merge_results.py — combine SITS (AI) + NDWI + S1 (bi-temporal) into a per-event flood area.

Inputs:
  data/sits_scores/{event}.npz   (Track B: SITS score + NDWI per patch)  -- from sits_score.py
  data/flood_extent.csv          (Track A: area_s1_km2, area_s2_km2, s2_post_images) -- re-run Track A first

Per event:
  1. SITS flood area: threshold chosen by
       (a) NDWI-calibration  -- if enough NDWI-flood patches AND they separate in SITS
       (b) Otsu              -- fallback (few NDWI positives but bimodal scores)
       (c) low-confidence    -- neither works (e.g. chronic/already-wet: SITS can't separate)
  2. NDWI flood area: from the patches (ndwi_flood pixels)
  3. Cloud routing:  optical available (S2 saw the flood) -> use optical (SITS if reliable else NDWI)
                     cloud-blind                          -> use S1 (radar, Track A)

Output: data/flood_combined.csv
Run:    python src/merge_results.py     (numpy + pandas only; no model / GEE)
"""
import os
import glob
import numpy as np
import pandas as pd

SCORES_DIR = 'data/sits_scores'
TRACK_A_CSV = 'data/flood_extent.csv'
OUT_CSV = 'data/flood_combined.csv'

PATCH_KM2 = (64 * 10 / 1000) ** 2   # 0.4096 km2 per patch
PX_KM2 = (10 / 1000) ** 2           # 1e-4 km2 per pixel
FLOOD_MIN_PX = 205                  # a patch is an "NDWI flood" patch if >= 5% (205/4096) is new water
MIN_POS = 20                        # need this many NDWI-flood patches to trust calibration
SEP_MIN = 0.05                      # min SITS median separation (flood - non-flood) to trust calibration
CAPTURE_PCTL = 15                   # threshold = this percentile of NDWI-flood patches' SITS scores


def _otsu(x):
    """Otsu threshold on scores in [0,1]."""
    hist, edges = np.histogram(x, bins=64, range=(0.0, 1.0))
    hist = hist.astype(float)
    total = hist.sum()
    if total == 0:
        return 0.5
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = total - w0
    csum = np.cumsum(hist * centers)
    mu_total = csum[-1] / total
    with np.errstate(divide='ignore', invalid='ignore'):
        mu0 = csum / w0
        mu1 = (csum[-1] - csum) / w1
        var_between = w0 * w1 * (mu0 - mu1) ** 2
    var_between = np.nan_to_num(var_between)
    return float(centers[int(np.argmax(var_between))])


def sits_threshold(scores, ndwi_flood):
    """Return (threshold, method) using NDWI-calibration -> Otsu -> low-confidence."""
    flood = ndwi_flood >= FLOOD_MIN_PX
    k = int(flood.sum())
    if k >= MIN_POS:
        sep = float(np.median(scores[flood]) - np.median(scores[~flood]))
        if sep >= SEP_MIN:
            return float(np.percentile(scores[flood], CAPTURE_PCTL)), 'ndwi-calib'
        else:
            return _otsu(scores), 'low-conf'       # NDWI floods don't separate -> SITS unreliable here
    return _otsu(scores), 'otsu'                    # too few NDWI positives -> plain Otsu


def main():
    # Track A (S1 + optical availability); may be missing/stale -> handle gracefully
    ta = {}
    if os.path.exists(TRACK_A_CSV):
        dfa = pd.read_csv(TRACK_A_CSV)
        for _, r in dfa.iterrows():
            ta[r['event_id']] = r
    else:
        print(f"WARN: {TRACK_A_CSV} missing -> no S1 / cloud routing (re-run Track A)")

    rows = []
    for f in sorted(glob.glob(os.path.join(SCORES_DIR, '*.npz'))):
        ev = os.path.basename(f)[:-4]
        d = np.load(f)
        scores = d['scores']
        ndwi_flood = d['ndwi_flood']

        thr, method = sits_threshold(scores, ndwi_flood)
        sits_area = float((scores > thr).sum()) * PATCH_KM2
        ndwi_area = float(ndwi_flood.sum()) * PX_KM2

        a = ta.get(ev, {})
        s1_area = a.get('area_s1_km2', None)
        s2_area = a.get('area_s2_km2', None)                # Track A optical (NDWI over district)
        optical_ok = pd.notna(s2_area) and float(a.get('s2_post_images', 0) or 0) > 0

        # cloud routing: optical (SITS if reliable, else NDWI) when clear; else S1
        if optical_ok:
            combined = sits_area if method == 'ndwi-calib' else ndwi_area
            source = 'SITS' if method == 'ndwi-calib' else 'NDWI'
        elif s1_area is not None and pd.notna(s1_area):
            combined = float(s1_area)
            source = 'S1(cloud)'
        else:
            combined = ndwi_area                            # no S1 available -> best optical guess
            source = 'NDWI(no-S1)'

        rows.append({
            'event_id': ev,
            'sits_flood_km2': round(sits_area, 2),
            'sits_threshold': round(thr, 3),
            'sits_method': method,
            'ndwi_flood_km2': round(ndwi_area, 2),
            's1_flood_km2': round(float(s1_area), 2) if (s1_area is not None and pd.notna(s1_area)) else None,
            'optical_available': optical_ok,
            'combined_km2': round(combined, 2),
            'combined_source': source,
        })
        print(f"  {ev}: sits={sits_area:6.1f} ({method:9s}) ndwi={ndwi_area:6.1f} "
              f"s1={s1_area}  -> combined={combined:6.1f} ({source})")

    if rows:
        pd.DataFrame(rows).to_csv(OUT_CSV, index=False)
        print(f"\nSaved -> {OUT_CSV}  ({len(rows)} events)")


if __name__ == '__main__':
    main()
