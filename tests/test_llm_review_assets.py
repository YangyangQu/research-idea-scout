from __future__ import annotations

import json

from idea_scout.llm_review_assets import parse_review_json, review_one


def sample_asset() -> dict:
    return {
        "asset_id": "taskonomy-001",
        "asset_type": "method",
        "challenge": "Old heuristic challenge.",
        "solution_pattern": "Old heuristic method.",
        "mechanism": "Old heuristic mechanism.",
        "why_it_is_hard": "Old heuristic difficulty.",
        "transferable_to": [],
        "non_transferable_parts": [],
        "evidence": [],
        "source_papers": [
            {
                "title": "Taskonomy: Disentangling Task Transfer Learning",
                "abstract": (
                    "We study how to transfer knowledge among visual tasks when exhaustive "
                    "pairwise transfer is expensive. We introduce Taskonomy, a computational "
                    "approach that models task dependencies and finds efficient transfer policies."
                ),
                "venue": "CVPR",
                "year": 2018,
            }
        ],
        "code": {"status": "repo_found", "url": "https://github.com/StanfordVL/taskonomy"},
        "pdf": {
            "status": "parsed",
            "extracted_sections": {
                "method": "Our method builds a task affinity graph and derives a taxonomy over tasks.",
                "experiments": "",
                "limitations": "",
            },
        },
        "scores": {
            "asset_score": 0.0,
            "transferability": 1.0,
            "evidence_strength": 2.0,
            "code_readiness": 5.0,
            "implementation_feasibility": 0.0,
        },
    }


def test_parse_review_json_accepts_fenced_json() -> None:
    parsed = parse_review_json(
        """
        Here is the review:
        ```json
        {"verdict": "accept", "asset_quality": 5, "confidence": 0.82}
        ```
        """
    )
    assert parsed["verdict"] == "accept"
    assert parsed["asset_quality"] == 5
    assert parsed["confidence"] == 0.82


def test_review_one_replaces_heuristic_fields_with_llm_judgment() -> None:
    response = json.dumps(
        {
            "verdict": "accept",
            "asset_quality": 5,
            "challenge": "Exhaustive task-transfer evaluation is too expensive.",
            "method": "Model tasks as an affinity graph and derive efficient transfer policies.",
            "reusable_insight": "When pairwise transfer is costly, learn a graph of dependency structure first.",
            "why_it_works": "The graph compresses many transfer trials into reusable structure.",
            "transfer_targets": ["model selection", "data-efficient adaptation"],
            "non_transferable_parts": ["visual-task-specific architecture choices"],
            "evidence_quotes": ["exhaustive pairwise transfer is expensive", "models task dependencies"],
            "code_assessment": "official",
            "review_notes": "Clear reusable mechanism with code available.",
            "confidence": 0.86,
        }
    )

    reviewed = review_one(sample_asset(), runner=lambda _prompt, _timeout: response)

    assert reviewed["llm_review"]["verdict"] == "accept"
    assert reviewed["challenge"] == "Exhaustive task-transfer evaluation is too expensive."
    assert reviewed["solution_pattern"] == "Model tasks as an affinity graph and derive efficient transfer policies."
    assert reviewed["mechanism"] == reviewed["solution_pattern"]
    assert reviewed["insight"]["reusable_insight"].startswith("When pairwise transfer")
    assert reviewed["transferable_to"] == ["model selection", "data-efficient adaptation"]
    assert reviewed["non_transferable_parts"] == ["visual-task-specific architecture choices"]
    assert reviewed["scores"]["evidence_strength"] >= 8.0
    assert reviewed["evidence"][0].startswith("LLM reusable insight:")


def test_review_one_preserves_fields_when_llm_rejects_asset() -> None:
    response = json.dumps(
        {
            "verdict": "reject",
            "asset_quality": 1,
            "challenge": "",
            "method": "",
            "reusable_insight": "",
            "why_it_works": "",
            "transfer_targets": [],
            "non_transferable_parts": ["insufficient method evidence"],
            "evidence_quotes": [],
            "code_assessment": "unknown",
            "review_notes": "Evidence is too thin to form a reusable asset.",
            "confidence": 0.71,
        }
    )

    reviewed = review_one(sample_asset(), runner=lambda _prompt, _timeout: response)

    assert reviewed["llm_review"]["verdict"] == "reject"
    assert reviewed["challenge"] == "Old heuristic challenge."
    assert reviewed["solution_pattern"] == "Old heuristic method."
    assert reviewed["scores"]["evidence_strength"] <= 3.0
    assert "LLM rejected asset" in reviewed["limitations"][0]
