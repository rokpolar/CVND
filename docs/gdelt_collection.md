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
- [GDELT Translingual 2.0 language coverage](https://blog.gdeltproject.org/gdelt-translingual-2-0-now-live-translates-everything-gdelt-monitors-in-109-languages-dialects/)
- [Census of India C-16 mother-tongue categories](https://censusindia.gov.in/nada/index.php/catalog/10191)
- [ISO 639-2 language code registry](https://www.loc.gov/standards/iso639-2/php/code_list.php)

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
5. Original source language belongs to the exact intersection of languages
   individually enumerated by India's Census C-16 table and languages supported
   by GDELT Translingual 2.0.
6. The exact GDELT `DocumentIdentifier` has not already been counted. Query
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
| `--languages en,hin,tam` | 16-language India Census × GDELT intersection | Override original source-language codes; use `all` to disable the filter |
| `--include-domain DOMAIN` | none | Keep only listed source domains; repeatable |
| `--exclude-domain DOMAIN` | none | Remove listed source domains; repeatable |
| `--no-district-term` | off | Require state/UT matching only |
| `--title-fallback` | off | Also scan GKG `Extras` page titles; improves recall but increases bytes billed |
| `--event-id E001` | all | Generate or execute a small event subset; repeatable |
| `--maximum-tib-billed 2.0` | `2.0` | Reject execution when BigQuery estimates a scan above this ceiling |
| `--article-metadata-profile basic\|rich` | `basic` | `basic` returns URL/date/language/event metadata without scanning extra columns; `rich` adds GKG ID, publisher source, title, authors, tone and image but increases bytes processed |

Historical GKG does not expose a dependable outlet-country field equivalent to
the recent DOC API's `sourcecountry:` operator. For historical comparisons,
use explicit domain allow/block lists and report them with the results.

The default codes are `en`, `ara`, `ben`, `guj`, `hin`, `kan`, `mal`, `mar`,
`nep`, `ori`, `pan`, `pus`, `snd`, `tam`, `tel`, and `urd`: English, Arabic,
Bengali, Gujarati, Hindi, Kannada, Malayalam, Marathi, Nepali, Odia, Punjabi,
Pashto, Sindhi, Tamil, Telugu, and Urdu. The scope is deliberately reproducible:
languages must be named categories in the nationwide Census C-16 table and
must also appear in GDELT's official Translingual 2.0 support list. Census
languages not supported by GDELT are not included merely because a plausible
three-letter code exists. Blank GKG `TranslationInfo` is classified as English
under the GKG codebook.

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

The generated SQL is stored as `data/raw/gdelt_emdat_query.sql`. `--execute`
runs that full article-level query once for every selected event and streams
the result instead of holding it in memory. It writes:

- `gdelt_bq.articles.jsonl.gz`: one row per assigned article, including URL,
  publication timestamp, event, state, source domain and language.
- `gdelt_bq.json`: event/language article counts and coverage dates derived
  locally for the MSS pipeline.
- `gdelt_bq.meta.json`: SQL and event hashes, BigQuery job ID, processed bytes,
  filters and retrieval time.

The default `--maximum-tib-billed 2.0` guard covers the current approximately
1.64 TiB basic-metadata estimate and rejects a larger scan before execution.

## Original article bodies

GDELT GKG contains extracted metadata and the original article URL, not the
complete article body. Fetch accessible pages separately after metadata
collection completes:

```bash
python src/download_articles.py \
  data/raw/gdelt_bq.articles.jsonl.gz \
  --output data/raw/gdelt_bq.articles.sqlite \
  --delay 1.0
```

The SQLite database separates unique downloaded documents from event/article
links, so one URL assigned to multiple state-events is fetched only once. It
stores the HTTP/final URL, retrieval time, response size, text hash, page title,
extracted body, extraction method/confidence, candidate count, and an explicit
status such as `ok`, `extract_weak`, `extract_empty`, `redirect_home`,
`redirect_listing`, `domain_parked`, `robots_denied`, `http_error`, `non_html`,
or `too_large`. Trafilatura, publisher JSON, and scored DOM candidates are
compared; repeated paragraphs, link-heavy widgets, current-headline tails, and
publisher boilerplate are removed. The default request delay is one second and
the default response limit is 5 MB. Re-running the same command processes only
`pending` URLs; use `--retry-failed` to retry failures and `--limit N` for a
small test run.

Publisher robots rules, access controls and paywalls are not bypassed. Deleted,
blocked and unsupported pages remain represented by their GDELT metadata and
download status rather than fabricated article text.

## Recommended sensitivity runs

Use the strict India-Census/GDELT-intersection result as the primary MSS input.
Run at least these
robustness checks separately instead of mixing them into the primary file:

1. Strict themes, English only.
2. Broad themes, the same 16-language intersection.
3. Strict themes, all GKG languages (`--languages all`).
4. State-only location matching (`--no-district-term`).

Compare event article-count ranks and zero-coverage rates across runs. Large
rank changes identify events whose measured media salience depends heavily on
query design rather than stable coverage.
