#!/usr/bin/env python3
"""Write a real CapCut draft from a slidecast build, so the cut opens ready to edit.

CapCut's draft format is undocumented and version-specific, so nothing here is
authored from scratch. A known-good draft made by hand in CapCut is kept as
`capcut_template.json`, and every material and segment is cloned from an
exemplar in it with fresh ids. That preserves the dozens of fields CapCut
writes but never explains.
"""

import copy
import json
import shutil
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).parent
TEMPLATE = HERE / "capcut_template.json"
META_TEMPLATE = HERE / "capcut_meta_template.json"
CONFIG = HERE / "config.json"

PICKER = chr(10).join([
    "import tkinter as tk",
    "from tkinter import filedialog",
    "root = tk.Tk()",
    "root.withdraw()",
    "root.attributes('-topmost', True)",
    "print(filedialog.askdirectory(title='Select your CapCut Drafts folder') or '')",
])


def _candidates():
    """Every plausible CapCut drafts folder on Windows or macOS."""
    home = Path.home()
    roots = [
        Path(os.environ.get("LOCALAPPDATA", str(home))) / "CapCut" / "User Data" / "Projects",
        home / "AppData" / "Local" / "CapCut" / "User Data" / "Projects",
        home / "Movies" / "CapCut" / "User Data" / "Projects",
        home / "Library" / "Application Support" / "CapCut" / "User Data" / "Projects",
    ]
    found = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            children = sorted(root.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir() and child.name.lower().endswith("-projects"):
                for inner in sorted(child.iterdir()):
                    if inner.is_dir() and "draft" in inner.name.lower():
                        found.append(inner)
        # Older CapCut keeps the drafts directly in com.lveditor.draft, which
        # is only the index folder on current versions.
        legacy = root / "com.lveditor.draft"
        if legacy.is_dir():
            found.append(legacy)
    # Two of the roots resolve to the same place on Windows.
    unique, seen = [], set()
    for path in found:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _roots():
    home = Path.home()
    return [
        Path(os.environ.get("LOCALAPPDATA", str(home))) / "CapCut" / "User Data" / "Projects",
        home / "AppData" / "Local" / "CapCut" / "User Data" / "Projects",
        home / "Movies" / "CapCut" / "User Data" / "Projects",
        home / "Library" / "Application Support" / "CapCut" / "User Data" / "Projects",
    ]


def from_index():
    """Where CapCut itself says its drafts live.

    `com.lveditor.draft` is the folder CapCut creates, but it only holds the
    index once a custom draft location is set. Each entry records its own
    `draft_root_path`, so the most recently touched draft tells us where CapCut
    is actually writing - no guessing from folder names.
    """
    for root in _roots():
        index = root / "com.lveditor.draft" / "root_meta_info.json"
        if not index.exists():
            continue
        try:
            data = json.loads(index.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        entries = [e for e in (data.get("all_draft_store") or [])
                   if isinstance(e, dict)]
        entries.sort(key=lambda e: e.get("tm_draft_modified") or 0, reverse=True)
        for entry in entries:
            where = entry.get("draft_root_path")
            if where and Path(where).is_dir():
                return Path(where)
        base = data.get("root_path")
        if base and Path(base).is_dir():
            return Path(base)
    return None


def discover():
    """Best guess at the drafts folder, preferring CapCut's own record."""
    recorded = from_index()
    if recorded:
        return recorded
    found = _candidates()
    for path in found:
        try:
            if any(path.iterdir()):
                return path
        except OSError:
            pass
    return found[0] if found else None


def drafts_folder():
    """What the user chose, else what we can find, else None."""
    if CONFIG.exists():
        try:
            saved = json.loads(CONFIG.read_text(encoding="utf-8")).get("drafts")
        except ValueError:
            saved = None
        if saved and Path(saved).is_dir():
            return Path(saved)
    return discover()


def set_drafts_folder(path):
    CONFIG.write_text(json.dumps({"drafts": str(Path(path))}), encoding="utf-8")
    return Path(path)


def index_for(drafts):
    """CapCut's draft list sits beside the drafts folder, not inside it."""
    here = Path(drafts)
    for parent in (here.parent, here.parent.parent, here.parent.parent.parent):
        candidate = parent / "com.lveditor.draft" / "root_meta_info.json"
        if candidate.exists():
            return candidate
    return None


def state():
    folder = drafts_folder()
    return {
        "drafts": str(folder) if folder else None,
        "exists": bool(folder and folder.is_dir()),
        "saved": CONFIG.exists(),
        "index": str(index_for(folder)) if folder and index_for(folder) else None,
    }


def pick_folder():
    """Open the OS folder chooser in its own process.

    A Tk dialog on the server thread is unreliable, and a separate process
    keeps the server answering while the chooser is open.
    """
    try:
        result = subprocess.run([sys.executable, "-c", PICKER],
                                capture_output=True, text=True, timeout=600)
    except Exception as exc:
        return {"ok": False, "error": f"Could not open the folder chooser: {exc}"}
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    chosen = lines[-1] if lines else ""
    if not chosen:
        return {"ok": False, "cancelled": True}
    if not Path(chosen).is_dir():
        return {"ok": False, "error": "That is not a folder."}
    set_drafts_folder(chosen)
    return {"ok": True, **state()}

US = 1_000_000          # CapCut counts in microseconds


def new_id():
    return str(uuid.uuid4()).upper()


def _index(materials):
    """id -> (list name, material) across every material list."""
    found = {}
    for name, entries in materials.items():
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and "id" in entry:
                    found[entry["id"]] = (name, entry)
    return found


LOCAL_TOKEN = "%CAPCUT_LOCAL%"


def local_capcut_root():
    """This machine's CapCut folder under LOCALAPPDATA (or the mac equivalent)."""
    home = Path.home()
    for base in (Path(os.environ.get("LOCALAPPDATA", str(home))),
                 home / "AppData" / "Local",
                 home / "Library" / "Application Support",
                 home / "Movies"):
        if (base / "CapCut").is_dir():
            return str(base).replace("\\", "/")
    return None


def localise(raw):
    """Put this machine's paths back into the template.

    The template ships with the author's paths replaced by a token, so the
    repository carries no one's username, and the fonts and cached effects it
    references resolve wherever CapCut actually lives.
    """
    root = local_capcut_root()
    return raw.replace(LOCAL_TOKEN, root) if root else raw


class Draft:
    """Builds a draft by cloning exemplars out of the template."""

    def __init__(self):
        self.doc = json.loads(localise(TEMPLATE.read_text(encoding="utf-8")))
        self.index = _index(self.doc["materials"])
        self.exemplars = {
            "video": self._segment("video"),
            "audio": self._segment("audio"),
            "text": self._segment("text"),
        }
        self.video_material = self._material("videos")
        self.audio_material = self._material("audios")
        self.text_material = self._material("texts")
        self.transition = copy.deepcopy(self.doc["materials"]["transitions"][0])
        # Start from empty lists; everything is rebuilt below.
        for name, entries in self.doc["materials"].items():
            if isinstance(entries, list):
                self.doc["materials"][name] = []
        self.doc["tracks"] = []

    def _segment(self, kind):
        track = next(t for t in self.doc["tracks"] if t["type"] == kind)
        return copy.deepcopy(track["segments"][0])

    def _material(self, name):
        return copy.deepcopy(self.doc["materials"][name][0])

    def _add(self, name, material):
        self.doc["materials"].setdefault(name, []).append(material)
        return material["id"]

    def _clone_aux(self, segment_exemplar, with_transition, fade_us):
        """Copy the little per-segment materials (speed, canvas, ...) with new ids."""
        refs = []
        for ref in segment_exemplar["extra_material_refs"]:
            entry = self.index.get(ref)
            if not entry:
                continue
            name, material = entry
            if name == "transitions":
                continue                      # added separately, only between slides
            clone = copy.deepcopy(material)
            clone["id"] = new_id()
            refs.append(self._add(name, clone))
        if with_transition:
            trans = copy.deepcopy(self.transition)
            trans["id"] = new_id()
            trans["duration"] = int(fade_us)
            refs.append(self._add("transitions", trans))
        return refs

    def track(self, kind, segments):
        self.doc["tracks"].append({
            "attribute": 0, "flag": 0, "id": new_id(),
            "is_default_name": True, "name": "", "type": kind,
            "segments": segments,
        })

    # ---- the three kinds of content -------------------------------------

    def slides(self, pngs, durations, fade_us, with_fades):
        segments, start = [], 0
        for i, (png, dur) in enumerate(zip(pngs, durations)):
            material = copy.deepcopy(self.video_material)
            material.update(id=new_id(), path=str(Path(png).resolve()),
                            material_name=Path(png).name, type="photo",
                            width=1920, height=1080)
            self._add("videos", material)

            seg = copy.deepcopy(self.exemplars["video"])
            seg["id"] = new_id()
            seg["material_id"] = material["id"]
            seg["render_index"] = 0
            # A transition belongs to the segment it starts from, so the last
            # slide never carries one.
            seg["extra_material_refs"] = self._clone_aux(
                self.exemplars["video"], with_fades and i < len(pngs) - 1, fade_us)
            length = int(round(dur * US))
            seg["source_timerange"] = {"start": 0, "duration": length}
            seg["target_timerange"] = {"start": start, "duration": length}
            segments.append(seg)
            start += length
        self.track("video", segments)
        return start

    def voice(self, clips):
        """clips: [(path, start_seconds, duration_seconds)]"""
        segments = []
        for path, start, dur in clips:
            material = copy.deepcopy(self.audio_material)
            length = int(round(dur * US))
            material.update(id=new_id(), path=str(Path(path).resolve()),
                            name=Path(path).name, duration=length,
                            music_id=str(uuid.uuid4()))
            self._add("audios", material)

            seg = copy.deepcopy(self.exemplars["audio"])
            seg["id"] = new_id()
            seg["material_id"] = material["id"]
            seg["volume"] = 1.0
            seg["last_nonzero_volume"] = 1.0
            seg["extra_material_refs"] = self._clone_aux(self.exemplars["audio"], False, 0)
            seg["source_timerange"] = {"start": 0, "duration": length}
            seg["target_timerange"] = {"start": int(round(start * US)), "duration": length}
            segments.append(seg)
        self.track("audio", segments)

    def music(self, path, file_seconds, total_seconds, volume):
        """Lay the track across the video, trimmed if long, repeated if short.

        A three minute track under a one minute video would otherwise run past
        the end, which is the trim you would do by hand in CapCut.
        """
        file_us = max(int(round(file_seconds * US)), 1)
        total_us = int(round(total_seconds * US))
        material = copy.deepcopy(self.audio_material)
        material.update(id=new_id(), path=str(Path(path).resolve()),
                        name=Path(path).name, duration=file_us,
                        music_id=str(uuid.uuid4()))
        self._add("audios", material)

        segments, placed = [], 0
        while placed < total_us:
            take = min(file_us, total_us - placed)
            seg = copy.deepcopy(self.exemplars["audio"])
            seg["id"] = new_id()
            seg["material_id"] = material["id"]
            seg["volume"] = float(volume)
            seg["last_nonzero_volume"] = float(volume)
            seg["extra_material_refs"] = self._clone_aux(
                self.exemplars["audio"], False, 0)
            seg["source_timerange"] = {"start": 0, "duration": take}
            seg["target_timerange"] = {"start": placed, "duration": take}
            segments.append(seg)
            placed += take
        self.track("audio", segments)

    def subtitles(self, events, style):
        segments = []
        for start, end, text in events:
            material = copy.deepcopy(self.text_material)
            material["id"] = new_id()
            content = json.loads(material["content"])
            content["text"] = text
            for span in content.get("styles", []):
                span["range"] = [0, len(text)]
                span["size"] = style["font_size"]
                span["fill"]["content"]["solid"]["color"] = style["fill"]
                for stroke in span.get("strokes", []):
                    stroke["content"]["solid"]["color"] = style["stroke"]
                    stroke["width"] = style["stroke_width"]
            material["content"] = json.dumps(content, ensure_ascii=False)
            material["font_size"] = style["font_size"]
            material["text_color"] = style["text_color"]
            material["border_color"] = style["border_color"]
            material["border_width"] = style["stroke_width"]
            self._add("texts", material)

            seg = copy.deepcopy(self.exemplars["text"])
            seg["id"] = new_id()
            seg["material_id"] = material["id"]
            seg["extra_material_refs"] = self._clone_aux(self.exemplars["text"], False, 0)
            seg["clip"]["transform"]["y"] = style["y"]
            seg["target_timerange"] = {"start": int(round(start * US)),
                                       "duration": int(round((end - start) * US))}
            segments.append(seg)
        self.track("text", segments)


def rgb(hex_colour):
    h = hex_colour.lstrip("#")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def _stash(src, media):
    """Copy a file into the draft so it does not depend on slidecast's workspace."""
    target = media / Path(src).name
    if Path(src).resolve() != target.resolve():
        target.write_bytes(Path(src).read_bytes())
    return str(target.resolve())


def free_name(drafts, name):
    """A name that is not taken, so a second build cannot delete the first."""
    if not (Path(drafts) / name).exists():
        return name
    n = 2
    while (Path(drafts) / f"{name}-{n}").exists():
        n += 1
    return f"{name}-{n}"


def write(name, pngs, durations, voice_clips, events, total, *,
          fade=0.4666, with_fades=True, music=None, music_volume=0.1,
          music_duration=0.0, style=None, drafts_dir=None,
          app_version=None, overwrite=False, log=print):
    """Create the draft folder and register it so CapCut lists it."""
    drafts = Path(drafts_dir) if drafts_dir else drafts_folder()
    if drafts is None:
        raise RuntimeError(
            "No CapCut Drafts folder is set. Click Change next to the CapCut "
            "folder in the Build panel and point at it.")
    if not TEMPLATE.exists():
        raise RuntimeError(f"CapCut template missing at {TEMPLATE}")

    style = {**{"font_size": 5.0, "text_color": "#ffffff", "border_color": "#000000",
                "stroke_width": 0.08, "y": -0.92778,
                "fill": [1.0, 1.0, 1.0], "stroke": [0.0, 0.0, 0.0]}, **(style or {})}

    # Reusing a name would destroy the earlier draft, including anything
    # edited in CapCut since. Take the next free name unless told otherwise.
    if not overwrite:
        chosen = free_name(drafts, name)
        if chosen != name:
            log(f"a draft called {name} already exists, writing {chosen} instead")
        name = chosen

    folder = drafts / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Resources").mkdir(exist_ok=True)

    # slidecast overwrites its workspace on every build, so the draft gets its
    # own copy of the media rather than a path that will rot.
    media = folder / "media"
    if media.exists():
        shutil.rmtree(media, ignore_errors=True)   # no orphans from last time
    media.mkdir(parents=True, exist_ok=True)
    pngs = [_stash(p, media) for p in pngs]
    voice_clips = [(_stash(p, media), s, d) for p, s, d in voice_clips]
    if music:
        music = _stash(music, media)

    draft = Draft()
    draft.slides(pngs, durations, fade * US, with_fades)
    draft.voice(voice_clips)
    draft.subtitles(events, style)
    if music:
        draft.music(music, music_duration or total, total, music_volume)

    now = int(time.time() * US)
    draft_id = new_id()
    doc = draft.doc

    # The draft claims a CapCut version, and CapCut refuses a draft newer than
    # itself. It inherits the template's version, so the template should come
    # from the oldest CapCut you want to open the result in. Also blank the
    # machine identifiers rather than stamping the template's device on
    # everything this ever writes.
    for block in ("platform", "last_modified_platform"):
        info = doc.get(block)
        if isinstance(info, dict):
            info["device_id"] = ""
            info["hard_disk_id"] = ""
            info["mac_address"] = ""
            if app_version:
                info["app_version"] = app_version
    doc["id"] = draft_id
    doc["name"] = ""
    doc["duration"] = int(round(total * US))
    doc["create_time"] = doc["update_time"] = 0
    (folder / "draft_content.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    meta = json.loads(localise(META_TEMPLATE.read_text(encoding="utf-8")))
    meta.update(draft_id=draft_id, draft_name=name,
                draft_fold_path=str(folder), draft_root_path=str(drafts),
                draft_cover=str(folder / "draft_cover.jpg"),
                tm_draft_create=now, tm_draft_modified=now,
                tm_duration=doc["duration"], draft_materials=[])
    (folder / "draft_meta_info.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    (folder / "draft_agency_config.json").write_text(
        json.dumps({"marterials": None, "use_converter": False,
                    "video_resolution": 1080}), encoding="utf-8")

    # Only touch CapCut's own index when writing into CapCut's own folder.
    index = index_for(drafts)
    if index:
        register(index, name, folder, drafts, draft_id, doc["duration"], now, log)
    else:
        log("no CapCut index found beside that folder, so it was not registered")
    claimed = doc.get("platform", {}).get("app_version", "?")
    log(f"CapCut draft written: {folder}")
    return {"folder": str(folder), "draft_id": draft_id, "app_version": claimed,
            "name": name, "overwritten": bool(overwrite)}


def register(index, name, folder, drafts, draft_id, duration, now, log=print):
    """Add the draft to CapCut's index, replacing any entry with the same name."""
    root = json.loads(index.read_text(encoding="utf-8"))
    store = root.setdefault("all_draft_store", [])
    entry = next((e for e in store if e.get("draft_name") == name), None)
    if entry is None:
        entry = copy.deepcopy(store[0]) if store else {}
        store.insert(0, entry)
    entry.update(draft_id=draft_id, draft_name=name,
                 draft_fold_path=str(folder), draft_root_path=str(drafts),
                 draft_json_file=str(folder / "draft_content.json"),
                 draft_cover=str(folder / "draft_cover.jpg"),
                 tm_draft_create=now, tm_draft_modified=now,
                 tm_draft_removed=0, tm_duration=duration)
    backup = index.with_suffix(".json.slidecast-backup")
    if not backup.exists():
        backup.write_text(index.read_text(encoding="utf-8"), encoding="utf-8")
    index.write_text(json.dumps(root, ensure_ascii=False), encoding="utf-8")
