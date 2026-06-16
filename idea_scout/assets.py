from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .io_utils import clean_text, paper_key, read_jsonl, write_jsonl


ASSET_TYPES = {"insight", "method", "evaluation", "dataset", "implementation"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [clean_text(x) for x in value if clean_text(x)]
    if isinstance(value, tuple):
        return [clean_text(x) for x in value if clean_text(x)]
    text = clean_text(value)
    return [text] if text else []


def first_text(obj: Dict[str, Any], keys: Iterable[str], max_chars: int = 0) -> str:
    for key in keys:
        value = clean_text(obj.get(key), max_chars)
        if value:
            return value
    return ""


def normalize_url(value: Any) -> str:
    text = clean_text(value)
    return text if text.startswith(("http://", "https://", "file://")) else text


def source_paper_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "paper_key": paper_key(row),
        "title": clean_text(row.get("title"), 500),
        "abstract": clean_text(row.get("abstract"), 2500),
        "venue": clean_text(row.get("venue")),
        "year": row.get("year"),
        "url": normalize_url(row.get("url") or row.get("paper_url")),
        "pdf_url": normalize_url(row.get("pdf_url") or row.get("pdf")),
        "code_url": normalize_url(row.get("code_url") or row.get("github_url") or row.get("repo_url")),
        "local_pdf_path": clean_text(row.get("local_pdf_path")),
        "text_path": clean_text(row.get("text_path")),
        "award_status": clean_text(row.get("award_status") or row.get("status")),
        "authors": row.get("authors", ""),
    }


def default_code(row: Dict[str, Any] | None = None) -> Dict[str, Any]:
    row = row or {}
    code_url = normalize_url(row.get("code_url") or row.get("github_url") or row.get("repo_url"))
    return {
        "url": code_url,
        "status": "repo_found" if code_url else "missing",
        "license": "",
        "stars": 0,
        "last_commit": "",
        "has_readme": False,
        "has_requirements": False,
        "runnable_status": "not_attempted",
        "checked_at": "",
        "failure_reason": "",
    }


def default_pdf(row: Dict[str, Any] | None = None) -> Dict[str, Any]:
    row = row or {}
    pdf_url = normalize_url(row.get("pdf_url") or row.get("pdf"))
    text_path = clean_text(row.get("text_path"))
    return {
        "url": pdf_url,
        "status": "missing",
        "text_path": text_path,
        "extracted_sections": {
            "method": "",
            "experiments": "",
            "limitations": "",
        },
        "checked_at": "",
        "failure_reason": "",
    }


def default_scores(row: Dict[str, Any] | None = None) -> Dict[str, float]:
    row = row or {}
    transfer = numeric(row.get("score_overall_fit") or row.get("rank_score"), 0.0)
    novelty = numeric(row.get("score_theory_novelty"), 0.0)
    code = 2.0 if first_text(row, ["code_url", "github_url", "repo_url"]) else 0.0
    pdf = 2.0 if first_text(row, ["pdf_url", "pdf"]) else 0.0
    return {
        "transferability": round(transfer, 4),
        "evidence_strength": round(max(novelty, pdf), 4),
        "code_readiness": round(code, 4),
        "implementation_feasibility": numeric(row.get("score_implementation_feasibility"), 0.0),
        "asset_score": 0.0,
    }


