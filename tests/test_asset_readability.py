from __future__ import annotations

from pathlib import Path

from idea_scout.extract_assets import extract_assets
from idea_scout.enhance_insights import enhance_one


def test_asset_id_stays_stable_when_summary_fields_change() -> None:
    base = {
        "paper_id": "paper::dense",
        "title": "Densely Connected Convolutional Networks",
        "abstract": "We introduce DenseNet.",
        "venue": "CVPR",
        "year": 2017,
    }
    changed = base | {
        "abstract": "A rewritten abstract should not change the identity.",
        "challenge": "Different challenge wording.",
        "solution_pattern": "Different solution wording.",
    }
    a = extract_assets([base], profile_name="bestpaper")[0]
    b = extract_assets([changed], profile_name="bestpaper")[0]
    assert a["asset_id"] == b["asset_id"]


def test_enhance_prefers_clean_abstract_over_noisy_pdf_layout(tmp_path: Path) -> None:
    noisy_text = tmp_path / "dense.txt"
    noisy_text.write_text(
        """
        Densely Connected Convolutional Networks
        Gao Huang Cornell University gh349@cornell.edu
        Abstract
        Recent work has shown that convolutional networks can be substantially deeper and efficient to train if they contain shorter connections between layers.
        In this paper, we introduce the Dense Convolutional Network (DenseNet), which connects each layer to every other layer in a feed-forward fashion.
        Figure 1: A 5-layer dense block.
        1. Introduction
        FractalNets [17] repeatedly combine sev- 20 years ago [18] unrelated two-column text.
        """,
        encoding="utf-8",
    )
    paper = {
        "paper_id": "paper::dense",
        "title": "Densely Connected Convolutional Networks",
        "abstract": (
            "Recent work has shown that convolutional networks can be substantially deeper, more accurate, "
            "and efficient to train if they contain shorter connections between layers close to the input and output. "
            "In this paper, we introduce the Dense Convolutional Network (DenseNet), which connects each layer "
            "to every other layer in a feed-forward fashion."
        ),
        "venue": "CVPR",
        "year": 2017,
        "text_path": str(noisy_text),
    }
    asset = extract_assets([paper], profile_name="bestpaper")[0]
    asset["pdf"]["text_path"] = str(noisy_text)
    enhanced = enhance_one(asset)
    joined = " ".join([
        enhanced["challenge"],
        enhanced["solution_pattern"],
        enhanced["insight"]["reusable_insight"],
    ])
    assert "Cornell" not in joined
    assert "gh349" not in joined
    assert "Figure 1" not in joined
    assert enhanced["challenge"].startswith("Recent work has shown")
    assert "DenseNet" in enhanced["solution_pattern"]



def test_enhance_selects_method_sentence_not_context_sentence(tmp_path: Path) -> None:
    text_path = tmp_path / "dense.txt"
    text_path.write_text("Abstract\nClean fallback text.", encoding="utf-8")
    abstract = (
        "Recent work has shown that convolutional networks can be substantially deeper and efficient to train "
        "if they contain shorter connections between layers close to the input and output. "
        "In this paper, we introduce the Dense Convolutional Network (DenseNet), which connects each layer "
        "to every other layer in a feed-forward fashion. "
        "DenseNets alleviate the vanishing-gradient problem, strengthen feature propagation, and encourage feature reuse."
    )
    paper = {
        "paper_id": "paper::dense",
        "title": "Densely Connected Convolutional Networks",
        "abstract": abstract,
        "venue": "CVPR",
        "year": 2017,
        "text_path": str(text_path),
    }
    asset = extract_assets([paper], profile_name="bestpaper")[0]
    asset["pdf"]["text_path"] = str(text_path)
    enhanced = enhance_one(asset)
    assert enhanced["challenge"].startswith("Recent work has shown")
    assert "introduce the Dense Convolutional Network" in enhanced["solution_pattern"]
    assert enhanced["challenge"] != enhanced["solution_pattern"]


def test_enhance_avoids_duplicate_problem_and_method_when_abstract_has_bottleneck(tmp_path: Path) -> None:
    text_path = tmp_path / "visprog.txt"
    text_path.write_text("Abstract\nClean fallback text.", encoding="utf-8")
    abstract = (
        "We present VISPROG, a neuro-symbolic approach to solving complex and compositional visual tasks "
        "given natural language instructions. "
        "VISPROG avoids the need for any task-specific training. "
        "Instead, it uses the in-context learning ability of large language models to generate python-like modular programs."
    )
    paper = {
        "paper_id": "paper::visprog",
        "title": "Visual Programming: Compositional visual reasoning without training",
        "abstract": abstract,
        "venue": "CVPR",
        "year": 2023,
        "text_path": str(text_path),
    }
    asset = extract_assets([paper], profile_name="bestpaper")[0]
    asset["pdf"]["text_path"] = str(text_path)
    enhanced = enhance_one(asset)
    assert "VISPROG" in enhanced["solution_pattern"]
    assert "task-specific training" in enhanced["challenge"]
    assert enhanced["challenge"] != enhanced["solution_pattern"]
