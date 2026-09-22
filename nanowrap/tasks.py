"""Every job nanoWrap can do, and the exact command it runs for you.

A task is a small dictionary: what it is called, which kind of file it wants,
the boxes to show on the page, and a ``plan`` function that turns your answers
into a list of commands. The plan functions are plain, pure functions — given
the same answers they produce the same command — which is why they can be
tested without a single video or PDF in sight.

Two rules are absolute here:

* Commands are always passed as a *list* of arguments, never as one string, and
  never through a shell. A file called ``my video; rm -rf ~.mp4`` is just a
  file with an odd name.
* Every file a task writes goes into nanoWrap's own output folder. Nothing is
  written next to your originals, and nothing is ever deleted.
"""

from __future__ import annotations

import os
import re
import shutil
import zipfile
from pathlib import Path

from . import store, toolbox

_SAFE = re.compile(r"[^A-Za-z0-9._\- ]+")


# --------------------------------------------------------------------------
# What a task is handed when it runs
# --------------------------------------------------------------------------
class Inputs:
    """The files you dropped, the answers you gave, and where to put results.

    The programs themselves are resolved once, before the job starts, and
    carried in ``tools`` — so a plan can be built (and tested) on a machine that
    has none of them installed.
    """

    def __init__(self, files: list, values: dict, out_dir=None, tools: dict | None = None):
        self.files = [str(path) for path in files]
        self.values = dict(values or {})
        self.out_dir = Path(out_dir) if out_dir else store.outputs_dir()
        self.tools = dict(tools or {})

    @property
    def first(self) -> str:
        return self.files[0] if self.files else ""

    def program(self, tool_id: str) -> str:
        """The full path of a program, or a readable refusal."""
        path = self.tools.get(tool_id)
        if not path:
            entry = toolbox.tool(tool_id) or {}
            raise ValueError("%s is not on this computer, so this job cannot run yet."
                             % (entry.get("called") or tool_id))
        return path

    @property
    def first(self) -> str:
        return self.files[0] if self.files else ""

    def value(self, name: str, default=None):
        value = self.values.get(name, default)
        return default if value in (None, "") else value

    def choice(self, name: str, default: str) -> str:
        return str(self.value(name, default))

    def number(self, name: str, default: float) -> float:
        try:
            return float(self.value(name, default))
        except (TypeError, ValueError):
            return float(default)

    def stem(self, name: str = "") -> str:
        return Path(name or self.first).stem

    def extension(self) -> str:
        return Path(self.first).suffix.lower()

    def out(self, name: str) -> str:
        """A path in the output folder that is not taken yet."""
        clean = _SAFE.sub("_", os.path.basename(name)).strip(" .") or "result"
        return str(store.free_name(clean, self.out_dir))

    def folder(self, name: str) -> Path:
        """A fresh folder in the output folder."""
        clean = _SAFE.sub("_", os.path.basename(name)).strip(" .") or "result"
        target = self.out_dir / clean
        counter = 2
        while target.exists():
            target = self.out_dir / ("%s-%d" % (clean, counter))
            counter += 1
        target.mkdir(parents=True, exist_ok=True)
        return target


def _size_mb(path: str) -> float:
    try:
        return os.path.getsize(path) / (1024 * 1024)
    except OSError:
        return 0.0


def ffprobe_path() -> str:
    """ffprobe lives beside ffmpeg and tells us how long a video is."""
    beside = os.path.join(os.path.dirname(toolbox.find("ffmpeg")["path"] or ""), "ffprobe")
    for candidate in (beside + ".exe", beside, "ffprobe"):
        found = shutil.which(candidate) if os.path.sep not in candidate else (
            candidate if os.path.isfile(candidate) else None)
        if found:
            return found
    return ""


