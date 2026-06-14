from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


def read_jsonl(path: str | Path) -> Iterable[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return
    with p.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    yield obj
            except Exception as e:
                raise ValueError(f"Bad JSONL at {p}:{line_no}: {e}") from e


def write_jsonl(path: str | Path, rows: Iterable[Dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for obj in rows:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def append_jsonl(path: str | Path, obj: Dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush()


def count_jsonl(path: str | Path) -> int:
    p = Path(path)
    if not p.exists():
        return 0
    return sum(1 for _ in read_jsonl(p))


def paper_key(obj: Dict[str, Any]) -> str:
    for k in ["paper_id", "id", "openreview_id", "doi", "url", "pdf_url"]:
        if obj.get(k):
            return f"{k}::{obj[k]}"
    seed = f"{obj.get('title','')}::{obj.get('venue','')}::{obj.get('year','')}"
    return "sha1::" + hashlib.sha1(seed.encode("utf-8")).hexdigest()


def load_done_keys(path: str | Path) -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    return {paper_key(o) for o in read_jsonl(p)}


def norm_year(y: Any) -> int | None:
    try:
        return int(y)
    except Exception:
        return None


def clean_text(x: Any, max_chars: int = 0) -> str:
    import re

    s = str(x or "").replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if max_chars and max_chars > 0 and len(s) > max_chars:
        return s[:max_chars] + " ..."
    return s


def write_csv(path: str | Path, rows: List[Dict[str, Any]], fields: List[str]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})
