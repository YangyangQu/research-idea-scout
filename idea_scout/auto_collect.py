from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from .filter_candidates import score_rule_based
from .io_utils import clean_text, norm_year, paper_key, read_jsonl, write_jsonl
from .profile import Profile, load_profile


AI_VENUES = {
    "aaai",
    "acl",
    "acm mm",
    "chi",
    "colm",
    "colt",
    "corl",
    "cvpr",
    "eccv",
    "emnlp",
    "hri",
    "iccv",
    "iclr",
    "icml",
    "icra",
    "ijcai",
    "iros",
    "kdd",
    "naacl",
    "neurips",
    "nips",
    "siggraph",
    "uist",
    "wacv",
}

DEFAULT_AI_CONTEXT_TERMS = [
    "artificial intelligence",
    "machine learning",
    "computer vision",
    "multimodal learning",
    "vision language model",
    "robotics",
    "human computer interaction",
]

TOPIC_ANCHOR_TERMS = [
    *DEFAULT_AI_CONTEXT_TERMS,
    "deep learning",
    "neural",
    "transformer",
    "foundation model",
    "vision language",
    "multimodal",
    "video",
    "egocentric",
    "first-person",
    "first person",
    "wearable",
    "augmented reality",
    "action anticipation",
    "action recognition",
    "activity recognition",
    "procedural",
    "procedure",
    "step",
    "workflow",
    "task progress",
    "task graph",
    "assistant",
    "assistance",
    "proactive",
    "online",
    "streaming",
]

OFF_TOPIC_DOMAIN_TERMS = [
    "agriculture",
    "biodiversity",
    "cancer",
    "clinical",
    "covid",
    "deep-sea mining",
    "ecg",
    "electrocardiogram",
    "education",
    "epidemic",
    "freelancing",
    "health care",
    "healthcare",
    "influenza",
    "learner",
    "medicine",
    "menstrual",
    "online learning",
    "patient",
    "pathology",
    "polyp",
    "public health",
    "remote freelancing",
    "student",
    "wastewater",
]

OFF_TOPIC_CORE_ANCHORS = [
    "egocentric",
    "first-person",
    "first person",
    "procedural",
    "procedure",
    "step",
    "workflow",
    "task graph",
    "task progress",
    "mistake detection",
    "proactive assistant",
    "streaming video",
    "video streams",
]

CORE_TOPIC_ANCHOR_TERMS = [
    "egocentric",
    "first-person",
    "first person",
    "wearable-egocentric",
    "procedural",
    "procedure",
    "step",
    "step-by-step",
    "workflow",
    "task graph",
    "task progress",
    "mistake detection",
    "out-of-plan",
    "assistant",
    "assistance",
    "proactive",
    "intervention",
    "action anticipation",
    "action forecasting",
    "online action detection",
    "temporal action segmentation",
    "streaming video assistance",
]

HIGH_VALUE_CORE_TOPIC_TERMS = [
    "procedural",
    "procedure",
    "step",
    "step-by-step",
    "workflow",
    "task graph",
    "task progress",
    "mistake detection",
    "out-of-plan",
    "assistant",
    "assistance",
    "proactive",
    "intervention",
    "action anticipation",
    "action forecasting",
    "online action detection",
    "temporal action segmentation",
    "streaming video assistance",
]

GENERIC_AI_VIDEO_TERMS = [
    "artificial intelligence",
    "computer vision",
    "deep learning",
    "human activity",
    "activity recognition",
    "video",
    "surveillance",
    "online",
    "real-time",
]

SOFT_MATCH_STOPWORDS = {
    "and",
    "for",
    "from",
    "with",
    "that",
    "this",
    "into",
    "using",
    "based",
    "towards",
    "toward",
    "online",
}

STOP_QUERY_TERMS = {
    "benchmark",
    "dataset",
    "dataset only",
    "leaderboard",
    "survey",
    "classification only",
    "segmentation only",
}

ARXIV_CATEGORIES = ["cs.CV", "cs.AI", "cs.LG", "cs.CL", "cs.RO", "cs.HC", "cs.MM"]


@dataclass(frozen=True)
class Preset:
    name: str
    raw_collect_limit: int
    prefilter_keep: int
    score_top_k: int
    per_query_limit: int
    per_query_keep: int
    max_queries: int
    abstract_max_chars: int
    years: str
    sources: Tuple[str, ...]


