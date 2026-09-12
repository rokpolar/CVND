"""Offline conversion of cached state articles into district QA candidates."""
import argparse
import gzip
import json
import sqlite3
from collections import Counter, defaultdict

import pandas as pd
from cvnd_layout import data_path
from district_articles import (
    _open_jsonl, prepare_district_registry, prepare_district_windows,
    has_district_evidence, write_collection_manifest, file_fingerprint,
    COLLECTION_INCOMPLETE, build_district_counts, write_district_counts,
)
from district_keys import normalize_name


def candidates(row, windows):
    """Reassign historical articles using current state and date windows."""
    try:
        published = pd.to_datetime(row.get('published_at'), utc=True, errors='raise')
        if pd.isna(published):
            return []
        published = published.date()
    except (ValueError, TypeError):
        return []
    return [w for w in windows
            if normalize_name(row.get('state', '')) == normalize_name(w['state'])
            and w['query_start'] <= published < w['query_end_exclusive']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    source = data_path('gdelt_articles')
    database = data_path('gdelt_article_database')
    output = data_path('district_gdelt_articles')
    manifest = data_path('district_gdelt_manifest')
    counts_path = data_path('district_gdelt_counts')
    qa = output.parent / 'district_article_qa_candidates.jsonl.gz'
    audit = output.parent / 'state_article_reuse_audit.json'
    for path in (source, database, data_path('event_districts')):
        if not path.is_file():
            raise FileNotFoundError(path)
    for path in (output, manifest, counts_path, qa, audit):
        if path.exists() and not args.overwrite:
            raise FileExistsError(f'{path}; pass --overwrite to regenerate')
    registry = prepare_district_registry(pd.read_csv(
        data_path('event_districts'), dtype=str, keep_default_na=False))
    by_source = defaultdict(list)
    for window in prepare_district_windows(registry):
        by_source[normalize_name(window['state'])].append(window)
    connection = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        titles = {url: (status, title) for url, status, title in connection.execute(
            'SELECT url, status, page_title FROM documents')}
    finally:
        connection.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    totals = Counter()
    seen = set()
    # Publish the payloads only after the complete source has been processed.
    import os
    import tempfile
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        from pathlib import Path
        accepted_path, pending_path = Path(tmp) / 'accepted.gz', Path(tmp) / 'pending.gz'
        with gzip.open(accepted_path, 'wt', encoding='utf-8') as accepted, gzip.open(pending_path, 'wt', encoding='utf-8') as pending:
            for row in _open_jsonl(source):
                totals['input_rows'] += 1
                options = candidates(row, by_source.get(normalize_name(row.get('state', '')), []))
                if not options:
                    totals['outside_window_or_unmatched_identity'] += 1
                    continue
                key = (row.get('url'), row.get('published_at'), row.get('source_record_id'), row.get('state'))
                if key in seen:
                    continue
                seen.add(key)
                status, title = titles.get(row.get('url'), ('missing', None))
                resolved = []
                for window in options:
                    candidate = {**row, **{k: window[k] for k in (
                        'event_district_id', 'event_id', 'source_record_id', 'state', 'district')},
                        'title': row.get('title') or title or '',
                        'locations_lower': row.get('locations_lower') or '',
                        'district_evidence': 'gkg_location'}
                    if not has_district_evidence(candidate):
                        candidate['district_evidence'] = 'title'
                    if has_district_evidence(candidate):
                        accepted.write(json.dumps(candidate, ensure_ascii=False) + '\n')
                        resolved.append(window['event_district_id'])
                        totals['district_candidate_rows'] += 1
                pending.write(json.dumps({**row, 'page_title': title,
                    'document_status': status, 'body_database': str(database),
                    'body_lookup_url': row.get('url'),
                    'candidate_districts': [{k: w[k] for k in ('event_district_id', 'state', 'district')} for w in options],
                    'evidence_matched_district_ids': resolved,
                    'llm_status': 'not_submitted'}, ensure_ascii=False) + '\n')
                totals['qa_candidate_rows'] += 1
                if not resolved:
                    totals['unresolved_rows'] += 1
        os.replace(accepted_path, output)
        os.replace(pending_path, qa)
    metadata = {'mode': 'local_state_reuse', 'source': str(source),
                'source_sha256': file_fingerprint(source), 'body_database': str(database),
                'reason': 'State corpus coverage and district semantic relevance are not verified',
                **dict(totals)}
    write_collection_manifest(manifest, registry, status=COLLECTION_INCOMPLETE,
                              metadata=metadata, article_payload_sha256=file_fingerprint(output))
    counts = build_district_counts(registry, _open_jsonl(output), manifest_path=manifest,
                                   article_database=database, article_payload_path=output)
    write_district_counts(counts, counts_path)
    audit.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    print(f'QA candidates (not submitted): {qa}')


if __name__ == '__main__':
    main()
