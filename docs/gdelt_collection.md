# EM-DAT-based GDELT collection

## Why BigQuery is the primary source

The GDELT DOC 2.0 API is useful for recent interactive searches, but its
official documentation limits precise searches to its rolling recent window
and caps Article List output at 250 records. CVND covers events from 2015, so
the reproducible source is the partitioned GDELT 2.0 GKG BigQuery table
`gdelt-bq.gdeltv2.gkg_partitioned`.

The GKG is article metadata derived from article text. It provides URL, source
domain, source language, extracted themes and extracted locations, but not a
reliable complete article body. CVND therefore measures GDELT-indexed coverage,
not all news published about an event.

Official references:

- [GDELT DOC 2.0 API documentation](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)
- [GDELT partitioned BigQuery tables](https://blog.gdeltproject.org/announcing-partitioned-gdelt-bigquery-tables/)
- [GDELT GKG BigQuery examples](https://blog.gdeltproject.org/google-bigquery-gkg-2-0-sample-queries/)
- [GDELT GKG theme lookup](https://data.gdeltproject.org/api/v2/guides/LOOKUP-GKGTHEMES.TXT)

## Default selection rule

Each canonical row is one official `DisNo. × state/UT` event. The default query
keeps an article only when all of the following hold:

1. Publication date is from event onset through onset + 93 days (94 calendar
   dates including the onset date).
2. GKG contains one of the 14 official `NATURAL_DISASTER_*FLOOD*` themes,
   including flood, flooding, flooded area/road, floodwater, flood warning and
   flash-flood variants.
3. GKG extracted at least one location block whose country field is India
   (`IN`, the GKG/FIPS country code).
4. Within that same Indian location block, a comma-delimited place-name
   component exactly matches the canonical state/UT, a documented state alias,
   or the state-linked district when available. This handles GKG names such as
   `Puri, Odisha, India` without accepting an unrelated foreign location.
5. The exact GDELT `DocumentIdentifier` has not already been counted. Query
   strings are retained because some publishers use them to distinguish real
   articles.

When windows for different official events overlap in the same state, one URL
is assigned to the nearest event onset. This prevents the same article from
being counted for several nearby floods in one state. An article may still
count for more than one state when it explicitly matches each state, which is
appropriate for a multi-state disaster.

## Selectable filters

| Option | Default | Effect |
| --- | --- | --- |
| `--topic-profile strict\|broad` | `strict` | `broad` also includes heavy rain, torrential rain, high water and monsoon themes; higher recall, lower precision |
| `--pre-days N` | `0` | Include anticipatory coverage before onset |
| `--post-days N` | `93` | Set the fixed post-onset observation window |
| `--languages en,hin,tam` | all | Restrict original source-language codes |
| `--include-domain DOMAIN` | none | Keep only listed source domains; repeatable |
| `--exclude-domain DOMAIN` | none | Remove listed source domains; repeatable |
| `--no-district-term` | off | Require state/UT matching only |
| `--title-fallback` | off | Also scan GKG `Extras` page titles; improves recall but increases bytes billed |
| `--event-id E001` | all | Generate or execute a small event subset; repeatable |

Historical GKG does not expose a dependable outlet-country field equivalent to
the recent DOC API's `sourcecountry:` operator. For historical comparisons,
use explicit domain allow/block lists and report them with the results.

## Commands

```bash
# Generate SQL only. This is safe, offline and incurs no BigQuery charge.
python src/collect_gdelt.py --overwrite

# Inspect a small event query.
python src/collect_gdelt.py --event-id E001 --dry-run

# Authenticate and run the complete historical query.
gcloud auth application-default login
GDELT_BILLING_PROJECT=your-project \
python src/collect_gdelt.py --estimate --overwrite

GDELT_BILLING_PROJECT=your-project \
python src/collect_gdelt.py --execute --overwrite
```

The generated SQL is stored as `data/raw/gdelt_emdat_query.sql`. Execution
writes `gdelt_bq.json` and `gdelt_bq.meta.json`; metadata includes the SQL hash,
event-registry hash, BigQuery job ID, billed bytes, filters and retrieval time.

## Recommended sensitivity runs

Use the strict all-language result as the primary MSS input. Run at least these
robustness checks separately instead of mixing them into the primary file:

1. Strict themes, English only.
2. Strict themes, English plus Indic languages.
3. Broad themes, all languages.
4. State-only location matching (`--no-district-term`).

Compare event article-count ranks and zero-coverage rates across runs. Large
rank changes identify events whose measured media salience depends heavily on
query design rather than stable coverage.
