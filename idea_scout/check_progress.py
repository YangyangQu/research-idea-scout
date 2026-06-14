from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from .io_utils import count_jsonl, read_jsonl


def avg(rows, key):
    vals = []
    for o in rows:
        try:
            vals.append(float(o.get(key, 0) or 0))
        except Exception:
            pass
    return sum(vals) / len(vals) if vals else 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description="Check JSONL scoring progress and score distribution.")
    ap.add_argument("--output", required=True)
    ap.add_argument("--target-total", type=int, default=0)
    args = ap.parse_args()

    p = Path(args.output)
    rows = list(read_jsonl(p)) if p.exists() else []
    total = len(rows)
    suffix = f" / {args.target_total}" if args.target_total else ""
    print(f"done = {total}{suffix}")
    if not rows:
        return
    print("priority:", dict(Counter(o.get("priority", "UNKNOWN") for o in rows)))
    print("venue_year:", dict(Counter((o.get("venue"), o.get("year")) for o in rows).most_common(20)))
    for k in ["rank_score", "score_overall_fit", "score_theory_novelty"]:
        print(k, round(avg(rows, k), 3))
    print("last item:", rows[-1].get("title"))


if __name__ == "__main__":
    main()
