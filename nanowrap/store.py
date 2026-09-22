"""Where nanoWrap keeps what you drop in, and what it makes.

One folder in your home directory, plain files, no database. Delete the folder
and nanoWrap forgets everything it has ever done.

Nothing here is ever uploaded anywhere. The only copies that leave this folder
are the ones you download yourself.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path

APP_DIR_NAME = ".nanowrap"
_lock = threading.Lock()

# Files you dropped in are yours; files nanoWrap made are a cache. The cache is
# tidied up after a week so a few large videos cannot quietly fill a disk.
KEEP_OUTPUTS_DAYS = 7

DEFAULT_SETTINGS = {
    "open_folder_when_done": False,   # reveal the finished file automatically
    "keep_days": KEEP_OUTPUTS_DAYS,
    "max_upload_mb": 2048,            # 2 GB — a phone video is usually well under this
}


# --------------------------------------------------------------------- folders
def data_dir() -> Path:
    """The one folder nanoWrap owns. Point it elsewhere with NANOWRAP_HOME."""
    override = os.environ.get("NANOWRAP_HOME")
    path = Path(override) if override else Path.home() / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def uploads_dir() -> Path:
    path = data_dir() / "dropped"
    path.mkdir(parents=True, exist_ok=True)
    return path


def outputs_dir() -> Path:
    path = data_dir() / "made"
    path.mkdir(parents=True, exist_ok=True)
    return path


def scratch_dir() -> Path:
    """A work area for half-finished files, so a failure never leaves a
    half-written file where you might pick it up by mistake."""
    path = data_dir() / "working"
    path.mkdir(parents=True, exist_ok=True)
    return path


def free_space_mb() -> int:
    """How much room is left on the disk nanoWrap writes to."""
    try:
        return shutil.disk_usage(str(data_dir())).free // (1024 * 1024)
    except OSError:
        return -1


# -------------------------------------------------------------------- settings
def _settings_path() -> Path:
    return data_dir() / "settings.json"


def load_settings() -> dict:
    with _lock:
        settings = dict(DEFAULT_SETTINGS)
        try:
            with open(_settings_path(), "r", encoding="utf-8") as handle:
                stored = json.load(handle)
            if isinstance(stored, dict):
                settings.update({key: stored[key] for key in DEFAULT_SETTINGS if key in stored})
        except (OSError, json.JSONDecodeError):
            pass
        return settings


def save_settings(patch: dict) -> dict:
    settings = load_settings()
    for key, value in (patch or {}).items():
        if key in DEFAULT_SETTINGS and isinstance(value, type(DEFAULT_SETTINGS[key])):
            settings[key] = value
        elif key in DEFAULT_SETTINGS and isinstance(DEFAULT_SETTINGS[key], (int, float)) and isinstance(value, (int, float)):
            settings[key] = type(DEFAULT_SETTINGS[key])(value)
    with _lock:
        tmp = _settings_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        os.replace(tmp, _settings_path())
    return settings


# --------------------------------------------------------------------- history
def _history_path() -> Path:
    return data_dir() / "history.json"


def load_history(limit: int = 40) -> list:
    with _lock:
        try:
            with open(_history_path(), "r", encoding="utf-8") as handle:
                items = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return []
    if not isinstance(items, list):
        return []
    alive = []
    for item in items:
        if not isinstance(item, dict):
            continue
        path = Path(str(item.get("path", "")))
        try:
            alive.append({**item, "size_mb": round(path.stat().st_size / (1024 * 1024), 2),
                          "here": path.is_file()})
        except OSError:
            alive.append({**item, "size_mb": item.get("size_mb", 0), "here": False})
    return alive[:limit]


def add_history(entry: dict) -> None:
    items = load_history(limit=200)
    items.insert(0, {**entry, "when": time.time()})
    with _lock:
        try:
            tmp = _history_path().with_suffix(".tmp")
            tmp.write_text(json.dumps(items[:200], indent=2), encoding="utf-8")
            os.replace(tmp, _history_path())
        except OSError:
            pass
    tidy_outputs()


def forget_history(entry_name: str = "") -> list:
    """Remove a remembered run — or all of them, if no name is given."""
    items = load_history(limit=200)
    if entry_name:
        items = [item for item in items if item.get("name") != entry_name]
    else:
        items = []
    with _lock:
        try:
            _history_path().write_text(json.dumps(items, indent=2), encoding="utf-8")
        except OSError:
            pass
    return items


# ---------------------------------------------------------------------- tidying
def tidy_outputs(keep_days: int | None = None) -> dict:
    """Delete made files older than `keep_days`.

    nanoWrap makes copies of things you already own, so throwing the old ones
    away is safe — and the alternative is a folder that grows forever until a
    disk fills up in the middle of somebody's wedding video.
    """
    days = KEEP_OUTPUTS_DAYS if keep_days is None else int(keep_days)
    removed = 0
    freed = 0
    if days <= 0:
        return {"removed": 0, "freed_mb": 0, "kept_days": days}
    cutoff = time.time() - days * 86400
    for folder in (outputs_dir(), scratch_dir()):
        for path in folder.iterdir():
            try:
                if path.stat().st_mtime >= cutoff:
                    continue
                size = path.stat().st_size if path.is_file() else 0
                if path.is_dir():
                    size = sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink()
                removed += 1
                freed += size
            except OSError:
                continue
    return {"removed": removed, "freed_mb": round(freed / (1024 * 1024), 1), "kept_days": days}


def clear_outputs() -> dict:
    """Throw away everything nanoWrap has made, on request."""
    removed = 0
    freed = 0
    for folder in (outputs_dir(), scratch_dir()):
        for path in folder.iterdir():
            try:
                if path.is_file():
                    freed += path.stat().st_size
                    path.unlink()
                elif path.is_dir():
                    freed += sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
                    shutil.rmtree(path, ignore_errors=True)
                removed += 1
            except OSError:
                continue
    forget_history()
    return {"removed": removed, "freed_mb": round(freed / (1024 * 1024), 1)}


def free_name(name: str, folder: Path | None = None) -> Path:
    """A path in `folder` that is not taken yet: holiday.mp4 → holiday-2.mp4."""
    folder = folder or outputs_dir()
    stem = Path(name).stem or "file"
    suffix = Path(name).suffix
    candidate = folder / (stem + suffix)
    counter = 2
    while candidate.exists():
        candidate = folder / ("%s-%d%s" % (stem, counter, suffix))
        counter += 1
    return candidate


def clear_dropped_input() -> None:
    """Delete dropped files at shutdown — they are copies, and the originals
    are still wherever the person kept them."""
    for path in uploads_dir().iterdir():
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            continue
