# SlideCast

Turns an HTML slide deck plus a Kokoro voiceover script into a finished MP4:
slides rendered at 1920x1080, narration generated with Kokoro, each slide held
for exactly as long as its narration, fades through black between slides, and
subtitles burned in from the script text.

## Setting up a new machine

On Windows, double-click **`setup.bat`**. On a mac, run **`./setup.sh`**. Each
reports what is already installed and offers to fetch the rest &mdash; with
winget on Windows, Homebrew on a mac:

| | Why |
|---|---|
| **Python 3** | Runs SlideCast. No pip packages are needed for a normal build. |
| **ffmpeg** | Cuts and encodes the video. `ffprobe` comes with it. |
| **Google Chrome** | Renders each slide to a PNG, headless. |
| **Docker Desktop** | Runs Kokoro, which speaks the script. |
| **WSL** | Windows only. Docker Desktop runs on it and will not start without it. |

**Running it from a terminal instead of double-clicking.** PowerShell will not
run a script sitting in the current folder unless the path says so, and plain
`setup.bat` fails there with "not recognized". The prefix differs per shell:

| Shell | Command |
|---|---|
| PowerShell | `.\setup.bat` |
| cmd.exe | `setup.bat` |
| Git Bash | `./setup.bat` |
| mac / Linux | `./setup.sh` |

The same applies to `run.bat` and `run.sh`.

Two things it cannot do for you. Windows only picks up newly installed programs
in a **new** console window, so close it and use `run.bat` afterwards. And
Docker Desktop has to be opened by hand once before it will start containers.

**WSL needs a restart, and only on Windows.** Docker Desktop for Windows runs
on WSL and will not start without it. Installing it needs administrator rights,
which is why that step asks separately, and it is not usable until the machine
reboots. Open Docker Desktop before that reboot and it fails with "WSL not
installed" even though the install worked.

To do it by hand, in an **Administrator** PowerShell, then restart:

```powershell
wsl --install
```

There is no mac equivalent and nothing to install: Docker Desktop for mac runs
its Linux containers in its own VM, so WSL never enters into it.

The mac support is written but untested: the Chrome and Docker Desktop
locations, `open -a` to launch Docker, and `pgrep` to see whether it is up are
all mac paths that have only ever run on Windows here.

Word-by-word subtitle highlighting is the one feature that needs a Python
package, because it listens back to the generated voice to time each word:

```bash
python -m pip install faster-whisper
```

**If that says "Python was not found; run without arguments to install from
the Microsoft Store"**, you are talking to a Windows stub, not to Python.
Windows keeps a fake `python.exe` in `WindowsApps` that only advertises the
Store, and it answers whenever the real Python is not on PATH - usually
because the terminal predates the install. Open a new terminal, and if it
persists use the launcher, which the stub cannot shadow:

```bash
py -m pip install faster-whisper
```

If `py --version` fails too, Python genuinely is not installed:
`winget install Python.Python.3.13`.

## The UI

Double-click **`run.bat`** (`./run.sh` on a mac), or run it from a terminal with
the prefix your shell wants &mdash; `.\run.bat` in PowerShell &mdash; or:

```bash
python serve.py
```

Opens `http://localhost:8770`. Drop in the deck HTML and the voiceover script,
supply any screenshots the deck references, adjust voice and subtitle settings,
hit Build. The MP4 and the `.srt` are downloadable when it finishes.

Screenshots only need uploading when the HTML is separated from its
`screenshots/` folder. Point the tool at the deck in its own folder and the
images resolve on their own.

Every file you add has a **Remove** button, the script has an **Edit** button
that opens it in a full editor, and **Build video** opens a pre-flight summary
first so a wrong setting does not cost you a three-minute render.

Editing the script updates what this build uses. The browser cannot write back
to the original file on disk, so **Save and download** if you want to keep the
change.

**Building warns about an unsaved video.** A build overwrites the previous
one, so if it was never downloaded you get the choice of saving it first,
building anyway, or cancelling. Only a real download counts as saved: the
inline player fetches the same file, so the Download button uses
`/video?save=1` to distinguish the two.

**Nothing is lost on refresh.** Your inputs, screenshots and settings are mirrored
to `workspace/session.json` as you pick them, and the finished video stays in
`workspace/` until the next build replaces it. Reloading the page restores all
of it, including the player and the download buttons, so a build cannot be
thrown away by an accidental refresh. Refreshing mid-build reattaches to the
running build and keeps streaming the log. Both survive restarting the server.

**The markup guard.** Upload `voiceover-kokoro.txt`, not `voiceover-script.md`.
Both parse, both produce identical subtitles, and both build without error, so
picking the wrong one fails silently in the audio only. The UI now warns when
the uploaded script contains no Kokoro markup.

## Music, and getting its level right

The Music panel exists so the level is judged against the real voice, not guessed.

