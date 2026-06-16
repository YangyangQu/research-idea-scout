from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List

from .assets import compute_asset_score, read_assets, utc_now, write_assets
from .io_utils import clean_text


SECTION_HEADERS = [
    "abstract", "introduction", "related work", "background", "method", "methodology", "approach",
    "model", "experiments", "evaluation", "results", "discussion", "limitations", "conclusion", "references",
]


def text_path(asset: Dict[str, Any]) -> str:
    pdf = asset.get("pdf") if isinstance(asset.get("pdf"), dict) else {}
    if clean_text(pdf.get("text_path")):
        return clean_text(pdf.get("text_path"))
    for paper in asset.get("source_papers") or []:
        if isinstance(paper, dict) and clean_text(paper.get("text_path")):
            return clean_text(paper.get("text_path"))
    raw = asset.get("raw") if isinstance(asset.get("raw"), dict) else {}
    return clean_text(raw.get("text_path"))


def read_text(asset: Dict[str, Any], max_chars: int = 350_000) -> str:
    path = text_path(asset)
    if path and Path(path).exists():
        return Path(path).read_text(encoding="utf-8", errors="ignore")[:max_chars]
    raw = asset.get("raw") if isinstance(asset.get("raw"), dict) else {}
    return "\n".join([
        clean_text(raw.get("abstract")),
        clean_text(asset.get("challenge")),
        clean_text(asset.get("solution_pattern")),
        "\n".join(asset.get("evidence") or []),
    ])


