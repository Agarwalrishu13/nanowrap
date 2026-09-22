"""Running the commands, and explaining them when they go wrong.

Everything happens on a background thread so the page never freezes, and the
output of the program is streamed into the job's log line by line — the same
lines a person would see in a terminal window, which is exactly what makes a
failure diagnosable instead of mysterious.

A failure is never shown to the user as a stack trace. :func:`explain_failure`
turns the program's own words into one sentence about what happened and what to
do next.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
import uuid

MAX_LOG_LINES = 3000
KEEP_JOBS = 40


class JobStopped(Exception):
    """Raised inside a job's work when somebody pressed Stop."""


class Job:
    """One thing being done, and everything that happened while it was done."""

    def __init__(self, title: str, tool_label: str = ""):
        self.id = uuid.uuid4().hex[:12]
        self.title = title
        self.tool = tool_label
        self.state = "running"          # running | done | error | stopped
        self.lines: list[str] = []
        self.progress = 0
        self.result: dict = {}
        self.error = ""
        self.started = time.time()
        self.ended = 0.0
        self.stopping = False
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()

    # -- things the work itself calls ------------------------------------
    def log(self, message: str) -> None:
        text = str(message).rstrip()
        if not text:
            return
        with self._lock:
            self.lines.append(text)
            if len(self.lines) > MAX_LOG_LINES:
                del self.lines[:len(self.lines) - MAX_LOG_LINES]

    def set_progress(self, value) -> None:
        try:
            self.progress = max(0, min(100, int(value)))
        except (TypeError, ValueError):
            self.progress = 0

    def check(self) -> None:
        """Called from inside long loops so Stop takes effect quickly."""
        if self.stopping:
            raise JobStopped()

    def finish(self, result: dict) -> None:
        self.result = dict(result or {})
        self.state = "stopped" if self.stopping else "done"
        self.progress = 100 if self.state == "done" else self.progress
        self.ended = time.time()

    def fail(self, message: str) -> None:
        self.error = str(message or "It did not finish.")
        self.state = "stopped" if self.stopping else "error"
        self.ended = time.time()

    # -- things the page asks for ----------------------------------------
    def stop(self) -> bool:
        """Ask this job to stop. True if it was still going."""
        if self.state != "running":
            return False
        self.stopping = True
        process = self._process
        if process and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
            threading.Thread(target=self._kill_soon, args=(process,), daemon=True).start()
        return True

    @staticmethod
    def _kill_soon(process) -> None:
        """Give it three seconds to leave politely, then insist."""
        for _ in range(30):
            if process.poll() is not None:
                return
            time.sleep(0.1)
        try:
            process.kill()
        except OSError:
            pass

    def payload(self, since: int = 0) -> dict:
        with self._lock:
            lines = list(self.lines)
        start = max(0, int(since))
        if start > len(lines):          # the log was trimmed under the cursor
            start = max(0, len(lines) - 200)
        clean = {key: value for key, value in self.result.items() if key != "_internal"}
        return {
            "id": self.id,
            "title": self.title,
            "tool": self.tool,
            "state": self.state,
            "progress": self.progress,
            "log": lines[start:],
            "cursor": len(lines),
            "error": self.error,
            "result": clean if self.state in ("done", "error", "stopped") else {},
            "seconds": round((self.ended or time.time()) - self.started, 1),
        }


# --------------------------------------------------------------------------
# The job book
# --------------------------------------------------------------------------
_jobs: dict[str, Job] = {}
_order: list[str] = []
_jobs_lock = threading.Lock()


def start_job(title: str, tool_label: str, work) -> Job:
    """Run `work(job)` on a background thread and hand back the job to watch."""
    job = Job(title, tool_label)
    with _jobs_lock:
        _jobs[job.id] = job
        _order.append(job.id)
        while len(_order) > KEEP_JOBS:
            _jobs.pop(_order.pop(0), None)

    def run() -> None:
        try:
            work(job)
        except JobStopped:
            job.fail("You stopped it. Nothing was finished — your original file is untouched.")
        except ValueError as exc:                     # a readable refusal from a task
            job.fail(str(exc))
        except Exception as exc:                      # a bug: say so, do not dump a trace
            job.log("Something inside nanoWrap went wrong: %s" % exc)
            job.fail("Something inside nanoWrap went wrong. The details are in the log above.")

    threading.Thread(target=run, name="nanowrap-job-" + job.id, daemon=True).start()
    return job


def get_job(job_id: str) -> Job | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def recent(limit: int = 8) -> list:
    with _jobs_lock:
        ids = list(_order)[-limit:]
    out = []
    for job_id in reversed(ids):
        job = get_job(job_id)
        if job:
            out.append({"id": job.id, "title": job.title, "state": job.state,
                        "when": job.started, "error": job.error})
    return out


def stop_job(job_id: str) -> bool:
    job = get_job(job_id)
    return bool(job and job.stop())


