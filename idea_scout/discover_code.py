from __future__ import annotations

import argparse
import json
import html as html_lib
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List

from .assets import compute_asset_score, read_assets, utc_now, write_assets
from .io_utils import clean_text


GITHUB_RE = re.compile(r"https?://(?:www\.)?github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
URL_RE = re.compile(r"https?://[^\s<>\\\]\)}\"']+")
STOPWORDS = {
    "the", "and", "for", "with", "from", "into", "that", "this", "using", "via", "towards", "toward",
    "learning", "deep", "neural", "networks", "network", "model", "models", "paper", "best", "large",
}


Fetcher = Callable[[str, int], str]
GithubSearcher = Callable[[str, int, int], List[Dict[str, Any]]]


def normalize_url(url: str) -> str:
    return clean_text(url).rstrip(".,);:]>}")


def normalize_github_url(url: str) -> str:
    url = normalize_url(url).replace("http://github.com/", "https://github.com/")
    url = url.replace("https://www.github.com/", "https://github.com/")
    match = GITHUB_RE.search(url)
    if not match:
        return ""
    parts = urllib.parse.urlparse(match.group(0)).path.strip("/").split("/")
    if len(parts) < 2:
        return ""
    owner, repo = parts[0], parts[1].removesuffix(".git")
    if not owner or not repo or repo in {"issues", "pulls", "topics"}:
        return ""
    return f"https://github.com/{owner}/{repo}"


def extract_urls(text: str) -> List[str]:
    seen: set[str] = set()
    urls: List[str] = []
    for match in URL_RE.finditer(text or ""):
        url = normalize_url(match.group(0))
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def extract_github_urls(text: str) -> List[str]:
    seen: set[str] = set()
    urls: List[str] = []
    for match in GITHUB_RE.finditer(text or ""):
        url = normalize_github_url(match.group(0))
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def github_url_contexts(html: str) -> List[Dict[str, str]]:
    contexts: List[Dict[str, str]] = []
    seen: set[str] = set()
    anchor_re = re.compile(r"(?is)<a[^>]+href=[\"']([^\"']*github\.com/[^\"']+)[\"'][^>]*>(.*?)</a>")
    for href, label in anchor_re.findall(html or ""):
        url = normalize_github_url(href)
        if not url or url in seen:
            continue
        context = clean_text(html_lib.unescape(re.sub(r"<[^>]+>", " ", label)), 800)
        seen.add(url)
        contexts.append({"url": url, "context": context})

    for match in GITHUB_RE.finditer(html or ""):
        url = normalize_github_url(match.group(0))
        if not url or url in seen:
            continue
        start = max(0, match.start() - 80)
        end = min(len(html), match.end() + 120)
        context = clean_text(html_lib.unescape(re.sub(r"<[^>]+>", " ", html[start:end])), 800)
        seen.add(url)
        contexts.append({"url": url, "context": context})
    return contexts


def homepage_github_match(title: str, html: str) -> Dict[str, str] | None:
    matches = []
    for item in github_url_contexts(html):
        url = item["url"]
        owner_repo = "/".join(urllib.parse.urlparse(url).path.strip("/").split("/")[:2])
        candidate = {
            "html_url": url,
            "full_name": owner_repo,
            "name": owner_repo.split("/")[-1],
            "description": item.get("context", ""),
            "stargazers_count": 0,
        }
        score = candidate_score(title, candidate)
        low_context = item.get("context", "").lower()
        if any(x in low_context for x in ["code", "github", "implementation", "repository", "project"]):
            score += 0.08
        if score >= 0.50:
            matches.append((score, item))
    if not matches:
        return None
    matches.sort(key=lambda x: x[0], reverse=True)
    best = dict(matches[0][1])
    best["match_score"] = str(round(matches[0][0], 4))
    return best


def contextual_homepage_urls(text: str) -> List[str]:
    urls: List[str] = []
    seen: set[str] = set()
    for match in URL_RE.finditer(text or ""):
        start = max(0, match.start() - 90)
        context = text[start:match.end() + 20].lower()
        if not any(label in context for label in ["project", "homepage", "home page", "code", "website", "demo", "available at"]):
            continue
        url = normalize_url(match.group(0))
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def asset_title(asset: Dict[str, Any]) -> str:
    source = (asset.get("source_papers") or [{}])[0]
    raw = asset.get("raw") if isinstance(asset.get("raw"), dict) else {}
    return clean_text(source.get("title") or raw.get("title") or asset.get("source_title"), 500)


def asset_text_path(asset: Dict[str, Any]) -> str:
    pdf = asset.get("pdf") if isinstance(asset.get("pdf"), dict) else {}
    if clean_text(pdf.get("text_path")):
        return clean_text(pdf.get("text_path"))
    for paper in asset.get("source_papers") or []:
        if isinstance(paper, dict) and clean_text(paper.get("text_path")):
            return clean_text(paper.get("text_path"))
    raw = asset.get("raw") if isinstance(asset.get("raw"), dict) else {}
    return clean_text(raw.get("text_path"))


def read_asset_text(asset: Dict[str, Any], max_chars: int = 250_000) -> str:
    path = asset_text_path(asset)
    if path and Path(path).exists():
        return Path(path).read_text(encoding="utf-8", errors="ignore")[:max_chars]
    raw = asset.get("raw") if isinstance(asset.get("raw"), dict) else {}
    parts = [
        asset.get("challenge", ""), asset.get("solution_pattern", ""), asset.get("mechanism", ""),
        "\n".join(asset.get("evidence") or []), raw.get("abstract", ""),
    ]
    return "\n".join(clean_text(p) for p in parts if clean_text(p))


def homepage_candidates(asset: Dict[str, Any], text: str, limit: int = 8) -> List[str]:
    raw = asset.get("raw") if isinstance(asset.get("raw"), dict) else {}
    source = (asset.get("source_papers") or [{}])[0]
    seeds = [raw.get("homepage"), raw.get("project_url"), raw.get("website"), source.get("url"), raw.get("url")]
    urls = []
    for seed in seeds:
        if clean_text(seed):
            urls.append(clean_text(seed))
    urls.extend(contextual_homepage_urls(text))
    urls.extend(extract_urls(text))

    out: List[str] = []
    seen: set[str] = set()
    for url in urls:
        url = normalize_url(url)
        lower = url.lower()
        if not url or url in seen:
            continue
        if "github.com" in lower:
            continue
        if lower.endswith((".pdf", ".zip", ".gz")):
            continue
        if any(x in lower for x in ["doi.org", "arxiv.org", "openaccess.thecvf", "creativecommons.org"]):
            continue
        should_fetch = any(x in lower for x in ["project", "code", "software", "demo", "github.io", "huggingface.co", "paperswithcode"])
        should_fetch = should_fetch or url in contextual_homepage_urls(text)
        if should_fetch:
            seen.add(url)
            out.append(url)
        if len(out) >= limit:
            break
    return out


def fetch_url(url: str, timeout: int = 8) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "research-idea-scout-assets"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read(1_000_000)
    return body.decode("utf-8", errors="ignore")


def title_tokens(title: str) -> List[str]:
    tokens = re.findall(r"[a-z0-9]+", title.lower())
    return [t for t in tokens if len(t) >= 3 and t not in STOPWORDS]


def candidate_score(title: str, candidate: Dict[str, Any]) -> float:
    tokens = title_tokens(title)
    if not tokens:
        return 0.0
    haystack = " ".join([
        clean_text(candidate.get("full_name")), clean_text(candidate.get("name")), clean_text(candidate.get("description")),
    ]).lower()
    matched = sum(1 for token in tokens if token in haystack)
    coverage = matched / len(tokens)
    exact_bonus = 0.35 if title.lower() in haystack else 0.0
    stars = int(candidate.get("stargazers_count") or 0)
    star_bonus = min(0.15, math.log10(stars + 1) / 20) if stars else 0.0
    return round(coverage + exact_bonus + star_bonus, 4)


def github_search_repositories(query: str, timeout: int = 10, per_page: int = 5) -> List[Dict[str, Any]]:
    params = urllib.parse.urlencode({"q": query, "per_page": per_page})
    req = urllib.request.Request(
        f"https://api.github.com/search/repositories?{params}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "research-idea-scout-assets"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("items", []) if isinstance(data, dict) else []
    except urllib.error.HTTPError as e:
        if e.code in {403, 429}:
            raise RuntimeError(f"github_rate_limited:{e.code}") from e
        return []
    except Exception:
        return []


def best_github_search_match(title: str, candidates: Iterable[Dict[str, Any]]) -> Dict[str, Any] | None:
    scored = []
    for candidate in candidates:
        url = normalize_github_url(clean_text(candidate.get("html_url")))
        if not url:
            continue
        score = candidate_score(title, candidate)
        if score >= 0.58:
            scored.append((score, candidate | {"html_url": url}))
    if not scored:
        return None
    scored.sort(key=lambda x: (x[0], int(x[1].get("stargazers_count") or 0)), reverse=True)
    best = scored[0][1]
    best["match_score"] = scored[0][0]
    return best


def set_discovered_code(out: Dict[str, Any], url: str, source: str, confidence: str, evidence: str) -> Dict[str, Any]:
    code = dict(out.get("code") or {})
    sources = list(code.get("discovery_sources") or [])
    sources.append({"source": source, "url": url, "confidence": confidence, "evidence": clean_text(evidence, 500)})
    code.update({
        "url": url,
        "status": "repo_found",
        "runnable_status": "metadata_only",
        "failure_reason": "",
        "discovery_source": source,
        "discovery_confidence": confidence,
        "discovery_sources": sources,
        "checked_at": utc_now(),
    })
    out["code"] = code
    out.setdefault("scores", {})["code_readiness"] = max(float(out.get("scores", {}).get("code_readiness", 0) or 0), 3.0)
    out["scores"]["asset_score"] = compute_asset_score(out)
    out["updated_at"] = utc_now()
    return out


def discover_one(
    asset: Dict[str, Any],
    timeout: int = 8,
    fetcher: Fetcher = fetch_url,
    github_searcher: GithubSearcher = github_search_repositories,
    use_github_search: bool = True,
    force: bool = False,
) -> Dict[str, Any]:
    out = dict(asset)
    code = dict(out.get("code") or {})
    if clean_text(code.get("url")) and not force:
        code.setdefault("discovery_source", "existing")
        code.setdefault("discovery_confidence", "high")
        out["code"] = code
        return out

    text = read_asset_text(out)
    for url in extract_github_urls(text):
        return set_discovered_code(out, url, "full_text", "high", "GitHub URL found in paper text")

    for homepage in homepage_candidates(out, text):
        try:
            html = fetcher(homepage, timeout)
        except Exception:
            continue
        match = homepage_github_match(asset_title(out), html)
        if match:
            found = match["url"]
            code = dict(out.get("code") or {})
            code["homepage_url"] = homepage
            code["implementation_kind"] = "official_or_project"
            code["homepage_match_score"] = match.get("match_score", "")
            out["code"] = code
            return set_discovered_code(out, found, "homepage", "high", homepage)

    if use_github_search:
        title = asset_title(out)
        if title:
            candidates = github_searcher(title, timeout, 5)
            best = best_github_search_match(title, candidates)
            if best:
                confidence = "high" if float(best.get("match_score") or 0) >= 0.85 else "medium"
                code = dict(out.get("code") or {})
                code["implementation_kind"] = "community_or_search_result"
                code["github_match_score"] = best.get("match_score", "")
                out["code"] = code
                evidence = f"{best.get('full_name', '')}: {best.get('description', '')}"
                return set_discovered_code(out, clean_text(best.get("html_url")), "github_search", confidence, evidence)

    code.update({
        "status": "missing",
        "url": "",
        "discovery_source": code.get("discovery_source", "not_found"),
        "discovery_confidence": code.get("discovery_confidence", "none"),
        "checked_at": utc_now(),
    })
    out["code"] = code
    out.setdefault("scores", {})["code_readiness"] = 0.0
    out["scores"]["asset_score"] = compute_asset_score(out)
    out["updated_at"] = utc_now()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Discover code repositories from paper text, project pages, and GitHub search.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--timeout", type=int, default=8)
    ap.add_argument("--no-github-search", action="store_true")
    ap.add_argument("--github-search-delay", type=float, default=0.0)
    ap.add_argument("--max-github-search", type=int, default=0, help="Maximum total GitHub search calls; 0 means unlimited.")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    assets = read_assets(args.input)
    out = []
    search_calls = 0

    def guarded_searcher(query: str, timeout: int, per_page: int) -> List[Dict[str, Any]]:
        nonlocal search_calls
        if args.no_github_search:
            return []
        if args.max_github_search and search_calls >= args.max_github_search:
            return []
        if args.github_search_delay and search_calls > 0:
            time.sleep(args.github_search_delay)
        search_calls += 1
        return github_search_repositories(query, timeout, per_page)

    for asset in assets:
        try:
            out.append(discover_one(
                asset,
                timeout=args.timeout,
                github_searcher=guarded_searcher,
                use_github_search=not args.no_github_search,
                force=args.force,
            ))
        except RuntimeError as e:
            current = dict(asset)
            code = dict(current.get("code") or {})
            code["failure_reason"] = str(e)
            code.setdefault("status", "missing")
            current["code"] = code
            out.append(current)
    write_assets(args.output, out)
    summary: Dict[str, int] = {}
    sources: Dict[str, int] = {}
    for asset in out:
        code = asset.get("code") or {}
        status = code.get("status", "unknown")
        summary[status] = summary.get(status, 0) + 1
        source = code.get("discovery_source", "")
        if source:
            sources[source] = sources.get(source, 0) + 1
    print(json.dumps({
        "input": args.input,
        "output": args.output,
        "assets": len(out),
        "code_status": summary,
        "discovery_sources": sources,
        "github_search_calls": search_calls,
    }, indent=2))


if __name__ == "__main__":
    main()
