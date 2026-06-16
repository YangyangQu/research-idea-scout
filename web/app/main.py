from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR.parent
DEFAULT_DB = WEB_DIR / "ideascout_portal.db"
DB_PATH = Path(os.environ.get("IDEASCOUT_PORTAL_DB", str(DEFAULT_DB))).resolve()

app = FastAPI(title="IdeaScout Portal", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id TEXT UNIQUE,
                asset_type TEXT,
                profile_name TEXT,
                challenge TEXT,
                solution_pattern TEXT,
                mechanism TEXT,
                why_it_is_hard TEXT,
                code_status TEXT,
                code_url TEXT,
                pdf_status TEXT,
                pdf_url TEXT,
                asset_score REAL,
                evidence_strength REAL,
                code_readiness REAL,
                source_title TEXT,
                source_venue TEXT,
                source_year INTEGER,
                raw_json TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_score ON assets(asset_score DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_code_status ON assets(code_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_pdf_status ON assets(pdf_status)")


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



def fetch_all_assets() -> List[Dict[str, Any]]:
    ensure_db()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM assets").fetchall()
    return [row_to_dict(r) for r in rows]


def score_value(article: Dict[str, Any], key: str) -> float:
    value = article.get(key)
    if value is None:
        raw = article.get("raw") or {}
        value = raw.get(key)
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def score_items(article: Dict[str, Any]) -> List[Tuple[str, float]]:
    raw = article.get("raw") or {}
    scores = article.get("scores") or {}
    items: List[Tuple[str, float]] = []

    for label, key in [
        ("Rank score", "rank_score"),
        ("Overall fit", "score_overall_fit"),
        ("Theory novelty", "score_theory_novelty"),
    ]:
        items.append((label, score_value(article, key)))

    for key, value in sorted(scores.items()):
        label = key.replace("_", " ").title()
        try:
            items.append((label, float(value or 0.0)))
        except Exception:
            items.append((label, 0.0))

    flat_keys = sorted(k for k in raw if k.startswith("score_") and k not in {"score_overall_fit", "score_theory_novelty"})
    seen = {name.lower() for name, _ in items}
    for key in flat_keys:
        label = key.replace("score_", "").replace("_", " ").title()
        if label.lower() in seen:
            continue
        items.append((label, score_value(article, key)))
    return items


def collect_dimension_stats(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    bucket: Dict[str, List[float]] = {}
    for a in articles:
        raw = a.get("raw") or {}
        scores = a.get("scores") or {}
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
        stats.append({"key": key, "label": key.replace("_", " ").title(), "avg": avg, "high": high})
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

    def text_blob(a: Dict[str, Any]) -> str:
        raw = a.get("raw") or {}
        parts = [
            a.get("title"), a.get("abstract"), a.get("venue"), a.get("year"),
            a.get("idea_core"), a.get("transferable_mechanism"), a.get("fit_reason"),
            a.get("risk_or_limitation"), raw.get("theory_bucket"), raw.get("theory_family"),
            raw.get("profile_name"), raw.get("url"),
        ]
        return " ".join(str(x) for x in parts if x).lower()

    out = []
    for a in articles:
        if q and q not in text_blob(a):
            continue
        if priority and (a.get("priority") or "").lower() != priority:
            continue
        out.append(a)

    if sort == "year":
        out.sort(key=lambda a: int(a.get("year") or 0), reverse=True)
    elif sort == "overall":
        out.sort(key=lambda a: score_value(a, "score_overall_fit"), reverse=True)
    elif sort == "novelty":
        out.sort(key=lambda a: score_value(a, "score_theory_novelty"), reverse=True)
    else:
        out.sort(key=lambda a: score_value(a, "rank_score"), reverse=True)
    return out


def filter_assets(
    assets: List[Dict[str, Any]],
    q: str = "",
    code_status: str = "",
    pdf_status: str = "",
    sort: str = "asset_score",
) -> List[Dict[str, Any]]:
    q = (q or "").strip().lower()
    code_status = (code_status or "").strip().lower()
    pdf_status = (pdf_status or "").strip().lower()

    def text_blob(a: Dict[str, Any]) -> str:
        raw = a.get("raw") or {}
        parts = [
            a.get("asset_id"), a.get("asset_type"), a.get("challenge"), a.get("solution_pattern"),
            a.get("mechanism"), a.get("why_it_is_hard"), a.get("source_title"), a.get("source_venue"),
            raw.get("limitations"), raw.get("evidence"), raw.get("transferable_to"),
        ]
        return " ".join(str(x) for x in parts if x).lower()

    out = []
    for a in assets:
        if q and q not in text_blob(a):
            continue
        if code_status and (a.get("code_status") or "").lower() != code_status:
            continue
        if pdf_status and (a.get("pdf_status") or "").lower() != pdf_status:
            continue
        out.append(a)

    if sort == "code":
        out.sort(key=lambda a: score_value(a, "code_readiness"), reverse=True)
    elif sort == "evidence":
        out.sort(key=lambda a: score_value(a, "evidence_strength"), reverse=True)
    else:
        out.sort(key=lambda a: score_value(a, "asset_score"), reverse=True)
    return out


@app.on_event("startup")
def on_startup() -> None:
    ensure_db()


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    articles = fetch_all_articles()
    n = len(articles)
    keep = sum(1 for a in articles if (a.get("priority") or "").lower() == "keep")
    avg_rank = sum(score_value(a, "rank_score") for a in articles) / n if n else 0.0
    top_score = max([score_value(a, "rank_score") for a in articles], default=0.0)
    top_papers = sorted(articles, key=lambda a: score_value(a, "rank_score"), reverse=True)[:8]
    dimensions = collect_dimension_stats(articles)
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
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
) -> HTMLResponse:
    all_articles = fetch_all_articles()
    filtered = filter_articles(all_articles, q=q, priority=priority, sort=sort)[:limit]
    return templates.TemplateResponse(
        "articles.html",
        {
            "request": request,
            "articles": filtered,
            "total": len(all_articles),
            "shown": len(filtered),
            "q": q,
            "priority": priority,
            "sort": sort,
            "limit": limit,
        },
    )


@app.get("/assets", response_class=HTMLResponse)
def assets_page(
    request: Request,
    q: str = Query(""),
    code_status: str = Query(""),
    pdf_status: str = Query(""),
    sort: str = Query("asset_score"),
    limit: int = Query(100, ge=1, le=1000),
) -> HTMLResponse:
    all_assets = fetch_all_assets()
    filtered = filter_assets(all_assets, q=q, code_status=code_status, pdf_status=pdf_status, sort=sort)[:limit]
    return templates.TemplateResponse(
        "assets.html",
        {
            "request": request,
            "assets": filtered,
            "total": len(all_assets),
            "shown": len(filtered),
            "q": q,
            "code_status": code_status,
            "pdf_status": pdf_status,
            "sort": sort,
            "limit": limit,
        },
    )


@app.get("/assets/{asset_id}", response_class=HTMLResponse)
def asset_detail(request: Request, asset_id: str) -> HTMLResponse:
    ensure_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
    if row is None:
        return templates.TemplateResponse(
            "asset_detail.html",
            {"request": request, "asset": None},
            status_code=404,
        )
    asset = row_to_dict(row)
    return templates.TemplateResponse("asset_detail.html", {"request": request, "asset": asset})


@app.get("/articles/{article_id}", response_class=HTMLResponse)
def article_detail(request: Request, article_id: int) -> HTMLResponse:
    ensure_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    if row is None:
        return templates.TemplateResponse(
            "article_detail.html",
            {"request": request, "article": None, "scores": []},
            status_code=404,
        )
    article = row_to_dict(row)
    return templates.TemplateResponse(
        "article_detail.html",
        {"request": request, "article": article, "scores": score_items(article)},
    )
