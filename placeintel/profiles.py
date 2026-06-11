"""Report profile loading: _core.yaml dimensions merge into every named profile."""

from __future__ import annotations

from pathlib import Path

import yaml

from . import config


def list_profiles() -> list[str]:
    return sorted(
        p.stem for p in config.PROFILES_DIR.glob("*.yaml") if not p.name.startswith("_")
    )


def load_profile(name: str = "generic") -> dict:
    """Return {'dimensions': {...core+profile...}, 'output_extras': {...}}."""
    core_path = config.PROFILES_DIR / "_core.yaml"
    profile_path = config.PROFILES_DIR / f"{name}.yaml"
    if not profile_path.exists():
        available = ", ".join(list_profiles())
        raise FileNotFoundError(f"Profile '{name}' not found. Available: {available}")

    core = yaml.safe_load(core_path.read_text()) or {}
    extra = yaml.safe_load(profile_path.read_text()) or {}

    dimensions = {**core.get("dimensions", {}), **(extra.get("dimensions") or {})}
    output_extras = {**core.get("output_extras", {}), **(extra.get("output_extras") or {})}
    return {"name": name, "dimensions": dimensions, "output_extras": output_extras}


def guess_profile(query: str) -> str:
    """Heuristic profile pick from the search query; falls back to generic."""
    q = query.lower()
    lesson_words = ("lesson", "class", "school", "teacher", "course", "教室", "课", "培训", "教学")
    rental_words = ("rent", "rental", "hire", "租", "出租")
    if any(w in q for w in rental_words):
        return "rental"
    if any(w in q for w in lesson_words):
        return "lessons"
    return "generic"
