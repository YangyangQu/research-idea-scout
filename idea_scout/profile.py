from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml


@dataclass
class Dimension:
    key: str
    description: str
    weight: float = 1.0


@dataclass
class Profile:
    name: str
    description: str
    target_tasks: List[str]
    positive_keywords: List[str]
    negative_keywords: List[str]
    scoring_dimensions: List[Dimension]
    prefer: List[str]
    downweight: List[str]
    language: str = "English"
    topic_anchors: Dict[str, List[str]] = field(default_factory=dict)


def _string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    return [str(value)]


def normalize_topic_anchors(value: Any) -> Dict[str, List[str]]:
    if not isinstance(value, dict):
        return {}
    allowed = {"high_value", "required_any", "broad_ai", "off_topic_domains"}
    return {key: _string_list(value.get(key)) for key in allowed if _string_list(value.get(key))}


def load_profile(path: str | Path) -> Profile:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    dims = []
    for item in raw.get("scoring_dimensions", []):
        if isinstance(item, str):
            dims.append(Dimension(key=item, description=item, weight=1.0))
        else:
            dims.append(Dimension(
                key=str(item["key"]),
                description=str(item.get("description", item["key"])),
                weight=float(item.get("weight", 1.0)),
            ))

    if not dims:
        raise ValueError("Profile must define at least one scoring dimension.")

    return Profile(
        name=str(raw.get("name", p.stem)),
        description=str(raw.get("description", "")),
        target_tasks=[str(x) for x in raw.get("target_tasks", [])],
        positive_keywords=[str(x) for x in raw.get("positive_keywords", [])],
        negative_keywords=[str(x) for x in raw.get("negative_keywords", [])],
        scoring_dimensions=dims,
        prefer=[str(x) for x in raw.get("prefer", [])],
        downweight=[str(x) for x in raw.get("downweight", [])],
        language=str(raw.get("language", "English")),
        topic_anchors=normalize_topic_anchors(raw.get("topic_anchors")),
    )


def profile_to_prompt_block(profile: Profile) -> str:
    dims = "\n".join(
        f'- {d.key}: {d.description}' for d in profile.scoring_dimensions
    )
    tasks = "\n".join(f'- {x}' for x in profile.target_tasks) or "- User-defined research task"
    prefer = "\n".join(f'- {x}' for x in profile.prefer) or "- Transferable research ideas"
    down = "\n".join(f'- {x}' for x in profile.downweight) or "- Generic papers without transferable mechanisms"

    return f"""
Research profile name: {profile.name}

Research profile description:
{profile.description}

Target tasks:
{tasks}

Prefer papers with:
{prefer}

Downweight papers with:
{down}

Scoring dimensions:
{dims}
""".strip()


def dimension_keys(profile: Profile) -> List[str]:
    return [d.key for d in profile.scoring_dimensions]