Pick a bed from the dropdown or load your own file. The built-in beds are
**generated by `make_beds.py`**, not downloaded: a web page calling a track
royalty-free is not a licence check, and SlideCast will not hand you a
copyright risk on something you publish. They are deliberately plain, meant to
sit under a voice rather than be listened to. `python make_beds.py` regenerates
them.

Anything you put in `music_library/` shows up in the dropdown beside them, so
tracks you have licensed yourself live in the same place.

**Play the track on its own** plays the whole file at full volume, which is a
different question from **Preview the mix** - that renders the entire narration
with the music under it at the chosen level, however long the video is.

Music never runs past the end. In the MP4 it is looped and cut to the voice; in
the CapCut draft it is laid out as segments covering the timeline, so a three
minute track under a one minute video arrives already trimmed to one minute.

The beds are loudness-normalised to about -16 LUFS, the level a commercial
track sits at, so the dB setting means the same thing whichever you pick.

**Generate the voice** once, then **Preview the mix** and listen. The preview
reports how far the music sits under the voice and says whether that is too
quiet, too loud, or a good bed. Adjust the dB and preview again; the build uses
whatever level is in the box.

The voice cache key covers the script and everything that changes the speech -
the voice, speed, the pauses, and whether Kokoro is sent whole slides or single
sentences. Change any of those and it is regenerated; change a subtitle colour
and it is not.

Default is **-20 dB**. Loudness varies by track, so trust the preview's verdict
rather than the number.

## Kokoro starts itself

You do not need to start Kokoro, or even Docker, by hand.

- **On server start** a background thread brings Kokoro up.
- **The Voice panel** shows whether it is answering, with a **Start Kokoro** button
  when it is not, and says which part is missing: Docker itself, the container,
  or just the API.
- **Every build** calls the same check first, so a build cannot get halfway in
  and then fail on a dead connection.

If Docker Desktop is closed it is launched and waited for (up to 3 minutes), then
`docker start kokoro-ui` runs, then it waits for the API. If the container has
never been created it is created with the documented `docker run`. Starting a
stopped container to a ready API takes about 30 seconds.

`python kokoro_docker.py` runs the same routine from the command line.

The CLI does not touch Docker. It fails immediately, before rendering any slides,
with the command to run.

## The command line

```bash
python slidecast.py <deck.html> <voiceover-kokoro.txt> -o out.mp4
```

Useful flags: `--voice af_sky` `--speed 1.0` `--font-size 54` `--outline 4`
`--margin-v 20` `--max-chars 56` `--min-sub 0.9` `--gap-slide 1.1` `--fade 0.45`
`--no-fades` `--no-subs` `--music track.mp3` `--music-db -20` `--bold`
`--chunk slide|sentence` `--highlight` `--align-words` `--whisper base`.
`--assets` takes a JSON file mapping a relative `src` to an absolute path.

## Deck design width

Slides are rendered at the CSS viewport width the deck was designed against,
then scaled up to 1080p. This matters more than it sounds.

A 1920x1080 screen running at 125% Windows scaling gives the browser a
**1536x864** CSS viewport. A deck laid out by eye in that browser uses type
sized in fixed pixels, so capturing it at a 1920 viewport instead makes
everything occupy a smaller share of the frame - same output size, visibly
smaller text.

**Deck design width** in the Build panel picks the viewport: 1536 for a
browser at 125% scaling (the default), 1920 for true 1:1, 1280 for 150%.
Whichever you choose, the render is 1920x1080; only the layout changes.

If the video looks more zoomed out than the deck does fullscreen in your
browser, this is the setting to change.

## How the timing works

Kokoro is sent **a whole slide at a time**, so it carries phrasing across
sentences the way it does when you paste a paragraph into its own UI. Sentence
boundaries then come from the word alignment. `--chunk sentence` reverts to one
call per sentence, which pins every boundary exactly without alignment at the
cost of each sentence starting cold; on the local-vs-local deck that was 37
calls and 182.4s against 6 calls and 166.7s.

Where a sentence is too long for a single subtitle line, only the *display* is
split, inside that sentence's exact window. Audio is never cut mid-sentence, so
Kokoro's delivery is unaffected and timing error never accumulates.

The split is not a character-count wrap. Every possible set of breaks is scored:
ending a line on punctuation earns a break, ending it on a dangling function
word is penalised. A plain wrap produced "...dbt project, both" / "of them on
your own machine."; this produces the clause breaks a person would choose, and
`--min-sub` stops a short trailing line flashing up for a fifth of a second.

Slide length follows the narration. The cut between two slides falls in the
middle of the silent gap, which is why `--gap-slide` must be at least twice
`--fade`: it guarantees the fade to black never covers a spoken word.

## Subtitles

Subtitle text comes from the Kokoro script with the pronunciation markup
stripped, so what is displayed is word-for-word what was spoken, with real
capitalisation and punctuation. `voiceover-script.md` is not needed as an input;
stripping `voiceover-kokoro.txt` reproduces it exactly.

