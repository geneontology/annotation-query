# CLAUDE.md — annotation-query

Instructions for agents working in this repo. Keep this file terse; extend it as conventions solidify.

Adapted from the sibling `geneontology/go-annotation` repo — the two share most of their reporter code and move together. Where they diverge, this file calls it out.

## What this repo is

Two things in one repo:

1. **Issue tracker** for GO annotation-review requests (curator-driven, not code).
2. **Label-triggered GitHub Actions report runner** that dumps TSVs into `reports/<issue-number>/` on `main` when an issue is opened with a matching label.

The code surface is small. Most commits are auto-commits from the runner; the "software" commits — `scripts/` and `.github/workflows/` — are what an agent usually touches.

## Layout

- `scripts/` — Python reporters.
  - `annotation-review-report.py` — main reporter, GOlr Solr query → GAF-like TSV.
  - `term-usage-report.py` — **unique to this repo.** Cross-ontology term-usage report via Ubergraph (`runoak ... usages`, from `oaklib`); used for obsoletion-impact analysis. Filters to `RELATIONSHIP_OBJECT` context and drops GO-internal usages.
  - `mapping-report.py` — greps GO terms out of `external2go` mapping files.
  - `extension-report.py` — variant of the review reporter; tracked but **not wired to any workflow**. Confirm before relying on it.
- `.github/workflows/` — label-gated runners (all trigger on `issues: [opened]`).
  - `report-direct-ann-term.yml` → label `direct_ann_to_list_of_terms`.
  - `report-regulates-ann-term.yml` → label `reg_ann_to_list_of_terms`.
  - `report-term-usage.yml` → label `term_usage`. **Unique to this repo.**
- `.github/ISSUE_TEMPLATE/` — two templates; each applies its primary label **plus** `term_usage`, so the term-usage workflow runs alongside the direct/reg report.
- `reports/` — archive of auto-committed TSV outputs, one subdirectory per issue number (~184 entries). Treated as immutable output. **Do not edit, reformat, rename, or rewrite history for anything under `reports/`** — the commit messages are permalinked into issue comments and rewriting breaks them.

Note: unlike go-annotation, this repo has **no `specs/` directory** — the GPAD/GPI specs live only in go-annotation.

## Runtime and deps

- Workflows run on `ubuntu-22.04`. No `requirements.txt`, no `pyproject.toml`.
- `report-direct-ann-term` / `report-regulates-ann-term`: system `python3`; deps `requests`, `pytz`, stdlib.
- `report-term-usage`: builds a venv and `pip install oaklib requests pytz` (needs `runoak`). This is the one workflow that departs from the "system python, no venv" pattern.
- No test suite, no linter config. Scripts are standalone and copy-paste-evolved — don't introduce a package structure or shared-utils module without discussing it first.

## Code style (match what's there)

- `argparse` at top of file, verbose flag toggles `logging.INFO`.
- `die_screaming()` idiom for fatal exits (non-zero status so CI notices).
- Globals at module scope are fine; existing scripts comment "they were here before I got here--don't judge" — don't refactor them away just because.
- Scripts are self-contained: new reporter → new `scripts/<name>.py`, new workflow → new `.github/workflows/<name>.yml`, don't factor.
- Keep comments sparse; explain *why* not *what*.

## External services

- **GOlr Solr** — `http://golr-aux.geneontology.io/solr/select?...`. Cloudflare 301s `http://` → `https://` and `requests` follows silently. The canonical `fl`/`rfields` list lives in `annotation-review-report.py`; add new fields there.
  - **WAF / User-Agent (important).** GOlr's WAF rate-limits bare `python-requests/*` with **HTTP 429**. `annotation-review-report.py` sets an identifiable `User-Agent` (`geneontology-annotation-query-action/...`) so the WAF can allowlist this workflow narrowly. This mirrors the go-annotation fix (`geneontology/go-annotation#6416`). **If this repo's UA is not on the WAF allowlist** (or the allowlist isn't a `geneontology-*-action` pattern), `report-direct-ann-term` will keep failing with 429 — coordinate the allowlist via `geneontology/operations`. The throttle is keyed to GitHub-Actions IP ranges, so it does **not** reproduce from a dev machine.
- **Ubergraph** — queried by `term-usage-report.py` via `runoak -i ubergraph: usages ...` (oaklib). Not behind the GOlr WAF.
- **External2go snapshot** — `http://snapshot.geneontology.org/ontology/external2go/`; the report workflows `wget -r` it then prune specific files (`pfam2go`, `pirsf2go`, …) — mirror that pattern if adding another mapping reporter.
- **GitHub issue search** — plain REST, `api.github.com/search/issues`. No auth in scripts; scripts `time.sleep(10)` before calling to respect rate limits.

## Commit / auto-commit conventions

- **Push-back is hand-rolled here, not `git-auto-commit-action`.** Each workflow's final step does `git add reports/` → commit → a `git pull --rebase origin main && git push` retry loop (5 attempts, jittered sleep). This was a deliberate switch to survive concurrent runs racing on `main` (see `05517c7` "Use different approach for concurrent reports" and `ca53f4d`). **Don't replace it with `stefanzweifel/git-auto-commit-action`** — that's the go-annotation approach and it doesn't serialize concurrent pushes.
- Committer identity is `sjcarbon@lbl.gov` / `sjcarbon`; don't change it casually.
- Every software commit links to an issue, `; for #NN` or cross-repo `; for org/repo#NN` (matches the `pipeline-from-goa` trailer convention).
- Never rewrite history that touches `reports/`.

## Label → workflow wiring

Adding a new report type = three coordinated edits:

1. Add/mint a GitHub label on the repo.
2. New workflow under `.github/workflows/` (clone an existing one, change the `if: contains(...labels...)` guard and the `--label` / `--field` args, and keep the hand-rolled push-back step).
3. Script either reuses `annotation-review-report.py` with new `--field` / `--prefix`, or a new `scripts/<name>.py`.

## Debugging CI

- This repo's whole job is its Actions runs, so debugging usually starts with `gh run list` and `gh run view <id> --log-failed`.
- Known failure mode: `report-direct-ann-term` 429 from GOlr → see the WAF/User-Agent note above.
- `report-term-usage` hits GitHub + Ubergraph (not GOlr), so a GOlr WAF problem won't show there — useful for isolating cause.

## Things to check with me first

- Touching `reports/` in any way (bulk cleanup, reorganization, archival).
- Mass issue operations (closing, relabeling, commenting across many tickets).
- Adding dependencies, a test harness, a linter, or a packaging layout. The repo has intentionally stayed minimal.
- Anything that changes the auto-commit identity or the hand-rolled push-back loop.
- Changing the GOlr `User-Agent` string (it's coupled to a WAF allowlist).

## Sibling repos that overlap

- `geneontology/go-annotation` — source of these reporter scripts; changes here and there often move together. It has the `specs/` and a richer issue-template set.
- `geneontology/pipeline-from-goa` — upstream data ingest feeding GOlr. Shares the `; for org/repo#NN` commit-trailer convention.
- `geneontology/operations` — documents the hosts behind `snapshot.geneontology.org` and `golr-aux.geneontology.io`, and is where GOlr WAF allowlist rules are coordinated.
- `geneontology/go-ontology` — authoritative source for GO terms referenced in tickets.
- `geneontology/go-site` / `geneontology/go-fastapi` — downstream public surface for the data this repo's reports describe.
