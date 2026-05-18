"""Dynamic skill→graph-builder loader.

Skills live in directories that may have hyphenated names (e.g.
``thesis-to-rules``), which can't be addressed as Python packages directly.
This loader uses ``importlib.util`` to import the skill's ``pipeline.py``
by file path, then returns its ``build_graph`` callable.

Result: ``api_server.py`` can route a run request to the right per-skill
graph without hard-coding skill names, and the resume callback can rebuild
the compiled graph for any pending approval to resolve interrupts.
"""

from __future__ import annotations

import importlib.util
import threading
from pathlib import Path
from typing import Any, Callable, Optional


# Default search root — the bundled skills directory.
_DEFAULT_SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"

# Process-wide cache so repeated lookups don't re-exec the same module file.
_CACHE: dict[tuple[str, str], Any] = {}
_CACHE_LOCK = threading.Lock()


def load_skill_pipeline(
    skill_name: str,
    *,
    skills_dir: Optional[Path] = None,
) -> Any:
    """Import ``{skills_dir}/{skill_name}/pipeline.py`` and return the module.

    Raises FileNotFoundError if the pipeline.py is missing, ImportError if it
    fails to execute. Cached by ``(skills_dir, skill_name)`` so the import
    cost is paid once per process.
    """
    skills_dir = skills_dir or _DEFAULT_SKILLS_DIR
    cache_key = (str(skills_dir), skill_name)
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached is not None:
            return cached

    pipeline_path = skills_dir / skill_name / "pipeline.py"
    if not pipeline_path.exists():
        raise FileNotFoundError(
            f"skill {skill_name!r} has no pipeline.py at {pipeline_path}"
        )

    module_name = f"_skill_pipeline__{skill_name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, pipeline_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load spec for {pipeline_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with _CACHE_LOCK:
        _CACHE[cache_key] = module
    return module


def get_build_graph(
    skill_name: str,
    *,
    skills_dir: Optional[Path] = None,
) -> Callable[..., Any]:
    """Return the skill's ``build_graph(approval_service, sqlite_path)`` callable.

    Raises ``AttributeError`` if the pipeline.py doesn't export ``build_graph``.
    """
    module = load_skill_pipeline(skill_name, skills_dir=skills_dir)
    fn = getattr(module, "build_graph", None)
    if fn is None:
        raise AttributeError(
            f"skill {skill_name!r} pipeline.py does not export build_graph()"
        )
    return fn


def clear_cache() -> None:
    """Drop the cached pipeline modules — used by tests."""
    with _CACHE_LOCK:
        _CACHE.clear()
