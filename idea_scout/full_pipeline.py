from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Sequence, Tuple

import yaml

from .auto_collect import default_paths, slugify
from .profile import Profile, load_profile


CommandRunner = Callable[[List[str], Path], None]


PROFILE_LIST_FIELDS = [
    "target_tasks",
    "prefer",
    "downweight",
    "positive_keywords",
    "negative_keywords",
]

TOPIC_ANCHOR_FIELDS = ["high_value", "required_any", "broad_ai", "off_topic_domains"]


def default_codex_cmd() -> str:
    return "codex.cmd exec" if os.name == "nt" else "codex exec"


def description_hash(description: str) -> str:
    return hashlib.sha1(description.encode("utf-8")).hexdigest()[:8]


def generated_profile_name(description: str) -> str:
    return f"generated_ai_profile_{description_hash(description)}"


def sanitize_key(text: Any, fallback: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9]+", "_", str(text or "")).strip("_").lower()
    return key or fallback


def stringify_list_item(value: Any) -> str:
    if isinstance(value, dict):
        name = value.get("name") or value.get("key") or value.get("title")
        desc = value.get("description") or value.get("detail") or value.get("value")
        if name and desc:
            return f"{name}: {desc}".strip()
        if name:
            return str(name).strip()
        if desc:
            return str(desc).strip()
    return str(value).strip()


def as_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for s in [stringify_list_item(value)] if s]
    if isinstance(value, Iterable):
        return [s for s in (stringify_list_item(x) for x in value) if s]
    return [stringify_list_item(value)]


