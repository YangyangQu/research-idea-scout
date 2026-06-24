#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable


def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception as e:
                print(f"[WARN] skip bad JSON line {line_no}: {e}")
                continue
            if isinstance(obj, dict):
                yield obj


def as_float(x: Any) -> float:
    try:
        return float(x or 0.0)
    except Exception:
        return 0.0


def as_int(x: Any) -> int:
    try:
        return int(x or 0)
    except Exception:
        return 0


def as_text(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, (list, dict)):
        return json.dumps(x, ensure_ascii=False)
    return str(x)


def ensure_db(conn: sqlite3.Connection) -> None:
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


def import_rows(input_path: Path, db_path: Path, replace: bool = True) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    ensure_db(conn)
    if replace:
        conn.execute("DELETE FROM articles")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'articles'")

    n = 0
    for obj in read_jsonl(input_path):
        scores = obj.get("scores") if isinstance(obj.get("scores"), dict) else {}
        row = {
            "title": as_text(obj.get("title")),
            "abstract": as_text(obj.get("abstract")),
            "venue": as_text(obj.get("venue")),
            "year": as_int(obj.get("year")),
            "url": as_text(obj.get("url") or obj.get("pdf_url")),
            "authors": as_text(obj.get("authors")),
            "priority": as_text(obj.get("priority") or obj.get("light_priority") or "maybe"),
            "profile_name": as_text(obj.get("profile_name")),
            "idea_core": as_text(obj.get("idea_core") or obj.get("theory_analysis_zh_md")),
            "transferable_mechanism": as_text(obj.get("transferable_mechanism") or obj.get("theory_used_how_zh_md")),
            "fit_reason": as_text(obj.get("fit_reason") or obj.get("recommendation_zh")),
            "risk_or_limitation": as_text(obj.get("risk_or_limitation") or obj.get("deep_risk_reason_zh")),
            "rank_score": as_float(obj.get("rank_score") or obj.get("final_score") or obj.get("rank_score_wp2_accent")),
            "score_overall_fit": as_float(obj.get("score_overall_fit") or obj.get("deep_overall_recommendation_score")),
            "score_theory_novelty": as_float(obj.get("score_theory_novelty") or obj.get("deep_theory_novelty_score")),
            "scores_json": json.dumps(scores, ensure_ascii=False),
            "raw_json": json.dumps(obj, ensure_ascii=False),
        }
        conn.execute(
            """
            INSERT INTO articles (
                title, abstract, venue, year, url, authors, priority, profile_name,
                idea_core, transferable_mechanism, fit_reason, risk_or_limitation,
                rank_score, score_overall_fit, score_theory_novelty, scores_json, raw_json
            ) VALUES (
                :title, :abstract, :venue, :year, :url, :authors, :priority, :profile_name,
                :idea_core, :transferable_mechanism, :fit_reason, :risk_or_limitation,
                :rank_score, :score_overall_fit, :score_theory_novelty, :scores_json, :raw_json
            )
            """,
            row,
        )
        n += 1
    conn.commit()
    conn.close()
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description="Import IdeaScout JSONL output into the web portal SQLite database.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--db", default="web/ideascout_portal.db")
    ap.add_argument("--append", action="store_true", help="Append instead of replacing existing articles.")
    args = ap.parse_args()
    n = import_rows(Path(args.input), Path(args.db), replace=not args.append)
    print(json.dumps({"input": args.input, "db": args.db, "rows": n}, indent=2))


if __name__ == "__main__":
    main()
