"""The programs nanoWrap knows how to drive, and how to find them.

Every entry answers three questions in plain language: what is this program,
what would I actually use it for, and how do I get it if it is missing.

Detection is deliberately boring: ask the operating system whether the program
is on the PATH (``shutil.which``) and run its version flag once. Nothing is
installed, nothing is downloaded, nothing is changed.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import threading

# --------------------------------------------------------------------------
# What kind of file is this?
# --------------------------------------------------------------------------
KINDS = {
    "video": (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".3gp"),
    "audio": (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff", ".amr"),
    "image": (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".avif"),
    "document": (".md", ".markdown", ".txt", ".docx", ".odt", ".rtf", ".html", ".htm", ".epub", ".tex", ".rst"),
    "pdf": (".pdf",),
    "sheet": (".csv", ".tsv", ".xlsx", ".ods"),
    "archive": (".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz"),
}

# The words used in sentences, so the app never says "input file type video".
KIND_WORDS = {
    "video": "video",
    "audio": "sound file",
    "image": "picture",
    "document": "document",
    "pdf": "PDF",
    "sheet": "spreadsheet",
    "archive": "zip file",
    "any": "file",
}

_KIND_LOOKUP = {extension: kind for kind, extensions in KINDS.items() for extension in extensions}


def kind_of(path: str) -> str:
    """What sort of file is this? Returns "any" when it is not recognised."""
    return _KIND_LOOKUP.get(os.path.splitext(str(path))[1].lower(), "any")


def kind_sentence(kind: str) -> str:
    return KIND_WORDS.get(kind, "file")


def is_video(path: str) -> bool:
    return kind_of(path) == "video"


def _os_key() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


OS_KEY = _os_key()
OS_LABEL = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}[OS_KEY]


# --------------------------------------------------------------------------
# The catalogue
# --------------------------------------------------------------------------
# `takes` is what a program is for, in the app's own words. `get_it` is a
# one-line instruction per operating system, because "install ffmpeg" is not
# an instruction, it is a hint.
TOOLS = (
    {
        "id": "ffmpeg",
        "called": "FFmpeg",
        "what": "Works with video and sound.",
        "takes": "video",
        "used_for": "Making a video small enough to send, taking the sound out of a "
                    "clip, turning a clip into a GIF, or grabbing a still picture from it.",
        "homepage": "https://ffmpeg.org/download.html",
        "get_it": {
            "windows": "winget install Gyan.FFmpeg   (or download from ffmpeg.org and unzip it)",
            "macos": "brew install ffmpeg",
            "linux": "sudo apt install ffmpeg",
        },
        "commands": ("ffmpeg",),
        "version_args": ("-version",),
    },
    {
        "id": "magick",
        "called": "ImageMagick",
        "what": "Works with pictures.",
        "takes": "image",
        "used_for": "Making photos smaller so they send faster, changing them from one "
                    "kind to another, or putting a pile of photos into one PDF.",
        "homepage": "https://imagemagick.org/script/download.php",
        "get_it": {
            "windows": "winget install ImageMagick.ImageMagick",
            "macos": "brew install imagemagick",
            "linux": "sudo apt install imagemagick",
        },
        # On Windows "convert" is a different program that reformats disks, so it
        # is never accepted there. Names are tried in order.
        "commands": ("magick",) if OS_KEY == "windows" else ("magick", "convert"),
        "version_args": ("-version",),
    },
    {
        "id": "pandoc",
        "called": "Pandoc",
        "what": "Changes one kind of document into another.",
        "takes": "document",
        "used_for": "Turning a Markdown file into a Word document, or a Word document "
                    "into plain text somebody can read anywhere.",
        "homepage": "https://pandoc.org/installing.html",
        "get_it": {
            "windows": "winget install JohnMacFarlane.Pandoc",
            "macos": "brew install pandoc",
            "linux": "sudo apt install pandoc",
        },
        "commands": ("pandoc",),
        "version_args": ("--version",),
    },
    {
        "id": "poppler",
        "called": "Poppler",
        "what": "Works with PDFs.",
        "takes": "pdf",
        "used_for": "Pulling the text out of a PDF so you can search or edit it, or "
                    "joining several PDFs into one.",
        "homepage": "https://poppler.freedesktop.org/",
        "get_it": {
            "windows": "winget install oschwartz10612.Poppler",
            "macos": "brew install poppler",
            "linux": "sudo apt install poppler-utils",
        },
        "commands": ("pdftotext",),
        "version_args": ("-v",),
    },
    {
        "id": "sevenzip",
        "called": "7-Zip",
        "what": "Packs things up and opens packs.",
        "takes": "archive",
        "used_for": "Making one file out of a folder of files, or opening a .7z or "
                    ".rar somebody sent you.",
        "homepage": "https://www.7-zip.org/download.html",
        "get_it": {
            "windows": "winget install 7zip.7zip",
            "macos": "brew install sevenzip",
            "linux": "sudo apt install 7zip",
        },
        "commands": ("7z", "7za", "7zr"),
        "version_args": (),
    },
    {
        "id": "curl",
        "called": "curl",
        "what": "Fetches a file from a web address.",
        "takes": "any",
        "used_for": "Saving a file that lives at a link, with a proper progress bar "
                    "and a name you choose.",
        "homepage": "https://curl.se/download.html",
        "get_it": {
            "windows": "comes with Windows 10 and newer — try checking again",
            "macos": "brew install curl",
            "linux": "sudo apt install curl",
        },
        "commands": ("curl",),
        "version_args": ("--version",),
    },
)

# These are not programs on your computer — they are written into nanoWrap
# itself, in plain Python, so they work on a machine where nothing is installed.
BUILTIN_TOOLS = (
    {
        "id": "wrap",
        "called": "nanoWrap",
        "what": "Packing, opening and tidying up files.",
        "takes": "any",
        "used_for": "Putting a pile of files into one zip to send, opening a zip "
                    "somebody sent you, or numbering a folder of photos in order.",
        "homepage": "",
        "get_it": {},
        "commands": (),
        "version_args": (),
        "builtin": True,
    },
)


def catalog() -> list:
    """Every tool, built-in ones first (they always work)."""
    return [dict(tool, builtin=tool.get("builtin", False)) for tool in (*BUILTIN_TOOLS, *TOOLS)]


def tool(tool_id: str) -> dict | None:
    for entry in catalog():
        if entry["id"] == tool_id:
            return entry
    return None


# --------------------------------------------------------------------------
# Finding them
# --------------------------------------------------------------------------
_cache_lock = threading.Lock()
_cache: dict[str, dict] = {}
_version_noise = re.compile(r"[^0-9]*([0-9]+(?:\.[0-9]+)+)")


def _first_version_number(text: str) -> str:
    """Pull a version out of whatever a program prints. An empty string is a
    perfectly good answer — plenty of programs do not have one."""
    for line in (text or "").splitlines():
        found = _version_noise.match(line.strip())
        if found:
            return found.group(1)
        if line.strip():
            return line.strip()[:60]
    return ""


def _probe(command_path: str, version_args: tuple) -> str:
    if not version_args:
        return ""
    try:
        finished = subprocess.run(
            [command_path, *version_args],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=6, text=True, errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return _first_version_number(finished.stdout or "")


def find(tool_id: str, use_cache: bool = True) -> dict:
    """Look for one program. Returns a plain dictionary the page can print."""
    with _cache_lock:
        if use_cache and tool_id in _cache:
            return dict(_cache[tool_id])

    entry = tool(tool_id)
    if entry is None:
        raise KeyError(tool_id)

    result = {
        "id": entry["id"],
        "called": entry["called"],
        "what": entry["what"],
        "takes": entry["takes"],
        "used_for": entry["used_for"],
        "homepage": entry["homepage"],
        "get_it": entry["get_it"].get(OS_KEY, "") if entry.get("get_it") else "",
        "builtin": bool(entry.get("builtin")),
        "available": bool(entry.get("builtin")),
        "path": "",
        "version": "",
        "command": "",
        "note": "comes with nanoWrap" if entry.get("builtin") else "",
    }

    if not entry.get("builtin"):
        for name in entry["commands"]:
            found = shutil.which(name)
            if not found:
                continue
            result["available"] = True
            result["path"] = found
            result["command"] = name
            result["version"] = _probe(found, entry["version_args"])
            break

    with _cache_lock:
        _cache[tool_id] = dict(result)
    return result


def find_all(use_cache: bool = True) -> list:
    return [find(entry["id"], use_cache=use_cache) for entry in catalog()]


def found_ones(use_cache: bool = True) -> list:
    return [entry for entry in find_all(use_cache) if entry["available"]]


def refresh() -> list:
    """Look again — for the person who just installed something."""
    with _cache_lock:
        _cache.clear()
    return find_all(use_cache=False)


def machine_note() -> str:
    """One honest sentence about this computer."""
    available = found_ones()
    missing = [entry for entry in find_all() if not entry["available"]]
    ready = [entry for entry in available if not entry["builtin"]]
    if not ready and not missing:
        return "nanoWrap found its own built-in tools, and has not looked for the others yet."
    if not ready:
        return ("None of the extra programs are installed on this computer yet. "
                "The built-in tools work anyway, and every missing program comes with "
                "a one-line way to get it.")
    return "%d of %d extra programs ready on this computer." % (len(ready), len(ready) + len(missing))


def version_line() -> str:
    return "%s · Python %s · %s" % (platform.platform(terse=True), sys.version.split()[0], OS_LABEL)
