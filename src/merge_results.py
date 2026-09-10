"""
merge_results.py — combine SITS (AI) + NDWI + S1 (bi-temporal) into a per-event flood area.

Inputs:
  data/cache/sits_scores/{event}.npz   (Track B: SITS score + NDWI per patch)
  data/cache/flood_extent.csv          (Track A: S1/S2 state-AOI results)

Per event:
  1. SITS is patch-level (a 0.4096 km2 tile is flagged whole even if only a sliver is water),
     so (#flagged * PATCH_KM2) is a DETECTION extent, not a water area (measured: tiles are
     ~0.8% water at the median -> using it as area over-counts ~100x).
     => SITS LOCATES flood tiles; a quality gate (Youden's J = SITS-NDWI agreement, not
        external validation) decides whether the fusion is used:
        (a) ndwi-calib  -- J>=0.15: SITS+NDWI fusion (SITS locates, NDWI quantifies)
        (b) otsu/low-conf -- SITS flags unreliable -> whole-AOI NDWI instead
  2. Flood AREA always comes from pixel-level NDWI (real water):
        SITS+NDWI  -> NDWI water *inside* SITS-flagged tiles (gated)
        NDWI       -> NDWI water over the whole state AOI
     Restore rule: if gating cut the water by >half AND S1 (radar) independently shows the
     larger extent is real, restore full-AOI NDWI (guards against SITS missing tiles).
  3. Cloud routing:  optical available (SITS kept clear patches) -> SITS+NDWI or NDWI
                     cloud-blind (0 SITS patches)                -> S1 (radar, Track A)
     Events with 0 SITS patches (fully clouded on the flood date) are pulled from Track A
     and routed to S1 (or Track A NDWI if no S1) -- not dropped.

Output: data/intermediate/flood_combined.csv
Run:    python src/merge_results.py     (numpy + pandas only; no model / GEE)
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cvnd_config import CLOUD_MAX_PCT  # noqa: E402
from cvnd_layout import data_path, ensure_printable_output  # noqa: E402

SCORES_DIR = str(data_path("sits_scores"))
TRACK_A_CSV = str(data_path("flood_extent"))
OUT_CSV = str(data_path("flood_combined"))

PATCH_KM2 = (64 * 10 / 1000) ** 2   # 0.4096 km2 per patch
PX_KM2 = (10 / 1000) ** 2           # 1e-4 km2 per pixel
FLOOD_MIN_PX = 205                  # a patch is an "NDWI flood" patch if >= 5% (205/4096) is new water
MIN_POS = 20                        # need this many NDWI-flood (and non-flood) patches to calibrate
J_MIN = 0.15                        # min Youden's J (SITS-NDWI agreement) to use the SITS+NDWI fusion
POST_CLOUD_CSV = str(data_path("post_cloud"))
AOI_AREA_CSV = str(data_path("event_aoi_area"))
SAR_CSV = str(data_path("sar_flood_area"))


def load_floodvit(path=SAR_CSV):
    """{event_id: flood_km2} from sar_flood_area.py, best method version only.

    This is the measurement the whole SAR switch was for, and until it is read
    here it does not reach the paper at all: severity came from the old
    threshold S1 and NDWI paths below.

    Controls are excluded -- they are the same AOI at a no-flood date, evidence
    about the method rather than events in the study. Rows with a status other
    than OK, or that stopped before every block was classified, are dropped: a
    partial run reports a smaller area for the same flood, which is
    indistinguishable downstream from a smaller flood.
    """
    if not os.path.exists(path):
        return {}, None
    df = pd.read_csv(path)
    if df.empty or 'flood_km2' not in df.columns:
        return {}, None
    if 'is_control' in df.columns:
        df = df[~df['is_control'].fillna(False).astype(bool)]
    if 'status' in df.columns:
        df = df[df['status'].astype(str) == 'OK']
    if {'blocks_done', 'blocks_total'} <= set(df.columns):
        full = df['blocks_total'].isna() | (df['blocks_done'] >= df['blocks_total'])
        df = df[full]
    df = df[df['flood_km2'].notna()]
    if df.empty:
        return {}, None
    version = None
    if 'method_version' in df.columns:
        # Areas from different method versions are not comparable -- that is the
        # whole reason the version is recorded -- so keep only the newest.
        version = int(df['method_version'].max())
        df = df[df['method_version'] == version]
    df = df.drop_duplicates('event_id', keep='last')
    return dict(zip(df['event_id'], df['flood_km2'].astype(float))), version


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
    with np.errstate(divide='ignore', invalid='ignore'):
        mu0 = csum / w0
        mu1 = (csum[-1] - csum) / w1
        var_between = w0 * w1 * (mu0 - mu1) ** 2
    var_between = np.nan_to_num(var_between)
    # edges[i+1], not centers[i]: w0 is a cumulative sum through bin i, so bin i
    # belongs to class 0, while callers select class 1 with `scores > t`. Returning
    # the bin centre put the upper half of that bin on the wrong side of the cut.
    return float(edges[int(np.argmax(var_between)) + 1])


def _youden(scores, labels):
    """Threshold that maximises TPR - FPR against NDWI-flood labels; returns (t, J).
    This is a *balanced* boundary (not 'capture 85% of positives'), so it does not
    over-flag the way a low percentile does. J also measures how separable the two are."""
    P = int(labels.sum())
    N = int((~labels).sum())
    if P == 0 or N == 0:
        return None, 0.0
    ts = np.quantile(scores, np.linspace(0.02, 0.98, 60))
    best_t, best_j = float(np.median(scores)), -1.0
    for t in ts:
        pred = scores > t
        tpr = (pred & labels).sum() / P
        fpr = (pred & ~labels).sum() / N
        j = tpr - fpr
        if j > best_j:
            best_j, best_t = j, float(t)
    return best_t, best_j


def sits_threshold(scores, ndwi_flood):
    """Return (threshold, method): NDWI-calibrated (Youden's J) -> Otsu -> low-confidence."""
    flood = ndwi_flood >= FLOOD_MIN_PX
    if int(flood.sum()) >= MIN_POS and int((~flood).sum()) >= MIN_POS:
        t, j = _youden(scores, flood)
        if t is not None and j >= J_MIN:            # good separation -> trust SITS
            return t, 'ndwi-calib'
        return _otsu(scores), 'low-conf'            # NDWI floods don't separate -> SITS unreliable
    return _otsu(scores), 'otsu'                    # too few NDWI positives -> plain Otsu


def summarise_sources(out):
    """How many events each measurement method supplied, and whether that mixes.

    Printed rather than buried in the CSV because a mixed column is the failure
    that matters most here: severity measured by different methods is not
    comparable between events, and the fallback methods are selected by cloud
    cover, which tracks rainfall and therefore severity itself.
    """
    counts = out['combined_source'].value_counts()
    lines = ['measurement method per event:']
    lines += [f'  {k:<26}{n:>5}' for k, n in counts.items()]
    other = int(counts.drop(labels=['FloodViT'], errors='ignore')
                .drop(labels=['none'], errors='ignore').sum())
    if 'FloodViT' in counts and other:
        lines.append(
            f'WARNING: {other} event(s) are not measured by FloodViT. Areas from '
            'different methods are not comparable, and which method an event '
            'falls back to depends on cloud cover, which tracks rainfall and so '
            'tracks severity. Measure them with sar_flood_area.py, or drop them '
            'from the analysis -- do not mix them in.')
    elif 'FloodViT' not in counts:
        lines.append(
            'WARNING: no event is measured by FloodViT, so the severity column is '
            'entirely the old cloud-routed threshold/NDWI mixture.')
    return '\n'.join(lines)


def main():
    ensure_printable_output()
    # Track A (S1 + optical availability); may be missing/stale -> handle gracefully
    ta = {}
    if os.path.exists(TRACK_A_CSV):
        dfa = pd.read_csv(TRACK_A_CSV)
        for _, r in dfa.iterrows():
            ta[r['event_id']] = r
    else:
        print(f"WARN: {TRACK_A_CSV} missing -> no S1 / cloud routing (re-run Track A)")

    # Flood-date cloud fraction over the state AOI (from post_cloud.py); optional.
    pcloud = {}
    if os.path.exists(POST_CLOUD_CSV):
        dfc = pd.read_csv(POST_CLOUD_CSV)
        pcloud = dict(zip(dfc['event_id'], dfc['cloud_pct']))
    else:
        print(f"WARN: {POST_CLOUD_CSV} missing -> no cloud-fraction routing (run post_cloud.py)")

    # State event-AOI area (for flood_ratio); optional.
    aoi_areas = {}
    if os.path.exists(AOI_AREA_CSV):
        dfd = pd.read_csv(AOI_AREA_CSV)
        aoi_areas = dict(zip(dfd['event_id'], dfd['aoi_km2']))
    else:
        print(f"WARN: {AOI_AREA_CSV} missing -> no flood_ratio (run event_aoi_area.py)")

    npz = {os.path.basename(f)[:-4]: f
           for f in glob.glob(os.path.join(SCORES_DIR, '*.npz'))}
    # union: every event with a SITS score OR a Track A row (cloud-blind 0-patch events
    # have no .npz but still have S1/NDWI in Track A -> route them to S1, don't drop them)
    floodvit, fv_version = load_floodvit()
    if floodvit:
        print(f"FloodViT: {len(floodvit)} events from {SAR_CSV} "
              f"(method version {fv_version})")
    else:
        print(f"WARN: no usable FloodViT areas at {SAR_CSV} -> severity falls "
              "back to the threshold S1 / NDWI paths, whose method is chosen by "
              "cloud cover (run sar_flood_area.py and copy its CSV here)")

    # Events with a FloodViT area but no SITS score and no Track A row would
    # otherwise be dropped before the loop even sees them.
    all_events = sorted(set(npz) | set(ta) | set(floodvit))

    rows = []
    for ev in all_events:
        a = ta.get(ev, {})
        s1_area = a.get('area_s1_km2', None)
        s2_area = a.get('area_s2_km2', None)                # Track A optical (NDWI over state AOI)
        optical_ok = pd.notna(s2_area) and float(a.get('s2_post_images', 0) or 0) > 0

        d = np.load(npz[ev]) if ev in npz else None
        has_sits = d is not None and len(d['scores']) > 0   # empty npz = 0 patches = cloud-blind

        if has_sits:
            # SITS kept clear patches (KEEP_VALID>=70%) -> optical DID see the flood.
            scores, ndwi_flood = d['scores'], d['ndwi_flood']
            thr, method = sits_threshold(scores, ndwi_flood)
            flagged = scores > thr
            # SITS tile extent is NOT a water area (tiles are ~0.8% water at the median);
            # SITS locates, pixel-level NDWI quantifies (gated). Kept for reference only.
            sits_detect = float(flagged.sum()) * PATCH_KM2          # flagged-tile extent
            ndwi_full = float(ndwi_flood.sum()) * PX_KM2            # all new-flood water in state AOI
            ndwi_gated = float(ndwi_flood[flagged].sum()) * PX_KM2  # water inside SITS-flagged tiles
            sits_area, ndwi_area = sits_detect, ndwi_full
            optical = True
            if method == 'ndwi-calib':      # quality gate passed -> SITS+NDWI fusion
                combined, source = ndwi_gated, 'SITS+NDWI'
                # SITS can also MISS flood tiles -> gating then under-counts. If gating cut the
                # water by >half AND radar (S1) independently confirms the larger extent
                # (so the trimmed water is real, not noise), restore the full-AOI NDWI.
                s1v = float(s1_area) if (s1_area is not None and pd.notna(s1_area)) else None
                if (ndwi_full > 0 and ndwi_gated < 0.5 * ndwi_full
                        and s1v is not None and s1v >= ndwi_full):
                    combined, source = ndwi_full, 'SITS+NDWI(restored)'
            else:                           # gate failed -> SITS flags unreliable, use plain NDWI
                combined, source = ndwi_full, 'NDWI'
            # Cloud-fraction routing: patches only cover the clear part of the state AOI.
            # If the flood-date S2 composite was mostly cloud (> CLOUD_MAX_PCT of the
            # AOI unseen), the optical number misses most of the ground -> radar.
            cl = pcloud.get(ev)
            if cl is not None and cl >= CLOUD_MAX_PCT:
                if s1_area is not None and pd.notna(s1_area):
                    combined, source = float(s1_area), f'S1(cloud>{CLOUD_MAX_PCT})'
                else:                       # too cloudy for optical AND no radar -> unmeasurable
                    combined, source = None, 'none'
        else:
            # 0 SITS patches = flood date too clouded for optical -> trust radar first.
            # (Track A's cloud-median can still report an NDWI, but with SITS blind it is
            #  unreliable, so S1 wins; NDWI is only a last resort when there is no S1.)
            thr, method, sits_area = None, 'no-sits', None
            ndwi_area = float(s2_area) if pd.notna(s2_area) else None   # Track A NDWI, if any
            optical = False
            cl = pcloud.get(ev)
            too_cloudy = cl is not None and cl >= CLOUD_MAX_PCT
            if s1_area is not None and pd.notna(s1_area):    # cloud-blind -> radar
                combined, source = float(s1_area), 'S1(cloud)'
            elif ndwi_area is not None and not too_cloudy:   # no S1, but optical mostly saw it
                combined, source = ndwi_area, 'NDWI(no-S1)'
                optical = optical_ok
            else:
                combined, source = None, 'none'             # no usable measurement at all

        # FloodViT overrides every branch above. Those branches pick a method by
        # cloud cover, and cloud cover during the monsoon tracks rainfall, which
        # tracks flood severity -- so the measurement method was correlated with
        # the quantity being measured. Radar sees through cloud, so one method
        # covers every event and that correlation is gone. The other columns stay
        # for comparison.
        fv_area = floodvit.get(ev)
        if fv_area is not None:
            combined, source = float(fv_area), 'FloodViT'

        aoi_km2 = aoi_areas.get(ev)
        ratio = (round(combined / aoi_km2, 4)
                 if (combined is not None and aoi_km2 and aoi_km2 > 0) else None)
        rows.append({
            'event_id': ev,
            'floodvit_km2': round(fv_area, 2) if fv_area is not None else None,
            'sits_detect_km2': round(sits_area, 2) if sits_area is not None else None,  # SITS tile extent (NOT area)
            'sits_threshold': round(thr, 3) if thr is not None else None,
            'sits_method': method,
            'ndwi_flood_km2': round(ndwi_area, 2) if ndwi_area is not None else None,   # full-AOI NDWI
            's1_flood_km2': round(float(s1_area), 2) if (s1_area is not None and pd.notna(s1_area)) else None,
            'optical_available': optical,
            'cloud_pct': pcloud.get(ev),                    # flood-date cloud over state AOI (QA)
            'combined_km2': round(combined, 2) if combined is not None else None,
            'aoi_km2': round(float(aoi_km2), 1) if aoi_km2 else None,
            'flood_ratio': ratio,
            'combined_source': source,
        })
        _s = f"{sits_area:6.1f}" if sits_area is not None else "   -  "
        _c = f"{combined:6.1f}" if combined is not None else "   -  "
        print(f"  {ev}: sits_detect={_s} ({method:9s}) ndwi_full={ndwi_area}  "
              f"s1={s1_area}  -> combined={_c} ({source})")

    if rows:
        out = pd.DataFrame(rows)
        out.to_csv(OUT_CSV, index=False)
        print(f"\nSaved -> {OUT_CSV}  ({len(rows)} events)")
        print(summarise_sources(out))


if __name__ == '__main__':
    main()
