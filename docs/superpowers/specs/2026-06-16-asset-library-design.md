# Research Idea Scout Assets Design

## Goal

Upgrade Research Idea Scout from an abstract-level paper ranker into an asset-centered research system that preserves reusable insights, verifies open-source code availability, and enriches assets with PDF full-text evidence.

## Scope

The first working version must include all three tracks:

- Asset library: `InsightAsset` / `MethodAsset` records are the primary output.
- Code verification: each asset has explicit code metadata and status.
- PDF full-text ingest: each asset has explicit PDF metadata and extracted evidence fields.

The first version may use lightweight heuristics and metadata checks, but the data model and command-line flow must support later stronger extraction and runnable code verification.

## Architecture

The system keeps the existing paper JSONL and profile-guided scoring tools, then adds an asset layer:

```text
paper JSONL or scored JSONL
  -> asset extraction
  -> code metadata verification
  -> PDF text ingest and section extraction
  -> asset export
  -> asset portal
```

The paper remains a source. The asset is the reusable research object.

## Asset Schema

Each asset is a JSON object with these top-level fields:

- `asset_id`: stable ID derived from source paper and challenge/solution text.
- `asset_type`: `insight`, `method`, `evaluation`, `dataset`, or `implementation`.
- `challenge`: the problem or challenge the source paper identifies.
- `why_it_is_hard`: concise explanation of why the challenge is hard.
- `solution_pattern`: reusable solution pattern.
- `mechanism`: technical mechanism that makes the solution work.
- `required_assumptions`: assumptions needed for transfer.
- `transferable_to`: target domains or problems where the asset may transfer.
- `non_transferable_parts`: parts likely tied to the original domain.
- `evidence`: evidence snippets, ablations, claims, or extracted section summaries.
- `limitations`: risks and known limitations.
- `source_papers`: source paper metadata.
- `code`: code availability and verification status.
- `pdf`: PDF availability, parsing status, and extracted sections.
- `scores`: transferability, evidence strength, code readiness, and feasibility.

Code is a hard field, not a note:

```json
{
  "url": "",
  "status": "missing",
  "license": "",
  "stars": 0,
  "last_commit": "",
  "has_readme": false,
  "has_requirements": false,
  "runnable_status": "not_attempted",
  "checked_at": ""
}
```

PDF is also a hard field:

```json
{
  "url": "",
  "status": "missing",
  "text_path": "",
  "extracted_sections": {
    "method": "",
    "experiments": "",
    "limitations": ""
  },
  "checked_at": ""
}
```

## Commands

The first version adds these commands:

- `scripts/extract_assets.py`: create assets from paper/scored JSONL.
- `scripts/verify_code.py`: enrich assets with GitHub/code metadata.
- `scripts/ingest_pdf.py`: download or read PDFs, extract text and coarse sections.
- `scripts/export_assets.py`: export ranked assets to CSV.

## Web Portal

The portal adds:

- `/assets`: asset library page.
- `/assets/{asset_id}`: asset detail page.

The asset pages display challenge, solution pattern, mechanism, evidence, limitations, code status, and PDF status.

## First-Version Success Criteria

The first version is considered locally runnable when this chain works on example data:

```text
examples/example_input.jsonl
  -> data/assets.jsonl
  -> data/assets_with_code.jsonl
  -> data/assets_with_pdf.jsonl
  -> data/assets.csv
  -> portal home/articles/assets pages return HTTP 200
```

The first version must support missing code and PDF gracefully. `code.status=missing` and `pdf.status=missing` are valid outcomes, but the fields and command flow must exist.
