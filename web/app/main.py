from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Tuple

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from idea_scout.full_pipeline import FullPipelineOptions, default_codex_cmd, run_full_pipeline

APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR.parent
ROOT_DIR = WEB_DIR.parent
DEFAULT_DB = WEB_DIR / "ideascout_portal.db"
DB_PATH = Path(os.environ.get("IDEASCOUT_PORTAL_DB", str(DEFAULT_DB))).resolve()
SCOUT_PIPELINE_ROOT = ROOT_DIR
SCOUT_JOB_DIR = ROOT_DIR / "logs" / "scout_jobs"
SCOUT_JOBS: Dict[str, Dict[str, Any]] = {}
SCOUT_LOCK = threading.Lock()

app = FastAPI(title="IdeaScout Portal", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

SUPPORTED_LANGS = {"zh", "en"}
LOCALIZED_FIELDS = [
    "abstract",
    "idea_core",
    "transferable_mechanism",
    "fit_reason",
    "risk_or_limitation",
]

PRIORITY_LABELS = {
    "zh": {
        "keep": "\u5f3a\u63a8\u8350",
        "maybe": "\u5019\u9009",
        "drop": "\u6682\u4e0d\u4f18\u5148",
    },
    "en": {
        "keep": "Keep",
        "maybe": "Maybe",
        "drop": "Drop",
    },
}

SCORE_LABELS = {
    "zh": {
        "rank_score": "\u7efc\u5408\u5206",
        "score_overall_fit": "\u5339\u914d\u5ea6",
        "score_theory_novelty": "\u65b0\u9896\u6027",
        "intervention_timing_value": "\u5e72\u9884\u65f6\u673a\u4ef7\u503c",
        "initiative_policy_fit": "\u4e3b\u52a8\u7b56\u7565\u5339\u914d",
        "procedural_diagnosis_to_assistance": "\u8bca\u65ad\u5230\u8f85\u52a9",
        "task_belief_and_progress_modeling": "\u4efb\u52a1\u8fdb\u5ea6\u5efa\u6a21",
        "dialogue_grounding_value": "\u5bf9\u8bdd\u4e0a\u4e0b\u6587\u652f\u6491",
        "prototype_or_retrieval_transferability": "\u539f\u578b/\u68c0\u7d22\u8fc1\u79fb",
        "grounded_response_and_recovery": "\u7ea0\u9519\u4e0e\u6062\u590d",
        "streaming_feasibility": "\u6d41\u5f0f\u53ef\u884c\u6027",
        "evaluation_relevance": "\u8bc4\u4f30\u76f8\u5173\u6027",
        "implementation_feasibility": "\u5b9e\u73b0\u53ef\u884c\u6027",
    },
    "en": {
        "rank_score": "Rank score",
        "score_overall_fit": "Overall fit",
        "score_theory_novelty": "Theory novelty",
        "intervention_timing_value": "Intervention timing value",
        "initiative_policy_fit": "Initiative policy fit",
        "procedural_diagnosis_to_assistance": "Diagnosis to assistance",
        "task_belief_and_progress_modeling": "Task progress modeling",
        "dialogue_grounding_value": "Dialogue grounding value",
        "prototype_or_retrieval_transferability": "Prototype/retrieval transferability",
        "grounded_response_and_recovery": "Grounded response and recovery",
        "streaming_feasibility": "Streaming feasibility",
        "evaluation_relevance": "Evaluation relevance",
        "implementation_feasibility": "Implementation feasibility",
    },
}

UI_TEXT = {
    "zh": {
        "app_name": "IdeaScout \u7814\u7a76\u96f7\u8fbe",
        "nav_home": "\u603b\u89c8",
        "nav_articles": "\u8bba\u6587\u5e93",
        "nav_scout": "\u81ea\u52a8\u6d41\u7a0b",
        "language_switch": "English",
        "home_title": "\u4ece\u5927\u91cf\u8bba\u6587\u91cc\u635e\u51fa\u771f\u6b63\u53ef\u80fd\u8fc1\u79fb\u7684\u60f3\u6cd5\u3002",
        "home_eyebrow": "ProAssist \u65b9\u5411 · \u81ea\u52a8\u7b5b\u9009\u7ed3\u679c",
        "home_desc": "\u8fd9\u91cc\u5c55\u793a\u81ea\u52a8\u6536\u96c6\u3001\u89c4\u5219\u9884\u8fc7\u6ee4\u548c Codex \u7cbe\u8bc4\u540e\u7684\u7ed3\u679c\u3002\u4f18\u5148\u770b\u5f3a\u63a8\u8350\u548c\u9ad8\u7efc\u5408\u5206\u8bba\u6587\uff0c\u518d\u8fdb\u5165\u8be6\u60c5\u5224\u65ad\u673a\u5236\u662f\u5426\u80fd\u8fc1\u79fb\u5230\u4f60\u7684\u6d41\u5f0f egocentric proactive assistant\u3002",
        "open_library": "\u8fdb\u5165\u8bba\u6587\u5e93",
        "metric_articles": "\u5df2\u7cbe\u8bc4\u8bba\u6587",
        "metric_keep": "\u5f3a\u63a8\u8350",
        "metric_avg": "\u5e73\u5747\u7efc\u5408\u5206",
        "metric_top": "\u6700\u9ad8\u5206",
        "score_overview": "\u5f97\u5206\u7ef4\u5ea6\u6982\u89c8",
        "reading_queue": "\u4f18\u5148\u9605\u8bfb\u961f\u5217",
        "view_all": "\u67e5\u770b\u5168\u90e8",
        "dimensions_count": "\u4e2a\u7ef4\u5ea6",
        "dimension_avg": "\u5e73\u5747",
        "dimension_high": "\u7bc7\u8fbe\u5230 7 \u5206\u4ee5\u4e0a",
        "no_dimensions": "\u8fd8\u6ca1\u6709\u53ef\u5c55\u793a\u7684\u5f97\u5206\u7ef4\u5ea6\u3002",
        "unknown_source": "\u672a\u77e5\u6765\u6e90",
        "unknown_year": "\u5e74\u4efd\u672a\u77e5",
        "current_database": "\u5f53\u524d\u6570\u636e\u6e90",
        "article_library": "\u7b5b\u9009\u8bba\u6587",
        "shown_total": "\u5f53\u524d\u663e\u793a {shown} \u7bc7 · \u5171 {total} \u7bc7",
        "search_placeholder": "\u641c\u7d22\u6807\u9898\u3001\u6838\u5fc3\u60f3\u6cd5\u3001\u8fc1\u79fb\u673a\u5236\u3001venue...",
        "all_priorities": "\u5168\u90e8\u4f18\u5148\u7ea7",
        "sort_rank": "\u7efc\u5408\u6392\u5e8f",
        "sort_overall": "\u6309\u5339\u914d\u5ea6",
        "sort_novelty": "\u6309\u65b0\u9896\u6027",
        "sort_year": "\u6309\u5e74\u4efd",
        "top_n": "\u524d {n} \u7bc7",
        "apply_filters": "\u5e94\u7528\u7b5b\u9009",
        "no_summary": "\u6682\u65e0\u6838\u5fc3\u60f3\u6cd5\u6458\u8981\u3002",
        "mechanism_prefix": "\u8fc1\u79fb\u673a\u5236\uff1a",
        "overall_score": "\u7efc\u5408\u5206",
        "fit_score": "\u5339\u914d\u5ea6",
        "novelty_score": "\u65b0\u9896\u6027",
        "no_matches": "\u6ca1\u6709\u8bba\u6587\u5339\u914d\u5f53\u524d\u7b5b\u9009\u6761\u4ef6\u3002",
        "paper_not_found": "\u6ca1\u6709\u627e\u5230\u8fd9\u7bc7\u8bba\u6587",
        "back_library": "\u8fd4\u56de\u8bba\u6587\u5e93",
        "why_read": "\u4e3a\u4ec0\u4e48\u503c\u5f97\u770b",
        "core_idea": "\u6838\u5fc3\u60f3\u6cd5",
        "transferable_mechanism": "\u53ef\u8fc1\u79fb\u673a\u5236",
        "fit_reason": "\u5339\u914d\u539f\u56e0",
        "risk": "\u98ce\u9669\u4e0e\u9650\u5236",
        "metadata": "\u8bba\u6587\u4fe1\u606f",
        "authors": "\u4f5c\u8005",
        "priority": "\u4f18\u5148\u7ea7",
        "source": "\u6765\u6e90",
        "year": "\u5e74\u4efd",
        "link": "\u94fe\u63a5",
        "open_paper": "\u6253\u5f00\u8bba\u6587",
        "score_breakdown": "\u8bc4\u5206\u62c6\u89e3",
        "abstract": "\u6458\u8981",
        "none": "\u6682\u65e0",
        "footer": "IdeaScout · \u9762\u5411\u4e2a\u4eba\u7814\u7a76\u65b9\u5411\u7684\u8de8\u9886\u57df\u8bba\u6587\u7b5b\u9009\u53f0",
        "scout_title": "\u81ea\u52a8\u7814\u7a76\u6d41\u7a0b",
        "scout_desc": "\u8f93\u5165\u4f60\u7684\u7814\u7a76\u65b9\u5411\uff0c\u8ba9 IdeaScout \u81ea\u52a8\u751f\u6210\u8bc4\u5206\u6a21\u677f\u3001\u6536\u96c6\u8bba\u6587\u3001\u9884\u7b5b\u3001\u7cbe\u8bc4\u548c\u5bfc\u5165\u7ed3\u679c\u3002",
        "research_direction": "\u7814\u7a76\u65b9\u5411",
        "research_placeholder": "\u4f8b\u5982\uff1a\u6211\u5173\u6ce8 streaming egocentric proactive assistant\uff0c\u5c24\u5176\u662f\u4e3b\u52a8\u4ecb\u5165\u65f6\u673a\u3001\u7a0b\u5e8f\u6027\u9519\u8bef\u8bca\u65ad\u548c\u6062\u590d\u8ddf\u8e2a\u3002",
        "preset": "\u8fd0\u884c\u89c4\u6a21",
        "data_sources": "\u6570\u636e\u6e90",
        "pipeline_options": "\u6d41\u7a0b\u9009\u9879",
        "score_with_codex": "Codex \u7cbe\u8bc4",
        "translate_zh": "\u751f\u6210\u4e2d\u6587\u5b57\u6bb5",
        "import_portal": "\u5bfc\u5165\u5f53\u524d\u7f51\u9875",
        "profile_llm": "Codex \u751f\u6210\u8bc4\u5206\u6a21\u677f",
        "dynamic_anchors": "AI \u52a8\u6001\u9884\u7b5b\u951a\u70b9",
        "advanced_limits": "\u4e0a\u9650",
        "raw_collect_limit": "\u6536\u96c6\u4e0a\u9650",
        "prefilter_keep": "\u9884\u7b5b\u4fdd\u7559",
        "score_top_k": "\u7cbe\u8bc4\u7bc7\u6570",
        "codex_command": "Codex \u547d\u4ee4",
        "start_pipeline": "\u542f\u52a8\u5168\u6d41\u7a0b",
        "dry_run": "\u53ea\u9884\u89c8\u547d\u4ee4",
        "job_status": "\u4efb\u52a1\u72b6\u6001",
        "job_waiting": "\u5c1a\u672a\u542f\u52a8\u4efb\u52a1\u3002",
        "latest_jobs": "\u6700\u8fd1\u4efb\u52a1",
        "live_log": "\u8fd0\u884c\u65e5\u5fd7",
        "outputs": "\u8f93\u51fa",
        "open_results": "\u6253\u5f00\u8bba\u6587\u5e93",
        "copy_paths": "\u8f93\u51fa\u8def\u5f84",
        "status_queued": "\u6392\u961f\u4e2d",
        "status_running": "\u8fd0\u884c\u4e2d",
        "status_done": "\u5b8c\u6210",
        "status_failed": "\u5931\u8d25",
    },
    "en": {
        "app_name": "IdeaScout Research Radar",
        "nav_home": "Overview",
        "nav_articles": "Article Library",
        "nav_scout": "Auto Scout",
        "language_switch": "\u4e2d\u6587",
        "home_title": "Surface transferable ideas from a noisy paper pool.",
        "home_eyebrow": "ProAssist profile · scored results",
        "home_desc": "This portal shows papers after automatic collection, cheap prefiltering, and Codex scoring. Start with keep/high-rank papers, then inspect whether the mechanism can transfer to streaming egocentric proactive assistance.",
        "open_library": "Open article library",
        "metric_articles": "Scored papers",
        "metric_keep": "Keep",
        "metric_avg": "Average rank",
        "metric_top": "Top score",
        "score_overview": "Scoring dimensions",
        "reading_queue": "Reading queue",
        "view_all": "View all",
        "dimensions_count": "dimensions",
        "dimension_avg": "Average",
        "dimension_high": "papers scored 7+",
        "no_dimensions": "No score dimensions available yet.",
        "unknown_source": "Unknown source",
        "unknown_year": "Unknown year",
        "current_database": "Current database",
        "article_library": "Article library",
        "shown_total": "{shown} shown · {total} total",
        "search_placeholder": "Search title, core idea, mechanism, venue...",
        "all_priorities": "All priorities",
        "sort_rank": "Rank score",
        "sort_overall": "Overall fit",
        "sort_novelty": "Novelty",
        "sort_year": "Year",
        "top_n": "Top {n}",
        "apply_filters": "Apply",
        "no_summary": "No idea summary available.",
        "mechanism_prefix": "Mechanism:",
        "overall_score": "Rank",
        "fit_score": "Overall",
        "novelty_score": "Novelty",
        "no_matches": "No papers match the current filters.",
        "paper_not_found": "Article not found",
        "back_library": "Back to library",
        "why_read": "Why read this",
        "core_idea": "Core idea",
        "transferable_mechanism": "Transferable mechanism",
        "fit_reason": "Fit reason",
        "risk": "Risk or limitation",
        "metadata": "Paper information",
        "authors": "Authors",
        "priority": "Priority",
        "source": "Source",
        "year": "Year",
        "link": "Link",
        "open_paper": "Open paper",
        "score_breakdown": "Score breakdown",
        "abstract": "Abstract",
        "none": "N/A",
        "footer": "IdeaScout · Profile-guided cross-domain research idea discovery",
        "scout_title": "Automatic research pipeline",
        "scout_desc": "Describe your research direction and let IdeaScout generate a scoring profile, collect papers, prefilter, score, translate, and import results.",
        "research_direction": "Research direction",
        "research_placeholder": "Example: I care about streaming egocentric proactive assistants, especially intervention timing, procedural error diagnosis, and recovery tracking.",
        "preset": "Run size",
        "data_sources": "Data sources",
        "pipeline_options": "Pipeline options",
        "score_with_codex": "Score with Codex",
        "translate_zh": "Generate Chinese fields",
        "import_portal": "Import into this portal",
        "profile_llm": "Generate profile with Codex",
        "dynamic_anchors": "AI dynamic prefilter anchors",
        "advanced_limits": "Limits",
        "raw_collect_limit": "Raw limit",
        "prefilter_keep": "Prefilter keep",
        "score_top_k": "Score top K",
        "codex_command": "Codex command",
        "start_pipeline": "Start pipeline",
        "dry_run": "Preview commands",
        "job_status": "Job status",
        "job_waiting": "No job has been started yet.",
        "latest_jobs": "Recent jobs",
        "live_log": "Live log",
        "outputs": "Outputs",
        "open_results": "Open article library",
        "copy_paths": "Output paths",
        "status_queued": "Queued",
        "status_running": "Running",
        "status_done": "Done",
        "status_failed": "Failed",
    },
}


def normalize_lang(lang: str | None) -> str:
    return lang if lang in SUPPORTED_LANGS else "zh"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                abstract TEXT,
                venue TEXT,
                year INTEGER,
                url TEXT,
                authors TEXT,
                priority TEXT,
                profile_name TEXT,
                idea_core TEXT,
                transferable_mechanism TEXT,
                fit_reason TEXT,
                risk_or_limitation TEXT,
                rank_score REAL,
                score_overall_fit REAL,
                score_theory_novelty REAL,
                scores_json TEXT,
                raw_json TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_rank ON articles(rank_score DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_year ON articles(year DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_priority ON articles(priority)")


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    obj = dict(row)
    for key in ["scores_json", "raw_json"]:
        if obj.get(key):
            try:
                obj[key.replace("_json", "")] = json.loads(obj[key])
            except Exception:
                obj[key.replace("_json", "")] = {}
        else:
            obj[key.replace("_json", "")] = {}
    return obj


def fetch_all_articles() -> List[Dict[str, Any]]:
    ensure_db()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM articles").fetchall()
    return [row_to_dict(r) for r in rows]


def priority_label(priority: str | None, lang: str) -> str:
    p = (priority or "maybe").lower()
    return PRIORITY_LABELS[lang].get(p, p or PRIORITY_LABELS[lang]["maybe"])


def score_label(key: str, lang: str) -> str:
    return SCORE_LABELS[lang].get(key, key.replace("_", " ").title())


def localize_article(article: Dict[str, Any], lang: str) -> Dict[str, Any]:
    out = dict(article)
    raw = out.get("raw") or {}
    if lang == "zh":
        for field in LOCALIZED_FIELDS:
            translated = raw.get(f"{field}_zh")
            if translated:
                out[field] = translated
    else:
        for field in LOCALIZED_FIELDS:
            original = raw.get(field)
            if original:
                out[field] = original
    out["priority_label"] = priority_label(out.get("priority"), lang)
    return out


def score_value(article: Dict[str, Any], key: str) -> float:
    value = article.get(key)
    if value is None:
        raw = article.get("raw") or {}
        value = raw.get(key)
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def score_items(article: Dict[str, Any], lang: str) -> List[Tuple[str, float]]:
    raw = article.get("raw") or {}
    scores = article.get("scores") or {}
    items: List[Tuple[str, float]] = []

    for key in ["rank_score", "score_overall_fit", "score_theory_novelty"]:
        items.append((score_label(key, lang), score_value(article, key)))

    for key, value in sorted(scores.items()):
        try:
            items.append((score_label(key, lang), float(value or 0.0)))
        except Exception:
            items.append((score_label(key, lang), 0.0))

    flat_keys = sorted(k for k in raw if k.startswith("score_") and k not in {"score_overall_fit", "score_theory_novelty"})
    seen = {name.lower() for name, _ in items}
    for key in flat_keys:
        label = score_label(key.replace("score_", ""), lang)
        if label.lower() in seen:
            continue
        items.append((label, score_value(article, key)))
    return items


def collect_dimension_stats(articles: List[Dict[str, Any]], lang: str) -> List[Dict[str, Any]]:
    bucket: Dict[str, List[float]] = {}
    for article in articles:
        raw = article.get("raw") or {}
        scores = article.get("scores") or {}
        for key, value in scores.items():
            try:
                bucket.setdefault(key, []).append(float(value or 0.0))
            except Exception:
                pass
        for key, value in raw.items():
            if not key.startswith("score_") or key in {"score_overall_fit", "score_theory_novelty"}:
                continue
            name = key.replace("score_", "")
            if name in bucket:
                continue
            try:
                bucket.setdefault(name, []).append(float(value or 0.0))
            except Exception:
                pass

    stats = []
    for key, vals in bucket.items():
        if not vals:
            continue
        avg = sum(vals) / len(vals)
        high = sum(1 for v in vals if v >= 7.0)
        stats.append({"key": key, "label": score_label(key, lang), "avg": avg, "high": high})
    stats.sort(key=lambda x: (x["avg"], x["high"]), reverse=True)
    return stats[:12]


def filter_articles(
    articles: List[Dict[str, Any]],
    q: str = "",
    priority: str = "",
    sort: str = "rank_score",
) -> List[Dict[str, Any]]:
    q = (q or "").strip().lower()
    priority = (priority or "").strip().lower()

    def text_blob(article: Dict[str, Any]) -> str:
        raw = article.get("raw") or {}
        parts = [
            article.get("title"),
            article.get("abstract"),
            article.get("venue"),
            article.get("year"),
            article.get("idea_core"),
            article.get("transferable_mechanism"),
            article.get("fit_reason"),
            article.get("risk_or_limitation"),
            raw.get("abstract_zh"),
            raw.get("idea_core_zh"),
            raw.get("transferable_mechanism_zh"),
            raw.get("fit_reason_zh"),
            raw.get("risk_or_limitation_zh"),
            raw.get("profile_name"),
            raw.get("url"),
        ]
        return " ".join(str(x) for x in parts if x).lower()

    out = []
    for article in articles:
        if q and q not in text_blob(article):
            continue
        if priority and (article.get("priority") or "").lower() != priority:
            continue
        out.append(article)

    if sort == "year":
        out.sort(key=lambda a: int(a.get("year") or 0), reverse=True)
    elif sort == "overall":
        out.sort(key=lambda a: score_value(a, "score_overall_fit"), reverse=True)
    elif sort == "novelty":
        out.sort(key=lambda a: score_value(a, "score_theory_novelty"), reverse=True)
    else:
        out.sort(key=lambda a: score_value(a, "rank_score"), reverse=True)
    return out


def base_context(request: Request, lang: str) -> Dict[str, Any]:
    other_lang = "en" if lang == "zh" else "zh"
    return {
        "request": request,
        "lang": lang,
        "ui": UI_TEXT[lang],
        "priority_labels": PRIORITY_LABELS[lang],
        "switch_lang": other_lang,
        "switch_url": str(request.url.include_query_params(lang=other_lang)),
    }


def bool_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def optional_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def normalize_sources(value: Any) -> Tuple[str, ...]:
    allowed = {"openalex", "arxiv", "semanticscholar"}
    if isinstance(value, str):
        raw = [x.strip() for x in value.split(",")]
    elif isinstance(value, list):
        raw = [str(x).strip() for x in value]
    else:
        raw = ["openalex", "arxiv"]
    sources = tuple(x for x in raw if x in allowed)
    return sources or ("openalex", "arxiv")


def scout_options_from_payload(payload: Dict[str, Any]) -> FullPipelineOptions:
    description = str(payload.get("description") or "").strip()
    if not description:
        raise ValueError("description is required")
    preset = str(payload.get("preset") or "frugal")
    if preset not in {"frugal", "balanced", "exploratory"}:
        preset = "frugal"
    return FullPipelineOptions(
        description=description,
        preset=preset,
        sources=normalize_sources(payload.get("sources")),
        profile_llm=bool_value(payload.get("profile_llm"), True),
        dynamic_anchors=bool_value(payload.get("dynamic_anchors"), True),
        score=bool_value(payload.get("score"), True),
        translate=bool_value(payload.get("translate"), False),
        import_portal=bool_value(payload.get("import_portal"), False),
        dry_run=bool_value(payload.get("dry_run"), False),
        codex_cmd=str(payload.get("codex_cmd") or default_codex_cmd()),
        raw_collect_limit=optional_int(payload.get("raw_collect_limit")),
        prefilter_keep=optional_int(payload.get("prefilter_keep")),
        score_top_k=optional_int(payload.get("score_top_k")),
        per_query_limit=optional_int(payload.get("per_query_limit")),
        per_query_keep=optional_int(payload.get("per_query_keep")),
        max_queries=optional_int(payload.get("max_queries")),
        abstract_max_chars=optional_int(payload.get("abstract_max_chars")),
    )


def write_job_log(job: Dict[str, Any], text: str) -> None:
    log_path = Path(job["log_path"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", errors="replace") as f:
        f.write(text)
        if not text.endswith("\n"):
            f.write("\n")


def read_job_log_tail(path: str | Path, max_chars: int = 12000) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8", errors="replace")
    return text[-max_chars:]


def run_logged_subprocess(cmd: List[str], cwd: Path, job: Dict[str, Any]) -> None:
    write_job_log(job, "[CMD] " + " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        write_job_log(job, line.rstrip("\n"))
    rc = proc.wait()
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)


def run_scout_job(job_id: str, options: FullPipelineOptions) -> None:
    global DB_PATH
    with SCOUT_LOCK:
        job = SCOUT_JOBS[job_id]
        job["status"] = "running"
        job["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    write_job_log(job, f"Job started: {job_id}")
    try:
        manifest = run_full_pipeline(
            options,
            root=SCOUT_PIPELINE_ROOT,
            runner=lambda cmd, cwd: run_logged_subprocess(cmd, cwd, job),
            emit_manifest=False,
        )
        db_path = manifest.get("paths", {}).get("db")
        if options.import_portal and db_path and Path(db_path).exists():
            DB_PATH = Path(db_path).resolve()
            ensure_db()
            write_job_log(job, f"Portal database switched to {DB_PATH}")
        with SCOUT_LOCK:
            job["status"] = "done"
            job["manifest"] = manifest
            job["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        write_job_log(job, "Job finished")
    except Exception as exc:
        with SCOUT_LOCK:
            job["status"] = "failed"
            job["error"] = str(exc)
            job["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        write_job_log(job, f"[ERROR] {exc}")


def start_scout_job(options: FullPipelineOptions) -> Dict[str, Any]:
    job_id = time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    SCOUT_JOB_DIR.mkdir(parents=True, exist_ok=True)
    job = {
        "job_id": job_id,
        "status": "queued",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "log_path": str(SCOUT_JOB_DIR / f"{job_id}.log"),
        "manifest": None,
        "error": "",
    }
    with SCOUT_LOCK:
        SCOUT_JOBS[job_id] = job
    thread = threading.Thread(target=run_scout_job, args=(job_id, options), daemon=True)
    thread.start()
    return job


def serialize_job(job: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(job)
    data["log_tail"] = read_job_log_tail(data.get("log_path", ""))
    data["active_db"] = str(DB_PATH)
    return data


def recent_jobs(limit: int = 8) -> List[Dict[str, Any]]:
    with SCOUT_LOCK:
        jobs = list(SCOUT_JOBS.values())
    jobs.sort(key=lambda j: str(j.get("created_at", "")), reverse=True)
    return [serialize_job(j) for j in jobs[:limit]]


@app.on_event("startup")
def on_startup() -> None:
    ensure_db()


@app.get("/scout", response_class=HTMLResponse)
def scout_page(request: Request, lang: str = Query("zh")) -> HTMLResponse:
    lang = normalize_lang(lang)
    return templates.TemplateResponse(
        request,
        "scout.html",
        {
            **base_context(request, lang),
            "jobs": recent_jobs(),
            "default_codex_cmd": default_codex_cmd(),
        },
    )


@app.post("/api/scout/jobs")
async def create_scout_job(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("JSON object expected")
        options = scout_options_from_payload(payload)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    job = start_scout_job(options)
    return JSONResponse({"job_id": job["job_id"], "status": job["status"]})


@app.get("/api/scout/jobs")
def list_scout_jobs() -> Dict[str, Any]:
    return {"jobs": recent_jobs()}


@app.get("/api/scout/jobs/{job_id}")
def get_scout_job(job_id: str) -> Dict[str, Any]:
    with SCOUT_LOCK:
        job = SCOUT_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return serialize_job(job)


@app.get("/", response_class=HTMLResponse)
def home(request: Request, lang: str = Query("zh")) -> HTMLResponse:
    lang = normalize_lang(lang)
    articles = [localize_article(a, lang) for a in fetch_all_articles()]
    n = len(articles)
    keep = sum(1 for a in articles if (a.get("priority") or "").lower() == "keep")
    avg_rank = sum(score_value(a, "rank_score") for a in articles) / n if n else 0.0
    top_score = max([score_value(a, "rank_score") for a in articles], default=0.0)
    top_papers = sorted(articles, key=lambda a: score_value(a, "rank_score"), reverse=True)[:8]
    dimensions = collect_dimension_stats(articles, lang)
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            **base_context(request, lang),
            "n": n,
            "keep": keep,
            "avg_rank": avg_rank,
            "top_score": top_score,
            "top_papers": top_papers,
            "dimensions": dimensions,
            "db_path": str(DB_PATH),
        },
    )


@app.get("/articles", response_class=HTMLResponse)
def articles_page(
    request: Request,
    q: str = Query(""),
    priority: str = Query(""),
    sort: str = Query("rank_score"),
    limit: int = Query(100, ge=1, le=1000),
    lang: str = Query("zh"),
) -> HTMLResponse:
    lang = normalize_lang(lang)
    all_articles = fetch_all_articles()
    filtered = filter_articles(all_articles, q=q, priority=priority, sort=sort)[:limit]
    localized = [localize_article(a, lang) for a in filtered]
    return templates.TemplateResponse(
        request,
        "articles.html",
        {
            **base_context(request, lang),
            "articles": localized,
            "total": len(all_articles),
            "shown": len(localized),
            "q": q,
            "priority": priority,
            "sort": sort,
            "limit": limit,
        },
    )


@app.get("/articles/{article_id}", response_class=HTMLResponse)
def article_detail(request: Request, article_id: int, lang: str = Query("zh")) -> HTMLResponse:
    lang = normalize_lang(lang)
    ensure_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    if row is None:
        return templates.TemplateResponse(
            request,
            "article_detail.html",
            {**base_context(request, lang), "article": None, "scores": []},
            status_code=404,
        )
    article = localize_article(row_to_dict(row), lang)
    return templates.TemplateResponse(
        request,
        "article_detail.html",
        {**base_context(request, lang), "article": article, "scores": score_items(article, lang)},
    )
