<div align="center">

# nanoWrap

**The programs already on your computer, with buttons.** No code, no flags, no manual.

Every computer already has powerful tools on it — the ones that shrink a video,
turn a photo into another kind of photo, or pull the text out of a PDF. They are
invisible because you have to type commands at them. nanoWrap finds them and
puts a page of plain-language buttons on top.

[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.9+-58a6ff.svg)]()
[![dependencies](https://img.shields.io/badge/required%20deps-0-f0883e.svg)]()
[![tests](https://img.shields.io/badge/tests-71%20passing-3ddc97.svg)]()

</div>

---

> **Part of [the nano family](https://github.com/Agarwalrishu13/nano)** — eleven offline-first apps for people who do not code. This is the map of the whole project.


## What this is, in one paragraph

There are two ways to help somebody who cannot use a command line. You can write
another program to replace the tools they already have — or you can admit that
FFmpeg is excellent, that it is already on millions of machines, and that the
only thing missing is a page with *"make this video smaller"* on it. nanoWrap is
the second one. It looks for the programs your computer already has, tells you
in plain words what each is for, and gives every useful job a drop zone, a few
choices and one button. It never installs anything, it never sends anything
anywhere, and when a program is missing it prints the single line that would get
it instead of a paragraph about package managers.

---

## Use it

1. Install Python if you do not have it — [python.org/downloads](https://www.python.org/downloads/).
2. Download this repo and unzip it.
3. **Windows:** double-click `run.bat`. **macOS / Linux:** `./run.sh`.
4. Your browser opens at `http://127.0.0.1:8765`.

Nothing to hand? Press **Make me some practice files** — nanoWrap makes a few
small files for you, including a short test video it draws itself, so you can try
every job without hunting for something to try it on.

<details>
<summary>Prefer the command line? (you do not need to)</summary>

```bash
python start.py                        # start and open the browser
python -m nanowrap doctor              # list the programs this computer has
python -m nanowrap --port 9000 --no-browser
```

</details>

---

## The four steps it walks you through

| step | what happens |
|---|---|
| **1. See what you have** | nanoWrap looks for FFmpeg, ImageMagick, Pandoc, Poppler, 7-Zip and curl, and shows what each is *for*, not what it is called. Missing ones come with the one line that gets them. |
| **2. Drop a file in** | A video, some photos, a PDF, a zip — anything. Files are copied in 4 MB slices, and nothing leaves your computer. |
| **3. Choose a job** | Only the jobs that fit what you dropped are offered. Each says what it will do and where the result will go. |
| **4. Take your file** | A live log of exactly what is happening, a **Stop** button that works, the result with *how much smaller it got*, and the exact command that ran, for anyone curious. |

### What it can do with the programs already installed

| if you have | you can |
|---|---|
| **FFmpeg** | Make a video small enough to send · take the sound out as an MP3 · turn a clip into a GIF · keep just part of it (trim) · save one frame as a photo · squeeze a sound file |
| **ImageMagick** | Make photos smaller · change them to JPG/PNG/WebP/TIFF · put a pile of photos into one PDF |
| **Pandoc** | Change a document into Word, PDF, HTML, plain text, Markdown or an e-book |
| **Poppler** | Get the text out of a PDF · join several PDFs into one |
| **7-Zip** | Pack things up · open a `.7z` or `.rar` somebody sent you |
| **curl** | Save a file that lives at a web address |
| **nothing at all** | Put files into one zip · open a zip · number a folder of photos in order · tell you how big things are |

### Things it does that you would not expect from a toy

- **It tells you what to install, not what is wrong.** "FFmpeg is not on this
  computer" comes with `winget install Gyan.FFmpeg` — one line, on the same page,
  and a **Check again** button for afterwards.
- **Your original file is never touched.** Every result is a new file in
  nanoWrap's own folder. There is no code path in this program that deletes or
  overwrites anything you gave it.
- **A file named `my video; rm -rf ~.mp4` is just a file with an odd name.**
  Commands are always passed as a list of arguments and never through a shell,
  and there is a test that proves it.
- **It explains failures in words.** Not `Exit code 1`. Things like *"That file
  does not look like something this program can read — it may be damaged, or a
  different kind of file wearing the wrong name."*
- **It shows you the exact command it ran.** Nobody has to take the app's word
  for anything: the last panel has the real command line, ready to copy.
- **It tidies up after itself.** Files it made are deleted after a week, so a few
  large videos cannot quietly fill a disk. The originals are wherever you kept
  them, untouched.

---

## What it does not do, honestly

- **It does not install anything.** If a job needs FFmpeg and FFmpeg is not
  there, the job is offered with an explanation and stays greyed out until the
  program is. That is a deliberate choice: nobody expects a button to change
  their system.
- **It cannot invent a tool that is not there.** Packing, numbering and sizes
  work everywhere because they are written into the app; everything else depends
  on the programs you have.
- **It does not edit your files in place.** Somebody who wants a video *replaced*
  by a smaller one will get a smaller copy instead, and will have to delete the
  original themselves.
- **It only runs the jobs in its own catalogue.** There is no "type a command
  here" box, on purpose.
- **A few conversions lose quality** — that is what "smaller" means. The size
  before and after is always shown, so the trade-off is visible rather than
  guessed at.

---

## Where your files live

```
~/.nanowrap/
  dropped/     files you dropped in (copies — deleted when nanoWrap closes)
  made/        everything nanoWrap made for you
  working/     half-finished files, kept out of the way
  settings.json
```

Delete that folder and nanoWrap forgets everything. Nothing is uploaded, there is
no account, and there is no telemetry of any kind.

---

## The rest of the family

| app | what it is for |
|---|---|
| 🧭 [nanoHome](https://github.com/Agarwalrishu13/nanohome) | one front door for every nano app on this computer |
| 🧠 [nanoLaama](https://github.com/Agarwalrishu13/nanolaama) | talk to an AI on your own computer, offline |
| 📚 [nanoDoc](https://github.com/Agarwalrishu13/nanodoc) | drop in a document, ask it anything |
| 📊 [nanoLearn](https://github.com/Agarwalrishu13/nanolearn) | drop a spreadsheet, get an answer machine |
| 🔊 [nanoSay](https://github.com/Agarwalrishu13/nanosay) | have anything read out loud |
| 🧲 [nanoPick](https://github.com/Agarwalrishu13/nanopick) | find your files by saying what you remember |
| 🎵 [nanoTune](https://github.com/Agarwalrishu13/nanotune) | your music, one page, no account |
| 🧰 [**nanoWrap**](https://github.com/Agarwalrishu13/nanowrap) | the best-known programs, with ready-made buttons — *this repo* |
| ⌨️ [nanoShell](https://github.com/Agarwalrishu13/nanoshell) | any program at all, with words instead of flags |
| 🗂 [nanoGit](https://github.com/Agarwalrishu13/nanogit) | your folder, kept safe without learning git |
| 🖥 [nanoDesk](https://github.com/Agarwalrishu13/nanodesk) | every nano-style app you have, one click away |
| 🃏 [nonoForge](https://github.com/Agarwalrishu13/nonoforge) | pick a card, press one button, you have an app |

And underneath them, for people who want to see the gears: [nanollama.c](https://github.com/Agarwalrishu13/nanollama.c) (the C engine), [nanobrain](https://github.com/Agarwalrishu13/nanobrain) (training from scratch), [nanoforge](https://github.com/Agarwalrishu13/nanoforge) (the model studio) and [nanorl](https://github.com/Agarwalrishu13/nanorl) (alignment).

The map of the whole project — what each app is for, and how they fit together — lives in [the nano family](https://github.com/Agarwalrishu13/nano).
## Tests

```bash
python -m unittest discover tests -v
```

71 tests. Most of them need nothing installed: the commands are built by pure
functions, so the tests check what *would* run against a make-believe machine.
The built-in jobs — packing, unpacking, numbering — are exercised for real,
including one that tries to escape the output folder with a `../../` zip entry.
When FFmpeg *is* present, one more test makes a real six-second video and shrinks it.

MIT licensed. No dependencies. `python start.py` is the whole install.
