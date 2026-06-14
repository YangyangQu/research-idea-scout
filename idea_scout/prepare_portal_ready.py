from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from .io_utils import read_jsonl, write_jsonl


def prepare_one(o: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(o)
    out["final_score"] = out.get("rank_score", out.get("score_overall_fit", 0))
    out["theory_novelty"] = out.get("score_theory_novelty", 0)
    out["submission_value"] = out.get("score_overall_fit", 0)
    out["theory_explanation_zh"] = out.get("idea_core", "")
    out["recommendation_zh"] = out.get("transferable_mechanism", "")
    out["fit_reason"] = out.get("fit_reason", "")
    out["risk_or_limitation"] = out.get("risk_or_limitation", "")
    if isinstance(out.get("scores"), dict):
        out["scores_json"] = json.dumps(out["scores"], ensure_ascii=False)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert idea-score JSONL to a portal-friendly JSONL.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    rows = [prepare_one(o) for o in read_jsonl(args.input)]
    write_jsonl(args.output, rows)
    print(json.dumps({"input": args.input, "output": args.output, "rows": len(rows)}, indent=2))


if __name__ == "__main__":
    main()
