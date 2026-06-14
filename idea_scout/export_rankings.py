from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from .io_utils import read_jsonl, write_csv
from .profile import load_profile


def f(obj: Dict[str, Any], key: str) -> float:
    try:
        return float(obj.get(key, 0) or 0)
    except Exception:
        return 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description="Export top-ranked papers to CSV.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--top-k", type=int, default=100)
    ap.add_argument("--sort-by", nargs="*", default=["rank_score", "score_overall_fit", "score_theory_novelty"])
    args = ap.parse_args()

    profile = load_profile(args.profile)
    rows = list(read_jsonl(args.input))
    rows.sort(key=lambda o: tuple(f(o, k) for k in args.sort_by), reverse=True)
    rows = rows[: args.top_k]

    dim_fields = [f"score_{d.key}" for d in profile.scoring_dimensions]
    fields = [
        "rank", "title", "venue", "year", "url", "pdf_url", "priority",
        "rank_score", "score_overall_fit", "score_theory_novelty",
        *dim_fields,
        "idea_core", "transferable_mechanism", "fit_reason", "risk_or_limitation",
    ]
    out_rows: List[Dict[str, Any]] = []
    for i, o in enumerate(rows, 1):
        row = dict(o)
        row["rank"] = i
        out_rows.append(row)
    write_csv(args.output, out_rows, fields)
    print(args.output)


if __name__ == "__main__":
    main()