Both a `.srt` and an `.ass` are written to the build folder. The `.ass` is what
gets burned in; its `PlayResX/Y` is set to the real frame size, so `--font-size`
is genuine pixels at 1080p rather than ffmpeg's default 384x288 subtitle space.

## Word timing and highlighting

Kokoro returns audio and nothing else, so SlideCast knows exactly when each
sentence starts and ends but not where the words fall inside it. Turning on
**Highlight the spoken word** recovers that: `faster-whisper` listens back to the
generated voice, and the words it hears are matched onto the script we already
know with a sequence match. The script is the truth; only the times come from
the recogniser, so a misheard word still gets a sensible time from its
neighbours.

The recogniser's absolute times drift - it reports the first word at 0.00 when
the audio really starts at 0.6 - but its relative spacing is good, so each
sentence's words are stretched onto the exact window Kokoro gave us. Best of
both: exact boundaries, real word positions.

Measured on the local-vs-local video: **524 of 524 words aligned, 28 seconds**
for a three minute track with the `base` model. The result is cached in
`word_times.json` next to the build.

With highlighting on, the `.ass` carries one line per word, each drawing the
whole caption with a single word recoloured, so only the current word lights up.
That is 524 dialogue lines rather than 76 - fine for libass.

`faster-whisper` needs no torch: it pulls ctranslate2 and onnxruntime, about
200 MB, and the `base` model is another 140 MB downloaded on first use.

**Style presets** cover plain white, plain black, white with black borders, black
with white borders, red, blue and green. The highlight colour is a separate
picker.

## Sending it to CapCut

**Send to CapCut** writes a real draft you can open and keep editing, using the
same subtitle style, black fade and layout as the hand-made project it was
modelled on. The format is undocumented, so nothing is authored from scratch:
`capcut_template.json` is a known-good draft and every material and segment is
cloned from an exemplar in it with fresh ids.

Nothing about the CapCut location is hardcoded. SlideCast looks in the usual
places on Windows (under LOCALAPPDATA, `CapCut/User Data/Projects/*-Projects/*Draft*`)
and macOS (`~/Movies/CapCut/...`, `~/Library/Application Support/CapCut/...`),
shows the folder it settled on in the Build panel, and gives you a **Change**
button that opens the OS folder chooser. The choice is saved to `config.json`.

If a saved path no longer exists - a different machine, or CapCut moved - it is
ignored and discovery runs again, so the tool does not get stuck on someone
else's path. CapCut's draft index is found relative to whatever folder you pick;
if there is no index beside it the draft is still written, and the panel says so.

Set **Black fades in the MP4** to *No* if you would rather add the transitions in
CapCut yourself; the exported draft still carries them.

Sending twice with the same draft name does not overwrite the first draft. The
next free name is used instead (`SlideCast-2`, `SlideCast-3`) and the panel says
so, because a draft you have since edited in CapCut is not SlideCast's to throw
away. Pick **Overwrite it** if replacing is what you actually want; the media
folder is cleared first so nothing stale is left behind.

The draft gets its own copy of the slides and voice under `media/`, because
SlideCast overwrites its workspace on the next build.

## Two things worth knowing

**Chrome needs its own profile directory.** Without `--user-data-dir`, a
headless launch is swallowed by an already-running Chrome: it exits 0 and writes
no PNG. This is the real cause of the old "only works from PowerShell" symptom,
which depended on whether Chrome happened to be open.

**Chrome refuses a relative `--screenshot` path** with "Access is denied" and
still exits 0, so the path is made absolute and the result is checked.

## Logo

The mark is a deck: three 16:9 slides of the same size, the front one lit
orange. The cards lean up-left rather than up-right, which is what keeps the
silhouette from reading as a folder icon.

| File | Use |
|---|---|
| `mark.svg` | Icon only. The frame is `currentColor`, so it takes the surrounding text colour. |
| `icon.svg` | App icon and favicon: the mark on its own dark rounded tile. Works on any background. |
| `logo.svg` | Horizontal lockup, mark plus wordmark. Wordmark is `currentColor` and orange. |
| `icons/*.png` | Rasters at 512/256/128/64/32. `icon`, plus `mark-on-dark` and `mark-on-light`. |

Regenerate the PNGs by rendering each SVG once at 512 in headless Chrome with
`--default-background-color=00000000`, then downscaling to the smaller sizes.
Two traps: `<img>` cannot inherit `currentColor`, so the mark's outline colour
has to be substituted into a copy of the SVG before rasterising; and a
`--window-size=128,128` render comes back cropped, which is why the small sizes
are derived from the 512 rather than rendered natively.

## What this does not do

The course lessons under `Rosetta-DBT-Studio-Beginners-Course/` are screen
recordings of the live app, not slideshows. This tool cannot generate that
footage. It applies to decks where every frame is a rendered slide, which is the
comparison videos.