PRESETS = {
    "frugal": Preset(
        name="frugal",
        raw_collect_limit=400,
        prefilter_keep=80,
        score_top_k=30,
        per_query_limit=35,
        per_query_keep=10,
        max_queries=8,
        abstract_max_chars=1200,
        years="2022-2026",
        sources=("openalex", "semanticscholar", "arxiv"),
    ),
    "balanced": Preset(
        name="balanced",
        raw_collect_limit=1200,
        prefilter_keep=160,
        score_top_k=80,
        per_query_limit=60,
        per_query_keep=25,
        max_queries=12,
        abstract_max_chars=1600,
        years="2021-2026",
        sources=("openalex", "semanticscholar", "arxiv"),
    ),
    "exploratory": Preset(
        name="exploratory",
        raw_collect_limit=3000,
        prefilter_keep=350,
        score_top_k=200,
        per_query_limit=100,
        per_query_keep=40,
        max_queries=18,
        abstract_max_chars=1800,
        years="2019-2026",
        sources=("openalex", "semanticscholar", "arxiv"),
    ),
}


def resolve_preset(name: str, **overrides: Any) -> Preset:
    if name not in PRESETS:
        raise ValueError(f"Unknown preset {name!r}. Choose one of: {', '.join(PRESETS)}")
    preset = PRESETS[name]
    updates = {k: v for k, v in overrides.items() if v is not None}
    if not updates:
        return preset
    allowed = set(preset.__dataclass_fields__)
    bad = sorted(set(updates) - allowed)
    if bad:
        raise ValueError(f"Unknown preset overrides: {', '.join(bad)}")
    return replace(preset, **updates)


def parse_year_range(spec: str) -> Tuple[int | None, int | None]:
    spec = str(spec or "").strip()
    if not spec:
        return None, None
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        return (int(lo) if lo else None), (int(hi) if hi else None)
    y = int(spec)
    return y, y


def in_year_range(year: Any, years: str) -> bool:
    y = norm_year(year)
    if y is None:
        return True
    lo, hi = parse_year_range(years)
    if lo is not None and y < lo:
        return False
    if hi is not None and y > hi:
        return False
    return True


def normalize_space(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def title_key(title: Any) -> str:
    s = normalize_space(title).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return normalize_space(s)


def text_blob(row: Dict[str, Any]) -> str:
    parts = [row.get("title"), row.get("abstract"), row.get("tldr"), row.get("venue")]
    return " ".join(clean_text(x) for x in parts if x).lower()


def query_candidate_phrases(profile: Profile) -> List[str]:
    fields: List[str] = []
    fields.extend(profile.positive_keywords)
    fields.extend(profile.target_tasks)
    fields.extend(profile.prefer)
    fields.extend(d.description for d in profile.scoring_dimensions)
    candidates: List[str] = []
    for item in fields:
        text = normalize_space(item)
        if not text:
            continue
        lowered = text.lower()
        if lowered in STOP_QUERY_TERMS:
            continue
        if len(text) <= 80 and 2 <= len(text.split()) <= 6:
            candidates.append(text)
            continue
        quoted = re.findall(r"\b[a-zA-Z][a-zA-Z-]*(?:\s+[a-zA-Z][a-zA-Z-]*){1,4}\b", text)
        for phrase in quoted:
            p = phrase.strip(" .,:;").lower()
            if p in STOP_QUERY_TERMS:
                continue
            if any(marker in p for marker in ["helps decide", "whether the", "can be", "user defined"]):
                continue
            if len(p.split()) >= 2:
                candidates.append(phrase.strip(" .,:;"))
    return candidates


def build_queries(profile: Profile, max_queries: int = 12, extra_queries: Sequence[str] | None = None) -> List[str]:
    scored: Dict[str, float] = {}

    def add(q: str, score: float) -> None:
        q = normalize_space(q).lower()
        if not q or q in STOP_QUERY_TERMS:
            return
        if len(q) < 4 or len(q.split()) > 8:
            return
        scored[q] = max(scored.get(q, -999), score)

    for q in extra_queries or []:
        add(q, 100.0)

    for kw in profile.positive_keywords:
        low = str(kw).lower()
        score = 50.0 if " " in str(kw) else 20.0
        if any(x in low for x in ["timing", "intervention", "assistant", "egocentric", "procedural", "dialogue"]):
            score += 25.0
        if "egocentric" in low and "video" in low:
            score += 10.0
        add(kw, score)

    for phrase in query_candidate_phrases(profile):
        bonus = 35.0
        low = phrase.lower()
        if any(x in low for x in ["timing", "intervention", "assistant", "egocentric", "procedural", "dialogue"]):
            bonus += 15.0
        add(phrase, bonus)

    fallback = [
        "intervention timing",
        "proactive assistant",
        "egocentric procedural assistance",
        "streaming video assistance",
        "procedural mistake detection",
        "task progress monitoring",
        "action anticipation",
        "dialogue state tracking",
        "recovery tracking",
        "online task monitoring",
        "multimodal assistant",
        "human AI assistance",
    ]
    for idx, q in enumerate(fallback):
        add(q, 80.0 - idx * 0.1)

    queries = [q for q, _ in sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))]
    return queries[:max_queries]


