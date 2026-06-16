# Asset Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an Insight/Method asset layer with code metadata verification, PDF ingest, CSV export, and portal browsing.

**Architecture:** Extend the existing `idea_scout` package with focused modules for asset schema, extraction, code verification, PDF ingest, and export. Keep scripts as thin wrappers and add portal tables/routes/templates for asset browsing.

**Tech Stack:** Python 3.9+, JSONL, SQLite, FastAPI, Jinja2, stdlib HTTP/SQLite utilities, optional external `pdftotext` when available.

---

### Task 1: Asset Schema and IO

**Files:**
- Create: `idea_scout/assets.py`
- Create: `tests/test_assets.py`

- [ ] Add asset defaults, stable IDs, normalization, scoring, and JSONL helpers.
- [ ] Verify asset generation handles papers without code or PDF fields.

### Task 2: Asset Extraction CLI

**Files:**
- Create: `idea_scout/extract_assets.py`
- Create: `scripts/extract_assets.py`
- Create: `tests/test_extract_assets.py`

- [ ] Convert paper or scored JSONL rows into `InsightAsset` records.
- [ ] Populate challenge, solution pattern, mechanism, evidence, limitations, source paper, code, PDF, and scores.
- [ ] Verify `examples/example_input.jsonl` creates assets.

### Task 3: Asset Export CLI

**Files:**
- Create: `idea_scout/export_assets.py`
- Create: `scripts/export_assets.py`
- Create: `tests/test_export_assets.py`

- [ ] Sort assets by asset score and code/PDF readiness.
- [ ] Export asset CSV with challenge, solution, code status, PDF status, and source paper fields.

### Task 4: Code Verification Metadata CLI

**Files:**
- Create: `idea_scout/verify_code.py`
- Create: `scripts/verify_code.py`
- Create: `tests/test_verify_code.py`

- [ ] Detect GitHub repository URLs from `code.url`, `code_url`, paper URL fields, and text fields.
- [ ] Mark missing code as `missing`.
- [ ] For GitHub URLs, use GitHub API when network is available and graceful fallback when unavailable.
- [ ] Populate license, stars, last commit, README presence, dependency-file presence, and runnable status.

### Task 5: PDF Ingest CLI

**Files:**
- Create: `idea_scout/ingest_pdf.py`
- Create: `scripts/ingest_pdf.py`
- Create: `tests/test_ingest_pdf.py`

- [ ] Accept PDF URLs, local PDF paths, or missing PDF fields.
- [ ] Extract text with `pdftotext` when available.
- [ ] Fall back to text fields when no PDF exists.
- [ ] Extract coarse method, experiments, and limitations sections.
- [ ] Preserve failure reasons without stopping the batch.

### Task 6: Portal Asset Import and Routes

**Files:**
- Modify: `web/import_jsonl.py`
- Modify: `web/app/main.py`
- Create: `web/app/templates/assets.html`
- Create: `web/app/templates/asset_detail.html`
- Modify: `web/app/templates/base.html`

- [ ] Add `assets` SQLite table.
- [ ] Import asset JSONL rows into the table.
- [ ] Add `/assets` and `/assets/{asset_id}` routes.
- [ ] Render asset list and detail pages with code/PDF status.

### Task 7: Documentation and Verification

**Files:**
- Modify: `README.md`
- Modify: `requirements.txt`

- [ ] Document asset flow and commands.
- [ ] Run `py_compile` for all modules.
- [ ] Run pytest.
- [ ] Run end-to-end example commands.
- [ ] Verify portal home/articles/assets/detail pages return HTTP 200.
