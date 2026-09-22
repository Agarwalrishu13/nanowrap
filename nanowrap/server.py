"""Every address the page talks to.

The shape of a session: **look** at what this computer has → **drop** a file in
→ **pick** a job → **watch** it work → **take** the result.

Long jobs run on a background thread and the page watches them by asking for
new log lines since a cursor, so a two-hour video does not freeze a tab.
"""

from __future__ import annotations

import atexit
import io
import os
import re
import subprocess
import sys
import threading
import uuid
import zipfile
from pathlib import Path

from . import APP_NAME, __version__, runner, store, tasks, toolbox
from .httpbase import App, Bytes, Error, Json

WEB_DIR = Path(__file__).parent / "web"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\- +()]+")

# One in-flight upload at a time per id; process-local on purpose.
_uploads: dict[str, dict] = {}
_uploads_lock = threading.Lock()


def _safe_filename(name: str) -> str:
    cleaned = _SAFE_NAME.sub("_", os.path.basename(name or "")).strip(" .")
    return cleaned[:160] or "file"


def _inside(folder: Path, name: str) -> Path | None:
    """A path inside `folder`, or None if the name tries to escape it."""
    target = (folder / _safe_filename(name)).resolve()
    try:
        target.relative_to(folder.resolve())
    except ValueError:
        return None
    return target


def _size_mb(path) -> float:
    try:
        path = Path(path)
        if path.is_dir():
            return round(sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
                         / (1024 * 1024), 2)
        return round(path.stat().st_size / (1024 * 1024), 2)
    except OSError:
        return 0.0


def _commands_text(plan: dict) -> str:
    lines = []
    for argv in plan.get("commands", []):
        lines.append(" ".join('"%s"' % part if " " in str(part) else str(part) for part in argv))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Doing the work
# --------------------------------------------------------------------------
def _make_work(entry: dict, spec: dict):
    """Build the function that runs on the background thread for one job."""
    plan = spec.get("plan") or {}
    inputs = spec["inputs"]
    builtin = entry.get("builtin_run")

    def work(job: runner.Job) -> None:
        job.log(entry.get("sentence") or "Working…")
        before = sum(_size_mb(path) for path in inputs.files)

        if builtin:
            outcome = builtin(job, inputs)
            made = outcome.get("made", [])
            note = outcome.get("note", "")
            folder = outcome.get("folder", "")
        else:
            commands = plan.get("commands") or []
            made = [path for path in plan.get("made", []) if os.path.exists(path)]
            note = plan.get("note", "")
            folder = ""
            # A progress percentage is only possible when we know how long the
            # recording is; ffprobe tells us, and it is optional.
            total_seconds = 0.0
            if entry["tool"] == "ffmpeg" and inputs.first and toolbox.kind_of(inputs.first) in ("video", "audio"):
                total_seconds = runner.duration_of(inputs.first)
            watcher = runner.progress_watcher(job, total_seconds)
            if total_seconds:
                job.log("This recording is %d minutes long." % round(total_seconds / 60))

            for position, argv in enumerate(commands, start=1):
                if len(commands) > 1:
                    job.log("File %d of %d…" % (position, len(commands)))
                    if not total_seconds:
                        job.set_progress(int((position - 1) * 100 / len(commands)))
                code = runner.run_command(job, argv, on_line=watcher)
                if code != 0:
                    label = toolbox.tool(entry["tool"])["called"] if toolbox.tool(entry["tool"]) else "The program"
                    job.fail(runner.explain_failure(label, code, job.lines[-120:]))
                    return
            made = [path for path in plan.get("made", []) if os.path.exists(path)]
            if not made and not plan.get("folders"):
                job.fail("It finished, but no file came out. The programme may not have "
                         "understood the file you dropped in.")
                return

        made = [path for path in made if os.path.exists(path)]
        after = sum(_size_mb(path) for path in made)
        files = []
        for path in made:
            item = Path(path)
            files.append({
                "name": item.name,
                "path": str(item),
                "is_folder": item.is_dir(),
                "size_mb": _size_mb(item),
                "download": "/api/download/" + item.name,
                "kind": "folder" if item.is_dir() else toolbox.kind_sentence(toolbox.kind_of(item.name)),
            })
        if not files:
            job.fail("It finished, but nothing appeared in nanoWrap's folder.")
            return

        saved = None
        if before and after and not Path(files[0]["path"]).is_dir():
            saved = int(round((1 - after / before) * 100)) if before > after else 0

        first = files[0]
        job.log("Finished: %s (%.1f MB)." % (first["name"], first["size_mb"]))
        job.finish({
            "note": note,
            "files": files,
            "folder": folder or str(store.outputs_dir()),
            "before_mb": round(before, 2),
            "after_mb": round(after, 2),
            "saved_pct": saved,
            "command": _commands_text(plan) if plan else "",
            "task": entry["id"],
            "title": entry["title"],
        })
        if first["is_folder"]:
            store.add_history({"name": first["name"], "path": first["path"],
                               "task": entry["id"], "title": entry["title"],
                               "is_folder": True, "size_mb": first["size_mb"]})
            for extra in files[1:]:
                store.add_history({"name": extra["name"], "path": extra["path"], "task": entry["id"],
                                   "title": entry["title"], "is_folder": extra["is_folder"],
                                   "size_mb": extra["size_mb"]})
        else:
            for extra in files:
                store.add_history({"name": extra["name"], "path": extra["path"], "task": entry["id"],
                                   "title": entry["title"], "is_folder": extra["is_folder"],
                                   "size_mb": extra["size_mb"]})

    return work


