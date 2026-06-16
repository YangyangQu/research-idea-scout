from __future__ import annotations

import argparse
from typing import Any, Dict, List

from .assets import read_assets
from .io_utils import write_csv


def score(asset: Dict[str, Any], key: str) -> float:
    try:
        if key.startswith("scores."):
            return float((asset.get("scores") or {}).get(key.split(".", 1)[1], 0) or 0)
        return float(asset.get(key, 0) or 0)
    except Exception:
        return 0.0


def flatten_asset(asset: Dict[str, Any], rank: int) -> Dict[str, Any]:
    source = (asset.get("source_papers") or [{}])[0]
    code = asset.get("code") or {}
    pdf = asset.get("pdf") or {}
    scores = asset.get("scores") or {}
    insight = asset.get("insight") if isinstance(asset.get("insight"), dict) else {}
    review = asset.get("llm_review") if isinstance(asset.get("llm_review"), dict) else {}
    return {
        "rank": rank,
        "asset_id": asset.get("asset_id", ""),
        "asset_type": asset.get("asset_type", ""),
        "profile_name": asset.get("profile_name", ""),
        "asset_score": scores.get("asset_score", 0),
        "transferability": scores.get("transferability", 0),
        "evidence_strength": scores.get("evidence_strength", 0),
        "code_readiness": scores.get("code_readiness", 0),
        "implementation_feasibility": scores.get("implementation_feasibility", 0),
        "llm_verdict": review.get("verdict", ""),
        "llm_asset_quality": review.get("asset_quality", ""),
        "llm_confidence": review.get("confidence", ""),
        "llm_code_assessment": review.get("code_assessment", ""),
        "llm_review_notes": review.get("review_notes", ""),
        "challenge": asset.get("challenge", ""),
        "solution_pattern": asset.get("solution_pattern", ""),
        "mechanism": asset.get("mechanism", ""),
        "reusable_insight": insight.get("reusable_insight", ""),
        "insight_method": insight.get("method", ""),
        "insight_status": insight.get("extraction_status", ""),
        "llm_why_it_works": review.get("why_it_works", ""),
        "llm_transfer_targets": " | ".join(review.get("transfer_targets") or []),
        "llm_non_transferable_parts": " | ".join(review.get("non_transferable_parts") or []),
        "llm_evidence_quotes": " | ".join(review.get("evidence_quotes") or []),
        "code_status": code.get("status", ""),
        "code_url": code.get("url", ""),
        "code_license": code.get("license", ""),
        "code_stars": code.get("stars", 0),
        "code_last_commit": code.get("last_commit", ""),
        "code_discovery_source": code.get("discovery_source", ""),
        "code_discovery_confidence": code.get("discovery_confidence", ""),
        "code_homepage_url": code.get("homepage_url", ""),
        "runnable_status": code.get("runnable_status", ""),
        "pdf_status": pdf.get("status", ""),
        "pdf_url": pdf.get("url", ""),
        "pdf_text_path": pdf.get("text_path", ""),
        "source_title": source.get("title", ""),
        "source_venue": source.get("venue", ""),
        "source_year": source.get("year", ""),
        "source_url": source.get("url", ""),
        "limitations": " | ".join(asset.get("limitations") or []),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Export ranked Insight/Method assets to CSV.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--top-k", type=int, default=0)
    ap.add_argument("--sort-by", nargs="*", default=["scores.asset_score", "scores.code_readiness", "scores.evidence_strength"])
    args = ap.parse_args()

    assets = read_assets(args.input)
    assets.sort(key=lambda a: tuple(score(a, k) for k in args.sort_by), reverse=True)
    if args.top_k and args.top_k > 0:
        assets = assets[: args.top_k]

    rows = [flatten_asset(asset, i) for i, asset in enumerate(assets, 1)]
    fields = list(rows[0].keys()) if rows else [
        "rank", "asset_id", "asset_type", "profile_name", "asset_score", "challenge", "solution_pattern",
        "code_status", "pdf_status", "source_title",
    ]
    write_csv(args.output, rows, fields)
    print(args.output)


if __name__ == "__main__":
    main()
