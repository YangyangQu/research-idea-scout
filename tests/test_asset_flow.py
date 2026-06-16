from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from idea_scout.export_assets import flatten_asset
from idea_scout.extract_assets import extract_assets
from idea_scout.import_bestpaper_manifest import build_records
from idea_scout.ingest_pdf import ingest_one
from idea_scout.io_utils import write_csv
from idea_scout.verify_code import verify_one
from web.import_jsonl import import_asset_rows


def sample_paper() -> dict:
    return {
        "title": "Subspace Editing for Controllable Representation Learning",
        "abstract": "We propose a method to discover linear subspaces and intervene on representations.",
        "venue": "ExampleConf",
        "year": 2026,
        "url": "https://example.org/paper1",
    }


def test_extract_asset_has_code_and_pdf_fields() -> None:
    assets = extract_assets([sample_paper()], profile_name="test_profile")
    assert len(assets) == 1
    asset = assets[0]
    assert asset["asset_id"]
    assert asset["challenge"]
    assert asset["solution_pattern"]
    assert asset["code"]["status"] == "missing"
    assert asset["pdf"]["status"] == "missing"
    assert "asset_score" in asset["scores"]


def test_code_verification_marks_missing_code() -> None:
    asset = extract_assets([sample_paper()])[0]
    checked = verify_one(asset, offline=True)
    assert checked["code"]["status"] == "missing"
    assert checked["code"]["runnable_status"] == "not_attempted"
    assert checked["scores"]["code_readiness"] == 0.0


def test_pdf_ingest_fallback_adds_evidence(tmp_path: Path) -> None:
    asset = extract_assets([sample_paper()])[0]
    checked = ingest_one(asset, output_dir=tmp_path)
    assert checked["pdf"]["status"] == "missing"
    assert checked["pdf"]["extracted_sections"]["method"]
    assert checked["scores"]["evidence_strength"] >= 3.0



def test_pdf_ingest_reuses_existing_text_path(tmp_path: Path) -> None:
    text_path = tmp_path / "paper.txt"
    text_path.write_text(
        "Abstract\nWe solve sparse tracking.\n\nMethod\nUse a reusable transformer module.\n\nExperiments\nIt works.",
        encoding="utf-8",
    )
    paper = sample_paper() | {"text_path": str(text_path)}
    asset = extract_assets([paper])[0]
    checked = ingest_one(asset, output_dir=tmp_path / "ingest")
    assert checked["pdf"]["status"] == "parsed"
    assert checked["pdf"]["text_path"] == str(text_path)
    assert checked["pdf"]["extracted_sections"]["method"].startswith("Use a reusable")


def test_bestpaper_manifest_builds_records_from_existing_text(tmp_path: Path) -> None:
    root = tmp_path / "bestpaper"
    text_dir = root / "cvpr" / "text" / "2025"
    pdf_dir = root / "cvpr" / "2025"
    text_dir.mkdir(parents=True)
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "sample-paper.pdf").write_bytes(b"%PDF-1.4")
    (text_dir / "sample-paper.txt").write_text(
        "Sample Paper\n\nAbstract\nWe present a method for robust ideas. Code is at https://github.com/acme/sample.",
        encoding="utf-8",
    )
    manifest = root / "manifest.csv"
    manifest.write_text(
        "venue,year,title,status,reason,pdf_url,relpath\n"
        "cvpr,2025,Sample Paper,downloaded,,https://example.org/sample.pdf,cvpr/2025/sample-paper.pdf\n",
        encoding="utf-8",
    )

    records = build_records(manifest, root, min_year=2016, max_year=2025)
    assert len(records) == 1
    record = records[0]
    assert record["title"] == "Sample Paper"
    assert record["venue"] == "CVPR"
    assert record["pdf_url"].startswith("file://")
    assert record["text_path"] == str(text_dir / "sample-paper.txt")
    assert record["code_url"] == "https://github.com/acme/sample"
    assert "robust ideas" in record["abstract"]

def test_export_asset_csv_row(tmp_path: Path) -> None:
    asset = ingest_one(verify_one(extract_assets([sample_paper()])[0], offline=True), output_dir=tmp_path)
    row = flatten_asset(asset, 1)
    out = tmp_path / "assets.csv"
    write_csv(out, [row], list(row.keys()))
    text = out.read_text()
    assert "asset_id" in text
    assert "code_status" in text
    assert "pdf_status" in text


def test_portal_import_and_asset_routes(tmp_path: Path, monkeypatch) -> None:
    asset = ingest_one(verify_one(extract_assets([sample_paper()])[0], offline=True), output_dir=tmp_path)
    jsonl = tmp_path / "assets.jsonl"
    jsonl.write_text(json.dumps(asset, ensure_ascii=False) + "\n")
    db = tmp_path / "portal.db"
    assert import_asset_rows(jsonl, db) == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("select count(*) from assets").fetchone()[0] == 1

    monkeypatch.setenv("IDEASCOUT_PORTAL_DB", str(db))
    import importlib
    import web.app.main as main

    importlib.reload(main)
    client = TestClient(main.app)
    assert client.get("/assets").status_code == 200
    assert client.get(f"/assets/{asset['asset_id']}").status_code == 200