def normalize_profile_dict(raw: Dict[str, Any], description: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = dict(raw)
    out["name"] = sanitize_key(out.get("name"), generated_profile_name(description))
    out["language"] = str(out.get("language") or "English")
    out["description"] = str(out.get("description") or description or "")

    for field_name in PROFILE_LIST_FIELDS:
        out[field_name] = as_string_list(out.get(field_name))

    anchors = out.get("topic_anchors")
    if isinstance(anchors, dict):
        out["topic_anchors"] = {
            key: as_string_list(anchors.get(key))
            for key in TOPIC_ANCHOR_FIELDS
            if as_string_list(anchors.get(key))
        }
    else:
        out["topic_anchors"] = {}

    dims: List[Dict[str, Any]] = []
    for idx, item in enumerate(out.get("scoring_dimensions") or [], 1):
        if isinstance(item, str):
            key = sanitize_key(item, f"dimension_{idx}")
            dims.append({"key": key, "description": item, "weight": 1.0})
            continue
        if not isinstance(item, dict):
            continue
        key = sanitize_key(item.get("key") or item.get("name") or item.get("description"), f"dimension_{idx}")
        try:
            weight = float(item.get("weight", 1.0))
        except Exception:
            weight = 1.0
        dims.append(
            {
                "key": key,
                "description": str(item.get("description") or item.get("name") or key),
                "weight": weight,
            }
        )
    out["scoring_dimensions"] = dims
    if not out["scoring_dimensions"]:
        raise ValueError("Generated profile must include at least one scoring dimension.")
    return out


def profile_yaml_from_dict(raw: Dict[str, Any], description: str = "") -> str:
    normalized = normalize_profile_dict(raw, description)
    return yaml.safe_dump(normalized, allow_unicode=True, sort_keys=False)


def _yaml_candidates(text: str) -> Iterable[str]:
    for match in re.finditer(r"```(?:yaml|yml)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL):
        yield match.group(1).strip()
    stripped = text.strip()
    if stripped:
        yield stripped
    start = re.search(r"(?m)^name\s*:", text)
    if start:
        yield text[start.start() :].strip()


def extract_profile_yaml(text: str, description: str = "") -> str:
    last_error = ""
    for candidate in _yaml_candidates(text):
        try:
            raw = yaml.safe_load(candidate)
            if isinstance(raw, dict):
                return profile_yaml_from_dict(raw, description)
        except Exception as exc:
            last_error = str(exc)
            continue
    raise ValueError(f"Could not extract a valid profile YAML mapping. {last_error}".strip())


def extracted_phrases(description: str) -> List[str]:
    phrases: List[str] = []
    for chunk in re.findall(r"[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z][A-Za-z0-9-]*){0,5}", description):
        phrase = re.sub(r"\s+", " ", chunk).strip().lower()
        if len(phrase) >= 3 and phrase not in phrases:
            phrases.append(phrase)
    return phrases[:8]


def fallback_profile_yaml(description: str, dynamic_anchors: bool = True) -> str:
    lowered = description.lower()
    assistant_like = any(
        marker in lowered
        for marker in [
            "assistant",
            "assist",
            "egocentric",
            "proactive",
            "procedural",
            "intervention",
            "主动",
            "介入",
            "恢复",
        ]
    )
    phrases = extracted_phrases(description)
    if assistant_like:
        positive = [
            "proactive assistance",
            "proactive intervention",
            "egocentric video",
            "streaming video",
            "procedural assistance",
            "intervention timing",
            "task monitoring",
            "task progress",
            "mistake detection",
            "recovery tracking",
            "grounded correction",
            "human AI collaboration",
        ]
        target_tasks = [
            "Find methods that improve when an AI assistant should proactively intervene.",
            "Screen for online task monitoring, mistake diagnosis, recovery tracking, and grounded feedback mechanisms.",
            "Prefer reusable AI mechanisms that can transfer to streaming procedural assistance.",
        ]
        dims = [
            ("intervention_timing_value", "Helps decide when to speak, wait, or intervene in an online assistance setting.", 2.0),
            ("procedural_state_modeling", "Models task progress, task state, valid next actions, or action-effect deviations.", 1.6),
            ("diagnosis_to_assistance", "Connects error or risk diagnosis to useful corrections, feedback, or follow-up actions.", 1.6),
            ("streaming_feasibility", "Looks practical for low-latency or incremental AI systems.", 1.2),
            ("transferable_mechanism", "Contains a mechanism that can transfer beyond the paper's original task.", 1.4),
            ("evaluation_value", "Suggests metrics for timing, recovery, grounding, usefulness, or interruption cost.", 1.0),
        ]
        topic_anchors = {
            "high_value": [
                "proactive assistance",
                "procedural state",
                "step completion",
                "intervention timing",
                "mistake detection",
                "recovery tracking",
            ],
            "required_any": ["assistant", "procedural", "egocentric", "workflow", "task progress"],
            "broad_ai": ["multimodal", "video", "large language model", "wearable"],
            "off_topic_domains": ["public health", "clinical", "education", "agriculture"],
        }
    else:
        positive = [
            "machine learning",
            "artificial intelligence",
            "representation learning",
            "multimodal learning",
            "foundation model",
            "retrieval",
            "reasoning",
            "alignment",
            "evaluation",
            "benchmarking",
        ]
        target_tasks = [
            "Find AI papers whose core mechanisms can transfer to the user's research direction.",
            "Screen for reusable methods, objectives, representations, data recipes, and evaluation protocols.",
            "Prefer feasible ideas that can become experiments rather than broad surveys.",
        ]
        dims = [
            ("transferability_to_direction", "Whether the paper's central idea can transfer to the described research direction.", 2.0),
            ("method_novelty", "Whether the method or theory contribution is genuinely interesting.", 1.4),
            ("mechanism_clarity", "Whether the paper exposes a reusable mechanism rather than only reporting a result.", 1.3),
            ("implementation_feasibility", "Whether the idea looks practical to reproduce or adapt.", 1.1),
            ("evaluation_value", "Whether the paper suggests useful metrics, diagnostics, or protocols.", 1.0),
        ]
        topic_anchors = {
            "high_value": [
                "reusable mechanism",
                "representation learning",
                "reasoning",
                "evaluation protocol",
                "agent",
                "retrieval",
            ],
            "required_any": ["artificial intelligence", "machine learning", "foundation model", "agent"],
            "broad_ai": ["deep learning", "transformer", "multimodal", "large language model"],
            "off_topic_domains": ["clinical", "public health", "education"],
        }

    raw = {
        "name": generated_profile_name(description),
        "language": "English",
        "description": description,
        "target_tasks": target_tasks,
        "prefer": [
            "Transferable mechanisms rather than surface keyword similarity.",
            "Papers with reusable modeling ideas, objectives, representations, policies, or evaluation protocols.",
            "Recent AI papers with enough methodological detail to inspire experiments.",
        ],
        "downweight": [
            "Survey papers without a new reusable mechanism.",
            "Dataset-only or benchmark-only papers.",
            "Pure application papers without a method that can transfer.",
        ],
        "positive_keywords": list(dict.fromkeys([*phrases, *positive])),
        "negative_keywords": [
            "survey",
            "dataset only",
            "benchmark only",
            "leaderboard",
            "position paper",
            "application only",
        ],
        "scoring_dimensions": [
            {"key": key, "description": desc, "weight": weight}
            for key, desc, weight in dims
        ],
    }
    if dynamic_anchors:
        raw["topic_anchors"] = topic_anchors
    return profile_yaml_from_dict(raw, description)


def build_profile_prompt(description: str, dynamic_anchors: bool = True) -> str:
    topic_anchor_schema = ""
    if dynamic_anchors:
        topic_anchor_schema = """
- Include topic_anchors to guide the cheap prefilter before LLM scoring.
- topic_anchors.high_value: 4-10 precise phrases that should strongly indicate relevance.
- topic_anchors.required_any: 3-8 core domain phrases; papers with only broad AI terms but none of these should be downweighted.
- topic_anchors.broad_ai: 3-8 broad method/context phrases that help retrieval but are not enough by themselves.
- topic_anchors.off_topic_domains: 3-8 domains likely to create false positives for this request.
""".rstrip()
    topic_anchor_yaml = ""
    if dynamic_anchors:
        topic_anchor_yaml = """
topic_anchors:
  high_value:
    - ...
  required_any:
    - ...
  broad_ai:
    - ...
  off_topic_domains:
    - ...
""".rstrip()
    return f"""
You are configuring an automated AI-paper screening pipeline.

Given the user's research direction, produce one YAML profile for IdeaScout.

Rules:
- Output YAML only. No markdown fence, no explanation.
- The profile content should be in English even if the user wrote another language, because paper search APIs work best with English phrases.
- name must be short lowercase ASCII snake_case.
- Use 2-4 specific target_tasks.
- Use 8-16 positive_keywords with search-friendly phrases, not only broad terms.
- Use 4-10 negative_keywords.
- Use 6-10 scoring_dimensions. Each dimension needs key, description, and weight.
- Dimensions should reward transferable mechanisms, implementation feasibility, evaluation value, and fit to the user's direction.
- Avoid over-collecting broad generic AI papers; make the profile focused enough to save LLM scoring tokens.
{topic_anchor_schema}

Required YAML schema:
name: short_snake_case
language: English
description: >
  ...
target_tasks:
  - ...
prefer:
  - ...
downweight:
  - ...
positive_keywords:
  - ...
negative_keywords:
  - ...
scoring_dimensions:
  - key: ...
    description: ...
    weight: 1.0
{topic_anchor_yaml}

User research direction:
{description}
""".strip()


def run_codex_text(prompt: str, codex_cmd: str, timeout: int) -> str:
    cmd = shlex.split(codex_cmd)
    if not cmd:
        raise ValueError("Empty codex command")
    if cmd[-1] != "-":
        cmd.append("-")
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
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-2000:] or f"codex returned {p.returncode}")
    return p.stdout or p.stderr or ""


