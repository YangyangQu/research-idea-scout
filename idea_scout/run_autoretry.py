from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import List

from .io_utils import count_jsonl, norm_year, read_jsonl


def count_target(input_path: Path, years: List[int], top_k: int) -> int:
    rows = list(read_jsonl(input_path))
    if years:
        ys = set(years)
        rows = [r for r in rows if norm_year(r.get("year")) in ys]
    if top_k and top_k > 0:
        rows = rows[:top_k]
    return len(rows)


def has_quota_error(text: str) -> bool:
    t = text.lower()
    return any(x in t for x in ["usage limit", "rate limit", "quota", "too many requests", "try again later"])


def has_auth_error(text: str) -> bool:
    t = text.lower()
    return any(x in t for x in [
        "401 unauthorized",
        "app_session_terminated",
        "token_revoked",
        "token_invalidated",
        "refresh_token_invalidated",
        "your session has ended",
        "please log in again",
        "failed to refresh token",
        "access token could not be refreshed",
        "refresh token was revoked",
    ])


def main() -> None:
    ap = argparse.ArgumentParser(description="Auto-retry wrapper for Codex idea scoring.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--failures-output", default="")
    ap.add_argument("--years", nargs="*", type=int, default=[])
    ap.add_argument("--top-k", type=int, default=0)
    ap.add_argument("--codex-cmd", default="codex exec")
    ap.add_argument("--batch-size", type=int, default=1)
    ap.add_argument("--sleep-between-rounds", type=int, default=2)
    ap.add_argument("--sleep-on-quota", type=int, default=3600)
    ap.add_argument("--sleep-on-error", type=int, default=600)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--max-retries", type=int, default=2)
    ap.add_argument("--retry-sleep", type=int, default=5)
    ap.add_argument("--abstract-max-chars", type=int, default=3000)
    ap.add_argument("--max-rounds", type=int, default=0)
    args = ap.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    target_total = count_target(input_path, args.years, args.top_k)
    print(f"[INIT] target_total={target_total} output={output_path}", flush=True)

    round_id = 0
    while True:
        round_id += 1
        if args.max_rounds and round_id > args.max_rounds:
            print(f"[STOP] reached max_rounds={args.max_rounds}", flush=True)
            break
        before = count_jsonl(output_path)
        if target_total > 0 and before >= target_total:
            print(f"[DONE] all done: {before}/{target_total}", flush=True)
            break

        print("=" * 100, flush=True)
        print(f"[ROUND {round_id}] before={before}/{target_total} batch={args.batch_size}", flush=True)
        cmd = [
            sys.executable,
            "-m", "idea_scout.codex_idea_score",
            "--input", args.input,
            "--profile", args.profile,
            "--output", args.output,
            "--top-k", str(args.top_k),
            "--codex-cmd", args.codex_cmd,
            "--max-new-items", str(args.batch_size),
            "--timeout", str(args.timeout),
            "--max-retries", str(args.max_retries),
            "--retry-sleep", str(args.retry_sleep),
            "--abstract-max-chars", str(args.abstract_max_chars),
            "--resume",
        ]
        if args.failures_output:
            cmd += ["--failures-output", args.failures_output]
        if args.years:
            cmd += ["--years"] + [str(y) for y in args.years]

        print("[CMD]", " ".join(cmd), flush=True)
        p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        combined = (p.stdout or "") + "\n" + (p.stderr or "")
        if p.stdout:
            print(p.stdout, end="" if p.stdout.endswith("\n") else "\n", flush=True)
        if p.stderr:
            print(p.stderr, end="" if p.stderr.endswith("\n") else "\n", file=sys.stderr, flush=True)

        after = count_jsonl(output_path)
        added = after - before
        print(f"[ROUND RESULT] returncode={p.returncode} newly_added={added} total_done={after}/{target_total}", flush=True)
        if added > 0:
            time.sleep(args.sleep_between_rounds)
            continue
        if has_auth_error(combined):
            print("[STOP_AUTH] Codex auth/session problem. Run: codex logout && codex login --device-auth", flush=True)
            sys.exit(2)
        if has_quota_error(combined):
            print(f"[SLEEP_QUOTA] sleeping {args.sleep_on_quota}s", flush=True)
            time.sleep(args.sleep_on_quota)
            continue
        print(f"[SLEEP_ERROR] no progress. sleeping {args.sleep_on_error}s", flush=True)
        time.sleep(args.sleep_on_error)


if __name__ == "__main__":
    main()
