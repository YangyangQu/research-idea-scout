from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, Tuple

from .assets import compute_asset_score, read_assets, utc_now, write_assets
from .io_utils import clean_text


GITHUB_RE = re.compile(r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")


def find_github_url(asset: Dict[str, Any]) -> str:
    code = asset.get("code") if isinstance(asset.get("code"), dict) else {}
    candidates = [code.get("url", "")]
    for paper in asset.get("source_papers") or []:
        if isinstance(paper, dict):
            candidates.extend([paper.get("code_url", ""), paper.get("url", ""), paper.get("pdf_url", "")])
    raw = asset.get("raw") if isinstance(asset.get("raw"), dict) else {}
    candidates.extend([raw.get("code_url", ""), raw.get("github_url", ""), raw.get("repo_url", ""), raw.get("url", "")])
    candidates.extend([
        asset.get("challenge", ""),
        asset.get("solution_pattern", ""),
        asset.get("mechanism", ""),
        " ".join(asset.get("evidence") or []),
    ])
    for value in candidates:
        text = clean_text(value)
        match = GITHUB_RE.search(text)
        if match:
            return f"https://github.com/{match.group(1)}/{match.group(2).removesuffix('.git')}"
    return ""


def github_owner_repo(url: str) -> Tuple[str, str]:
    match = GITHUB_RE.search(url)
    if not match:
        return "", ""
    return match.group(1), match.group(2).removesuffix(".git")


def github_api_json(path: str, timeout: int) -> Tuple[Dict[str, Any], str]:
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "research-idea-scout-assets"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), ""
    except urllib.error.HTTPError as e:
        return {}, f"http_{e.code}"
    except Exception as e:
        return {}, str(e)


def github_contents_exists(owner: str, repo: str, names: Iterable[str], timeout: int) -> bool:
    for name in names:
        data, err = github_api_json(f"/repos/{owner}/{repo}/contents/{name}", timeout)
        if data and not err:
            return True
    return False


def verify_one(asset: Dict[str, Any], timeout: int = 12, offline: bool = False) -> Dict[str, Any]:
    out = dict(asset)
    code = dict(out.get("code") or {})
    url = code.get("url") or find_github_url(out)
    code["url"] = url
    code["checked_at"] = utc_now()

    if not url:
        code.update({
            "status": "missing",
            "runnable_status": "not_attempted",
            "failure_reason": "",
        })
        out["code"] = code
        out.setdefault("scores", {})["code_readiness"] = 0.0
        out["scores"]["asset_score"] = compute_asset_score(out)
        return out

    owner, repo = github_owner_repo(url)
    if not owner or not repo:
        code.update({
            "status": "unavailable",
            "runnable_status": "not_attempted",
            "failure_reason": "unsupported_code_url",
        })
        out["code"] = code
        out.setdefault("scores", {})["code_readiness"] = 1.0
        out["scores"]["asset_score"] = compute_asset_score(out)
        return out

    if offline:
        code.update({
            "status": "repo_found",
            "runnable_status": "metadata_only",
            "failure_reason": "offline_mode",
        })
        out["code"] = code
        out.setdefault("scores", {})["code_readiness"] = 3.0
        out["scores"]["asset_score"] = compute_asset_score(out)
        return out

    repo_data, err = github_api_json(f"/repos/{owner}/{repo}", timeout)
    if err or not repo_data:
        if err == "http_404":
            code.update({
                "status": "unavailable",
                "runnable_status": "not_attempted",
                "failure_reason": err,
            })
            readiness = 1.0
        else:
            code.update({
                "status": "repo_found",
                "runnable_status": "metadata_lookup_failed",
                "failure_reason": f"metadata_lookup:{err or 'empty_github_response'}",
            })
            readiness = max(float(out.get("scores", {}).get("code_readiness", 0) or 0), 3.0)
        out["code"] = code
        out.setdefault("scores", {})["code_readiness"] = readiness
        out["scores"]["asset_score"] = compute_asset_score(out)
        return out

    license_obj = repo_data.get("license") if isinstance(repo_data.get("license"), dict) else {}
    code.update({
        "status": "open_source_verified",
        "license": license_obj.get("spdx_id") or license_obj.get("name") or "",
        "stars": int(repo_data.get("stargazers_count") or 0),
        "last_commit": "",
        "has_readme": github_contents_exists(owner, repo, ["README.md", "readme.md", "README.rst"], timeout),
        "has_requirements": github_contents_exists(
            owner,
            repo,
            ["requirements.txt", "environment.yml", "pyproject.toml", "setup.py", "Pipfile", "package.json"],
            timeout,
        ),
        "runnable_status": "metadata_only",
        "failure_reason": "",
    })

    commits, commit_err = github_api_json(f"/repos/{owner}/{repo}/commits?per_page=1", timeout)
    if isinstance(commits, list) and commits:
        commit = commits[0].get("commit") if isinstance(commits[0], dict) else {}
        author = commit.get("author") if isinstance(commit, dict) else {}
        code["last_commit"] = author.get("date", "")
    elif commit_err:
        code["failure_reason"] = f"commit_lookup:{commit_err}"

    readiness = 5.0
    if code.get("license"):
        readiness += 1.0
    if code.get("has_readme"):
        readiness += 1.0
    if code.get("has_requirements"):
        readiness += 1.0
    if code.get("stars", 0) > 0:
        readiness += 0.5
    out["code"] = code
    out.setdefault("scores", {})["code_readiness"] = min(10.0, readiness)
    out["scores"]["asset_score"] = compute_asset_score(out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Verify open-source code metadata for Insight/Method assets.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--timeout", type=int, default=12)
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    assets = [verify_one(asset, timeout=args.timeout, offline=args.offline) for asset in read_assets(args.input)]
    write_assets(args.output, assets)
    summary = {}
    for asset in assets:
        status = (asset.get("code") or {}).get("status", "unknown")
        summary[status] = summary.get(status, 0) + 1
    print(json.dumps({"input": args.input, "output": args.output, "assets": len(assets), "code_status": summary}, indent=2))


if __name__ == "__main__":
    main()