def request_json(url: str, timeout: int = 30, headers: Dict[str, str] | None = None) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "IdeaScout/0.1 (mailto:research@example.com)",
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def reconstruct_openalex_abstract(index: Dict[str, List[int]] | None) -> str:
    if not index:
        return ""
    positions: List[Tuple[int, str]] = []
    for token, locs in index.items():
        for pos in locs:
            positions.append((int(pos), token))
    if not positions:
        return ""
    positions.sort(key=lambda x: x[0])
    words = [word for _, word in positions]
    text = " ".join(words)
    text = re.sub(r"\s+([,.;:!?%)\]])", r"\1", text)
    text = re.sub(r"([(])\s+", r"\1", text)
    return normalize_space(text)


def normalize_openalex_work(work: Dict[str, Any], query: str) -> Dict[str, Any]:
    primary = work.get("primary_location") or {}
    source = primary.get("source") or {}
    authorships = work.get("authorships") or []
    authors = []
    for item in authorships[:12]:
        author = item.get("author") or {}
        if author.get("display_name"):
            authors.append(author["display_name"])
    ids = work.get("ids") or {}
    doi = work.get("doi") or ids.get("doi")
    url = doi or ids.get("openalex") or work.get("id")
    pdf_url = ""
    oa = work.get("open_access") or {}
    if oa.get("oa_url"):
        pdf_url = oa.get("oa_url")
    return {
        "paper_id": work.get("id"),
        "title": normalize_space(work.get("title") or work.get("display_name")),
        "abstract": reconstruct_openalex_abstract(work.get("abstract_inverted_index")),
        "venue": source.get("display_name") or work.get("host_venue", {}).get("display_name") or "",
        "year": work.get("publication_year"),
        "url": url,
        "pdf_url": pdf_url,
        "doi": doi,
        "authors": authors,
        "citation_count": work.get("cited_by_count") or 0,
        "source": "openalex",
        "source_query": query,
    }


def openalex_search(query: str, limit: int, years: str) -> List[Dict[str, Any]]:
    lo, hi = parse_year_range(years)
    filters = ["type:article"]
    if lo:
        filters.append(f"from_publication_date:{lo}-01-01")
    if hi:
        filters.append(f"to_publication_date:{hi}-12-31")
    params = {
        "search": query,
        "filter": ",".join(filters),
        "per-page": str(min(max(limit, 1), 200)),
        "select": ",".join(
            [
                "id",
                "doi",
                "ids",
                "title",
                "display_name",
                "publication_year",
                "abstract_inverted_index",
                "primary_location",
                "authorships",
                "cited_by_count",
                "open_access",
            ]
        ),
    }
    mailto = os.environ.get("OPENALEX_MAILTO")
    if mailto:
        params["mailto"] = mailto
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    data = request_json(url)
    return [normalize_openalex_work(w, query) for w in data.get("results", [])]


def normalize_semantic_scholar_paper(paper: Dict[str, Any], query: str) -> Dict[str, Any]:
    authors = [a.get("name", "") for a in paper.get("authors") or [] if a.get("name")]
    external = paper.get("externalIds") or {}
    tldr = paper.get("tldr") or {}
    oa = paper.get("openAccessPdf") or {}
    doi = external.get("DOI")
    arxiv_id = external.get("ArXiv")
    url = paper.get("url")
    if doi:
        url = f"https://doi.org/{doi}"
    elif arxiv_id:
        url = f"https://arxiv.org/abs/{arxiv_id}"
    return {
        "paper_id": paper.get("paperId"),
        "title": normalize_space(paper.get("title")),
        "abstract": normalize_space(paper.get("abstract")),
        "venue": paper.get("venue") or "",
        "year": paper.get("year"),
        "url": url or "",
        "pdf_url": oa.get("url") or (f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else ""),
        "doi": doi,
        "arxiv_id": arxiv_id,
        "authors": authors,
        "citation_count": paper.get("citationCount") or 0,
        "tldr": tldr.get("text") or "",
        "source": "semanticscholar",
        "source_query": query,
    }