def numeric(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return default


def compute_asset_score(asset: Dict[str, Any]) -> float:
    scores = asset.get("scores") if isinstance(asset.get("scores"), dict) else {}
    transfer = numeric(scores.get("transferability"))
    evidence = numeric(scores.get("evidence_strength"))
    code = numeric(scores.get("code_readiness"))
    feasibility = numeric(scores.get("implementation_feasibility"))
    score = 0.40 * transfer + 0.25 * evidence + 0.20 * code + 0.15 * feasibility
    return round(score, 4)


def stable_asset_id(seed: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", seed.lower()).strip("-")[:56]
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
    return f"{slug}-{digest}" if slug else f"asset-{digest}"


def infer_asset_type(row: Dict[str, Any]) -> str:
    text = " ".join([
        clean_text(row.get("title")),
        clean_text(row.get("abstract")),
        clean_text(row.get("idea_core")),
        clean_text(row.get("transferable_mechanism")),
    ]).lower()
    if any(x in text for x in ["benchmark", "dataset", "corpus"]):
        return "dataset"
    if any(x in text for x in ["evaluation", "metric", "diagnostic"]):
        return "evaluation"
    if any(x in text for x in ["implementation", "system", "library"]):
        return "implementation"
    if any(x in text for x in ["method", "mechanism", "model", "architecture", "loss", "training"]):
        return "method"
    return "insight"


def row_to_asset(row: Dict[str, Any], profile_name: str = "") -> Dict[str, Any]:
    source = source_paper_from_row(row)
    title = source["title"] or "Untitled paper"
    abstract = source["abstract"]
    idea_core = first_text(row, ["idea_core", "theory_analysis_zh_md"], 420)
    transferable = first_text(row, ["transferable_mechanism", "theory_used_how_zh_md"], 420)
    fit_reason = first_text(row, ["fit_reason", "recommendation_zh"], 420)
    risk = first_text(row, ["risk_or_limitation", "deep_risk_reason_zh"], 420)

    challenge = first_text(row, ["challenge", "problem", "fit_reason"], 420)
    if not challenge:
        challenge = f"Identify whether the core idea in '{title}' can transfer beyond its original domain."

    solution = first_text(row, ["solution_pattern", "transferable_mechanism", "idea_core"], 420)
    if not solution:
        solution = idea_core or f"Use the paper's proposed mechanism from '{title}' as a transferable research pattern."

    mechanism = first_text(row, ["mechanism", "transferable_mechanism", "idea_core"], 420) or solution
    evidence = as_list(row.get("evidence"))
    if idea_core:
        evidence.append(f"Core idea: {idea_core}")
    if fit_reason:
        evidence.append(f"Fit reason: {fit_reason}")
    if not evidence and abstract:
        evidence.append(f"Abstract signal: {abstract[:420]}")

    limitations = as_list(row.get("limitations"))
    if risk:
        limitations.append(risk)

    scores = default_scores(row)
    asset = {
        "asset_id": stable_asset_id(paper_key(row)),
        "asset_type": infer_asset_type(row),
        "profile_name": clean_text(profile_name or row.get("profile_name")),
        "challenge": challenge,
        "why_it_is_hard": first_text(row, ["why_it_is_hard"], 420) or "The transfer conditions are not fully proven from metadata alone.",
        "solution_pattern": solution,
        "mechanism": mechanism,
        "required_assumptions": as_list(row.get("required_assumptions")) or [
            "The source paper's mechanism is separable from its original task setting.",
            "The target problem has compatible data, representation, or evaluation structure.",
        ],
        "transferable_to": as_list(row.get("transferable_to")) or as_list(row.get("rule_positive_hits")),
        "non_transferable_parts": as_list(row.get("non_transferable_parts")),
        "evidence": evidence,
        "limitations": limitations or ["Needs full-text and code review before being treated as implementation-ready."],
        "source_papers": [source],
        "code": default_code(row),
        "pdf": default_pdf(row),
        "scores": scores,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "raw": row,
    }
    asset["scores"]["asset_score"] = compute_asset_score(asset)
    return normalize_asset(asset)


def normalize_asset(asset: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(asset)
    out["asset_type"] = out.get("asset_type") if out.get("asset_type") in ASSET_TYPES else "insight"
    for key in [
        "required_assumptions",
        "transferable_to",
        "non_transferable_parts",
        "evidence",
        "limitations",
    ]:
        out[key] = as_list(out.get(key))
    if not isinstance(out.get("source_papers"), list):
        out["source_papers"] = []
    if not isinstance(out.get("code"), dict):
        out["code"] = default_code()
    if not isinstance(out.get("pdf"), dict):
        out["pdf"] = default_pdf()
    if not isinstance(out.get("scores"), dict):
        out["scores"] = default_scores()
    out["scores"]["asset_score"] = compute_asset_score(out)
    if not out.get("asset_id"):
        out["asset_id"] = stable_asset_id(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return out


def read_assets(path: str | Path) -> List[Dict[str, Any]]:
    return [normalize_asset(o) for o in read_jsonl(path)]


def write_assets(path: str | Path, assets: Iterable[Dict[str, Any]]) -> None:
    write_jsonl(path, (normalize_asset(o) for o in assets))
