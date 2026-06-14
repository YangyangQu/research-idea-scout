from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from .io_utils import append_jsonl, clean_text, load_done_keys, norm_year, paper_key, read_jsonl
from .profile import Profile, dimension_keys, load_profile, profile_to_prompt_block


def clamp_score(x: Any) -> float:
    try:
        v = float(x)
    except Exception:
        return 0.0
    return round(max(0.0, min(10.0, v)), 4)


def extract_json_object(text: str) -> Dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    raise ValueError("Could not extract JSON object from Codex output")


def make_prompt(paper: Dict[str, Any], profile: Profile, abstract_max_chars: int) -> str:
    compact = {
        "title": clean_text(paper.get("title"), 650),
        "abstract": clean_text(paper.get("abstract"), abstract_max_chars),
        "venue": paper.get("venue"),
        "year": paper.get("year"),
        "url": paper.get("url") or paper.get("pdf_url"),
        "rule_score": paper.get("rule_score") or paper.get("theory_signal_score"),
        "rule_positive_hits": paper.get("rule_positive_hits") or paper.get("theory_family_hits"),
        "rule_negative_hits": paper.get("rule_negative_hits") or paper.get("negative_hits"),
    }

    keys = dimension_keys(profile)
    scores_schema = "\n".join(f'    "{k}": 0,' for k in keys)

    return f"""
You are helping a researcher screen papers for their own research direction.

CRITICAL INSTRUCTIONS:
- Do NOT score by keyword overlap only.
- First infer the paper's core idea from the title and abstract.
- Then judge whether this idea can transfer to the user's research profile.
- The paper may come from a different field. Reward transferable mechanisms, not surface topic similarity.
- Return compact JSON only. No markdown.

{profile_to_prompt_block(profile)}

Paper:
{json.dumps(compact, ensure_ascii=False)}

Return ONLY one valid compact JSON object with this schema:
{{
  "is_suitable": true,
  "priority": "keep|maybe|drop",
  "idea_core": "one short sentence describing the paper's core idea",
  "transferable_mechanism": "one short sentence explaining the transferable mechanism",
  "fit_reason": "one short sentence explaining why it fits or does not fit the profile",
  "risk_or_limitation": "one short sentence naming the main risk or limitation",
  "score_overall_fit": 0,
  "score_theory_novelty": 0,
  "scores": {{
{scores_schema.rstrip(',')}
  }}
}}

Scoring rules:
- Use 0 to 10.
- 8-10: strong fit, worth detailed reading.
- 5-7: possible fit, keep for later review.
- 0-4: weak fit.
- score_overall_fit should reflect real transfer potential to the user's profile, not keyword overlap.
""".strip()