def generate_profile_yaml(
    description: str,
    codex_cmd: str,
    timeout: int,
    allow_fallback: bool = True,
    dynamic_anchors: bool = True,
) -> Tuple[str, str]:
    try:
        output = run_codex_text(build_profile_prompt(description, dynamic_anchors=dynamic_anchors), codex_cmd, timeout)
        return extract_profile_yaml(output, description), "llm"
    except Exception:
        if not allow_fallback:
            raise
        return fallback_profile_yaml(description, dynamic_anchors=dynamic_anchors), "fallback"


def write_profile_yaml(path: Path, yaml_text: str) -> Profile:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_text, encoding="utf-8")
    return load_profile(path)


def run_subprocess_command(cmd: List[str], cwd: Path) -> None:
    print("[CMD]", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd), check=True)


@dataclass
class FullPipelineOptions:
    description: str
    preset: str = "frugal"
    sources: Tuple[str, ...] = ("openalex", "arxiv")
    extra_queries: Tuple[str, ...] = ()
    profile_output: str = ""
    profile_llm: bool = True
    strict_profile_llm: bool = False
    dynamic_anchors: bool = True
    score: bool = True
    translate: bool = False
    import_portal: bool = False
    dry_run: bool = False
    codex_cmd: str = field(default_factory=default_codex_cmd)
    timeout: int = 900
    profile_timeout: int = 300
    translation_timeout: int = 300
    max_retries: int = 2
    sleep: float = 1.0
    raw_input: str = ""
    raw_collect_limit: int | None = None
    prefilter_keep: int | None = None
    score_top_k: int | None = None
    per_query_limit: int | None = None
    per_query_keep: int | None = None
    max_queries: int | None = None
    abstract_max_chars: int | None = None
    years: str = ""


def maybe_add(cmd: List[str], flag: str, value: Any) -> None:
    if value is None or value == "":
        return
    cmd.extend([flag, str(value)])


