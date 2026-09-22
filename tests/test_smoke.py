"""Tests for nanoWrap.

The interesting ones are not "did the endpoint answer 200" but:

* every plan is a *list* of arguments, never one string handed to a shell — a
  file called ``my video; rm -rf ~.mp4`` is a file with a silly name;
* the built-in jobs really do their work, on a bare interpreter, with no
  programs installed;
* a failure comes back as a sentence a person can act on, never as a traceback.

Nothing here needs FFmpeg, ImageMagick, Pandoc or 7-Zip to be installed. The
plans are pure functions, so they are checked against a make-believe machine —
and when a tool *is* present, an extra test uses it for real.
"""

import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = tempfile.mkdtemp(prefix="nanowrap-tests-")
os.environ["NANOWRAP_HOME"] = _TMP

from nanowrap import runner, store, tasks, toolbox  # noqa: E402
from nanowrap.httpbase import free_port  # noqa: E402
from nanowrap.server import create_app, _inside  # noqa: E402


def _write(path, text="hello\n"):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def _fake_machine(*wanted):
    """A tools map as if these programs were installed at tidy pretend paths."""
    table = {
        "ffmpeg": "/pretend/ffmpeg", "magick": "/pretend/magick",
        "pandoc": "/pretend/pandoc", "poppler": "/pretend/pdftotext",
        "sevenzip": "/pretend/7z", "curl": "/pretend/curl",
    }
    return {name: table[name] for name in (wanted or table)}


