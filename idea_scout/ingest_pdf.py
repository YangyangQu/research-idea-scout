from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Dict

from .assets import compute_asset_score, read_assets, utc_now, write_assets
from .io_utils import clean_text


SECTION_PATTERNS = {
    "method": re.compile(r"(?is)(?:^|\n)\s*(?:\d+\.?\s*)?(method|methodology|approach|model|proposed method)\s*\n(.{0,8000})"),
    "experiments": re.compile(r"(?is)(?:^|\n)\s*(?:\d+\.?\s*)?(experiments|evaluation|experimental setup|results)\s*\n(.{0,8000})"),
    "limitations": re.compile(r"(?is)(?:^|\n)\s*(?:\d+\.?\s*)?(limitations|discussion|conclusion)\s*\n(.{0,8000})"),
}


def asset_pdf_url(asset: Dict) -> str:
    pdf = asset.get("pdf") if isinstance(asset.get("pdf"), dict) else {}
    if clean_text(pdf.get("url")):
        return clean_text(pdf.get("url"))
    for paper in asset.get("source_papers") or []:
        if isinstance(paper, dict) and clean_text(paper.get("pdf_url")):
            return clean_text(paper.get("pdf_url"))
    raw = asset.get("raw") if isinstance(asset.get("raw"), dict) else {}
    return clean_text(raw.get("pdf_url") or raw.get("pdf") or "")


def asset_existing_text_path(asset: Dict) -> Path | None:
    candidates = []
    pdf = asset.get("pdf") if isinstance(asset.get("pdf"), dict) else {}
    candidates.append(pdf.get("text_path"))
    for paper in asset.get("source_papers") or []:
        if isinstance(paper, dict):
            candidates.append(paper.get("text_path"))
    raw = asset.get("raw") if isinstance(asset.get("raw"), dict) else {}
    candidates.append(raw.get("text_path"))

    for candidate in candidates:
        text = clean_text(candidate)
        if not text:
            continue
        path = Path(text)
        if path.exists() and path.is_file():
            return path
    return None


def safe_name(asset_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", asset_id)[:120] or "asset"


def download_pdf(url: str, pdf_path: Path, timeout: int) -> str:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    if url.startswith("file://"):
        src = Path(url[len("file://"):])
        shutil.copyfile(src, pdf_path)
        return ""
    local = Path(url)
    if local.exists():
        shutil.copyfile(local, pdf_path)
        return ""
    req = urllib.request.Request(url, headers={"User-Agent": "research-idea-scout-assets"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            pdf_path.write_bytes(resp.read())
        return ""
    except Exception as e:
        return str(e)


def extract_text(pdf_path: Path, text_path: Path, timeout: int) -> str:
    text_path.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("pdftotext"):
        try:
            subprocess.run(
                ["pdftotext", str(pdf_path), str(text_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
                check=True,
            )
            return ""
        except Exception as e:
            return str(e)
    return "pdftotext_not_found"


def fallback_text(asset: Dict) -> str:
    source = (asset.get("source_papers") or [{}])[0]
    raw = asset.get("raw") if isinstance(asset.get("raw"), dict) else {}
    parts = [
        asset.get("challenge", ""),
        asset.get("solution_pattern", ""),
        asset.get("mechanism", ""),
        " ".join(asset.get("evidence") or []),
        source.get("abstract", ""),
        raw.get("abstract", ""),
    ]
    return "\n\n".join(clean_text(p) for p in parts if clean_text(p))


def trim_section(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def extract_sections(text: str, max_chars: int = 1800) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    for name, pattern in SECTION_PATTERNS.items():
        match = pattern.search(text)
        if match:
            sections[name] = trim_section(match.group(2), max_chars)
        else:
            sections[name] = ""
    if not any(sections.values()):
        compact = trim_section(text, max_chars)
        sections["method"] = compact
        sections["experiments"] = ""
        sections["limitations"] = ""
    return sections


def ingest_one(asset: Dict, output_dir: Path, timeout: int = 30, use_fallback: bool = True) -> Dict:
    out = dict(asset)
    pdf = dict(out.get("pdf") or {})
    url = asset_pdf_url(out)
    pdf["url"] = url
    pdf["checked_at"] = utc_now()

    text = ""
    existing_text_path = asset_existing_text_path(out)
    if existing_text_path:
        text = existing_text_path.read_text(encoding="utf-8", errors="ignore")
        pdf.update({"status": "parsed", "failure_reason": "", "text_path": str(existing_text_path)})
    elif url:
        base = safe_name(out.get("asset_id", "asset"))
        pdf_path = output_dir / "pdfs" / f"{base}.pdf"
        text_path = output_dir / "texts" / f"{base}.txt"
        err = download_pdf(url, pdf_path, timeout)
        if err:
            pdf.update({"status": "failed", "failure_reason": f"download:{err}", "text_path": ""})
        else:
            err = extract_text(pdf_path, text_path, timeout)
            if err:
                pdf.update({"status": "failed", "failure_reason": f"extract:{err}", "text_path": ""})
            else:
                text = text_path.read_text(encoding="utf-8", errors="ignore")
                pdf.update({"status": "parsed", "failure_reason": "", "text_path": str(text_path)})
    elif use_fallback:
        text = fallback_text(out)
        pdf.update({"status": "missing", "failure_reason": "", "text_path": ""})
    else:
        pdf.update({"status": "missing", "failure_reason": "", "text_path": ""})

    if text:
        sections = extract_sections(text)
        pdf["extracted_sections"] = sections
        evidence = list(out.get("evidence") or [])
        for label in ["method", "experiments", "limitations"]:
            if sections.get(label):
                evidence.append(f"{label.title()} evidence: {sections[label]}")
        out["evidence"] = evidence
        if sections.get("limitations"):
            limits = list(out.get("limitations") or [])
            limits.append(sections["limitations"])
            out["limitations"] = limits
        out.setdefault("scores", {})["evidence_strength"] = max(
            float(out.get("scores", {}).get("evidence_strength", 0) or 0),
            6.0 if pdf.get("status") == "parsed" else 3.0,
        )
    else:
        pdf.setdefault("extracted_sections", {"method": "", "experiments": "", "limitations": ""})

    out["pdf"] = pdf
    out.setdefault("scores", {})["asset_score"] = compute_asset_score(out)
    out["updated_at"] = utc_now()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest PDF text and section evidence for Insight/Method assets.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--work-dir", default="data/pdf_ingest")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--no-fallback", action="store_true")
    args = ap.parse_args()

    output_dir = Path(args.work_dir)
    assets = [
        ingest_one(asset, output_dir=output_dir, timeout=args.timeout, use_fallback=not args.no_fallback)
        for asset in read_assets(args.input)
    ]
    write_assets(args.output, assets)
    summary = {}
    for asset in assets:
        status = (asset.get("pdf") or {}).get("status", "unknown")
        summary[status] = summary.get(status, 0) + 1
    print(json.dumps({"input": args.input, "output": args.output, "assets": len(assets), "pdf_status": summary}, indent=2))


if __name__ == "__main__":
    main()