def build_auto_scout_command(options: FullPipelineOptions, profile_path: Path, import_portal_now: bool) -> List[str]:
    cmd = [
        sys.executable,
        "scripts/auto_scout.py",
        "--profile",
        str(profile_path),
        "--preset",
        options.preset,
    ]
    if options.sources:
        cmd.append("--sources")
        cmd.extend(options.sources)
    for query in options.extra_queries:
        cmd.extend(["--extra-query", query])
    if options.raw_input:
        cmd.extend(["--raw-input", options.raw_input])
    maybe_add(cmd, "--raw-collect-limit", options.raw_collect_limit)
    maybe_add(cmd, "--prefilter-keep", options.prefilter_keep)
    maybe_add(cmd, "--score-top-k", options.score_top_k)
    maybe_add(cmd, "--per-query-limit", options.per_query_limit)
    maybe_add(cmd, "--per-query-keep", options.per_query_keep)
    maybe_add(cmd, "--max-queries", options.max_queries)
    maybe_add(cmd, "--abstract-max-chars", options.abstract_max_chars)
    maybe_add(cmd, "--years", options.years)
    cmd.extend(["--sleep", str(options.sleep)])
    if options.score:
        cmd.append("--score")
        cmd.extend(["--codex-cmd", options.codex_cmd])
        cmd.extend(["--timeout", str(options.timeout)])
        cmd.extend(["--max-retries", str(options.max_retries)])
    if import_portal_now:
        cmd.append("--import-portal")
    if not options.dynamic_anchors:
        cmd.append("--no-profile-anchors")
    return cmd


def build_translate_command(options: FullPipelineOptions, score_path: Path, bilingual_path: Path) -> List[str]:
    return [
        sys.executable,
        "scripts/translate_results.py",
        "--input",
        str(score_path),
        "--output",
        str(bilingual_path),
        "--codex-cmd",
        options.codex_cmd,
        "--timeout",
        str(options.translation_timeout),
        "--max-retries",
        str(options.max_retries),
    ]


def build_import_command(input_path: Path, db_path: Path) -> List[str]:
    return [
        sys.executable,
        "web/import_jsonl.py",
        "--input",
        str(input_path),
        "--db",
        str(db_path),
    ]


def create_profile(options: FullPipelineOptions, root: Path) -> Tuple[Path, Profile, str]:
    if options.profile_llm:
        yaml_text, source = generate_profile_yaml(
            options.description,
            options.codex_cmd,
            options.profile_timeout,
            allow_fallback=not options.strict_profile_llm,
            dynamic_anchors=options.dynamic_anchors,
        )
    else:
        yaml_text, source = fallback_profile_yaml(options.description, dynamic_anchors=options.dynamic_anchors), "fallback"

    provisional = load_profile_from_text(yaml_text, root / ".tmp_generated_profile.yaml")
    profile_path = Path(options.profile_output) if options.profile_output else root / "configs" / "generated" / f"profile_{slugify(provisional.name)}.yaml"
    if not profile_path.is_absolute():
        profile_path = root / profile_path
    profile = write_profile_yaml(profile_path, yaml_text)
    return profile_path, profile, source


def load_profile_from_text(yaml_text: str, temp_path: Path) -> Profile:
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.write_text(yaml_text, encoding="utf-8")
    try:
        return load_profile(temp_path)
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


def stringify_paths(paths: Dict[str, Path]) -> Dict[str, str]:
    return {k: str(v) for k, v in paths.items()}