# ==========================================================================
# Recognising files
# ==========================================================================
class TestKinds(unittest.TestCase):
    def test_it_knows_what_a_file_is(self):
        cases = {
            "holiday.MP4": "video", "song.mp3": "audio", "photo.jpeg": "image",
            "report.pdf": "pdf", "notes.md": "document", "data.csv": "sheet",
            "stuff.zip": "archive", "mystery.qqq": "any", "noextension": "any",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(toolbox.kind_of(name), expected)

    def test_the_words_read_like_a_person_talks(self):
        self.assertEqual(toolbox.kind_sentence("audio"), "sound file")
        self.assertEqual(toolbox.kind_sentence("any"), "file")
        self.assertEqual(toolbox.kind_sentence("nonsense"), "file")


# ==========================================================================
# The catalogue of programs
# ==========================================================================
class TestToolbox(unittest.TestCase):
    def test_every_entry_is_finished(self):
        for entry in toolbox.catalog():
            with self.subTest(tool=entry["id"]):
                for key in ("id", "called", "what", "takes", "used_for", "homepage", "commands"):
                    self.assertIn(key, entry)
                if not entry.get("builtin"):
                    self.assertTrue(entry["get_it"], "every missing program needs a way to get it")

    def test_the_built_in_tools_always_work(self):
        builtins = [entry for entry in toolbox.find_all() if entry["builtin"]]
        self.assertTrue(builtins)
        for entry in builtins:
            self.assertTrue(entry["available"])
            self.assertEqual(entry["note"], "comes with nanoWrap")

    def test_convert_is_never_mistaken_for_imagemagick_on_windows(self):
        """Windows ships a ``convert`` that reformats disks. The catalog must
        never pick it up, on any operating system."""
        entry = next(item for item in toolbox.catalog() if item["id"] == "magick")
        if sys.platform.startswith("win"):
            self.assertNotIn("convert", entry["commands"])
        self.assertIn("magick", entry["commands"])

    def test_asking_for_a_program_that_does_not_exist_is_an_error(self):
        with self.assertRaises(KeyError):
            toolbox.find("no-such-program")

    def test_the_summary_sentence_is_a_sentence(self):
        note = toolbox.machine_note()
        self.assertTrue(note.endswith("."))
        self.assertGreater(len(note), 20)

    def test_looking_again_finds_the_same_thing(self):
        first = {entry["id"]: entry["available"] for entry in toolbox.find_all()}
        second = {entry["id"]: entry["available"] for entry in toolbox.refresh()}
        self.assertEqual(first, second)


# ==========================================================================
# The jobs — checked as pure plans, on a pretend machine
# ==========================================================================
class TestPlans(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="nanowrap-plan-")
        self.video = _write(os.path.join(self.folder, "holiday.mp4"))
        self.photo = _write(os.path.join(self.folder, "beach.jpg"))
        self.photo2 = _write(os.path.join(self.folder, "sunset.png"))
        self.doc = _write(os.path.join(self.folder, "letter.docx"))
        self.pdf = _write(os.path.join(self.folder, "invoice.pdf"))
        self.pack = _write(os.path.join(self.folder, "stuff.zip"))
        self.tools = _fake_machine()

    def plan(self, task_id, files, **values):
        return tasks.plan_for(task_id, files, values, out_dir=self.folder, tools=self.tools)

    # -- ffmpeg ----------------------------------------------------------
    def test_making_a_video_smaller_uses_the_size_you_chose(self):
        wanted = {"tiny": "32", "small": "28", "good": "23"}
        for how_small, crf in wanted.items():
            with self.subTest(how_small=how_small):
                plan = self.plan("shrink-video", [self.video], how_small=how_small)["plan"]
                command = plan["commands"][0]
                self.assertIsInstance(command, list)
                self.assertIn("-crf", command)
                self.assertEqual(command[command.index("-crf") + 1], crf)
                self.assertIn(self.video, command)
                self.assertEqual(len(plan["made"]), 1)
                self.assertTrue(plan["made"][0].endswith(".mp4"))
                self.assertTrue(plan["made"][0].startswith(self.folder))

    def test_taking_the_sound_out(self):
        command = self.plan("sound-from-video", [self.video])["plan"]["commands"][0]
        self.assertIn("-vn", command)
        self.assertIn("libmp3lame", command)

    def test_a_gif_is_built_from_a_palette(self):
        command = self.plan("video-to-gif", [self.video], how_big="small")["plan"]["commands"][0]
        self.assertIn("palettegen", " ".join(command))
        self.assertTrue(command[-1].endswith(".gif"))

    def test_cutting_a_bit_out_writes_the_times_the_way_people_do(self):
        plan = self.plan("trim", [self.video], start="0:30", end="1:02:15")["plan"]
        command = plan["commands"][0]
        self.assertEqual(command[command.index("-ss") + 1], "00:00:30")
        self.assertEqual(command[command.index("-to") + 1], "01:02:15")

    def test_a_cut_with_no_end_time_stops_at_the_end(self):
        command = self.plan("trim", [self.video], start="5", end="")["plan"]["commands"][0]
        self.assertNotIn("-to", command)

    def test_a_still_picture_from_a_video(self):
        command = self.plan("still", [self.video], at="0:05")["plan"]["commands"][0]
        self.assertIn("-frames:v", command)
        self.assertTrue(command[-1].endswith(".jpg"))

    def test_sound_files_get_the_bitrate_you_chose(self):
        sound = _write(os.path.join(self.folder, "talk.mp3"))
        command = self.plan("shrink-audio", [sound], bitrate="96k")["plan"]["commands"][0]
        self.assertIn("96k", command)

    # -- pictures --------------------------------------------------------
    def test_one_command_per_picture(self):
        plan = self.plan("resize-pictures", [self.photo, self.photo2], size="800")["plan"]
        self.assertEqual(len(plan["commands"]), 2)
        self.assertEqual(len(plan["made"]), 2)
        self.assertEqual(len(set(plan["made"])), 2, "two pictures must not overwrite each other")
        for command, made in zip(plan["commands"], plan["made"]):
            self.assertIn("800x800>", command)
            self.assertTrue(made.endswith("-800px.jpg"))

    def test_pictures_into_one_pdf(self):
        plan = self.plan("pictures-to-pdf", [self.photo, self.photo2], name="holiday")["plan"]
        self.assertEqual(len(plan["commands"]), 1)
        self.assertTrue(plan["commands"][0][-1].endswith("holiday.pdf"))
        self.assertIn(self.photo, plan["commands"][0])
        self.assertIn(self.photo2, plan["commands"][0])

    # -- documents and PDFs ----------------------------------------------
    def test_a_document_changes_into_the_kind_you_asked_for(self):
        command = self.plan("change-document", [self.doc], format="html")["plan"]["commands"][0]
        self.assertTrue(command[-1].endswith(".html"))
        self.assertEqual(command[-2], "-o")

    def test_the_text_comes_out_of_a_pdf(self):
        command = self.plan("pdf-to-text", [self.pdf])["plan"]["commands"][0]
        self.assertEqual(command[0], "/pretend/pdftotext")
        self.assertTrue(command[-1].endswith(".txt"))

    def test_two_pdfs_are_joined_in_order(self):
        second = _write(os.path.join(self.folder, "more.pdf"))
        command = self.plan("join-pdfs", [self.pdf, second], name="everything")["plan"]["commands"][0]
        self.assertTrue(command[0].endswith("pdfunite"))
        self.assertEqual(command[1:3], [self.pdf, second])
        self.assertTrue(command[3].endswith("everything.pdf"))

    # -- downloading -----------------------------------------------------
    def test_a_web_address_is_downloaded_with_the_name_you_chose(self):
        command = self.plan("download", [self.doc], url="https://example.com/a.pdf")["plan"]["commands"][0]
        self.assertIn("https://example.com/a.pdf", command)
        self.assertIn("-L", command)

    def test_a_name_is_taken_from_the_web_address_when_none_is_given(self):
        plan = self.plan("download", [self.doc], url="https://example.com/report.pdf?x=1")["plan"]
        self.assertTrue(plan["made"][0].endswith("report.pdf"))

    def test_something_that_is_not_a_web_address_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            self.plan("download", [self.doc], url="not a link")
        self.assertIn("http", str(caught.exception))

    # -- refusals --------------------------------------------------------
    def test_a_pdf_job_given_a_video_says_so_plainly(self):
        with self.assertRaises(ValueError) as caught:
            self.plan("pdf-to-text", [self.video])
        self.assertIn("PDF", str(caught.exception))
        self.assertIn("holiday.mp4", str(caught.exception))

    def test_a_missing_program_stops_the_job_with_a_readable_reason(self):
        with self.assertRaises(ValueError) as caught:
            tasks.plan_for("shrink-video", [self.video], {}, out_dir=self.folder, tools={})
        self.assertIn("FFmpeg", str(caught.exception))

    def test_a_job_for_one_file_refuses_a_pile(self):
        with self.assertRaises(ValueError) as caught:
            self.plan("shrink-video", [self.video, self.video])
        self.assertIn("one file at a time", str(caught.exception))

    def test_an_unknown_job_is_an_error(self):
        with self.assertRaises(ValueError):
            self.plan("make-me-a-sandwich", [self.video])

    def test_dropping_nothing_in_is_an_error(self):
        with self.assertRaises(ValueError) as caught:
            self.plan("pack", [])
        self.assertIn("Drop a file", str(caught.exception))

    # -- the shape of every plan -----------------------------------------
    def test_no_plan_ever_hands_a_string_to_a_shell(self):
        """Every command is a list, no element is a shell operator, and an
        awkward file name stays exactly one argument."""
        awkward = _write(os.path.join(self.folder, "my video; rm -rf ~.mp4"))
        checked = 0
        for entry in tasks.all_tasks():
            if entry["tool"] == "wrap":
                continue
            kind_file = {
                "video": self.video, "audio": self.video, "image": self.photo,
                "document": self.doc, "pdf": self.pdf, "archive": self.pack, "any": self.doc,
            }[entry["wants"]]
            files = [kind_file]
            if entry.get("many"):
                files = [kind_file, kind_file]
            if entry["id"] == "download":
                files = [self.doc]
            try:
                plan = self.plan(entry["id"], files, url="https://example.com/x.pdf")["plan"]
            except ValueError:
                continue
            for command in plan["commands"]:
                checked += 1
                self.assertIsInstance(command, list)
                for part in command:
                    self.assertIsInstance(part, str)
                    self.assertNotIn(part, ("&&", "|", ";", ">", "`"))
        self.assertGreater(checked, 10, "the sweep should have checked most of the catalogue")

        plan = self.plan("shrink-video", [awkward])["plan"]
        self.assertIn(awkward, plan["commands"][0], "the odd name must survive as one argument")

    def test_times_are_read_the_way_people_write_them(self):
        cases = {"0:30": 30, "90": 90, "1:02:15": 3735, "00:00:05": 5, "": 0, "junk": 0}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(tasks.seconds_of(text), expected)
        self.assertEqual(tasks.stamp(3735), "01:02:15")
        self.assertEqual(tasks.stamp(30), "00:00:30")


# ==========================================================================
# The built-in jobs, doing the real thing
# ==========================================================================
class TestBuiltinJobs(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="nanowrap-builtin-")
        self.out = tempfile.mkdtemp(prefix="nanowrap-out-")
        self.files = [_write(os.path.join(self.folder, name), "line\n" * 20)
                      for name in ("one.txt", "two.txt", "three.txt")]

    def run_it(self, task_id, files=None, **values):
        job = runner.Job("test")
        spec = tasks.plan_for(task_id, files or self.files, values, out_dir=self.out)
        outcome = spec["task"]["builtin_run"](job, spec["inputs"])
        return job, outcome

    def test_packing_files_into_one_zip(self):
        job, outcome = self.run_it("pack", name="bundle")
        target = outcome["made"][0]
        self.assertTrue(target.endswith("bundle.zip"))
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(sorted(archive.namelist()), ["one.txt", "three.txt", "two.txt"])
            self.assertIn("line", archive.read("one.txt").decode("utf-8"))
        self.assertTrue(any("one.txt" in line for line in job.lines))

    def test_opening_a_zip_gives_the_files_back(self):
        _job, packed = self.run_it("pack", name="bundle")
        job, outcome = self.run_it("unpack", files=[packed["made"][0]])
        folder = outcome["folder"]
        for name in ("one.txt", "two.txt", "three.txt"):
            self.assertTrue(os.path.isfile(os.path.join(folder, name)), name)
        self.assertEqual(job.progress, 100)

    def test_opening_a_zip_may_not_write_outside_its_folder(self):
        """A zip can claim a file is called ../../escaped.txt. It must not be."""
        nasty = os.path.join(self.folder, "nasty.zip")
        with zipfile.ZipFile(nasty, "w") as archive:
            archive.writestr("../../escaped.txt", "should never be written")
            archive.writestr("fine.txt", "this one is fine")
        _job, outcome = self.run_it("unpack", files=[nasty])
        folder = outcome["folder"]
        self.assertTrue(os.path.isfile(os.path.join(folder, "fine.txt")))
        escaped = os.path.abspath(os.path.join(folder, "..", "..", "escaped.txt"))
        self.assertFalse(os.path.exists(escaped), "zip slip was not stopped")

    def test_numbering_files_in_order_leaves_the_originals_alone(self):
        job, outcome = self.run_it("renumber", prefix="photo")
        folder = outcome["folder"]
        self.assertEqual(sorted(os.listdir(folder)), ["photo-01.txt", "photo-02.txt", "photo-03.txt"])
        with open(os.path.join(folder, "photo-01.txt"), encoding="utf-8") as handle:
            with open(self.files[0], encoding="utf-8") as original:
                self.assertEqual(handle.read(), original.read())
        for path in self.files:
            self.assertTrue(os.path.isfile(path), "the originals must still be there")
        self.assertEqual(job.progress, 100)

    def test_asking_how_big_things_are_writes_a_list(self):
        _job, outcome = self.run_it("sizes")
        report = outcome["made"][0]
        text = open(report, encoding="utf-8").read()
        self.assertIn("one.txt", text)
        self.assertIn("TOTAL", text)

    def test_the_built_in_jobs_work_with_nothing_installed(self):
        self.assertEqual(tasks.plan_for("pack", self.files, {}, out_dir=self.out)["kind"], "builtin")


class TestStopping(unittest.TestCase):
    def test_stop_takes_effect_between_files(self):
        folder = tempfile.mkdtemp(prefix="nanowrap-stop-")
        files = [_write(os.path.join(folder, "f%d.txt" % number)) for number in range(60)]
        job = runner.Job("stop me")
        spec = tasks.plan_for("pack", files, {}, out_dir=tempfile.mkdtemp())
        job.stop()
        with self.assertRaises(runner.JobStopped):
            spec["task"]["builtin_run"](job, spec["inputs"])

    def test_a_stopped_job_is_reported_as_stopped(self):
        job = runner.Job("stop me")

        def work(inner):
            inner.stop()
            inner.check()

        started = runner.start_job("stop me", "nanoWrap", work)
        for _ in range(100):
            if started.state != "running":
                break
            time.sleep(0.05)
        self.assertEqual(started.state, "stopped")
        self.assertIn("stopped", started.error.lower())


# ==========================================================================
# Running real programs
# ==========================================================================
class TestRunner(unittest.TestCase):
    def test_a_command_runs_and_its_output_is_kept(self):
        job = runner.Job("python")
        code = runner.run_command(job, [sys.executable, "-c", "print('hello from the tool')"])
        self.assertEqual(code, 0)
        self.assertTrue(any("hello from the tool" in line for line in job.lines))
        self.assertTrue(any(line.startswith("$ ") for line in job.lines), "the command is logged too")

    def test_arguments_reach_the_program_exactly_as_given(self):
        """Nothing is split, quoted or interpreted on the way."""
        job = runner.Job("python")
        awkward = "a file; rm -rf ~ && echo oops"
        runner.run_command(job, [sys.executable, "-c", "import sys; print(sys.argv[1])", awkward])
        self.assertTrue(any(awkward in line for line in job.lines),
                        "the argument should come back out of the program in one piece")

    def test_a_program_that_is_not_there_is_a_readable_error(self):
        job = runner.Job("nothing")
        with self.assertRaises(ValueError) as caught:
            runner.run_command(job, ["definitely-not-a-real-program-xyz", "--go"])
        self.assertIn("not on this computer", str(caught.exception))

    def test_running_nothing_is_an_error(self):
        with self.assertRaises(ValueError):
            runner.run_command(runner.Job("empty"), [])

    def test_failures_are_explained_in_words(self):
        cases = {
            "ffmpeg version 6.0\nInvalid data found when processing input": "does not look like",
            "No such file or directory": "could not find one of the files",
            "Permission denied": "would not let it write",
            "No space left on device": "not enough free space",
        }
        for text, fragment in cases.items():
            with self.subTest(text=text):
                sentence = runner.explain_failure("FFmpeg", 1, text.splitlines())
                self.assertIn(fragment, sentence)

    def test_a_silent_failure_still_says_something_useful(self):
        sentence = runner.explain_failure("FFmpeg", 1, [])
        self.assertIn("FFmpeg", sentence)
        self.assertNotIn("Traceback", sentence)

    def test_version_banners_are_not_repeated_back_as_the_problem(self):
        lines = ["ffmpeg version 6.0 Copyright (c) 2000-2023", "configuration: --enable-gpl",
                 "built with gcc 12", "real problem: the file is empty"]
        self.assertEqual(runner.interesting(lines), ["real problem: the file is empty"])


# ==========================================================================
# The folder it owns
# ==========================================================================
class TestStore(unittest.TestCase):
    def test_settings_round_trip_and_ignore_nonsense(self):
        store.save_settings({"keep_days": 3})
        self.assertEqual(store.load_settings()["keep_days"], 3)
        store.save_settings({"keep_days": "not a number"})
        self.assertEqual(store.load_settings()["keep_days"], 3)
        store.save_settings({"nonsense": 1})
        self.assertNotIn("nonsense", store.load_settings())

    def test_a_name_that_is_taken_gets_a_number(self):
        folder = store.outputs_dir()
        first = store.free_name("holiday.mp4", folder)
        first.write_text("x", encoding="utf-8")
        second = store.free_name("holiday.mp4", folder)
        self.assertNotEqual(first, second)
        self.assertTrue(second.name.startswith("holiday-2"))
        first.unlink()

    def test_tidying_removes_old_files_and_leaves_new_ones(self):
        old = store.outputs_dir() / "ancient.txt"
        new = store.outputs_dir() / "yesterday.txt"
        old.write_text("old", encoding="utf-8")
        new.write_text("new", encoding="utf-8")
        ancient = time.time() - 30 * 86400
        os.utime(old, (ancient, ancient))
        outcome = store.tidy_outputs(keep_days=7)
        self.assertGreaterEqual(outcome["removed"], 1)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())
        new.unlink()

    def test_history_remembers_and_forgets(self):
        store.forget_history()
        store.add_history({"name": "made.zip", "path": str(store.outputs_dir() / "made.zip"),
                           "title": "Put these into one file", "size_mb": 1.5})
        items = store.load_history()
        self.assertEqual(items[0]["name"], "made.zip")
        self.assertFalse(items[0]["here"], "a file that is not there any more must say so")
        store.forget_history()
        self.assertEqual(store.load_history(), [])

    def test_a_name_can_never_escape_the_output_folder(self):
        """Whatever is asked for, the answer is a path inside the folder."""
        folder = store.outputs_dir()
        for nasty in ("../settings.json", "..%2Fsettings.json", "../../secrets.txt",
                      os.path.join("..", "..", "secrets.txt"), "sub/../../escape.txt",
                      "", ".", "..", "/etc/passwd", "C:\\Windows\\system.ini"):
            with self.subTest(name=nasty):
                found = _inside(folder, nasty)
                if found is not None:
                    found.relative_to(folder.resolve())     # raises if it escaped
        good = _inside(folder, "fine.zip")
        self.assertEqual(good.parent, folder.resolve())
        self.assertEqual(good.name, "fine.zip")