def normalize_text(text: str) -> str:
    text = text.replace("\x0c", "\n").replace("\r", "\n")
    text = re.sub(r"-\n", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text


def section_regex(names: List[str]) -> re.Pattern[str]:
    name_alt = "|".join(re.escape(n) for n in names)
    header_alt = "|".join(re.escape(h) for h in SECTION_HEADERS)
    return re.compile(
        rf"(?is)(?:^|\n)\s*(?:\d+(?:\.\d+)*\.?\s*)?(?:{name_alt})\s*(?:\n|$)(.*?)(?=\n\s*(?:\d+(?:\.\d+)*\.?\s*)?(?:{header_alt})\s*(?:\n|$)|\Z)"
    )


def extract_section(text: str, names: List[str], max_chars: int = 7000) -> str:
    normalized = normalize_text(text)
    pattern = section_regex(names)
    match = pattern.search(normalized)
    if not match:
        return ""
    return clean_text(match.group(1), max_chars)


def clean_sentence_text(text: str) -> str:
    text = text.replace("\x0c", " ").replace("\r", " ")
    text = re.sub(r"-\s+(?=[a-z])", "", text)
    text = re.sub(r"\b(?:Figure|Fig\.|Table)\s+\d+[^.]*\.", " ", text, flags=re.I)
    text = re.sub(r"\b[A-Za-z0-9]\d\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def sentences(text: str) -> List[str]:
    compact = clean_sentence_text(text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", compact)
    out = []
    for part in parts:
        part = part.strip()
        if len(part) < 35:
            continue
        low = part.lower()
        if any(x in low for x in ["@", "university", "copyright", "proceedings", "open access version"]):
            continue
        out.append(part)
    return out


def best_sentence(text: str, keywords: List[str], fallback: str = "") -> str:
    scored = []
    for sent in sentences(text):
        low = sent.lower()
        score = sum(1 for k in keywords if k in low)
        if score:
            scored.append((score, min(len(sent), 500), sent))
    if scored:
        scored.sort(key=lambda x: (x[0], -abs(x[1] - 220)), reverse=True)
        return clean_text(scored[0][2], 420)
    return clean_text(fallback, 420)


def ranked_sentence(text: str, positive: List[str], negative: List[str] | None = None, exclude: str = "") -> str:
    negative = negative or []
    exclude_norm = clean_sentence_text(exclude).lower()
    scored = []
    for idx, sent in enumerate(sentences(text)):
        low = sent.lower()
        if exclude_norm and clean_sentence_text(sent).lower() == exclude_norm:
            continue
        score = sum(2 for k in positive if k in low) - sum(1 for k in negative if k in low)
        if "?" in sent and any(k in positive for k in ["question", "relationship"]):
            score += 1
        if score > 0:
            scored.append((score, -idx, sent))
    if scored:
        scored.sort(reverse=True)
        return clean_text(scored[0][2], 420)
    return ""


def first_sentence(text: str, exclude: str = "") -> str:
    exclude_norm = clean_sentence_text(exclude).lower()
    for sent in sentences(text):
        if exclude_norm and clean_sentence_text(sent).lower() == exclude_norm:
            continue
        return clean_text(sent, 420)
    return ""


def source_title(asset: Dict[str, Any]) -> str:
    source = (asset.get("source_papers") or [{}])[0]
    raw = asset.get("raw") if isinstance(asset.get("raw"), dict) else {}
    return clean_text(source.get("title") or raw.get("title"), 300)


def source_abstract(asset: Dict[str, Any]) -> str:
    source = (asset.get("source_papers") or [{}])[0]
    raw = asset.get("raw") if isinstance(asset.get("raw"), dict) else {}
    return clean_text(source.get("abstract") or raw.get("abstract"), 2400)


def first_method_sentence(method_text: str, abstract: str) -> str:
    method_pos = [
        "we propose", "we present", "we introduce", "we develop", "we model", "we use", "our method",
        "our approach", "instead", "by ", "which ", "connects", "generates", "learns", "builds",
    ]
    method_neg = ["recent work", "challenge", "problem", "hard", "difficult", "expensive", "requires", "avoid", "need for"]
    sent = ranked_sentence(abstract, method_pos, method_neg)
    if sent:
        return sent
    sent = ranked_sentence(method_text, method_pos, method_neg)
    if sent:
        return sent
    return first_sentence(abstract or method_text)


def challenge_sentence(intro_text: str, abstract: str, title: str, exclude: str = "") -> str:
    problem_pos = [
        "problem", "challenge", "hard", "difficult", "costly", "expensive", "limited", "requires", "lack",
        "bottleneck", "avoid", "need for", "without", "relationship", "unrelated", "if ", "whether", "question",
        "recent work", "shown that",
    ]
    method_neg = ["we propose", "we present", "we introduce", "our method", "our approach", "we develop"]
    sent = ranked_sentence(abstract, problem_pos, method_neg, exclude=exclude)
    if sent:
        return sent
    sent = first_sentence(abstract, exclude=exclude)
    if sent:
        return sent
    sent = ranked_sentence(intro_text, problem_pos, method_neg, exclude=exclude)
    if sent:
        return sent
    return f"Understand the problem setting addressed by '{title}' and identify when its core mechanism transfers."


def reusable_insight(challenge: str, method: str) -> str:
    challenge = clean_sentence_text(clean_text(challenge, 260))
    method = clean_sentence_text(clean_text(method, 300))
    if not method:
        return "Reusable insight: keep the paper as a candidate asset, but manually inspect the method before transfer."
    if challenge:
        return f"Reusable insight: the transferable pattern is to address '{challenge}' by applying '{method}'."
    return f"Reusable insight: test whether the method pattern '{method}' transfers to problems with a similar bottleneck."


def enhance_one(asset: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(asset)
    text = read_text(out)
    abstract = source_abstract(out)
    title = source_title(out)
    intro = extract_section(text, ["introduction"], 9000)
    method = extract_section(text, ["method", "methodology", "approach", "model", "proposed method"], 9000)
    if not method:
        pdf = out.get("pdf") if isinstance(out.get("pdf"), dict) else {}
        sections = pdf.get("extracted_sections") if isinstance(pdf.get("extracted_sections"), dict) else {}
        method = clean_text(sections.get("method"), 9000)

    method_sent = first_method_sentence(method, abstract)
    challenge = challenge_sentence(intro, abstract, title, exclude=method_sent)
    insight = reusable_insight(challenge, method_sent)
    why_hard = best_sentence(abstract, ["hard", "difficult", "costly", "expensive", "requires", "limited", "bottleneck"], "")
    if not why_hard:
        why_hard = best_sentence(intro, ["hard", "difficult", "costly", "expensive", "requires", "limited", "bottleneck"], out.get("why_it_is_hard", ""))

    out["insight"] = {
        "challenge": challenge,
        "method": method_sent,
        "reusable_insight": insight,
        "why_it_is_hard": why_hard or out.get("why_it_is_hard", ""),
        "method_section_excerpt": clean_text(method, 1600),
        "introduction_excerpt": clean_text(intro, 1200),
        "extraction_status": "full_text" if text_path(out) else "fallback",
    }
    if challenge:
        out["challenge"] = challenge
    if method_sent:
        out["solution_pattern"] = method_sent
        out["mechanism"] = method_sent
    if why_hard:
        out["why_it_is_hard"] = why_hard
    evidence = list(out.get("evidence") or [])
    if insight not in evidence:
        evidence.insert(0, insight)
    if method_sent:
        method_evidence = f"Method insight: {method_sent}"
        if method_evidence not in evidence:
            evidence.insert(1, method_evidence)
    out["evidence"] = evidence[:12]
    out.setdefault("scores", {})["evidence_strength"] = max(float(out.get("scores", {}).get("evidence_strength", 0) or 0), 7.0 if text_path(out) else 4.0)
    out["scores"]["asset_score"] = compute_asset_score(out)
    out["updated_at"] = utc_now()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Enhance assets with full-text challenge -> method -> reusable insight fields.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    assets = [enhance_one(asset) for asset in read_assets(args.input)]
    write_assets(args.output, assets)
    status: Dict[str, int] = {}
    for asset in assets:
        key = ((asset.get("insight") or {}).get("extraction_status") or "unknown") if isinstance(asset.get("insight"), dict) else "missing"
        status[key] = status.get(key, 0) + 1
    print(json.dumps({"input": args.input, "output": args.output, "assets": len(assets), "insight_status": status}, indent=2))


if __name__ == "__main__":
    main()
