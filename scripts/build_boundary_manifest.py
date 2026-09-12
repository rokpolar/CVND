"""Create explicit reviewed reference-boundary decisions; no fuzzy matching."""
import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'data/raw/geoboundaries_2021'
API = 'https://www.geoboundaries.org/api/current/gbOpen/IND/ADM2/'
CENSUS = 'https://censusindia.gov.in/nada/index.php/catalog/42557'

# Human-reviewed label equivalences, scoped to a state. These assert district
# identity, not event-year boundary equivalence. Spelling judgments are explicit.
ALIASES = {
 'Andhra Pradesh': {'YSR Kadapa':'Kadapa(YSR)'},
 'Assam': {'East Karbi Anglong':'Karbi Anglong East', 'West Karbi Anglong':'Karbi Anglong West',
           'West Karbi-Anglong':'Karbi Anglong West', 'South Salmara':'South Salmara-Mankachar',
           'Sribhumi (Karimganj)':'Karimganj'},
 'Bihar': {'East Champaran':'Purba Champaran','West Champaran':'Pashchim Champaran','Purnea':'Purnia'},
 'Chhattisgarh': {'Gariyaband':'Gariaband','Kabirdham':'Kabeerdham'},
 'Delhi': {'Central Delhi':'Central','East Delhi':'East','North East Delhi':'North East'},
 'Gujarat': {'Ahmedabad':'Ahmadabad','Aravalli':'Aravali','Botad':'Batod','Dang':'The Dangs',
             'Kutch':'Kachchh','Mehsana':'Mahesana','Panchmahal':'Panch Mahals'},
 'Himachal Pradesh': {'Lahaul and Spiti':'Lahul & Spiti'},
 'Jammu and Kashmir': {'Bandipora':'Bandipore','Baramulla':'Baramula','Budgam':'Badgam','Shopian':'Shupiyan'},
 'Karnataka': {'Belagavi':'Belgaum','Chikkamagaluru':'Chikmagalur','Kalaburagi':'Gulbarga',
               'Mysuru':'Mysore','Shivamogga':'Shimoga','Vijayapura':'Bijapur'},
 'Madhya Pradesh': {'Agar Malwa':'Agar','Khandwa':'Khandwa (East Nimar)',
                    'Khargone':'Khargone (West Nimar)','Narmadapuram':'Hoshangabad'},
 'Maharashtra': {'Ahilyanagar':'Ahmadnagar','Beed':'Bid','Buldhana':'Buldana','Gondia':'Gondiya','Raigad':'Raigarh'},
 'Odisha': {'Balasore':'Baleshwar','Bauda':'Baudh'},
 'Punjab': {'Ferozepur':'Firozpur','SAS Nagar':'Sahibzada Ajit Singh Nagar',
            'SBS Nagar':'Shahid Bhagat Singh Nagar','Sri Muktsar Sahib':'Muktsar'},
 'Rajasthan': {'Chittorgarh':'Chittaurgarh','Dholpur':'Dhaulpur','Jalore':'Jalor'},
 'Sikkim': {'Mangan':'North District'},
 'Tamil Nadu': {'Chengalpattu':'Chengalputtu','Kanchipuram':'Kancheepuram','Kanyakumari':'Kanniyakumari',
                'Sivagangai':'Sivaganga','Tirupattur':'Tirupathur','Tiruvallur':'Thiruvallur','Tiruvarur':'Thiruvarur'},
 'Telangana': {'Bhadradri Kothagudem':'Bhadradri','Jayashankar Bhupalpally':'Jayashankar'},
 'Tripura': {'Sepahijala':'Sipahijula','Unakoti':'Unokoti'},
 'Uttar Pradesh': {'Amroha':'Jyotiba Phule Nagar','Ayodhya':'Faizabad','Kasganj':'Kanshiram Nagar',
                   'Prayagraj':'Allahabad','Shamli':'Samli'},
 'West Bengal': {'Cooch Behar':'Koch Bihar','Darjeeling':'Darjiling','East Medinipur':'Purba Medinipur',
                 'Hooghly':'Hugli','Howrah':'Haora','Malda':'Maldah','Paschim Bardhaman':'Paschim Barddhaman',
                 'Purba Bardhaman':'Barddhaman','Purulia':'Puruliya','West Medinipur':'Paschim Medinipur'},
}
EVIDENCE = {
 ('Uttar Pradesh','Amroha'): 'https://amroha.nic.in/history/',
 ('Uttar Pradesh','Ayodhya'): 'https://ayodhya.nic.in/',
 ('Uttar Pradesh','Prayagraj'): 'https://prayagraj.nic.in/history/',
 ('Madhya Pradesh','Narmadapuram'): 'https://narmadapuram.nic.in/en/notice/regarding-changing-the-name-of-hoshangabad-city-and-district-to-narmadapuram/',
 ('Maharashtra','Ahilyanagar'): 'https://rdd.maharashtra.gov.in/en/document/notification-regarding-changing-the-name-of-ahmednagar-to-ahilyanagar/',
 ('Sikkim','Mangan'): 'https://sikkim.nic.in/district-centres/',
}
BLOCK = {
 ('Maharashtra','Mumbai'): 'City versus suburban district scope is ambiguous; do not choose one or union both.',
 ('Bihar','Jogbani'): 'Municipality, not a district; do not substitute Araria district.',
 ('Kerala','Chengannur'): 'Town/taluk, not a district; do not substitute Alappuzha district.',
 ('Sikkim','Gyalshing'): 'West District predates Soreng split; parent polygon would overstate remaining district.',
}