# ==========================================================================
# The whole app, over HTTP
# ==========================================================================
class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.port = free_port(8795)
        cls.base = "http://127.0.0.1:%d" % cls.port
        cls.thread = threading.Thread(
            target=cls.app.serve, kwargs={"host": "127.0.0.1", "port": cls.port,
                                          "open_browser": False, "quiet": True},
            daemon=True)
        cls.thread.start()
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(cls.base + "/api/health", timeout=2) as response:
                    if json.loads(response.read().decode("utf-8")).get("ok"):
                        return
            except Exception:
                time.sleep(0.15)
        raise AssertionError("the app never came up on %s" % cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.app.stop()

    # -- helpers ---------------------------------------------------------
    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return json.loads(exc.read().decode("utf-8"))

    def post(self, path, payload):
        request = urllib.request.Request(
            self.base + path, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return json.loads(exc.read().decode("utf-8"))

    def raw(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=60) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def deliver(self, name, content=b"hello there\n"):
        started = self.post("/api/upload/start", {"name": name, "size_mb": len(content) / 1048576})
        self.assertIn("id", started, started)
        offset = 0
        while offset < len(content):
            piece = content[offset:offset + 262144]
            request = urllib.request.Request(
                self.base + "/api/upload/chunk?id=%s&offset=%d" % (started["id"], offset),
                data=piece, method="POST")
            with urllib.request.urlopen(request, timeout=30) as response:
                offset = json.loads(response.read().decode("utf-8"))["received"]
        return self.post("/api/upload/finish", {"id": started["id"]})

    def wait_for(self, job_id, seconds=90):
        deadline = time.time() + seconds
        payload = {}
        while time.time() < deadline:
            payload = self.get("/api/job/" + job_id)
            if payload.get("state") != "running":
                return payload
            time.sleep(0.2)
        self.fail("the job never finished: %s" % payload)


class TestApi(ServerCase):
    def test_the_app_says_hello(self):
        self.assertTrue(self.get("/api/health")["ok"])

    def test_the_first_paint_has_everything_the_page_needs(self):
        state = self.get("/api/state")
        for key in ("tools", "tasks", "history", "settings", "note", "folder", "system"):
            self.assertIn(key, state)
        self.assertTrue(state["tools"])
        self.assertTrue(state["tasks"])
        self.assertTrue(all(task["ready"] for task in state["tasks"] if task["tool"] == "wrap"),
                        "the jobs built into nanoWrap are always ready")
        self.assertTrue(any(task["tool"] == "wrap" and task["ready"] for task in state["tasks"]))

    def test_a_dropped_file_is_recognised(self):
        arrived = self.deliver("holiday.mp4")
        self.assertEqual(arrived["kind"], "video")
        self.assertEqual(arrived["kind_word"], "video")
        self.assertIn("shrink-video", arrived["tasks"])
        self.assertTrue(os.path.isfile(arrived["path"]))

    def test_a_spreadsheet_is_not_offered_video_jobs(self):
        arrived = self.deliver("numbers.csv", b"a,b\n1,2\n")
        self.assertEqual(arrived["kind"], "sheet")
        self.assertNotIn("shrink-video", arrived["tasks"])
        self.assertIn("pack", arrived["tasks"])

    def test_packing_works_end_to_end_over_http(self):
        first = self.deliver("one.txt", b"the first file\n")
        second = self.deliver("two.txt", b"the second file\n")
        started = self.post("/api/run", {"task": "pack", "files": [first["path"], second["path"]],
                                         "values": {"name": "bundle"}})
        self.assertIn("job_id", started, started)
        payload = self.wait_for(started["job_id"])
        self.assertEqual(payload["state"], "done", payload.get("error"))
        self.assertEqual(payload["progress"], 100)
        made = payload["result"]["files"][0]
        self.assertEqual(made["name"], "bundle.zip")

        status, body = self.raw(made["download"])
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            self.assertEqual(sorted(archive.namelist()), ["one.txt", "two.txt"])
        self.assertTrue(payload["result"]["note"])

    def test_numbering_works_end_to_end_and_the_folder_can_be_downloaded_as_a_zip(self):
        files = [self.deliver("pic-%d.jpg" % number, b"pretend photo %d" % number) for number in (1, 2)]
        started = self.post("/api/run", {"task": "renumber", "files": [f["path"] for f in files],
                                         "values": {"prefix": "holiday"}})
        payload = self.wait_for(started["job_id"])
        self.assertEqual(payload["state"], "done", payload.get("error"))
        made = payload["result"]["files"][0]
        self.assertTrue(made["is_folder"], made)
        status, body = self.raw(made["download"])
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            self.assertIn("holiday-in-order/holiday-01.jpg", archive.namelist())

    def test_a_job_whose_program_is_missing_says_which_program(self):
        video = self.deliver("clip.mp4", b"not really a video")
        if toolbox.find("ffmpeg")["available"]:
            self.skipTest("FFmpeg is installed here, so this job would run")
        answer = self.post("/api/run", {"task": "shrink-video", "files": [video["path"]], "values": {}})
        self.assertIn("FFmpeg", answer["error"])

    def test_the_wrong_kind_of_file_is_refused_before_anything_runs(self):
        arrived = self.deliver("newsletter.pdf", b"%PDF-1.4 pretend\n")
        answer = self.post("/api/run", {"task": "shrink-video", "files": [arrived["path"]], "values": {}})
        self.assertIn("error", answer)

    def test_a_file_nanowrap_did_not_receive_is_never_touched(self):
        outside = _write(os.path.join(tempfile.mkdtemp(prefix="nanowrap-outside-"), "mine.txt"))
        answer = self.post("/api/run", {"task": "pack", "files": [outside], "values": {}})
        self.assertIn("error", answer)
        self.assertIn("not one nanoWrap received", answer["error"])

    def test_a_file_that_has_vanished_says_so(self):
        arrived = self.deliver("gone.txt")
        os.unlink(arrived["path"])
        answer = self.post("/api/run", {"task": "pack", "files": [arrived["path"]], "values": {}})
        self.assertIn("error", answer)
        self.assertIn("Drop it in again", answer["error"])

    def test_practice_files_can_be_made_and_packed(self):
        answer = self.post("/api/sample", {})
        self.assertTrue(answer["files"], answer)
        names = [item["name"] for item in answer["files"]]
        self.assertIn("practice-files.zip", names)
        self.assertIn("practice-shopping-list.txt", names)
        started = self.post("/api/run", {"task": "pack",
                                         "files": [item["path"] for item in answer["files"]],
                                         "values": {"name": "practice"}})
        payload = self.wait_for(started["job_id"])
        self.assertEqual(payload["state"], "done", payload.get("error"))

    def test_output_files_cannot_be_reached_from_outside(self):
        status, _body = self.raw("/api/download/..%2Fsettings.json")
        self.assertIn(status, (403, 404))
        status, _body = self.raw("/api/download/nothing-here.zip")
        self.assertEqual(status, 404)

    def test_an_address_that_does_not_exist_is_a_clean_answer(self):
        answer = self.get("/api/nonsense")
        self.assertIn("error", answer)

    def test_settings_can_be_changed(self):
        saved = self.post("/api/settings", {"open_folder_when_done": True, "keep_days": 3})
        self.assertEqual(saved["settings"]["keep_days"], 3)
        self.assertTrue(self.get("/api/state")["settings"]["open_folder_when_done"])
        self.post("/api/settings", {"open_folder_when_done": False})

    def test_forgetting_the_history_keeps_the_files(self):
        self.post("/api/run", {"task": "pack", "files": [self.deliver("keep.txt")["path"]], "values": {}})
        self.assertTrue(self.get("/api/history")["history"])
        self.post("/api/forget", {"what": "history"})
        self.assertEqual(self.get("/api/history")["history"], [])

    def test_asking_for_something_it_cannot_forget_is_an_error(self):
        self.assertIn("error", self.post("/api/forget", {"what": "the-alps"}))

    def test_checking_again_reports_what_it_found(self):
        answer = self.post("/api/check", {})
        self.assertIn("message", answer)
        self.assertIn("tools", answer)

    def test_stopping_a_job_that_is_not_running_is_an_error(self):
        self.assertIn("error", self.post("/api/job/deadbeef/stop", {}))

    def test_an_unknown_job_is_a_clean_404(self):
        answer = self.get("/api/job/deadbeef")
        self.assertIn("error", answer)

    def test_the_about_page_points_at_the_other_nano_apps(self):
        about = self.get("/api/about")
        self.assertTrue(about["offline"])
        self.assertTrue(about["siblings"])
        self.assertIn("nanolaama", json.dumps(about))


# ==========================================================================
# If a real program is here, use it for real
# ==========================================================================
@unittest.skipUnless(toolbox.find("ffmpeg")["available"], "FFmpeg is not installed here")
class TestWithRealFfmpeg(unittest.TestCase):  # pragma: no cover - only on machines with FFmpeg
    def test_a_real_video_really_gets_smaller(self):
        """FFmpeg draws a six-second test clip; nanoWrap shrinks it."""
        import subprocess
        folder = tempfile.mkdtemp(prefix="nanowrap-ffmpeg-")
        source = os.path.join(folder, "source.mp4")
        built = subprocess.run(
            [toolbox.find("ffmpeg")["path"], "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", "testsrc2=size=640x360:rate=24:duration=6", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", source], capture_output=True)
        if built.returncode != 0:
            self.skipTest("this FFmpeg build cannot make a test clip")

        before = os.path.getsize(source)
        spec = tasks.plan_for("shrink-video", [source], {"how_small": "tiny"}, out_dir=folder)
        job = runner.Job("shrink")
        for command in spec["plan"]["commands"]:
            self.assertEqual(runner.run_command(job, command, timeout=180), 0, "\n".join(job.lines))
        made = spec["plan"]["made"][0]
        self.assertTrue(os.path.isfile(made))
        self.assertLess(os.path.getsize(made), before)
        self.assertGreater(os.path.getsize(made), 1000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