# --------------------------------------------------------------------------
# Running one command
# --------------------------------------------------------------------------
def run_command(job: Job, argv: list, on_line=None, timeout: int = 3600) -> int:
    """Run one command, stream its output into the job log, return its code.

    ``argv`` must be a list. There is no ``shell=True`` anywhere in nanoWrap, so
    a file named ``; rm -rf *.mp4`` is a file with a silly name and nothing more.
    """
    job.check()
    program = argv[0] if argv else ""
    if not program:
        raise ValueError("There is no program to run for this job.")
    if not os.path.isfile(program) and not _which(program):
        raise ValueError("%s is not on this computer, so this job cannot run." % os.path.basename(program))

    shown = " ".join(_quote(part) for part in argv)
    job.log("$ " + shown)
    try:
        process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True, bufsize=1,
            errors="replace", cwd=str(_home()),
        )
    except FileNotFoundError:
        raise ValueError("%s is not on this computer any more. Try “Check again”."
                         % os.path.basename(program))
    except OSError as exc:
        raise ValueError("That program would not start (%s)." % exc)

    job._process = process
    deadline = time.time() + timeout
    assert process.stdout is not None
    try:
        for line in iter(process.stdout.readline, ""):
            job.log(line)
            if on_line:
                on_line(line)
            if job.stopping:
                try:
                    process.terminate()
                except OSError:
                    pass
                break
            if time.time() > deadline:
                job.log("This is taking far longer than it should — stopping it.")
                try:
                    process.terminate()
                except OSError:
                    pass
                break
    finally:
        try:
            process.stdout.close()
        except OSError:
            pass
    process.wait()
    job._process = None
    job.check()
    return process.returncode


def _quote(part: str) -> str:
    return '"%s"' % part if " " in part else part


def _which(name: str) -> str:
    import shutil
    return shutil.which(name) or ""


def _home():
    from . import store
    return store.data_dir()


# --------------------------------------------------------------------------
# Turning a program's own words into a sentence for a person
# --------------------------------------------------------------------------
_TROUBLE = (
    (re.compile(r"no such file or directory|cannot find the file|system cannot find", re.I),
     "It could not find one of the files — it may have been moved or renamed while it was working."),
    (re.compile(r"invalid data found when processing input|moov atom not found|"
                r"does not contain any stream|error opening input|invalid argument", re.I),
     "That file does not look like something this program can read. It may be damaged, "
     "or it may be a different kind of file wearing the wrong name."),
    (re.compile(r"permission denied|access is denied", re.I),
     "This computer would not let it write the finished file. Try again — if it keeps "
     "happening, the folder may be set to read-only."),
    (re.compile(r"no space left|not enough space|disk full", re.I),
     "There is not enough free space on the disk to write the result."),
    (re.compile(r"unrecognized option|unknown option|not recognized as an internal", re.I),
     "The version of this program on your computer is older than nanoWrap expects, so it "
     "did not understand one of the instructions."),
    (re.compile(r"not a valid zip|badzipfile|cannot open the file", re.I),
     "That file is not a proper zip. It may have only been half downloaded — try downloading it again."),
)


def interesting(lines: list, limit: int = 3) -> list:
    """The lines worth repeating: no version banners, no progress spam."""
    noisy = re.compile(r"^(ffmpeg version|configuration:|built with|lib[a-z]+|"
                       r"frame=|size=|Copyright|welcome to|pandoc [0-9]|"
                       r"ImageMagick|Deleting|Paths:|Features:|Delegates:|"
                       r"HDRI|Operating system|Version:|zlib|Libxml|"
                       r"7-Zip|Scanning|Creating|Everything is Ok|Extracting)", re.I)
    keep = []
    for line in lines:
        text = str(line).strip()
        if not text or noisy.match(text):
            continue
        keep.append(text[:300])
    return keep[-limit:]


def explain_failure(tool_label: str, code: int, lines: list) -> str:
    """One sentence a person can act on."""
    joined = "\n".join(str(line) for line in lines[-200:])
    for pattern, sentence in _TROUBLE:
        if pattern.search(joined):
            return sentence
    if code in (-9, -15, 1, 130) and not joined.strip():
        return "%s stopped without saying why." % (tool_label or "The program")
    tail = interesting(lines)
    if tail:
        return "%s stopped (code %d). The last thing it said was: “%s”" % (
            tool_label or "The program", code, tail[-1])
    return "%s stopped with code %d and did not say why." % (tool_label or "The program", code)


# --------------------------------------------------------------------------
# Progress for programs that report it
# --------------------------------------------------------------------------
_TIME = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


def duration_of(path: str) -> float:
    """How long is this recording, in seconds? 0 when we cannot tell."""
    from .tasks import ffprobe_path
    probe = ffprobe_path()
    if not probe:
        return 0.0
    try:
        finished = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20,
            text=True, errors="replace",
        )
        return float((finished.stdout or "0").strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def progress_watcher(job: Job, total_seconds: float):
    """A callback that turns ffmpeg's ``time=`` line into a percentage."""
    if total_seconds <= 0:
        return None

    def watch(line: str) -> None:
        found = _TIME.search(line)
        if not found:
            return
        hours, minutes, seconds = int(found.group(1)), int(found.group(2)), float(found.group(3))
        done = hours * 3600 + minutes * 60 + seconds
        job.set_progress(int(min(99, done * 100 / total_seconds)))

    return watch
