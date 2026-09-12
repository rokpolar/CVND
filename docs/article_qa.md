# Article QA operations (WSL)

The primary observation remains 14 UTC days from onset. The 30-day table is a
separate sensitivity artifact; satellite post-windows remain 14 days.
The coverage scope is local_state_plus_targeted_bigquery. Targeted supplementation
cannot establish exhaustive coverage of all districts with some local candidates.

## Prepare without paid calls

Run from the project root:

    venv/bin/python src/build_emdat_events.py
    venv/bin/python src/build_district_covariates.py
    venv/bin/python src/article_qa.py prepare
    venv/bin/python src/article_qa.py counts

The state JSONL and SQLite are read-only. Derived files are in
data/intermediate/article_qa/. requests.jsonl contains one article/event request
with district candidates; pending.jsonl retains missing/failed bodies.
No confidence field is emitted. Prior source_record_id does not restrict
reassignment to current state/date windows.

Registry changes archive affected CSV caches under data/archive/registry/.
Only unchanged IDs, identities and geometry IDs survive migration. Geometry
values from different references are never combined. Old article manifests
fail registry hash checks and must be regenerated.

## Targeted supplementation

    venv/bin/python src/article_qa.py retry-text
    venv/bin/python src/article_qa.py prepare
    venv/bin/python src/article_qa.py supplement --maximum-tib 0.25
    venv/bin/python src/article_qa.py supplement --execute --maximum-tib 0.25
    venv/bin/python src/article_qa.py download-new
    venv/bin/python src/article_qa.py prepare

The first supplement command is a BigQuery dry-run estimate, not a billed query.
Execution also estimates before submitting. One combined query covers all gaps,
so the cap applies to the whole run. Returning fewer URLs does not imply a
smaller scan. The query targets districts without usable local district evidence
in the 30-day window, with strict themes, district/state evidence, rich metadata
and title fallback. Successful zero-result queries are recorded.
Known URLs retain new district metadata but are not downloaded again.
Body downloads respect the existing downloader's robots and host controls.
Only explicitly selected transient URLs are retried, with one network retry,
four workers and no browser fallback.

## Luna Batch

Set OPENAI_API_KEY in the environment. The shell pipeline reads .env; direct
Python commands use exported variables. No key is printed or saved in artifacts.

    venv/bin/python src/article_qa.py submit --execute
    venv/bin/python src/article_qa.py status
    venv/bin/python src/article_qa.py collect
    venv/bin/python src/article_qa.py counts

For automatic sequential submission and collection:

    venv/bin/python src/article_qa.py run-batches --execute

The command polls every 60 seconds. Ctrl-C preserves its ledger. Invoke the same
command to resume. Each shard contains at most 1,000 requests and 4 MB of JSONL,
and only one batch is active. Account-specific queue limits may still reject a
submission; the recorded error must be resolved before retrying.

For failed, expired, refused or invalid outputs, inspect errors.json and use:

    venv/bin/python src/article_qa.py submit --execute --retry-failed
    venv/bin/python src/article_qa.py run-batches --execute

Only requests without valid results are retried.
If submission acknowledgement was lost, the runner first searches
provider batch metadata. An unresolvable submission stops until an explicit
retry, rather than assuming that the first attempt was rejected.
Every candidate must appear
exactly once in the structured response. Unknown/duplicate/missing IDs fail the
request. Relevant evidence must be an exact excerpt of the supplied text.
Article content is untrusted input, never an instruction to the classifier.

## Full pipeline and outputs

    REUSE_STATE_ARTICLES=1 RUN_ARTICLE_SUPPLEMENT=1 RUN_LLM_QA=1 \
      GDELT_SUPPLEMENT_MAX_TIB=0.25 LLM_QA_MODEL=gpt-5.6-luna \
      bash scripts/run_pipeline.sh

Satellite options retain their existing meanings. To inspect commands without
queries, downloads, submission or artifact replacement:

    REUSE_STATE_ARTICLES=1 RUN_ARTICLE_SUPPLEMENT=1 RUN_LLM_QA=1 \
      bash scripts/run_pipeline.sh --dry-run

The pipeline waits for QA batches. Failed requests stop automatic progression
until retry; missing text and uncertain verdicts remain unobserved, with final
count NA for the affected district. Completed relevant decisions count once per
URL/canonical district, assigned to the nearest eligible onset.

counts_14d.csv feeds the primary join. counts_30d.csv feeds
data/results/district_flood_articles_30d.csv with separate QC/exclusions.
The existing statistical model runs on the primary table. The 30-day table is
available for separately labelled sensitivity modeling.

Always retain manifest.json, supplement.json, batches.json, results.json and
the raw provider output beside the final decisions. Token usage belongs to a
request and is repeated in pair records for provenance: deduplicate by custom_id
when totaling cost.