def run_full_pipeline(
    options: FullPipelineOptions,
    root: Path | None = None,
    runner: CommandRunner = run_subprocess_command,
    emit_manifest: bool = False,
) -> Dict[str, Any]:
    if not options.description.strip():
        raise ValueError("description is required")
    if (options.translate or options.import_portal) and not options.score:
        raise ValueError("--translate and --import-portal require scoring output; remove --no-score.")

    root = (root or Path.cwd()).resolve()
    profile_path, profile, profile_source = create_profile(options, root)
    paths = default_paths(root, profile)
    bilingual_path = root / "data" / f"{slugify(profile.name)}_idea_scores_bilingual.jsonl"
    manifest_path = root / "reports" / f"{slugify(profile.name)}_full_pipeline_manifest.json"

    import_during_auto = bool(options.import_portal and not options.translate)
    commands: List[List[str]] = [build_auto_scout_command(options, profile_path, import_during_auto)]
    if options.translate:
        commands.append(build_translate_command(options, paths["scores"], bilingual_path))
    if options.import_portal and options.translate:
        commands.append(build_import_command(bilingual_path, paths["db"]))

    if not options.dry_run:
        for cmd in commands:
            runner(cmd, root)

    path_summary = stringify_paths(paths)
    path_summary.update(
        {
            "profile": str(profile_path),
            "manifest": str(manifest_path),
            "bilingual_scores": str(bilingual_path),
        }
    )
    manifest: Dict[str, Any] = {
        "description": options.description,
        "profile_name": profile.name,
        "profile_source": profile_source,
        "preset": options.preset,
        "sources": list(options.sources),
        "score": options.score,
        "translate": options.translate,
        "import_portal": options.import_portal,
        "dry_run": options.dry_run,
        "dynamic_anchors": options.dynamic_anchors,
        "paths": path_summary,
        "commands": commands,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if emit_manifest:
        print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    return manifest


def read_description(args: argparse.Namespace) -> str:
    parts: List[str] = []
    if args.description:
        parts.append(args.description)
    if args.description_file:
        parts.append(Path(args.description_file).read_text(encoding="utf-8"))
    description = "\n\n".join(p.strip() for p in parts if p.strip())
    if not description:
        raise SystemExit("Provide --description or --description-file.")
    return description


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run the full IdeaScout pipeline from a natural-language research direction.")
    ap.add_argument("--description", default="", help="Natural-language research direction.")
    ap.add_argument("--description-file", default="", help="Read the research direction from a UTF-8 text file.")
    ap.add_argument("--profile-output", default="", help="Where to save the generated profile YAML.")
    ap.add_argument("--no-profile-llm", action="store_true", help="Use the heuristic fallback profile generator instead of Codex.")
    ap.add_argument("--strict-profile-llm", action="store_true", help="Fail instead of falling back if Codex cannot generate the profile.")
    ap.add_argument("--dynamic-anchors", dest="dynamic_anchors", action="store_true", default=True, help="Generate and use profile-specific prefilter anchors.")
    ap.add_argument("--no-dynamic-anchors", dest="dynamic_anchors", action="store_false", help="Use default prefilter anchors instead of profile-specific anchors.")
    ap.add_argument("--preset", choices=["frugal", "balanced", "exploratory"], default="frugal")
    ap.add_argument("--sources", nargs="*", choices=["openalex", "semanticscholar", "arxiv"], default=["openalex", "arxiv"])
    ap.add_argument("--extra-query", action="append", default=[])
    ap.add_argument("--score", dest="score", action="store_true", default=True)
    ap.add_argument("--no-score", dest="score", action="store_false")
    ap.add_argument("--translate", action="store_true", help="Translate scored paper summaries into Simplified Chinese fields.")
    ap.add_argument("--import-portal", action="store_true", help="Import final scored output into the web portal database.")
    ap.add_argument("--dry-run", action="store_true", help="Generate the profile and manifest without running collection/scoring commands.")
    ap.add_argument("--codex-cmd", default=default_codex_cmd())
    ap.add_argument("--timeout", type=int, default=900, help="Per-paper scoring timeout.")
    ap.add_argument("--profile-timeout", type=int, default=300)
    ap.add_argument("--translation-timeout", type=int, default=300)
    ap.add_argument("--max-retries", type=int, default=2)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--raw-input", default="", help="Reuse an existing raw JSONL instead of collecting from APIs.")
    ap.add_argument("--raw-collect-limit", type=int, default=None)
    ap.add_argument("--prefilter-keep", type=int, default=None)
    ap.add_argument("--score-top-k", type=int, default=None)
    ap.add_argument("--per-query-limit", type=int, default=None)
    ap.add_argument("--per-query-keep", type=int, default=None)
    ap.add_argument("--max-queries", type=int, default=None)
    ap.add_argument("--abstract-max-chars", type=int, default=None)
    ap.add_argument("--years", default="")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    options = FullPipelineOptions(
        description=read_description(args),
        preset=args.preset,
        sources=tuple(args.sources or []),
        extra_queries=tuple(args.extra_query or []),
        profile_output=args.profile_output,
        profile_llm=not args.no_profile_llm,
        strict_profile_llm=args.strict_profile_llm,
        dynamic_anchors=args.dynamic_anchors,
        score=args.score,
        translate=args.translate,
        import_portal=args.import_portal,
        dry_run=args.dry_run,
        codex_cmd=args.codex_cmd,
        timeout=args.timeout,
        profile_timeout=args.profile_timeout,
        translation_timeout=args.translation_timeout,
        max_retries=args.max_retries,
        sleep=args.sleep,
        raw_input=args.raw_input,
        raw_collect_limit=args.raw_collect_limit,
        prefilter_keep=args.prefilter_keep,
        score_top_k=args.score_top_k,
        per_query_limit=args.per_query_limit,
        per_query_keep=args.per_query_keep,
        max_queries=args.max_queries,
        abstract_max_chars=args.abstract_max_chars,
        years=args.years,
    )
    run_full_pipeline(options, emit_manifest=True)


if __name__ == "__main__":
    main()