def semantic_scholar_search(query: str, limit: int, years: str) -> List[Dict[str, Any]]:
    fields = [
        "paperId",
        "title",
        "abstract",
        "venue",
        "year",
        "url",
        "authors",
        "citationCount",
        "externalIds",
        "openAccessPdf",
        "tldr",
        "fieldsOfStudy",
        "publicationTypes",
    ]
    params = {
        "query": query,
        "limit": str(min(max(limit, 1), 100)),
        "fields": ",".join(fields),
        "fieldsOfStudy": "Computer Science",
    }
    lo, hi = parse_year_range(years)
    if lo or hi:
        params["year"] = f"{lo or ''}-{hi or ''}"
    headers = {}
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(params)
    data = request_json(url, headers=headers)
    return [normalize_semantic_scholar_paper(p, query) for p in data.get("data", [])]


def normalize_arxiv_entry(entry: ET.Element, query: str) -> Dict[str, Any]:
    ns = "{http://www.w3.org/2005/Atom}"
    aid = entry.findtext(f"{ns}id", "").split("/abs/")[-1]
    base_id = aid.split("v")[0]
    title = normalize_space(entry.findtext(f"{ns}title", ""))
    abstract = normalize_space(entry.findtext(f"{ns}summary", ""))
    authors = [a.findtext(f"{ns}name", "") for a in entry.findall(f"{ns}author")]
    published = entry.findtext(f"{ns}published", "")
    year = norm_year(published[:4])
    categories = [c.get("term", "") for c in entry.findall(f"{ns}category")]
    return {
        "paper_id": f"arxiv:{base_id}",
        "title": title,
        "abstract": abstract,
        "venue": "arXiv",
        "year": year,
        "url": f"https://arxiv.org/abs/{base_id}",
        "pdf_url": f"https://arxiv.org/pdf/{base_id}.pdf",
        "arxiv_id": base_id,
        "authors": authors,
        "categories": categories,
        "citation_count": 0,
        "source": "arxiv",
        "source_query": query,
    }


def arxiv_search(query: str, limit: int, years: str) -> List[Dict[str, Any]]:
    category_part = " OR ".join(f"cat:{cat}" for cat in ARXIV_CATEGORIES)
    search_query = f"all:{query} AND ({category_part})"
    params = {
        "search_query": search_query,
        "start": "0",
        "max_results": str(min(max(limit, 1), 100)),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "IdeaScout/0.1"})
    with urllib.request.urlopen(req, timeout=30) as response:
        root = ET.fromstring(response.read())
    rows = [normalize_arxiv_entry(e, query) for e in root.findall("{http://www.w3.org/2005/Atom}entry")]
    return [r for r in rows if in_year_range(r.get("year"), years)]