def key(s):
    return re.sub(r'[\W_]+', '', unicodedata.normalize('NFKC', str(s)).casefold())

def state_key(s):
    return key(''.join(c for c in unicodedata.normalize('NFKD',str(s)) if not unicodedata.combining(c)))

def main():
    features = json.loads((BASE/'ADM2.geojson').read_text())['features']
    catalog = json.loads((BASE/'district_catalog.json').read_text())
    geometries = [shape(f['geometry']) for f in features]
    tree = STRtree(geometries)
    assert all(g.is_valid and not g.is_empty for g in geometries)
    records = json.loads((ROOT/'data/cache/district/satellite_checkpoint_a.json').read_text())
    failed = [r for r in records.values() if r['baseline_status'].startswith('ERROR')]
    counts = Counter((r['state'],r['district']) for r in failed)
    census = list(csv.DictReader((ROOT/'data/raw/district_name_crosswalk.csv').open()))
    accepted, audit = [], []
    for (state,district), count in sorted(counts.items()):
        target = ALIASES.get(state,{}).get(district,district)
        choices = [(i,r) for i,r in enumerate(catalog) if state_key(r['state'])==state_key(state) and key(r['district'])==key(target)]
        decision = dict(state=state,district=district,event_rows=count,reference_name=target,
                        method='exact_or_spacing' if target==district else 'reviewed_alias',
                        evidence=EVIDENCE.get((state,district), API), boundary_year=2021,
                        historical_boundary_verified=False)
        if any(r['registry_state']==state and r['registry_district']==district and key(r['census_district'])==key(target) for r in census):
            decision['evidence']=CENSUS
            decision['method']='census_label_alias'
        if state=='Karnataka' and target!=district:
            decision['evidence']='https://assets.publishing.service.gov.uk/media/5a7e0e2d40f0b62305b80813/Karnataka_State_India_Name_Changes_20141112.pdf'
        reason=BLOCK.get((state,district))
        if not reason and len(choices)!=1:
            reason='No unique district polygon in the pinned reference layer; parent substitution prohibited.'
        if not reason:
            i,r=choices[0]; geom=geometries[i]
            decision.update(shape_id=r['shape_id'],state_overlap=r['state_overlap'])
            overlaps=[]
            for j in tree.query(geom):
                if int(j)==i: continue
                shared=geom.intersection(geometries[int(j)]).area
                if shared / min(geom.area,geometries[int(j)].area) > .01:
                    overlaps.append(catalog[int(j)]['district'])
            if overlaps:
                reason='Reference layer overlaps another district by >1%: '+', '.join(overlaps)
            elif r['state_overlap'] < .90:
                reason='State containment below 90%; conflicting reference boundaries require review.'
        decision['decision']='unresolved' if reason else 'accepted_reference_boundary'
        decision['note']=reason or 'District identity matched; 2021 reference geometry, NOT event-year boundary equivalence. No parent substitution.'
        audit.append(decision)
        if not reason: accepted.append(decision)
    manifest={'version':'gb2021-recovery-v1','source':API,'boundary_year':2021,
              'license':'Open Data Commons Open Database License 1.0',
              'source_sha256':hashlib.sha256((BASE/'ADM2.geojson').read_bytes()).hexdigest(),
              'decisions':accepted}
    (BASE/'recovery_manifest.json').write_text(json.dumps(manifest,indent=2))
    fields=sorted(set(k for r in audit for k in r))
    with (ROOT/'data/intermediate/aoi_boundary_decisions.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(audit)
    print('ACCEPTED',len(accepted),sum(r['event_rows'] for r in accepted),'UNRESOLVED',len(audit)-len(accepted))
    for r in audit:
        if r['decision']=='unresolved': print(r['state'],r['district'],r['event_rows'],r['note'])

if __name__=='__main__': main()