def seconds_of(value, default: float = 0.0) -> float:
    """Read "1:30", "90", "01:02:03" the way a person would write it."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return default
    if ":" not in text:
        try:
            return float(text)
        except ValueError:
            return default
    total = 0.0
    for part in text.split(":"):
        try:
            total = total * 60 + float(part)
        except ValueError:
            return default
    return total


def stamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return "%02d:%02d:%02d" % (hours, minutes, secs)


# ==========================================================================
# FFmpeg — video and sound
# ==========================================================================
def _plan_shrink(inputs: Inputs) -> dict:
    sizes = {
        "tiny": ("32", "960:-2", "Tiny — good for WhatsApp and email"),
        "small": ("28", "1280:-2", "Small — good for sharing, still looks sharp"),
        "good": ("23", "1920:-2", "Good — keeps it close to the original"),
    }
    crf, scale, _label = sizes.get(inputs.choice("how_small", "small"), sizes["small"])
    out = inputs.out(inputs.stem() + "-small.mp4")
    return {
        "commands": [[
            inputs.program("ffmpeg"), "-y", "-i", inputs.first,
            "-vf", "scale=%s" % scale,
            "-c:v", "libx264", "-crf", crf, "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            out,
        ]],
        "made": [out],
        "note": "Smaller files come from throwing away detail your eye will not miss.",
    }


def _plan_sound_from_video(inputs: Inputs) -> dict:
    out = inputs.out(inputs.stem() + ".mp3")
    return {
        "commands": [[inputs.program("ffmpeg"), "-y", "-i", inputs.first,
                      "-vn", "-c:a", "libmp3lame", "-q:a", "2", out]],
        "made": [out],
        "note": "This keeps the sound and drops the picture.",
    }


def _plan_video_to_gif(inputs: Inputs) -> dict:
    width = {"small": "360", "medium": "480", "large": "640"}.get(inputs.choice("how_big", "medium"), "480")
    speed = str(int(inputs.number("speed", 12)))
    out = inputs.out(inputs.stem() + ".gif")
    return {
        "commands": [[
            inputs.program("ffmpeg"), "-y", "-i", inputs.first,
            "-vf", "fps=%s,scale=%s:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" % (speed, width),
            "-loop", "0", out,
        ]],
        "made": [out],
        "note": "A GIF has no sound and only 256 colours, so keep it short.",
    }


def _plan_trim(inputs: Inputs) -> dict:
    start = stamp(seconds_of(inputs.value("start", "0")))
    end = inputs.value("end", "")
    command = [inputs.program("ffmpeg"), "-y", "-i", inputs.first, "-ss", start]
    if end:
        command += ["-to", stamp(seconds_of(end))]
    out = inputs.out(inputs.stem() + "-cut.mp4")
    command += ["-c:v", "libx264", "-crf", "23", "-preset", "veryfast", "-c:a", "aac", out]
    return {
        "commands": [command],
        "made": [out],
        "note": "Times are written like 0:30 or 1:02:15 — both work.",
    }


def _plan_still(inputs: Inputs) -> dict:
    at = stamp(seconds_of(inputs.value("at", "1")))
    out = inputs.out(inputs.stem() + "-picture.jpg")
    return {
        "commands": [[inputs.program("ffmpeg"), "-y", "-ss", at, "-i", inputs.first,
                      "-frames:v", "1", "-q:v", "2", out]],
        "made": [out],
        "note": "A single frame from the video, saved as a photo.",
    }


def _plan_audio(inputs: Inputs) -> dict:
    bitrate = inputs.choice("bitrate", "192k")
    out = inputs.out(inputs.stem() + "-" + bitrate + ".mp3")
    return {
        "commands": [[inputs.program("ffmpeg"), "-y", "-i", inputs.first,
                      "-vn", "-c:a", "libmp3lame", "-b:a", bitrate, out]],
        "made": [out],
        "note": "128k is fine for talking; 192k or 256k is better for music.",
    }


# ==========================================================================
# ImageMagick — pictures
# ==========================================================================
def _plan_resize_pictures(inputs: Inputs) -> dict:
    width = inputs.choice("size", "1600")
    quality = {"800": "78", "1600": "84", "2400": "88"}.get(width, "84")
    commands, made = [], []
    for path in inputs.files:
        out = inputs.out("%s-%spx.jpg" % (Path(path).stem, width))
        commands.append([inputs.program("magick"), path, "-auto-orient", "-resize", "%sx%s>" % (width, width),
                         "-strip", "-quality", quality, out])
        made.append(out)
    return {"commands": commands, "made": made,
            "note": "Photos from phones are enormous; this makes them friendly to send."}


def _plan_change_picture_kind(inputs: Inputs) -> dict:
    wanted = inputs.choice("kind", "png")
    commands, made = [], []
    for path in inputs.files:
        out = inputs.out("%s.%s" % (Path(path).stem, wanted))
        commands.append([inputs.program("magick"), path, "-auto-orient", out])
        made.append(out)
    return {"commands": commands, "made": made,
            "note": "PNG for sharp lines and screenshots, JPG for photographs."}


def _plan_pictures_to_pdf(inputs: Inputs) -> dict:
    out = inputs.out(inputs.value("name", "pictures") + ".pdf")
    command = [inputs.program("magick")]
    for path in inputs.files:
        command += [path, "-auto-orient"]
    command.append(out)
    return {"commands": [command], "made": [out],
            "note": "One page per picture, in the order you dropped them."}


# ==========================================================================
# Pandoc — documents
# ==========================================================================
def _plan_change_document(inputs: Inputs) -> dict:
    wanted = inputs.choice("format", "docx")
    out = inputs.out("%s.%s" % (inputs.stem(), wanted))
    command = [inputs.program("pandoc"), inputs.first, "-o", out]
    if wanted == "pdf":
        command = [inputs.program("pandoc"), inputs.first, "-o", out, "--pdf-engine=xelatex"]
    return {"commands": [command], "made": [out],
            "note": "PDF needs a LaTeX program installed as well; the others do not."}


# ==========================================================================
# Poppler — PDFs
# ==========================================================================
def _plan_pdf_to_text(inputs: Inputs) -> dict:
    out = inputs.out(inputs.stem() + ".txt")
    return {"commands": [[inputs.program("poppler"), "-layout", "-enc", "UTF-8", inputs.first, out]],
            "made": [out],
            "note": "If the result is empty, the PDF is probably a scan — a picture of "
                    "words rather than words. That needs different tools."}


def _plan_join_pdfs(inputs: Inputs) -> dict:
    out = inputs.out(inputs.value("name", "joined") + ".pdf")
    # pdfunite lives in the same folder as pdftotext.
    unite = os.path.join(os.path.dirname(inputs.program("poppler")), "pdfunite")
    command = [unite, *inputs.files, out]
    return {"commands": [command], "made": [out],
            "note": "The PDFs go in together in the order you dropped them."}


# ==========================================================================
# 7-Zip and curl
# ==========================================================================
def _plan_pack_with_7zip(inputs: Inputs) -> dict:
    out = inputs.out(inputs.value("name", "packed") + ".zip")
    return {"commands": [[inputs.program("sevenzip"), "a", "-tzip", "-mx=5", out, *inputs.files]],
            "made": [out],
            "note": "ZIP is the format every computer and phone can open."}


def _plan_open_with_7zip(inputs: Inputs) -> dict:
    folder = inputs.folder(inputs.stem() + "-opened")
    command = [inputs.program("sevenzip"), "x", "-y", "-o" + str(folder), inputs.first]
    return {"commands": [command], "made": [str(folder)], "folders": [str(folder)],
            "note": "Everything inside comes out into a folder of its own."}


def _plan_download(inputs: Inputs) -> dict:
    url = str(inputs.value("url", "")).strip()
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("That does not look like a web address. It should start with http:// or https://")
    name = str(inputs.value("name", "")).strip() or os.path.basename(url.split("?")[0]) or "download"
    if "." not in os.path.basename(name):
        name = name + ".bin"
    out = inputs.out(name)
    return {"commands": [[inputs.program("curl"), "-L", "--fail", "--silent", "--show-error",
                          "--output", out, url]],
            "made": [out],
            "note": "Only download things you have the right to download."}


# ==========================================================================
# Built into nanoWrap — pure Python, no programs needed
# ==========================================================================
def _zip_folder(job, inputs: Inputs, paths: list, target: Path, note: str = "") -> None:
    total = len(paths)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for position, path in enumerate(paths, start=1):
            job.check()
            source = Path(path)
            if source.is_dir():
                members = [child for child in source.rglob("*") if child.is_file()]
                for member in members:
                    archive.write(member, member.relative_to(source.parent))
                job.log("Added the folder %s (%d files)." % (source.name, len(members)))
            else:
                archive.write(source, source.name)
                job.log("Added %s (%.1f MB)." % (source.name, _size_mb(path)))
            job.set_progress(int(position * 100 / max(1, total)))
    if note:
        job.log(note)


def _run_pack(job, inputs: Inputs) -> dict:
    target = Path(inputs.out(str(inputs.value("name", "packed")) + ".zip"))
    job.log("Packing %d item%s into one file…" % (len(inputs.files), "" if len(inputs.files) == 1 else "s"))
    _zip_folder(job, inputs, inputs.files, target)
    before = sum(_size_mb(path) for path in inputs.files if os.path.isfile(path))
    job.log("Done — %.1f MB went in, %.1f MB came out." % (before, _size_mb(str(target))))
    return {"made": [str(target)], "note": "Send this one file; whoever gets it can open it "
            "without installing anything."}


def _run_unpack(job, inputs: Inputs) -> dict:
    folder = inputs.folder(inputs.stem() + "-opened")
    job.log("Opening %s…" % os.path.basename(inputs.first))
    count = 0
    total_bytes = 0
    with zipfile.ZipFile(inputs.first) as archive:
        names = archive.namelist()
        for name in names:
            job.check()
            # A zip can claim a file is called "../../something" — refuse that.
            safe = Path(name.replace("\\", "/"))
            if safe.is_absolute() or ".." in safe.parts:
                job.log("Skipped a file with a suspicious name: %s" % name)
                continue
            archive.extract(name, folder)
            count += 1
            total_bytes += archive.getinfo(name).file_size
            if count % 25 == 0 or count == len(names):
                job.set_progress(int(count * 100 / max(1, len(names))))
    job.log("Unpacked %d files (%.1f MB) into “%s”." % (count, total_bytes / (1024 * 1024), folder.name))
    return {"made": [str(folder)], "folder": str(folder),
            "note": "The files are in a folder of their own. Use “Show me the folder” to open it."}


def _run_renumber(job, inputs: Inputs) -> dict:
    prefix = _SAFE.sub("-", str(inputs.value("prefix", "file")).strip()) or "file"
    width = max(2, len(str(len(inputs.files))))
    folder = inputs.folder(prefix + "-in-order")
    for position, path in enumerate(inputs.files, start=1):
        job.check()
        source = Path(path)
        target = folder / ("%s-%0*d%s" % (prefix, width, position, source.suffix.lower()))
        shutil.copy2(source, target)
        job.log("%s  →  %s" % (source.name, target.name))
        job.set_progress(int(position * 100 / max(1, len(inputs.files))))
    job.log("Numbered %d files in the order you dropped them." % len(inputs.files))
    return {"made": [str(folder)], "folder": str(folder),
            "note": "Your originals are untouched — these are copies with tidy names."}


def _run_list_sizes(job, inputs: Inputs) -> dict:
    lines = []
    for path in inputs.files:
        size = _size_mb(path)
        lines.append("%10.2f MB  %s" % (size, os.path.basename(path)))
        job.log(lines[-1])
    total = sum(_size_mb(path) for path in inputs.files)
    lines.append("%10.2f MB  TOTAL (%d files)" % (total, len(inputs.files)))
    job.log(lines[-1])
    report = Path(inputs.out("sizes.txt"))
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"made": [str(report)], "note": "A small text file listing what you dropped in."}


# ==========================================================================
# The catalogue
# ==========================================================================
def _choice(name, label, options, default, help_text=""):
    return {"name": name, "label": label, "type": "choice", "default": default,
            "options": [{"value": value, "label": text} for value, text in options], "help": help_text}


def _text(name, label, default="", help_text="", placeholder=""):
    return {"name": name, "label": label, "type": "text", "default": default,
            "help": help_text, "placeholder": placeholder}


TASKS = (
    # ---------------------------------------------------------------- wrap
    {
        "id": "pack",
        "tool": "wrap",
        "title": "Put these into one file",
        "blurb": "Everything you drop becomes a single .zip to send to somebody.",
        "wants": "any", "many": True, "builtin_run": _run_pack,
        "fields": [_text("name", "What should the file be called?", "packed", "No need to add .zip")],
        "sentence": "Packing your files…",
    },
    {
        "id": "unpack",
        "tool": "wrap",
        "title": "Open this zip file",
        "blurb": "Take everything out of a .zip somebody sent you.",
        "wants": "archive", "many": False, "builtin_run": _run_unpack,
        "fields": [],
        "sentence": "Opening your zip…",
    },
    {
        "id": "renumber",
        "tool": "wrap",
        "title": "Number these files in order",
        "blurb": "Turn a messy pile into photo-01, photo-02, photo-03…",
        "wants": "any", "many": True, "builtin_run": _run_renumber,
        "fields": [_text("prefix", "Start each name with", "photo", "Letters, numbers and dashes")],
        "sentence": "Numbering your files…",
    },
    {
        "id": "sizes",
        "tool": "wrap",
        "title": "Tell me how big these are",
        "blurb": "A tidy list of names and sizes, biggest last.",
        "wants": "any", "many": True, "builtin_run": _run_list_sizes,
        "fields": [],
        "sentence": "Measuring your files…",
    },

    # -------------------------------------------------------------- ffmpeg
    {
        "id": "shrink-video",
        "tool": "ffmpeg",
        "title": "Make this video smaller",
        "blurb": "For sending by email, chat or WhatsApp without it being refused.",
        "wants": "video", "many": False, "plan": _plan_shrink,
        "fields": [_choice("how_small", "How small?", [
            ("tiny", "Tiny — about 5 MB a minute"),
            ("small", "Small — about 12 MB a minute"),
            ("good", "Good — about 25 MB a minute"),
        ], "small", "A phone video is often 200 MB a minute. This is the single most useful button here.")],
        "sentence": "Making your video smaller…",
    },
    {
        "id": "sound-from-video",
        "tool": "ffmpeg",
        "title": "Take the sound out",
        "blurb": "Turn a video into an MP3 you can listen to anywhere.",
        "wants": "video", "many": False, "plan": _plan_sound_from_video,
        "fields": [],
        "sentence": "Taking the sound out…",
    },
    {
        "id": "video-to-gif",
        "tool": "ffmpeg",
        "title": "Turn this into a GIF",
        "blurb": "A short, silent, endlessly looping clip — the kind you paste in a chat.",
        "wants": "video", "many": False, "plan": _plan_video_to_gif,
        "fields": [
            _choice("how_big", "How big?", [("small", "Small"), ("medium", "Medium"), ("large", "Large")], "medium"),
            _text("speed", "Pictures a second", "12", "10–15 looks smooth; 6 looks choppy on purpose"),
        ],
        "sentence": "Building your GIF…",
    },
    {
        "id": "trim",
        "tool": "ffmpeg",
        "title": "Keep just part of it",
        "blurb": "Cut a clip down to the bit you want.",
        "wants": "video", "many": False, "plan": _plan_trim,
        "fields": [
            _text("start", "Start at", "0:00", "Written like 0:30 or 1:02:15"),
            _text("end", "Stop at", "", "Leave empty to keep the rest"),
        ],
        "sentence": "Cutting your video…",
    },
    {
        "id": "still",
        "tool": "ffmpeg",
        "title": "Take a picture out of it",
        "blurb": "Save one moment of the video as a photo.",
        "wants": "video", "many": False, "plan": _plan_still,
        "fields": [_text("at", "At what time?", "1", "0:05 is five seconds in")],
        "sentence": "Grabbing that moment…",
    },
    {
        "id": "shrink-audio",
        "tool": "ffmpeg",
        "title": "Make this sound file smaller",
        "blurb": "A long recording that is too big to send.",
        "wants": "audio", "many": False, "plan": _plan_audio,
        "fields": [_choice("bitrate", "Quality", [
            ("96k", "Smallest — fine for speech"),
            ("128k", "Small — good all round"),
            ("192k", "Good — close to the original"),
            ("256k", "Best — for music you care about"),
        ], "192k")],
        "sentence": "Re-encoding your sound file…",
    },

    # -------------------------------------------------------------- pictures
    {
        "id": "resize-pictures",
        "tool": "magick",
        "title": "Make these photos smaller",
        "blurb": "Drop as many as you like; you get a smaller copy of each.",
        "wants": "image", "many": True, "plan": _plan_resize_pictures,
        "fields": [_choice("size", "How wide should they be?", [
            ("800", "800 dots — thumbnails and web pages"),
            ("1600", "1600 dots — good for sending and printing small"),
            ("2400", "2400 dots — keep the detail"),
        ], "1600")],
        "sentence": "Resizing your photos…",
    },
    {
        "id": "change-picture-kind",
        "tool": "magick",
        "title": "Change what kind of picture these are",
        "blurb": "JPG, PNG or WebP — whatever the place you are sending them wants.",
        "wants": "image", "many": True, "plan": _plan_change_picture_kind,
        "fields": [_choice("kind", "Change them to", [
            ("jpg", "JPG — photographs"),
            ("png", "PNG — screenshots and logos"),
            ("webp", "WebP — small files for websites"),
            ("tiff", "TIFF — for printing shops"),
        ], "jpg")],
        "sentence": "Changing your pictures…",
    },
    {
        "id": "pictures-to-pdf",
        "tool": "magick",
        "title": "Put these pictures into one PDF",
        "blurb": "Perfect for sending a stack of photos, receipts or drawings as one file.",
        "wants": "image", "many": True, "plan": _plan_pictures_to_pdf,
        "fields": [_text("name", "Call the PDF", "pictures")],
        "sentence": "Building your PDF…",
    },

    # ------------------------------------------------------------- documents
    {
        "id": "change-document",
        "tool": "pandoc",
        "title": "Change this document into another kind",
        "blurb": "Markdown into Word, Word into plain text, anything into HTML.",
        "wants": "document", "many": False, "plan": _plan_change_document,
        "fields": [_choice("format", "Change it into", [
            ("docx", "A Word document (.docx)"),
            ("pdf", "A PDF"),
            ("html", "A web page (.html)"),
            ("txt", "Plain text (.txt)"),
            ("md", "Markdown (.md)"),
            ("epub", "An e-book (.epub)"),
        ], "docx")],
        "sentence": "Changing your document…",
    },

    # ------------------------------------------------------------------ PDFs
    {
        "id": "pdf-to-text",
        "tool": "poppler",
        "title": "Get the text out of this PDF",
        "blurb": "So you can copy, search or edit the words inside it.",
        "wants": "pdf", "many": False, "plan": _plan_pdf_to_text,
        "fields": [],
        "sentence": "Reading the words out of your PDF…",
    },
    {
        "id": "join-pdfs",
        "tool": "poppler",
        "title": "Join these PDFs into one",
        "blurb": "Drop them in the order you want them to appear.",
        "wants": "pdf", "many": True, "plan": _plan_join_pdfs,
        "fields": [_text("name", "Call the joined PDF", "joined")],
        "sentence": "Joining your PDFs…",
    },

    # -------------------------------------------------------------- archives
    {
        "id": "sevenzip-pack",
        "tool": "sevenzip",
        "title": "Put these into one file (7-Zip)",
        "blurb": "The same idea as nanoWrap's own packing, with more squeezing.",
        "wants": "any", "many": True, "plan": _plan_pack_with_7zip,
        "fields": [_text("name", "Call the file", "packed")],
        "sentence": "Packing with 7-Zip…",
    },
    {
        "id": "sevenzip-open",
        "tool": "sevenzip",
        "title": "Open this archive",
        "blurb": "For .7z and .rar files, which the built-in opener cannot read.",
        "wants": "archive", "many": False, "plan": _plan_open_with_7zip,
        "fields": [],
        "sentence": "Opening your archive…",
    },

    # ------------------------------------------------------------------ curl
    {
        "id": "download",
        "tool": "curl",
        "title": "Save a file from a web address",
        "blurb": "Paste a link, get the file, with the name you want.",
        "wants": "any", "many": False, "plan": _plan_download,
        "fields": [
            _text("url", "The web address", "", "It should start with https://", "https://example.com/report.pdf"),
            _text("name", "Save it as", "", "Leave empty to keep the name it already has"),
        ],
        "sentence": "Downloading your file…",
    },
)

_BY_ID = {task["id"]: task for task in TASKS}


def all_tasks() -> list:
    return [dict(task) for task in TASKS]


def task(task_id: str) -> dict | None:
    return _BY_ID.get(task_id)


def for_kind(kind: str) -> list:
    """The jobs that make sense for a file of this kind."""
    out = []
    for entry in TASKS:
        wants = entry["wants"]
        if wants == "any" or wants == kind:
            out.append(entry)
        elif kind == "any" and entry["tool"] == "wrap":
            out.append(entry)
    return out


def public_listing(available_tools: dict) -> list:
    """The catalogue as the page sees it: only jobs whose program is present."""
    listing = []
    for entry in TASKS:
        present = available_tools.get(entry["tool"], False)
        listing.append({
            "id": entry["id"],
            "tool": entry["tool"],
            "title": entry["title"],
            "blurb": entry["blurb"],
            "wants": entry["wants"],
            "many": bool(entry.get("many")),
            "fields": entry.get("fields", []),
            "sentence": entry.get("sentence", "Working…"),
            "ready": present,
        })
    return listing


def plan_for(task_id: str, files: list, values: dict, out_dir=None, tools: dict | None = None):
    """Work out exactly what will run, without running it.

    Raising ``ValueError`` with a readable sentence is the expected way to say
    "these files and answers do not go together".
    """
    entry = task(task_id)
    if entry is None:
        raise ValueError("There is no job called that.")

    wanted = entry["wants"]
    if not files:
        raise ValueError("Drop a file in first — there is nothing to work on.")
    if not entry.get("many") and len(files) > 1:
        raise ValueError("This job works on one file at a time, and you dropped %d in. "
                         "Take the others out and leave the one you want." % len(files))
    if wanted != "any":
        wrong = [path for path in files if toolbox.kind_of(path) != wanted]
        if wrong:
            raise ValueError("This job needs a %s, and “%s” is not one." % (
                toolbox.kind_sentence(wanted), os.path.basename(wrong[0])))

    if tools is None:
        tools = {found["id"]: found["path"] for found in toolbox.find_all() if found["available"]}
    if entry["tool"] != "wrap" and not tools.get(entry["tool"]):
        raise ValueError("%s is not on this computer, so this job cannot run yet." % (
            (toolbox.tool(entry["tool"]) or {}).get("called", entry["tool"])))

    inputs = Inputs(files, values, out_dir=out_dir, tools=tools)
    if entry.get("builtin_run"):
        return {"kind": "builtin", "task": entry, "inputs": inputs}
    return {"kind": "commands", "task": entry, "inputs": inputs, "plan": entry["plan"](inputs)}
