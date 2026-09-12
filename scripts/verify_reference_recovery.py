"""Verify identity preservation and cross-file consistency against a backup."""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from boundary_recovery import load_boundaries,load_supplemental,cache_reference_matches

def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--backup',required=True)
    parser.add_argument('--final',action='store_true')
    args=parser.parse_args()
    before=json.loads((Path(args.backup)/'satellite_checkpoint_a.json').read_text())
    after=json.loads((ROOT/'data/cache/district/satellite_checkpoint_a.json').read_text())
    decisions,_,_=load_boundaries(); extra,_=load_supplemental(); decisions={**decisions,**extra}
    targets={k for k,r in before.items() if r['baseline_status'].startswith('ERROR') and (r['state'],r['district']) in decisions}
    assert set(before)==set(after)
    changed={k for k in before if json.dumps(before[k],sort_keys=True)!=json.dumps(after[k],sort_keys=True)}
    assert changed<=targets, 'Non-target result changed'
    aoi=pd.read_csv(ROOT/'data/intermediate/district_aoi.csv',dtype={'geometry_id':'string'}).set_index('event_district_id')
    flood=pd.read_csv(ROOT/'data/cache/district/flood_extent.csv',dtype={'geometry_id':'string'}).set_index('event_district_id')
    assert len(flood)==len(after)==1630 and flood.index.is_unique and aoi.index.is_unique
    assert set(flood.index)==set(after)
    for k in changed:
        r=after[k]
        for field in ('event_district_id','event_id','source_record_id','state','district','start_date','spec_version'):
            assert r[field]==before[k][field], (k,field)
        assert flood.loc[k,'baseline_status']==r['baseline_status']
        if r.get('aoi_match_status')=='matched':
            assert cache_reference_matches(r,r)
            for col in ('aoi_source','geometry_id','aoi_match_status'):
                assert aoi.loc[k,col]==r[col] and flood.loc[k,col]==r[col],(k,col)
            assert r['aoi_historical_boundary_verified'] is False
            assert abs(float(aoi.loc[k,'aoi_area_km2'])-r['aoi_area_km2'])<1e-6
    pending=[k for k in targets if after[k]['baseline_status'].startswith('ERROR')]
    if args.final: assert not pending, pending
    result={'rows':len(after),'approved_target_rows':len(targets),'changed_rows':len(changed),
            'unchanged_rows':len(after)-len(changed),'approved_rows_still_error':len(pending),
            'status_counts':dict(Counter(r['baseline_status'].split(':')[0] for r in after.values())),
            'original_successes_preserved':True,'identity_and_aoi_consistency':'passed','final':args.final,
            'baseline_backup':args.backup}
    unresolved=[{'event_district_id':k,'state':r['state'],'district':r['district'],'error':r['baseline_status']}
                for k,r in after.items() if r['baseline_status'].startswith('ERROR')]
    if args.final:
        audit=pd.read_csv(ROOT/'data/intermediate/aoi_boundary_decisions.csv').fillna('')
        reasons={(r['state'],r['district']):r['note'] for _,r in audit.iterrows()}
        rejected=json.loads((ROOT/'data/raw/osm_boundary_review/recovery_manifest.json').read_text())['rejected']
        for r in unresolved:
            r['review_reason']=rejected.get(r['district'],reasons.get((r['state'],r['district']),''))
        final_rows=[]
        for k,r in before.items():
            if not r['baseline_status'].startswith('ERROR'): continue
            current=after[k]
            fields=('event_district_id','state','district','baseline_status','aoi_match_status',
                    'aoi_source','geometry_id','aoi_match_method','aoi_boundary_year',
                    'aoi_historical_boundary_verified','aoi_match_evidence','aoi_boundary_note')
            record={field:current.get(field) for field in fields}
            record['review_reason']=current.get('aoi_boundary_note') or rejected.get(r['district'],reasons.get((r['state'],r['district']),''))
            final_rows.append(record)
        pd.DataFrame(final_rows).to_csv(ROOT/'data/intermediate/aoi_matching_final.csv',index=False)
        (ROOT/'data/intermediate/reference_recovery_verification.json').write_text(json.dumps(result,indent=2))
        pd.DataFrame(unresolved).to_csv(ROOT/'data/intermediate/aoi_remaining_unresolved.csv',index=False)
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
