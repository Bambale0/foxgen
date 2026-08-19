from __future__ import annotations

from typing import Any

from fastapi.routing import iter_route_contexts


def route_paths(app: Any) -> set[str]:
    """Return effective paths across FastAPI included-router contexts."""
    return {
        path
        for context in iter_route_contexts(app.routes)
        if isinstance((path := context.path), str)
    }


def route_methods_by_path(app: Any) -> dict[str, set[str]]:
    """Return effective HTTP methods keyed by effective route path."""
    result: dict[str, set[str]] = {}
    for context in iter_route_contexts(app.routes):
        path = context.path
        methods = context.methods
        if not isinstance(path, str) or methods is None:
            continue
        result.setdefault(path, set()).update(methods)
    return result
