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

The BigQuery extraction assigns a URL to the nearest event onset within each
state only to keep the raw export deterministic. That assignment is not the
final article/event decision. `classify_event_articles.py prepare` later
re-expands each `(state, URL, publication date)` to every official event whose
onset-through-onset+93-day window contains the publication date. The keyword
and LLM stages then decide each article/event pair independently, so one URL
may correctly count for several events and states.

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
  --workers 32 \
  --extract-workers 4 \
  --delay 1.0
```

The SQLite database separates unique downloaded documents from event/article
links, so one URL assigned to multiple state-events is fetched only once. It
stores the HTTP/final URL, retrieval time, response size, text hash, page title,
extracted body, extraction method/confidence, candidate count, and an explicit
status such as `ok`, `extract_weak`, `extract_empty`, `redirect_home`,
`redirect_listing`, `domain_parked`, `host_deferred`, `robots_denied`,
`http_error`, `non_html`, or `too_large`. Trafilatura, publisher JSON, and scored DOM candidates are
compared; repeated paragraphs, link-heavy widgets, current-headline tails, and
publisher boilerplate are removed. The default request delay is one second and
the default response limit is 5 MB. The delay applies independently to each
origin; a bounded round-robin queue fetches up to 32 different origins
concurrently by default, and
`Crawl-delay` or `Request-rate` from robots.txt can only make an origin slower.
HTML extraction runs in a separate process pool and SQLite writes commit in
batches. Interactive terminals use tqdm's terminal-width-aware live progress
display: one static line shows completion, throughput, and ETA while a second
static line shows compact status counts. Both lines are redrawn in place without
wrapping or scrolling the terminal. Redirected output retains a stable log line
every 100 URLs. Set the standard `NO_COLOR` environment variable to disable
ANSI colors.

For `extract_empty` or `extract_weak`, the downloader can retry same-site URLs
explicitly declared by canonical or AMP markup. It can also upgrade a failed
HTTP URL to HTTPS. Playwright rendering is reserved for pages detected as thin
JavaScript application shells; images, media and fonts are blocked. These
fallbacks never bypass robots rules, paywalls, access errors, home/listing
redirects, or parked domains. Every logical attempt is recorded in
`download_attempts`; `documents.fallback_used` and `selected_attempt_url`
identify the winning attempt.

Browser fallback uses the Playwright Python package and the `chrome` channel by
default. Install Google Chrome or select another installed Playwright channel
with `--browser-channel`; use `--no-browser-fallback` on systems without a
supported browser.

Re-running the same command processes only `pending` URLs. `--retry-failed`
retries transient network/HTTP failures and weak/empty extractions, while
terminal failures remain untouched. Use `--limit N` for a small test run,
`--no-browser-fallback` to disable browser rendering, and tune `--workers`,
`--browser-workers`, `--commit-every`, and `--retries` when needed. Three
consecutive transient failures open a host circuit for the current run and mark
the remaining URLs `host_deferred`; a later `--retry-failed` run tries them with
a fresh circuit.

Publisher robots rules, access controls and paywalls are not bypassed. Deleted,
blocked and unsupported pages remain represented by their GDELT metadata and
download status rather than fabricated article text.

## Event-level article classification

`src/classify_event_articles.py` maps accessible article bodies to official
EM-DAT state-events without changing MSS. Its fixed sequence is:

1. Re-expand GDELT metadata to every same-state event for which the publication
   date is between event onset and onset + 93 days, inclusive.
2. Inspect exactly the first 2,000 body characters. Keep only excerpts that
   contain a flood term from the English, Arabic, Bengali, Gujarati, Hindi,
   Kannada, Malayalam, Marathi, Nepali, Odia, Punjabi, Pashto, Sindhi, Tamil,
   Telugu, or Urdu lexicon. All language lexicons are searched regardless of
   GDELT's source-language label. Generic rain and monsoon terms do not pass.
3. Send each surviving article/event candidate to the OpenAI Batch API as a
   strict structured-output question: does this excerpt discuss this specific
   official event? Unparseable or ambiguous output is stored as `ambiguous_no`
   and counts as NO.
4. Count distinct original URLs with a YES decision for each event. Separate
   URLs with the same body remain separate articles; their LLM decision is
   cached by body hash, event-profile hash, prompt version, and model ID.

Only `documents.status IN ('ok', 'extract_weak')` with non-empty body text can
reach the classifier. Missing or inaccessible bodies are recorded as
`no_body` and excluded from the final count. This strict policy means the final
count is the number of positively identified articles among successfully
retrieved bodies, not an estimate for inaccessible URLs.

The model is intentionally fixed to `gpt-5.6-luna` in code, with
`reasoning.effort="none"` for this short binary classification task. There is no
`--model` option. A future model or reasoning-setting change must also bump the
prompt version so cached decisions cannot be mixed across classifier contracts.

```bash
# 1. Build candidates and run the offline multilingual keyword filter.
./venv/bin/python src/classify_event_articles.py prepare

# Optional small offline check.
./venv/bin/python src/classify_event_articles.py \
  --database /tmp/cvnd_event_relevance_test.sqlite \
  prepare \
  --event-id E001 \
  --limit 1000

# 2. Inspect request volume before spending API credits.
./venv/bin/python src/classify_event_articles.py estimate

# 3. After setting the API key, submit JSONL Batch jobs.
export OPENAI_API_KEY="your-api-key"
./venv/bin/python src/classify_event_articles.py submit

# 4. Check or wait for completion, then collect and export.
./venv/bin/python src/classify_event_articles.py status
./venv/bin/python src/classify_event_articles.py status --wait
./venv/bin/python src/classify_event_articles.py collect
./venv/bin/python src/classify_event_articles.py export
```

Batch input files are capped at 150 MiB and 50,000 requests by default, below
the API's 200 MB file limit and at its per-batch request limit. Requests use
`/v1/responses`, unique stable `custom_id` values, a strict boolean JSON schema,
and 24-hour completion windows. Output order is irrelevant because collection
joins responses by `custom_id`. `submit --retry-failed` resubmits only failed,
expired, or cancelled requests that do not already have a decision.
`collect` also saves partial successful responses from expired or cancelled
batches before the unfinished requests are made eligible for retry.

`submit` enqueues at most 3,000 requests per invocation by default because the
model-specific queued-token allowance depends on the OpenAI usage tier. The
command refuses to enqueue another wave while a prior batch is active or while
its completed output is still uncollected. Run `status`, then `collect`, before
the next `submit`. Increase `--limit` only after checking the account's Batch
queue token limit; this safety limit is independent of the 50,000-request file
limit.

OpenAI references: [Batch API](https://developers.openai.com/api/docs/guides/batch),
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

Generated artifacts:

- `data/intermediate/gdelt_event_relevance.sqlite`: candidates, heuristics,
  request cache, decisions, Batch jobs, and run provenance.
- `data/intermediate/gdelt_event_relevance_batches/`: local Batch JSONL inputs
  and downloaded output/error files.
- `data/results/event_article_counts.csv`: one row for every official event,
  including candidate/body/heuristic/LLM counts and `final_article_count`.
- `data/results/event_articles.csv.gz`: auditable URL-to-event mapping with the
  heuristic, LLM status, fixed model, prompt version, and final `related` flag.

The pipeline does not generate a manually labeled evaluation sample, so its
outputs must not be described as having measured precision or recall.

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
