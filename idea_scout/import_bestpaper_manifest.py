from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List

from .io_utils import clean_text, write_jsonl


GITHUB_RE = re.compile(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def file_url(path: Path) -> str:
    return "file://" + str(path.resolve())


def text_path_for_relpath(root: Path, relpath: str) -> Path:
    pdf_rel = Path(relpath)
    parts = pdf_rel.parts
    if len(parts) >= 3:
        venue, year = parts[0], parts[1]
        return root / venue / "text" / year / (pdf_rel.stem + ".txt")
    return root / pdf_rel.with_suffix(".txt")


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def read_pdf_raw_text(pdf_path: Path, timeout: int = 15) -> str:
    if not pdf_path.exists() or not shutil.which("pdftotext"):
        return ""
    try:
        result = subprocess.run(
            ["pdftotext", "-raw", str(pdf_path), "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=True,
        )
        return result.stdout
    except Exception:
        return ""


def clean_pdf_text(text: str) -> str:
    text = text.replace("\x0c", "\n").replace("\r", "\n")
    text = re.sub(r"-\n(?=[a-z])", "", text)
    text = re.sub(r"\n+", "\n", text)
    return text


def strip_figure_lines(text: str) -> str:
    lines = []
    for line in text.splitlines():
        compact = line.strip()
        if not compact:
            lines.append(line)
            continue
        if re.match(r"(?i)^(figure|fig\.|table)\s+\d+", compact):
            continue
        if re.match(r"^[A-Za-z0-9]\d$", compact):
            continue
        if len(compact) <= 3 and re.fullmatch(r"[A-Za-z0-9_.-]+", compact):
            continue
        lines.append(line)
    return "\n".join(lines)


def extract_abstract(text: str, max_chars: int = 2400) -> str:
    if not text:
        return ""
    normalized = strip_figure_lines(clean_pdf_text(text))
    match = re.search(r"(?is)(?:^|\n)\s*abstract\s*\n?(.*?)(?=\n\s*(?:1\.?\s*)?introduction\b|\n\s*keywords\b|\Z)", normalized)
    if match:
        snippet = match.group(1)
        return clean_text(snippet, max_chars)
    match = re.search(r"(?is)\babstract\b[:.\-\s]*(.{200,5000})", normalized)
    if match:
        snippet = re.split(r"(?is)\b(?:1\.?\s*)?introduction\b|\bkeywords\b", match.group(1), maxsplit=1)[0]
        return clean_text(snippet, max_chars)
    return clean_text(normalized[:max_chars], max_chars)


def find_github_url(text: str) -> str:
    if not text:
        return ""
    match = GITHUB_RE.search(text)
    if not match:
        return ""
    return match.group(0).rstrip(".,);:]")


def record_from_manifest_row(row: Dict[str, str], root: Path) -> Dict[str, object] | None:
    relpath = clean_text(row.get("relpath"))
    title = clean_text(row.get("title"), 500)
    if not relpath or not title:
        return None
    try:
        year = int(clean_text(row.get("year")))
    except Exception:
        return None

    pdf_path = root / relpath
    text_path = text_path_for_relpath(root, relpath)
    text = read_pdf_raw_text(pdf_path) or read_text(text_path)
    local_pdf_url = file_url(pdf_path) if pdf_path.exists() else ""
    source_pdf_url = clean_text(row.get("pdf_url"))
    code_url = find_github_url(text)
    venue = clean_text(row.get("venue")).upper()

    return {
        "paper_id": f"bestpaper::{venue.lower()}::{year}::{Path(relpath).stem}",
        "title": title,
        "abstract": extract_abstract(text),
        "venue": venue,
        "year": year,
        "url": source_pdf_url or local_pdf_url,
        "pdf_url": local_pdf_url or source_pdf_url,
        "source_pdf_url": source_pdf_url,
        "local_pdf_path": str(pdf_path.resolve()) if pdf_path.exists() else "",
        "text_path": str(text_path.resolve()) if text_path.exists() else "",
        "code_url": code_url,
        "award_status": clean_text(row.get("status")),
        "source_manifest_relpath": relpath,
        "profile_name": "bestpaper_2016_2025",
    }


def build_records(
    manifest: str | Path,
    root: str | Path,
    min_year: int = 2016,
    max_year: int = 2025,
    status: str = "downloaded",
) -> List[Dict[str, object]]:
    manifest_path = Path(manifest)
    root_path = Path(root)
    records: List[Dict[str, object]] = []
    with manifest_path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if status and clean_text(row.get("status")).lower() != status.lower():
                continue
            record = record_from_manifest_row(row, root_path)
            if not record:
                continue
            year = int(record["year"])
            if min_year <= year <= max_year:
                records.append(record)
    return records


def main() -> None:
    ap = argparse.ArgumentParser(description="Build paper JSONL from the local bestpaper manifest and extracted text files.")
    ap.add_argument("--root", required=True, help="Bestpaper corpus root directory.")
    ap.add_argument("--manifest", default="", help="Manifest CSV path. Defaults to ROOT/manifest.csv.")
    ap.add_argument("--output", required=True)
    ap.add_argument("--min-year", type=int, default=2016)
    ap.add_argument("--max-year", type=int, default=2025)
    ap.add_argument("--status", default="downloaded")
    args = ap.parse_args()

    root = Path(args.root)
    manifest = Path(args.manifest) if args.manifest else root / "manifest.csv"
    records = build_records(manifest, root, min_year=args.min_year, max_year=args.max_year, status=args.status)
    write_jsonl(args.output, records)
    code_count = sum(1 for r in records if r.get("code_url"))
    text_count = sum(1 for r in records if r.get("text_path"))
    print({
        "input": str(manifest),
        "output": args.output,
        "papers": len(records),
        "with_text": text_count,
        "with_code_url": code_count,
        "year_range": [args.min_year, args.max_year],
    })


if __name__ == "__main__":
    main()
