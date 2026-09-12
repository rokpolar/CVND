"""Resume approved failed rows, preserving all previous non-error records."""
import argparse
import json
import shutil
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import satellite as sat
from boundary_recovery import load_boundaries, load_supplemental

def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--workers',type=int,default=8)
    parser.add_argument('--limit',type=int)
    parser.add_argument('--supplemental-only',action='store_true')
    args=parser.parse_args()
    sat.ensure_gee()
    sat.ee.data.setDeadline(180000)
    decisions,_,manifest=load_boundaries()
    supplemental,_=load_supplemental()
    decisions=supplemental if args.supplemental_only else {**decisions,**supplemental}
    cache=ROOT/'data/cache/district'; out=ROOT/'data/intermediate'
    cp=cache/'satellite_checkpoint_a.json'
    records=json.loads(cp.read_text())
    original_keys=set(records)
    registry=pd.read_csv(out/'event_districts.csv')
    rows={sat.analysis_key(r):r for _,r in registry.iterrows()}
    targets=[rows[k] for k,r in records.items() if r['baseline_status'].startswith('ERROR') and (r['state'],r['district']) in decisions]
    if args.limit: targets=targets[:args.limit]
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=cache/('before_reference_recovery_'+stamp); backup.mkdir()
    for path in (cp,cache/'flood_extent.csv',out/'district_aoi.csv'):
        shutil.copy2(path,backup/path.name)
    shutil.copy2(ROOT/'data/raw/geoboundaries_2021/recovery_manifest.json',backup/'manifest.json')
    osm_manifest=ROOT/'data/raw/osm_boundary_review/recovery_manifest.json'
    if osm_manifest.exists(): shutil.copy2(osm_manifest,backup/'osm_manifest.json')
    aoi=pd.read_csv(out/'district_aoi.csv').set_index('event_district_id',drop=False)
    for col in (*sat.AOI_COLUMNS,'aoi_error'):
        if col in aoi and col!='aoi_area_km2': aoi[col]=aoi[col].astype(object)
    summary={'backup':str(backup),'target_rows':len(targets),'completed':0,'source_sha256':manifest['source_sha256']}
    print(json.dumps(summary),flush=True)
    def persist():
        assert set(records)==original_keys
        temp=cp.with_suffix('.reference.tmp'); sat.save_checkpoint(records,str(temp)); temp.replace(cp)
        temp=cache/'flood_extent.reference.tmp'
        pd.DataFrame(records.values()).sort_values('event_district_id').to_csv(temp,index=False)
        temp.replace(cache/'flood_extent.csv')
        temp=out/'district_aoi.reference.tmp'; aoi.to_csv(temp,index=False); temp.replace(out/'district_aoi.csv')
        summary['status_counts']=dict(Counter(r['baseline_status'].split(':')[0] for r in records.values()))
        temp=out/'boundary_recovery_summary.tmp'; temp.write_text(json.dumps(summary,indent=2)); temp.replace(out/'boundary_recovery_summary.json')
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs={pool.submit(sat.detect_flood_baseline,row):sat.analysis_key(row) for row in targets}
        for n,future in enumerate(as_completed(jobs),1):
            identity=jobs[future]
            result=future.result()
            assert sat._cache_identity_matches(result,rows[identity])
            records[identity]=result
            if result.get('aoi_match_status')=='matched':
                for col,value in result.items():
                    if col.startswith('aoi_') or col=='geometry_id':
                        if col not in aoi: aoi[col]=pd.Series(index=aoi.index,dtype=object)
                        aoi.loc[identity,col]=value
                aoi.loc[identity,'aoi_error']=''
            summary['completed']=n
            persist()
            print(f'RECOVERED {n}/{len(targets)} {identity} {result["baseline_status"]}',flush=True)
    persist()
    print(json.dumps(summary),flush=True)

if __name__=='__main__': main()