def run_codex(prompt: str, codex_cmd: str, timeout: int) -> Tuple[int, str, str]:
    cmd = shlex.split(codex_cmd)
    if not cmd:
        raise ValueError("Empty codex command")
    if cmd[-1] != "-":
        cmd.append("-")
    p = subprocess.run(
        cmd,
        input=prompt,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    return p.returncode, p.stdout or "", p.stderr or ""


def normalize_result(raw: Dict[str, Any], profile: Profile) -> Dict[str, Any]:
    out = dict(raw)
    out["is_suitable"] = bool(out.get("is_suitable", False))
    priority = str(out.get("priority", "maybe")).lower().strip()
    out["priority"] = priority if priority in {"keep", "maybe", "drop"} else "maybe"
    out["score_overall_fit"] = clamp_score(out.get("score_overall_fit"))
    out["score_theory_novelty"] = clamp_score(out.get("score_theory_novelty"))

    scores = out.get("scores") if isinstance(out.get("scores"), dict) else {}
    norm_scores = {}
    weights = {}
    for d in profile.scoring_dimensions:
        norm_scores[d.key] = clamp_score(scores.get(d.key, out.get(d.key, 0)))
        weights[d.key] = float(d.weight)
    out["scores"] = norm_scores

    denom = sum(max(w, 0.0) for w in weights.values()) or 1.0
    weighted_profile_score = sum(norm_scores[k] * max(weights[k], 0.0) for k in norm_scores) / denom
    out["rank_score"] = round(
        0.45 * out["score_overall_fit"]
        + 0.40 * weighted_profile_score
        + 0.15 * out["score_theory_novelty"],
        4,
    )

    for k in ["idea_core", "transferable_mechanism", "fit_reason", "risk_or_limitation"]:
        out[k] = clean_text(out.get(k), 240)

    # Flatten dimension scores for CSV, databases, and simpler browsing.
    for k, v in norm_scores.items():
        out[f"score_{k}"] = v

    return out


def process_one(
    paper: Dict[str, Any],
    profile: Profile,
    codex_cmd: str,
    timeout: int,
    max_retries: int,
    retry_sleep: int,
    abstract_max_chars: int,
) -> Dict[str, Any]:
    prompt = make_prompt(paper, profile, abstract_max_chars)
    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            rc, stdout, stderr = run_codex(prompt, codex_cmd, timeout)
            if rc != 0:
                last_error = f"returncode={rc}; stderr={stderr[-2500:]}"
                raise RuntimeError(last_error)
            raw = extract_json_object(stdout.strip() or stderr.strip())
            result = normalize_result(raw, profile)
            out = dict(paper)
            out.update(result)
            out["profile_name"] = profile.name
            out["analysis_tier"] = "idea_score"
            out["idea_score_model"] = codex_cmd
            out["idea_score_ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
            return out
        except Exception as e:
            last_error = str(e)
            print(f"[WARN] attempt={attempt}/{max_retries} failed: {last_error}", file=sys.stderr, flush=True)
            if attempt < max_retries:
                time.sleep(retry_sleep)
    raise RuntimeError(last_error)


def main() -> None:
    ap = argparse.ArgumentParser(description="Use Codex to score paper ideas against a user-defined research profile.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--failures-output", default="")
    ap.add_argument("--years", nargs="*", type=int, default=[])
    ap.add_argument("--top-k", type=int, default=0)
    ap.add_argument("--codex-cmd", default="codex exec")
    ap.add_argument("--resume", action="store_true", default=True)
    ap.add_argument("--no-resume", action="store_false", dest="resume")
    ap.add_argument("--max-new-items", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--max-retries", type=int, default=2)
    ap.add_argument("--retry-sleep", type=int, default=5)
    ap.add_argument("--abstract-max-chars", type=int, default=3000)
    args = ap.parse_args()

    profile = load_profile(args.profile)
    rows = list(read_jsonl(args.input))
    if args.years:
        ys = set(args.years)
        rows = [r for r in rows if norm_year(r.get("year")) in ys]
    if args.top_k and args.top_k > 0:
        rows = rows[: args.top_k]

    output_path = Path(args.output)
    failure_path = Path(args.failures_output) if args.failures_output else None
    done = load_done_keys(output_path) if args.resume else set()

    added = 0
    for idx, paper in enumerate(rows, 1):
        key = paper_key(paper)
        if key in done:
            print(f"[SKIP] {idx}/{len(rows)} already done: {clean_text(paper.get('title'), 100)}", flush=True)
            continue
        if args.max_new_items and added >= args.max_new_items:
            print(f"[STOP] reached max_new_items={args.max_new_items}", flush=True)
            break
        print(f"[RUN ] {idx}/{len(rows)} [{paper.get('venue')} {paper.get('year')}] {clean_text(paper.get('title'), 120)}", flush=True)
        try:
            result = process_one(
                paper=paper,
                profile=profile,
                codex_cmd=args.codex_cmd,
                timeout=args.timeout,
                max_retries=args.max_retries,
                retry_sleep=args.retry_sleep,
                abstract_max_chars=args.abstract_max_chars,
            )
            append_jsonl(output_path, result)
            done.add(key)
            added += 1
            print(
                f"[OK  ] added={added} rank={result.get('rank_score')} "
                f"overall={result.get('score_overall_fit')} priority={result.get('priority')}",
                flush=True,
            )
        except Exception as e:
            print(f"[FAIL] {idx}/{len(rows)} {clean_text(paper.get('title'), 100)} :: {e}", file=sys.stderr, flush=True)
            if failure_path:
                fail = dict(paper)
                fail["failure_reason"] = str(e)
                fail["failure_ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
                append_jsonl(failure_path, fail)
    print(f"[DONE] added={added} output={output_path}", flush=True)


if __name__ == "__main__":
    main()
