from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from .io_utils import clean_text, read_jsonl, write_jsonl

TRANSLATE_FIELDS = [
    "abstract",
    "idea_core",
    "transferable_mechanism",
    "fit_reason",
    "risk_or_limitation",
]


def extract_json_object(text: str) -> Dict[str, Any]:
    decoder = json.JSONDecoder()
    text = text.strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    raise ValueError("Could not extract JSON object from translation output")


def make_prompt(row: Dict[str, Any], abstract_max_chars: int) -> str:
    payload = {
        "title": clean_text(row.get("title"), 300),
        "abstract": clean_text(row.get("abstract"), abstract_max_chars),
        "idea_core": clean_text(row.get("idea_core"), 500),
        "transferable_mechanism": clean_text(row.get("transferable_mechanism"), 500),
        "fit_reason": clean_text(row.get("fit_reason"), 500),
        "risk_or_limitation": clean_text(row.get("risk_or_limitation"), 500),
    }
    return f"""
Translate selected paper-review fields into concise Simplified Chinese for a research portal.

Rules:
- Keep the paper title untranslated; do not output title_zh.
- Preserve technical terms such as ProAssist, egocentric, streaming, intervention timing when useful.
- Be faithful, not decorative.
- Return compact JSON only.

Input:
{json.dumps(payload, ensure_ascii=False)}

Return this JSON schema:
{{
  "abstract_zh": "...",
  "idea_core_zh": "...",
  "transferable_mechanism_zh": "...",
  "fit_reason_zh": "...",
  "risk_or_limitation_zh": "..."
}}
""".strip()


def run_codex(prompt: str, codex_cmd: str, timeout: int, max_retries: int = 2, retry_sleep: float = 5.0) -> Dict[str, Any]:
    cmd = shlex.split(codex_cmd)
    if cmd[-1] != "-":
        cmd.append("-")
    last_error = ""
    for attempt in range(1, max(1, max_retries) + 1):
        p = subprocess.run(
            cmd,
            input=prompt,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        if p.returncode == 0:
            return extract_json_object(p.stdout or p.stderr)
        last_error = p.stderr[-2000:] or f"codex returned {p.returncode}"
        if attempt < max(1, max_retries):
            print(f"[WARN] translate attempt={attempt}/{max_retries} failed; retrying", file=sys.stderr, flush=True)
            time.sleep(retry_sleep)
    raise RuntimeError(last_error)


def needs_translation(row: Dict[str, Any]) -> bool:
    return any(clean_text(row.get(field)) and not clean_text(row.get(f"{field}_zh")) for field in TRANSLATE_FIELDS)


def translate_rows(
    rows: List[Dict[str, Any]],
    codex_cmd: str,
    timeout: int,
    abstract_max_chars: int,
    limit: int,
    max_retries: int,
    retry_sleep: float,
) -> int:
    translated = 0
    for idx, row in enumerate(rows, 1):
        if limit and translated >= limit:
            break
        if not needs_translation(row):
            continue
        print(f"[TRANSLATE] {idx}/{len(rows)} {clean_text(row.get('title'), 100)}", flush=True)
        raw = run_codex(make_prompt(row, abstract_max_chars), codex_cmd, timeout, max_retries=max_retries, retry_sleep=retry_sleep)
        for field in TRANSLATE_FIELDS:
            key = f"{field}_zh"
            if raw.get(key):
                row[key] = clean_text(raw[key])
        translated += 1
    return translated


def main() -> None:
    ap = argparse.ArgumentParser(description="Add Simplified Chinese display fields to IdeaScout scored JSONL.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--codex-cmd", default="codex.cmd exec")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--abstract-max-chars", type=int, default=1600)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-retries", type=int, default=2)
    ap.add_argument("--retry-sleep", type=float, default=5.0)
    args = ap.parse_args()

    rows = list(read_jsonl(args.input))
    translated = translate_rows(
        rows,
        args.codex_cmd,
        args.timeout,
        args.abstract_max_chars,
        args.limit,
        args.max_retries,
        args.retry_sleep,
    )
    write_jsonl(args.output, rows)
    print(json.dumps({"input": args.input, "output": args.output, "rows": len(rows), "translated": translated}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