def collect_from_sources(
    queries: Sequence[str],
    sources: Sequence[str],
    per_query_limit: int,
    years: str,
    raw_collect_limit: int,
    sleep: float = 1.0,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    source_fns = {
        "openalex": openalex_search,
        "semanticscholar": semantic_scholar_search,
        "arxiv": arxiv_search,
    }
    per_source_limit = max(1, math.ceil(per_query_limit / max(len(sources), 1)))
    for query in queries:
        for source in sources:
            if len(rows) >= raw_collect_limit:
                return rows[:raw_collect_limit], failures
            fn = source_fns.get(source)
            if fn is None:
                failures.append({"source": source, "query": query, "error": "unknown source"})
                continue
            try:
                got = fn(query, per_source_limit, years)
                rows.extend(got)
                print(f"[COLLECT] source={source} query={query!r} rows={len(got)} total={len(rows)}", flush=True)
            except urllib.error.HTTPError as e:
                error = f"HTTP {e.code}: {e.reason or ''}".strip()
                if source == "semanticscholar" and e.code == 429:
                    error += "; set SEMANTIC_SCHOLAR_API_KEY for higher rate limits"
                failures.append({"source": source, "query": query, "error": error})
                print(f"[WARN] source={source} query={query!r} failed: {error}", file=sys.stderr, flush=True)
            except Exception as e:
                failures.append({"source": source, "query": query, "error": str(e)})
                print(f"[WARN] source={source} query={query!r} failed: {e}", file=sys.stderr, flush=True)
            time.sleep(max(sleep, 0.0))
    return rows[:raw_collect_limit], failures


def record_quality(row: Dict[str, Any]) -> float:
    score = 0.0
    if clean_text(row.get("title")):
        score += 2.0
    abstract_len = len(clean_text(row.get("abstract")))
    if abstract_len >= 300:
        score += 4.0
    elif abstract_len >= 100:
        score += 2.0
    score += min(float(row.get("citation_count") or 0), 100.0) / 20.0
    if row.get("pdf_url"):
        score += 0.5
    if row.get("url"):
        score += 0.5
    if row.get("source") == "semanticscholar" and row.get("tldr"):
        score += 1.0
    return score


def deduplicate_papers(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    best: Dict[str, Dict[str, Any]] = {}
    title_index: Dict[str, str] = {}
    for row in rows:
        tkey = title_key(row.get("title"))
        key = ""
        for k in ["doi", "arxiv_id", "paper_id", "url"]:
            if row.get(k):
                key = f"{k}:{str(row[k]).lower()}"
                break
        if tkey and tkey in title_index:
            key = title_index[tkey]
        if not key:
            key = f"title:{tkey}"
        if not key or key == "title:":
            continue
        if tkey:
            title_index[tkey] = key
        current = best.get(key)
        if current is None:
            best[key] = dict(row)
            continue
        merged = dict(current)
        for field in ["abstract", "url", "pdf_url", "doi", "arxiv_id", "venue", "tldr"]:
            if not clean_text(merged.get(field)) and clean_text(row.get(field)):
                merged[field] = row.get(field)
        for field in ["authors", "categories"]:
            if not merged.get(field) and row.get(field):
                merged[field] = row.get(field)
        merged["citation_count"] = max(float(merged.get("citation_count") or 0), float(row.get("citation_count") or 0))
        sources = set(str(merged.get("source", "")).split("+")) | set(str(row.get("source", "")).split("+"))
        merged["source"] = "+".join(sorted(x for x in sources if x))
        if record_quality(row) > record_quality(merged):
            replacement = dict(row)
            for k, v in merged.items():
                if not replacement.get(k) and v:
                    replacement[k] = v
            replacement["source"] = merged["source"]
            replacement["citation_count"] = merged["citation_count"]
            merged = replacement
        best[key] = merged
    return list(best.values())


def venue_bonus(venue: Any) -> float:
    v = normalize_space(venue).lower()
    if not v:
        return 0.0
    if v == "arxiv":
        return 0.5
    if any(name in v for name in AI_VENUES):
        return 1.5
    return 0.0


def recency_bonus(year: Any) -> float:
    y = norm_year(year)
    if y is None:
        return 0.0
    if y >= 2024:
        return 1.0
    if y >= 2021:
        return 0.5
    return 0.0


def negative_penalty(blob: str, profile: Profile) -> float:
    penalty = 0.0
    for kw in profile.negative_keywords:
        k = kw.lower().strip()
        if k and k in blob:
            penalty += 2.0 if " " in k else 1.2
    for phrase in ["survey", "benchmark", "dataset", "leaderboard"]:
        if phrase in blob:
            penalty += 0.8
    return penalty


def profile_anchor_terms(profile: Profile, key: str, use_profile_anchors: bool = True) -> List[str]:
    if not use_profile_anchors:
        return []
    anchors = getattr(profile, "topic_anchors", {}) or {}
    values = anchors.get(key, []) if isinstance(anchors, dict) else []
    return [str(x).lower().strip() for x in values if str(x).strip()]


def merged_terms(default_terms: Sequence[str], extra_terms: Sequence[str]) -> List[str]:
    terms: List[str] = []
    for term in [*default_terms, *extra_terms]:
        t = str(term).lower().strip()
        if t and t not in terms:
            terms.append(t)
    return terms


def topic_anchor_score(blob: str, profile: Profile, use_profile_anchors: bool = True) -> Tuple[float, List[str]]:
    hits: List[str] = []
    terms = merged_terms(
        TOPIC_ANCHOR_TERMS,
        [
            *profile_anchor_terms(profile, "high_value", use_profile_anchors),
            *profile_anchor_terms(profile, "required_any", use_profile_anchors),
            *profile_anchor_terms(profile, "broad_ai", use_profile_anchors),
        ],
    )
    for term in terms:
        t = term.lower().strip()
        if t and t in blob and t not in hits:
            hits.append(t)
    if not hits:
        return -2.5, []
    return min(len(hits), 5) * 0.7, hits[:8]


def off_topic_domain_penalty(blob: str, profile: Profile, use_profile_anchors: bool = True) -> Tuple[float, List[str]]:
    hits: List[str] = []
    terms = merged_terms(OFF_TOPIC_DOMAIN_TERMS, profile_anchor_terms(profile, "off_topic_domains", use_profile_anchors))
    for term in terms:
        t = term.lower().strip()
        if t and t in blob and t not in hits:
            hits.append(t)
    if not hits:
        return 0.0, []

    core_hits = [t for t in OFF_TOPIC_CORE_ANCHORS if t in blob]
    if core_hits:
        return min(len(hits), 4) * 0.4, hits[:8]
    return 3.5 + min(len(hits), 4) * 0.5, hits[:8]


def weak_topic_penalty(blob: str, profile: Profile, use_profile_anchors: bool = True) -> Tuple[float, List[str]]:
    core_hits: List[str] = []
    core_terms = merged_terms(
        CORE_TOPIC_ANCHOR_TERMS,
        [
            *profile_anchor_terms(profile, "high_value", use_profile_anchors),
            *profile_anchor_terms(profile, "required_any", use_profile_anchors),
        ],
    )
    for term in core_terms:
        t = term.lower().strip()
        if t and t in blob and t not in core_hits:
            core_hits.append(t)

    generic_hits = []
    generic_terms = merged_terms(GENERIC_AI_VIDEO_TERMS, profile_anchor_terms(profile, "broad_ai", use_profile_anchors))
    for term in generic_terms:
        t = term.lower().strip()
        if t and t in blob and t not in generic_hits:
            generic_hits.append(t)

    if core_hits:
        high_value_terms = merged_terms(HIGH_VALUE_CORE_TOPIC_TERMS, profile_anchor_terms(profile, "high_value", use_profile_anchors))
        high_value_hits = [t for t in high_value_terms if t in blob]
        if high_value_hits:
            return 0.0, core_hits[:8]
        if generic_hits:
            return 3.0, core_hits[:8]
        return 0.8, core_hits[:8]

    if generic_hits:
        return 1.8, []
    return 0.0, []


def profile_phrase_tokens(phrase: str) -> List[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9-]+", phrase.lower())
    return [t for t in tokens if len(t) > 3 and t not in SOFT_MATCH_STOPWORDS]


def token_in_blob(token: str, blob: str) -> bool:
    pattern = r"\b" + re.escape(token) + r"s?\b"
    return re.search(pattern, blob) is not None


def soft_positive_score(blob: str, profile: Profile, exact_hits: Sequence[str]) -> Tuple[float, List[str]]:
    exact = {h.lower().strip() for h in exact_hits}
    hits: List[str] = []
    score = 0.0
    for kw in profile.positive_keywords:
        key = kw.lower().strip()
        if not key or key in exact:
            continue
        tokens = profile_phrase_tokens(key)
        if len(tokens) < 2:
            continue
        matched = [t for t in tokens if token_in_blob(t, blob)]
        coverage = len(matched) / len(tokens)
        if len(matched) >= 2 and coverage >= 0.6:
            hits.append(kw)
            score += 1.0 + 0.25 * len(matched)
    return min(score, 5.0), hits[:8]


def cheap_score(row: Dict[str, Any], profile: Profile, use_profile_anchors: bool = True) -> Dict[str, Any]:
    rule = score_rule_based(row, profile)
    blob = text_blob(row)
    source_query = str(row.get("source_query") or "").lower()
    query_hits = sum(1 for token in source_query.split() if len(token) > 3 and token in blob)
    citations = float(row.get("citation_count") or 0)
    anchor_score, anchor_hits = topic_anchor_score(blob, profile, use_profile_anchors=use_profile_anchors)
    off_topic_penalty, off_topic_hits = off_topic_domain_penalty(blob, profile, use_profile_anchors=use_profile_anchors)
    weak_penalty, core_topic_hits = weak_topic_penalty(blob, profile, use_profile_anchors=use_profile_anchors)
    soft_score, soft_hits = soft_positive_score(blob, profile, rule.get("rule_positive_hits") or [])
    score = (
        float(rule["rule_score"])
        + soft_score
        + 0.35 * min(citations, 80.0) ** 0.5
        + venue_bonus(row.get("venue"))
        + recency_bonus(row.get("year"))
        + anchor_score
        + 0.3 * query_hits
        + (0.8 if len(clean_text(row.get("abstract"))) >= 300 else 0.0)
        - negative_penalty(blob, profile)
        - off_topic_penalty
        - weak_penalty
    )
    out = dict(row)
    out.update(rule)
    out["topic_anchor_hits"] = anchor_hits
    out["core_topic_hits"] = core_topic_hits
    out["soft_positive_hits"] = soft_hits
    out["off_topic_domain_hits"] = off_topic_hits
    out["cheap_score"] = round(score, 4)
    out["profile_name"] = profile.name
    return out


def prefilter_papers(
    rows: Iterable[Dict[str, Any]],
    profile: Profile,
    keep_total: int,
    per_query_keep: int,
    use_profile_anchors: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    scored = [cheap_score(r, profile, use_profile_anchors=use_profile_anchors) for r in rows if clean_text(r.get("title")) and clean_text(r.get("abstract"))]
    scored.sort(key=lambda r: (float(r.get("cheap_score") or 0), float(r.get("citation_count") or 0)), reverse=True)
    by_query: Counter[str] = Counter()
    keep: List[Dict[str, Any]] = []
    reject: List[Dict[str, Any]] = []
    for row in scored:
        query = str(row.get("source_query") or "")
        if len(keep) < keep_total and by_query[query] < per_query_keep:
            keep.append(row)
            by_query[query] += 1
        else:
            reject.append(row)
    summary = {
        "profile": profile.name,
        "kept": len(keep),
        "rejected": len(reject),
        "avg_cheap_score": round(sum(float(r.get("cheap_score") or 0) for r in keep) / len(keep), 4) if keep else 0,
        "by_source": dict(Counter(str(r.get("source") or "") for r in keep)),
        "by_query": dict(Counter(str(r.get("source_query") or "") for r in keep)),
        "profile_anchors": bool(use_profile_anchors and getattr(profile, "topic_anchors", None)),
    }
    return keep, reject, summary


def run_subprocess(cmd: List[str], cwd: Path) -> None:
    print("[CMD]", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd), check=True)


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return s or "ideascout"


def default_paths(root: Path, profile: Profile) -> Dict[str, Path]:
    slug = slugify(profile.name)
    return {
        "raw": root / "data" / f"{slug}_raw_papers.jsonl",
        "raw_failures": root / "data" / f"{slug}_collect_failures.jsonl",
        "prefiltered": root / "data" / f"{slug}_prefiltered.jsonl",
        "rejected": root / "data" / f"{slug}_prefilter_rejected.jsonl",
        "summary": root / "reports" / f"{slug}_auto_collect_summary.json",
        "scores": root / "data" / f"{slug}_idea_scores.jsonl",
        "score_failures": root / "data" / f"{slug}_idea_score_failures.jsonl",
        "csv": root / "data" / f"{slug}_top_ideas.csv",
        "db": root / "web" / f"{slug}_portal.db",
    }


def write_summary(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Collect AI papers from public metadata APIs and run the IdeaScout funnel.")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--preset", choices=sorted(PRESETS), default="balanced")
    ap.add_argument("--sources", nargs="*", default=None, choices=["openalex", "semanticscholar", "arxiv"])
    ap.add_argument("--extra-query", action="append", default=[])
    ap.add_argument("--raw-input", default="", help="Reuse an existing raw JSONL instead of collecting from APIs.")
    ap.add_argument("--raw-output", default="")
    ap.add_argument("--prefilter-output", default="")
    ap.add_argument("--rejected-output", default="")
    ap.add_argument("--summary-output", default="")
    ap.add_argument("--scores-output", default="")
    ap.add_argument("--csv-output", default="")
    ap.add_argument("--db-output", default="")
    ap.add_argument("--raw-collect-limit", type=int, default=None)
    ap.add_argument("--prefilter-keep", type=int, default=None)
    ap.add_argument("--score-top-k", type=int, default=None)
    ap.add_argument("--per-query-limit", type=int, default=None)
    ap.add_argument("--per-query-keep", type=int, default=None)
    ap.add_argument("--max-queries", type=int, default=None)
    ap.add_argument("--abstract-max-chars", type=int, default=None)
    ap.add_argument("--years", default=None)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--score", action="store_true", help="Run Codex LLM scoring after prefiltering.")
    ap.add_argument("--no-export", action="store_true")
    ap.add_argument("--import-portal", action="store_true")
    ap.add_argument("--no-profile-anchors", action="store_true", help="Ignore topic_anchors from the profile YAML.")
    ap.add_argument("--codex-cmd", default="codex.cmd exec" if os.name == "nt" else "codex exec")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--max-retries", type=int, default=2)
    args = ap.parse_args()

    root = Path.cwd()
    profile = load_profile(args.profile)
    preset = resolve_preset(
        args.preset,
        raw_collect_limit=args.raw_collect_limit,
        prefilter_keep=args.prefilter_keep,
        score_top_k=args.score_top_k,
        per_query_limit=args.per_query_limit,
        per_query_keep=args.per_query_keep,
        max_queries=args.max_queries,
        abstract_max_chars=args.abstract_max_chars,
        years=args.years,
        sources=tuple(args.sources) if args.sources else None,
    )
    paths = default_paths(root, profile)
    raw_path = Path(args.raw_output) if args.raw_output else paths["raw"]
    prefilter_path = Path(args.prefilter_output) if args.prefilter_output else paths["prefiltered"]
    rejected_path = Path(args.rejected_output) if args.rejected_output else paths["rejected"]
    summary_path = Path(args.summary_output) if args.summary_output else paths["summary"]
    scores_path = Path(args.scores_output) if args.scores_output else paths["scores"]
    csv_path = Path(args.csv_output) if args.csv_output else paths["csv"]
    db_path = Path(args.db_output) if args.db_output else paths["db"]

    if args.raw_input:
        raw_rows = list(read_jsonl(args.raw_input))
        failures: List[Dict[str, Any]] = []
        print(f"[RAW] loaded {len(raw_rows)} rows from {args.raw_input}", flush=True)
    else:
        queries = build_queries(profile, max_queries=preset.max_queries, extra_queries=args.extra_query)
        print(f"[QUERIES] {json.dumps(queries, ensure_ascii=False)}", flush=True)
        raw_rows, failures = collect_from_sources(
            queries=queries,
            sources=preset.sources,
            per_query_limit=preset.per_query_limit,
            years=preset.years,
            raw_collect_limit=preset.raw_collect_limit,
            sleep=args.sleep,
        )
        if failures:
            write_jsonl(paths["raw_failures"], failures)

    raw_rows = [r for r in raw_rows if in_year_range(r.get("year"), preset.years)]
    deduped = deduplicate_papers(raw_rows)
    write_jsonl(raw_path, deduped)
    keep, reject, summary = prefilter_papers(
        deduped,
        profile,
        keep_total=preset.prefilter_keep,
        per_query_keep=preset.per_query_keep,
        use_profile_anchors=not args.no_profile_anchors,
    )
    write_jsonl(prefilter_path, keep)
    write_jsonl(rejected_path, reject)
    summary.update(
        {
            "preset": preset.__dict__,
            "raw_rows": len(raw_rows),
            "deduped_rows": len(deduped),
            "raw_output": str(raw_path),
            "prefilter_output": str(prefilter_path),
            "rejected_output": str(rejected_path),
            "score_output": str(scores_path),
            "csv_output": str(csv_path),
            "collect_failures": len(failures),
        }
    )
    write_summary(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)

    if args.score:
        run_subprocess(
            [
                sys.executable,
                "-u",
                "scripts/run_autoretry.py",
                "--input",
                str(prefilter_path),
                "--profile",
                args.profile,
                "--output",
                str(scores_path),
                "--failures-output",
                str(paths["score_failures"]),
                "--top-k",
                str(preset.score_top_k),
                "--codex-cmd",
                args.codex_cmd,
                "--batch-size",
                "1",
                "--sleep-between-rounds",
                "2",
                "--timeout",
                str(args.timeout),
                "--max-retries",
                str(args.max_retries),
                "--abstract-max-chars",
                str(preset.abstract_max_chars),
            ],
            root,
        )
        if not args.no_export:
            run_subprocess(
                [
                    sys.executable,
                    "scripts/export_rankings.py",
                    "--input",
                    str(scores_path),
                    "--profile",
                    args.profile,
                    "--output",
                    str(csv_path),
                    "--top-k",
                    str(preset.score_top_k),
                ],
                root,
            )
        if args.import_portal:
            run_subprocess(
                [
                    sys.executable,
                    "web/import_jsonl.py",
                    "--input",
                    str(scores_path),
                    "--db",
                    str(db_path),
                ],
                root,
            )


if __name__ == "__main__":
    main()
