"""Settings persistence: the section settings live in the project file (scope "xsections").

The model file paths of MODFLOW 6 surfaces (mf6_path, mf6_head_path) are stored the way the project stores its layer
sources: through its path resolver, so relative to the project file when it uses relative paths, and they are
resolved back to absolute paths when loaded (the settings in memory always hold absolute paths). Moving a job folder
with its project and model runs keeps the model surfaces. A project not saved yet stores absolute paths; the dock
stores the settings again while the project is written (Save As), relative to its new place.

Per-user conveniences that do not belong to a project (the last export folder, and from 0.3.6 the ⋯ menu's Verbose
switch, "xsections/verbose": widgets.verbose) go to QgsSettings.
"""
from __future__ import annotations

import dataclasses
import json
import math
import os
from dataclasses import fields
from typing import Any, Callable, Optional, Tuple

from qgis.core import QgsProject, QgsSettings

from ..core.model import (Settings, clean_hidden, clean_other_points, clean_point_layers, clean_surfaces,
                          migrate_settings)

SCOPE = "xsections"
KEY = "settings"
USER_PREFIX = "xsections/"
PATH_KEYS = ("mf6_path", "mf6_head_path")     # surface keys holding file paths


def _map_paths(settings: Settings, fn: Callable[[str], str]) -> Settings:
    """A copy of `settings` with fn applied to every non-empty model file path of its surfaces."""
    surfaces = []
    for d in settings.surfaces:
        if isinstance(d, dict) and any(d.get(k) for k in PATH_KEYS):
            d = dict(d)
            for k in PATH_KEYS:
                if isinstance(d.get(k), str) and d[k]:
                    d[k] = fn(d[k])
        surfaces.append(d)
    return dataclasses.replace(settings, surfaces=surfaces)


def _is_relative(path: str) -> bool:
    return not os.path.isabs(path) and not path.startswith(("\\", "/"))


def paths_for_project(project: QgsProject, settings: Settings) -> Settings:
    """The settings as stored: model file paths through the project's path resolver (relative to the project file
    when the project stores relative paths and has a file; unchanged otherwise)."""
    resolver = project.pathResolver()
    return _map_paths(settings, lambda p: resolver.writePath(p) or p)


def paths_from_project(project: QgsProject, settings: Settings) -> Settings:
    """Stored settings -> absolute model file paths (a relative path is resolved from the project file's folder;
    an absolute one is kept exactly as stored)."""
    resolver = project.pathResolver()
    return _map_paths(settings, lambda p: os.path.normpath(resolver.readPath(p)) if _is_relative(p) else p)


def stored_json(project: QgsProject) -> str:
    """The raw JSON stored in the project, or "" if there is none."""
    text, ok = project.readEntry(SCOPE, KEY, "")
    return text if ok and text else ""


def load(project: QgsProject) -> Optional[Settings]:
    """Settings saved in the project, or None if the project has none (or they are unreadable).

    Settings saved by an older version are migrated first (model.migrate_settings). Values of the wrong
    kind (a hand-edited project, or one saved by another version) are dropped one by one, so those
    settings take their defaults and the rest still apply.

    Version 6 (0.3.3): an older project's single explorations layer (the flat per-layer keys) comes back as the
    first exploration row (point_layers), with the same fields, types and water-level table; the rows, the other
    points and the left-off list are cleaned row by row and key by key (model.clean_point_layers ...).

    Version 7 (0.3.4): a project saved with its data lines coloured by type opens with its Black rows in Color (each
    exploration's colour from the layer's own style), and the grid and depth line width keys are cleaned or take
    their defaults (model.migrate_settings, clean_sheet_style).
    """
    text = stored_json(project)
    if not text:
        return None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    data = migrate_settings(data)        # settings saved by an older version: renamed keys
    clean = {}
    for f in fields(Settings):
        if f.name in data:
            ok, value = _coerce(data[f.name], getattr(_DEFAULTS, f.name), f.name)
            if ok:
                clean[f.name] = value
    try:
        return paths_from_project(project, Settings(**clean))
    except (ValueError, TypeError):
        return None


_DEFAULTS = Settings()
_ROW_CLEANERS = {"point_layers": clean_point_layers, "other_points": clean_other_points,
                 "hidden_points": clean_hidden}


def _coerce(value: Any, default: Any, name: str) -> Tuple[bool, Any]:
    """(usable, value) for one stored setting, judged by the kind of its default."""
    if name == "line_fid":
        if value is None or (isinstance(value, int) and not isinstance(value, bool)):
            return True, value
        return False, None
    if name == "surfaces":                         # a list of dicts, each cleaned key by key
        return (True, clean_surfaces(value)) if isinstance(value, list) else (False, None)
    if name in _ROW_CLEANERS:                      # point rows (dicts, cleaned key by key) and the left-off list
        return (True, _ROW_CLEANERS[name](value)) if isinstance(value, list) else (False, None)
    if isinstance(default, bool):
        return (True, value) if isinstance(value, bool) else (False, None)
    if isinstance(default, int):
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return (True, value) if isinstance(value, int) and not isinstance(value, bool) else (False, None)
    if isinstance(default, float):
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return True, float(value)
        return False, None
    if isinstance(default, str):
        return (True, value) if isinstance(value, str) else (False, None)
    if isinstance(default, list):
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            return True, list(value)
        return False, None
    return False, None


def save(project: QgsProject, settings: Settings) -> bool:
    """Write the settings to the project (model file paths as the project stores paths, paths_for_project).
    Returns True if the stored value changed.

    Writing an unchanged value is skipped so that opening a project does not mark it dirty.
    """
    text = paths_for_project(project, settings).to_json()
    if text == stored_json(project):
        return False
    project.writeEntry(SCOPE, KEY, text)
    return True


def clear(project: QgsProject) -> None:
    project.removeEntry(SCOPE, KEY)


def user_value(name: str, default: str = "") -> str:
    value = QgsSettings().value(USER_PREFIX + name, default)
    return str(value) if value is not None else default


def set_user_value(name: str, value: str) -> None:
    QgsSettings().setValue(USER_PREFIX + name, value)
