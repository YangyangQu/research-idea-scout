from __future__ import annotations

from pathlib import Path

from idea_scout.discover_code import discover_one
from idea_scout.enhance_insights import enhance_one
from idea_scout.extract_assets import extract_assets
from idea_scout.verify_code import verify_one


def base_asset(tmp_path: Path, text: str) -> dict:
    text_path = tmp_path / "paper.txt"
    text_path.write_text(text, encoding="utf-8")
    paper = {
        "title": "Taskonomy: Disentangling Task Transfer Learning",
        "abstract": "We introduce task transfer modeling.",
        "venue": "CVPR",
        "year": 2018,
        "text_path": str(text_path),
    }
    asset = extract_assets([paper], profile_name="test")[0]
    asset["code"] = {"status": "missing", "url": ""}
    asset["pdf"]["text_path"] = str(text_path)
    return asset


def test_discover_code_uses_project_homepage_github_link(tmp_path: Path) -> None:
    asset = base_asset(
        tmp_path,
        "Abstract\nProject page: https://example.org/taskonomy.\nMethod\nWe learn transfer structure.",
    )

    def fetcher(url: str, timeout: int) -> str:
        assert url == "https://example.org/taskonomy"
        return '<a href="https://github.com/StanfordVL/taskonomy">Code</a>'

    discovered = discover_one(asset, fetcher=fetcher, github_searcher=lambda *_args, **_kwargs: [])
    assert discovered["code"]["url"] == "https://github.com/StanfordVL/taskonomy"
    assert discovered["code"]["status"] == "repo_found"
    assert discovered["code"]["discovery_confidence"] == "high"
    assert discovered["code"]["discovery_sources"][0]["source"] == "homepage"


def test_discover_code_uses_github_search_candidate(tmp_path: Path) -> None:
    asset = base_asset(tmp_path, "Abstract\nNo project page here.")

    def searcher(query: str, timeout: int, per_page: int):
        return [
            {
                "html_url": "https://github.com/StanfordVL/taskonomy",
                "full_name": "StanfordVL/taskonomy",
                "description": "Taskonomy: Disentangling Task Transfer Learning [Best Paper, CVPR2018]",
                "stargazers_count": 800,
            }
        ]

    discovered = discover_one(asset, fetcher=lambda *_args, **_kwargs: "", github_searcher=searcher)
    assert discovered["code"]["url"] == "https://github.com/StanfordVL/taskonomy"
    assert discovered["code"]["discovery_source"] == "github_search"
    assert discovered["code"]["discovery_confidence"] in {"high", "medium"}


def test_enhance_insights_extracts_challenge_method_and_reusable_insight(tmp_path: Path) -> None:
    asset = base_asset(
        tmp_path,
        """
        Abstract
        We study how to transfer knowledge among visual tasks when exhaustive pairwise transfer is expensive.
        We introduce Taskonomy, a computational approach that models task dependencies and finds efficient transfer policies.

        1. Introduction
        The challenge is that transfer relationships among tasks are dense, costly to evaluate, and domain dependent.

        3. Method
        Our method builds a task affinity graph by training transfer functions between tasks and then derives a taxonomy over tasks.
        """,
    )
    clean_abstract = (
        "We study how to transfer knowledge among visual tasks when exhaustive pairwise transfer is expensive. "
        "We introduce Taskonomy, a computational approach that models task dependencies and finds efficient transfer policies."
    )
    asset["source_papers"][0]["abstract"] = clean_abstract
    asset["raw"]["abstract"] = clean_abstract
    enhanced = enhance_one(asset)
    assert enhanced["insight"]["challenge"].startswith("We study how to transfer knowledge")
    assert "Taskonomy" in enhanced["insight"]["method"] or "task affinity graph" in enhanced["insight"]["method"]
    assert "Reusable insight" in enhanced["insight"]["reusable_insight"]
    assert enhanced["challenge"] == enhanced["insight"]["challenge"]
    assert enhanced["solution_pattern"] == enhanced["insight"]["method"]


def test_verify_code_preserves_repo_found_when_metadata_rate_limited(monkeypatch, tmp_path: Path) -> None:
    asset = base_asset(tmp_path, "Abstract\nCode exists.")
    asset["code"] = {"status": "repo_found", "url": "https://github.com/StanfordVL/taskonomy"}

    def fake_api(path: str, timeout: int):
        return {}, "http_403"

    monkeypatch.setattr("idea_scout.verify_code.github_api_json", fake_api)
    checked = verify_one(asset, timeout=1, offline=False)
    assert checked["code"]["status"] == "repo_found"
    assert checked["code"]["failure_reason"] == "metadata_lookup:http_403"
    assert checked["scores"]["code_readiness"] >= 3.0


def test_homepage_discovery_chooses_title_matching_github_link(tmp_path: Path) -> None:
    asset = base_asset(
        tmp_path,
        "Abstract\nProject page: https://example.org/project.\nMethod\nWe learn transfer structure.",
    )

    def fetcher(url: str, timeout: int) -> str:
        return """
        <a href='https://github.com/zenodo/zenodo-rdm'>site dependency</a>
        <a href='https://github.com/StanfordVL/taskonomy'>Taskonomy: Disentangling Task Transfer Learning code</a>
        """

    discovered = discover_one(asset, fetcher=fetcher, github_searcher=lambda *_args, **_kwargs: [])
    assert discovered["code"]["url"] == "https://github.com/StanfordVL/taskonomy"
    assert discovered["code"]["implementation_kind"] == "official_or_project"


def test_homepage_discovery_ignores_unrelated_github_link(tmp_path: Path) -> None:
    asset = base_asset(
        tmp_path,
        "Abstract\nProject page: https://zenodo.org/records/123.\nMethod\nWe learn transfer structure.",
    )

    def fetcher(url: str, timeout: int) -> str:
        return "<a href='https://github.com/zenodo/zenodo-rdm'>platform source</a>"

    discovered = discover_one(asset, fetcher=fetcher, github_searcher=lambda *_args, **_kwargs: [])
    assert discovered["code"]["status"] == "missing"
