from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .io_utils import clean_text, paper_key, read_jsonl, write_jsonl
from .profile import Profile, load_profile


def text_for_paper(obj: Dict[str, Any]) -> str:
    return " ".join([
        clean_text(obj.get("title")),
        clean_text(obj.get("abstract")),
        clean_text(obj.get("keywords")),
    ]).lower()


def keyword_score(text: str, keywords: List[str]) -> tuple[float, List[str]]:
    hits = []
    score = 0.0
    for kw in keywords:
        k = kw.lower().strip()
        if not k:
            continue
        if k in text:
            hits.append(kw)
            score += 1.0 if " " not in k else 1.5
    return score, hits


def score_rule_based(obj: Dict[str, Any], profile: Profile) -> Dict[str, Any]:
    text = text_for_paper(obj)
    pos_score, pos_hits = keyword_score(text, profile.positive_keywords)
    neg_score, neg_hits = keyword_score(text, profile.negative_keywords)
    final = pos_score - 1.25 * neg_score
    return {
        "rule_score": round(final, 4),
        "rule_positive_score": round(pos_score, 4),
        "rule_negative_score": round(neg_score, 4),
        "rule_positive_hits": pos_hits,
        "rule_negative_hits": neg_hits,
    }


def filter_rows(
    rows: Iterable[Dict[str, Any]],
    profile: Profile,
    years: set[int] | None = None,
    target_total: int = 0,
    min_score: float = 1.0,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    seen = set()
    scored = []
    rejected = []

    for obj in rows:
        if years:
            try:
                if int(obj.get("year")) not in years:
                    continue
            except Exception:
                continue
        key = paper_key(obj)
        if key in seen:
            continue
        seen.add(key)

        extra = score_rule_based(obj, profile)
        out = dict(obj)
        out.update(extra)
        out["profile_name"] = profile.name

        if out["rule_score"] >= min_score:
            scored.append(out)
        else:
            rejected.append(out)

    scored.sort(key=lambda o: (float(o.get("rule_score", 0)), str(o.get("title", ""))), reverse=True)
    if target_total and target_total > 0:
        keep = scored[:target_total]
        rejected = scored[target_total:] + rejected
    else:
        keep = scored

    summary = {
        "profile": profile.name,
        "kept": len(keep),
        "rejected": len(rejected),
        "kept_by_venue_year": {f"{k[0]}::{k[1]}": v for k, v in Counter((o.get("venue"), o.get("year")) for o in keep).items()},
    }
    return keep, rejected, summary


def main() -> None:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Rule-based filtering before LLM scoring.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--output-keep", required=True)
    ap.add_argument("--output-reject", required=True)
    ap.add_argument("--output-summary", required=True)
    ap.add_argument("--years", nargs="*", type=int, default=[])
    ap.add_argument("--target-total", type=int, default=0)
    ap.add_argument("--min-score", type=float, default=1.0)
    args = ap.parse_args()

    profile = load_profile(args.profile)
    keep, reject, summary = filter_rows(
        read_jsonl(args.input),
        profile,
        years=set(args.years) if args.years else None,
        target_total=args.target_total,
        min_score=args.min_score,
    )
    write_jsonl(args.output_keep, keep)
    write_jsonl(args.output_reject, reject)
    Path(args.output_summary).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