# --------------------------------------------------------------------------
def create_app() -> App:
    app = App(APP_NAME, WEB_DIR, __version__)

    # ------------------------------------------------------------------ look
    @app.get("/api/health")
    def health(_request):
        return Json({"ok": True, "app": APP_NAME, "version": __version__})

    def _state(use_cache: bool = True) -> dict:
        found = toolbox.find_all(use_cache=use_cache)
        available = {tool["id"]: tool["available"] for tool in found}
        settings = store.load_settings()
        return {
            "app": APP_NAME,
            "version": __version__,
            "python": sys.version.split()[0],
            "tools": found,
            "tasks": tasks.public_listing(available),
            "history": store.load_history(),
            "settings": settings,
            "note": toolbox.machine_note(),
            "system": toolbox.version_line(),
            "folder": str(store.outputs_dir()),
            "free_mb": store.free_space_mb(),
            "running": runner.recent(6),
        }

    @app.get("/api/state")
    def state(_request):
        return Json(_state())

    @app.post("/api/check")
    def check(_request):
        """Look again for the programs, in case one was just installed."""
        before = {tool["id"]: tool["available"] for tool in toolbox.find_all()}
        found = toolbox.refresh()
        after = {tool["id"]: tool["available"] for tool in found}
        arrived = [tool["called"] for tool in found if after[tool["id"]] and not before[tool["id"]]]
        missing = [tool["called"] for tool in found if not tool["available"] and not tool["builtin"]]
        if arrived:
            message = "Found %s. %s" % (", ".join(arrived), "It is ready to use now.")
        elif missing:
            message = "Still missing: %s. Every one of them comes with a one-line way to get it." % ", ".join(missing)
        else:
            message = "Everything nanoWrap knows about is on this computer."
        return Json({**_state(use_cache=False), "message": message})

    @app.post("/api/settings")
    def settings(request):
        patch = request.json()
        if not isinstance(patch, dict):
            return Error("Settings must be named values.")
        return Json({"settings": store.save_settings(patch)})

    # ---------------------------------------------------------------- upload
    @app.post("/api/upload/start")
    def upload_start(request):
        body = request.json()
        name = _safe_filename(str(body.get("name", "file")))
        settings_now = store.load_settings()
        try:
            size_mb = float(body.get("size_mb") or 0)
        except (TypeError, ValueError):
            size_mb = 0
        if size_mb and size_mb > float(settings_now.get("max_upload_mb", 2048)):
            return Error("That file is %.0f MB. nanoWrap stops at %.0f MB — make it smaller first, "
                         "or raise the limit in Settings." % (size_mb, float(settings_now["max_upload_mb"])))
        if store.free_space_mb() not in (-1,) and size_mb and store.free_space_mb() < size_mb * 1.5:
            return Error("There is only %d MB free on this disk, which is not enough room for a "
                         "%.0f MB file plus the copy nanoWrap would make." % (store.free_space_mb(), size_mb))
        upload_id = uuid.uuid4().hex
        target = store.uploads_dir() / (upload_id + ".part")
        target.write_bytes(b"")
        with _uploads_lock:
            _uploads[upload_id] = {"name": name, "path": target, "received": 0}
        return Json({"id": upload_id, "name": name, "chunk_bytes": 4 * 1024 * 1024})

    @app.post("/api/upload/chunk")
    def upload_chunk(request):
        upload_id = request.q("id", "")
        with _uploads_lock:
            entry = _uploads.get(upload_id)
        if not entry:
            return Error("That upload expired. Start again.")
        try:
            offset = int(request.q("offset", "-1"))
        except ValueError:
            return Error("Bad offset.")
        if offset != entry["received"]:
            return Error("The pieces arrived out of order.", 409, expected=entry["received"])
        with open(entry["path"], "ab") as handle:
            handle.write(request.body)
        entry["received"] += len(request.body)
        return Json({"received": entry["received"]})

    @app.post("/api/upload/finish")
    def upload_finish(request):
        upload_id = str(request.json().get("id", ""))
        with _uploads_lock:
            entry = _uploads.pop(upload_id, None)
        if not entry:
            return Error("That upload expired. Start again.")
        destination = store.uploads_dir() / entry["name"]
        os.replace(entry["path"], destination)
        return Json(_describe_arrival(destination, upload_id))

    def _describe_arrival(path: Path, reference: str) -> dict:
        """Everything the page needs to know about a file that just arrived."""
        kind = toolbox.kind_of(path.name)
        note = ""
        if kind == "video" and _ffprobe_present() and runner.duration_of(str(path)) == 0:
            note = ("I could not find any video inside that file. It may be damaged, or it may "
                    "really be a different kind of file with a .mp4 name.")
        return {
            "id": reference,
            "name": path.name,
            "path": str(path),
            "kind": kind,
            "kind_word": toolbox.kind_sentence(kind),
            "size_mb": _size_mb(path),
            "tasks": [task["id"] for task in tasks.for_kind(kind)],
            "note": note,
        }

    def _ffprobe_present() -> bool:
        try:
            return bool(tasks.ffprobe_path())
        except Exception:
            return False

    # --------------------------------------------------------------- practice
    @app.post("/api/sample")
    def sample(_request):
        """Make a few small files to practise on, so nobody has to hunt for one.

        The video and the pictures are drawn by FFmpeg itself when it is here —
        a made-up picture pattern and a tone, nothing that belongs to anybody.
        """
        folder = store.uploads_dir()
        made: list[Path] = []
        texts = {
            "practice-shopping-list.txt": "shopping list\n\nbread\nmilk\ncoffee\n"
                                          "something for dinner\nstamps\n",
            "practice-notes.md": "# Notes\n\nThis is a small text file nanoWrap made for you.\n"
                                 "Drop it on the page and try the built-in jobs: pack it, "
                                 "number it, or ask how big it is.\n",
            "practice-recipe.md": "# Toast\n\n1. Bread in the toaster.\n2. Wait.\n"
                                  "3. Butter, salt, eat.\n",
        }
        for name, text in texts.items():
            path = folder / name
            path.write_text(text, encoding="utf-8")
            made.append(path)

        pack = folder / "practice-files.zip"
        with zipfile.ZipFile(pack, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in texts:
                archive.write(folder / name, name)
        made.append(pack)

        ffmpeg = toolbox.find("ffmpeg")
        if ffmpeg["available"]:
            video = folder / "practice-video.mp4"
            if _try_ffmpeg([
                ffmpeg["path"], "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24:duration=6",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video),
            ]):
                made.append(video)
            for number in (1, 2, 3):
                picture = folder / ("practice-picture-%d.png" % number)
                if _try_ffmpeg([
                    ffmpeg["path"], "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc2=size=900x600:rate=1", "-frames:v", "1", str(picture),
                ]):
                    made.append(picture)
            sound = folder / "practice-sound.mp3"
            if _try_ffmpeg([
                ffmpeg["path"], "-y", "-loglevel", "error", "-f", "lavfi",
                "-i", "sine=frequency=440:duration=8", "-c:a", "libmp3lame", "-b:a", "128k", str(sound),
            ]):
                made.append(sound)

        files = [_describe_arrival(path, "sample-" + path.stem) for path in made if path.exists()]
        note = ("Made %d practice files for you — they are small and made up." % len(files))
        if not ffmpeg["available"]:
            note += (" No video or pictures this time, because FFmpeg is not installed yet; "
                     "the text files and the zip still work.")
        return Json({"files": files, "message": note})

    def _try_ffmpeg(argv: list) -> bool:
        """Make one practice file. A failure here is not an error — it is a
        bonus that did not happen, so it never reaches the page as one."""
        try:
            finished = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      timeout=90, text=True, errors="replace")
        except (OSError, subprocess.SubprocessError):
            return False
        return finished.returncode == 0

    # ------------------------------------------------------------------- run
    @app.post("/api/run")
    def run(request):
        body = request.json()
        task_id = str(body.get("task", ""))
        files = [str(path) for path in (body.get("files") or [])]
        values = body.get("values") or {}
        if not isinstance(values, dict):
            return Error("The answers should be named values.")

        for path in files:
            if not os.path.isfile(path):
                return Error("I cannot find “%s” any more. Drop it in again." % os.path.basename(path))
            allowed = store.uploads_dir().resolve()
            try:
                Path(path).resolve().relative_to(allowed)
            except ValueError:
                return Error("That file is not one nanoWrap received, so it will not touch it.")
        try:
            spec = tasks.plan_for(task_id, files, values)
        except ValueError as exc:
            return Error(str(exc))

        entry = spec["task"]
        job = runner.start_job(entry["title"], toolbox.tool(entry["tool"])["called"], _make_work(entry, spec))
        return Json({"job_id": job.id, "title": job.title, "message": entry.get("sentence", "Started.")})

    @app.get("/api/job/{job_id}")
    def job_status(request):
        job = runner.get_job(request.params["job_id"])
        if not job:
            return Error("I lost track of that job. It may have been one of the older ones.", 404)
        return Json(job.payload(since=request.q_int("since", 0)))

    @app.post("/api/job/{job_id}/stop")
    def job_stop(request):
        if not runner.stop_job(request.params["job_id"]):
            return Error("That job is not running any more.")
        return Json({"message": "Stopping. Nothing half-finished will be kept."})

    # -------------------------------------------------------------- downloads
    @app.get("/api/download/{name}")
    def download(request):
        target = _inside(store.outputs_dir(), request.params["name"])
        if target is None:
            return Error("Not allowed.", 403)
        if not target.exists():
            return Error("That file is gone — nanoWrap tidies up files it made after a while.", 404)
        if target.is_dir():
            # A folder is handed over as one zip, built the moment you ask.
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for child in sorted(target.rglob("*")):
                    if child.is_file():
                        archive.write(child, child.relative_to(target.parent))
            return Bytes(buffer.getvalue(), "application/zip")
        return Bytes(target.read_bytes(), _content_type(target.name))

    def _content_type(name: str) -> str:
        kind = toolbox.kind_of(name)
        mapping = {
            "video": "video/mp4", "audio": "audio/mpeg", "image": "image/jpeg",
            "pdf": "application/pdf", "archive": "application/zip",
            "document": "application/octet-stream", "sheet": "text/csv; charset=utf-8",
        }
        if name.endswith(".txt"):
            return "text/plain; charset=utf-8"
        if name.endswith(".png"):
            return "image/png"
        if name.endswith(".jpg") or name.endswith(".jpeg"):
            return "image/jpeg"
        if name.endswith(".gif"):
            return "image/gif"
        if name.endswith(".zip"):
            return "application/zip"
        return mapping.get(kind, "application/octet-stream")

    @app.post("/api/reveal")
    def reveal(request):
        """Open nanoWrap's folder in the file manager — the answer to
        'where did my file go?'."""
        wanted = str(request.json().get("name", ""))
        folder = store.outputs_dir()
        if wanted:
            candidate = _inside(folder, wanted)
            if candidate is None:
                return Error("Not allowed.", 403)
            if candidate.is_dir():
                folder = candidate
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(folder))                        # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except (OSError, AttributeError) as exc:
            return Json({"opened": False, "folder": str(folder),
                         "message": "I could not open a folder window (%s), but your files are in %s"
                                    % (exc, folder)})
        return Json({"opened": True, "folder": str(folder),
                     "message": "Opened %s" % folder})

    @app.post("/api/forget")
    def forget(request):
        what = str(request.json().get("what", "history"))
        if what == "history":
            store.forget_history()
            return Json({"message": "The list of recent files is cleared. The files themselves are still there.",
                         "history": []})
        if what == "all":
            outcome = store.clear_outputs()
            return Json({"message": "Removed %d item%s and freed %.1f MB. Your original files were never touched."
                                    % (outcome["removed"], "" if outcome["removed"] == 1 else "s",
                                       outcome["freed_mb"]),
                         "history": []})
        return Error("I do not know how to forget that.")

    @app.get("/api/history")
    def history(_request):
        return Json({"history": store.load_history()})

    @app.get("/api/about")
    def about(_request):
        return Json({
            "app": APP_NAME,
            "version": __version__,
            "folder": str(store.outputs_dir()),
            "offline": True,
            "what_it_runs": [
                {"id": tool["id"], "called": tool["called"], "available": tool["available"],
                 "path": tool["path"]} for tool in toolbox.find_all()
            ],
            "siblings": [
                {"name": "nanolaama", "url": "https://github.com/Agarwalrishu13/nanolaama",
                 "what": "talk to an AI on your own computer"},
                {"name": "nanolearn", "url": "https://github.com/Agarwalrishu13/nanolearn",
                 "what": "drop a spreadsheet, get an answer machine"},
                {"name": "nanosay", "url": "https://github.com/Agarwalrishu13/nanosay",
                 "what": "have a document read out loud"},
                {"name": "nonoforge", "url": "https://github.com/Agarwalrishu13/nonoforge",
                 "what": "make a whole project without coding"},
                {"name": "nanohome", "url": "https://github.com/Agarwalrishu13/nanohome",
                 "what": "one window for all of these"},
            ],
        })

    # Files dropped in are copies; the originals stay wherever you kept them, so
    # the copies are cleared out when the app closes.
    atexit.register(store.clear_dropped_input)
    return app
