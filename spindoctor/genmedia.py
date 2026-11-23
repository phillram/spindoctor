"""Make the media a wheel is missing: ``spindoctor generate-media``.

What is missing is judged the way HyperSpin looks for it, per wheel:

* the wheel picture is ``Media\\<System>\\Images\\Wheel\\<game>.png``; with
  ``[filters] wheels_only=true`` a game without one isn't on the wheel at all;
* the video is ``<game>.mp4`` / ``.flv`` in ``Media\\<System>\\Video``, or only
  in the folder ``[video defaults] path=`` names.  A ``<game>.png`` there is a
  still that HyperSpin shows where the video would play, so that is where a
  screenshot goes.  Theme slots (Artwork1-4) hold boxes, cartridges or discs,
  and differ per wheel;
* with ``[themes] use_parent_vids=true`` a clone without a video plays its
  parent's, so it isn't missing one (and a stand-in would hide that video);
* with no video at all HyperSpin plays its own ``Media\\Frontend\\Video\\No
  Video.flv``.

Nothing is written to the media folders until it is *put in*.  Everything made
lands in a staging folder of its own with a ``review.html`` to look at;
:func:`put_in` then fills only the places that are still empty, through
``media-scan``'s import, so its undo manifest covers it.

Works without internet: no scraper, artwork service or AI is involved.
Recording games is :mod:`spindoctor.gamecapture`; drawing is
:mod:`spindoctor.titleart`.
"""
from __future__ import annotations

import fnmatch
import html
import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

from . import clips, placeholders, titleart
from ._undo import checkpoint
from ._utils import atomic_write_bytes, is_within, unique_path, win_safe_stem
from .config import CONFIG_DIR, Config
from .database import load_database
from .health import _HS_VIDEO_EXTS, _HS_WHEEL_ART_EXTS, _NOT_IN_FILE_NAMES
from .rl_rom_paths import _raw_game_names
from .rocketlauncher import _read_rl_ini
from .romutils import normalize

STILL_EXTS = (".png", ".jpg", ".jpeg")
STAGE_FILE = "stage.json"
REVIEW_FILE = "review.html"
STAGE_DIR_NAME = "generated-media"

FRONTEND = "Frontend"                   # the pseudo-system of HyperSpin's own No Video clip
NO_VIDEO_FILE = "No Video.flv"
NO_VIDEO_TEXT = "No video found"
NO_SCREENSHOT_TEXT = "No screenshot found"

#: What a staged file is.  The first three stand in for missing media.
STANDIN_KINDS = ("drawn", "clip", "picture")


class GenMediaError(ValueError):
    """The request can't be carried out (unknown wheel, nothing to put in)."""


# ─── what is missing ──────────────────────────────────────────────────────────

@dataclass
class GameState:
    system: str
    name: str               # as written in the wheel's database
    title: str              # what a picture says
    stem: str               # its media files' name
    clone_of: str = ""
    year: str = ""
    manufacturer: str = ""
    wheel: str = "no"       # "yes", "drawn" (a title SpinDoctor drew) or "no"
    video: str = "no"       # "yes", "parent", "still", "placeholder" or "no"
    hidden: bool = False    # not on the wheel, because it has no wheel picture


@dataclass
class WheelState:
    system: str
    games: list[GameState] = field(default_factory=list)
    wheel_dir: Path = Path()
    video_dir: Path = Path()
    wheels_only: bool = False
    problem: str = ""           # why nothing can be made for this wheel
    video_problem: str = ""     # why no video or still can be put in

    def count(self, **want: str) -> int:
        return sum(1 for g in self.games
                   if all(getattr(g, key) == value for key, value in want.items()))

    @property
    def hidden(self) -> int:
        return sum(1 for g in self.games if g.hidden)


def _files(folder: Path, exts: tuple[str, ...]) -> dict[str, list[Path]]:
    """The non-empty files in *folder* ending in one of *exts*, by lower-case stem."""
    out: dict[str, list[Path]] = {}
    try:
        with os.scandir(folder) as entries:
            for e in entries:
                stem, ext = os.path.splitext(e.name)
                if ext.lower() not in exts:
                    continue
                try:
                    if e.is_file() and e.stat().st_size > 0:
                        out.setdefault(stem.lower(), []).append(Path(e.path))
                except OSError:
                    continue
    except OSError:
        pass
    return out


def media_stem(name: str) -> str:
    """The file name HyperSpin looks for: the name as written, without the
    characters no file name can have."""
    return name if _NOT_IN_FILE_NAMES.isdisjoint(name) else win_safe_stem(name)


def wheel_state(config: Config, system: str) -> WheelState:
    """What every game HyperSpin lists on *system*'s wheel has and lacks."""
    hs_dir = Path(config.hyperspin_dir)
    state = WheelState(system, wheel_dir=config.media_dir / system / "Images" / "Wheel",
                       video_dir=config.media_dir / system / "Video")
    try:
        entries = load_database(system, config.databases_dir).games()
    except Exception as exc:  # noqa: BLE001 - doctor reports broken databases
        state.problem = f"its database can't be read: {exc}"
        return state
    if not entries:
        state.problem = "its database is missing or lists no games"
        return state
    ini = _read_rl_ini(hs_dir / "Settings" / f"{system}.ini")

    def on(section: str, key: str) -> bool:
        return ini.get(section, {}).get(key, "").strip().lower() == "true"

    state.wheels_only = on("filters", "wheels_only")
    parents_only = on("filters", "parents_only")
    parent_videos = on("themes", "use_parent_vids")
    redirect = ini.get("video defaults", {}).get("path", "").strip().strip('"').strip()
    if redirect:
        state.video_dir = Path(redirect)
        if not Path(redirect).is_dir():
            state.video_problem = (f"HyperSpin reads its videos from {redirect}, which doesn't exist "
                                   f"([video defaults] path= in Settings\\{system}.ini)")
        elif not Path(redirect).is_absolute():
            state.video_problem = (f"HyperSpin reads its videos from a relative path, {redirect} "
                                   f"([video defaults] path= in Settings\\{system}.ini)")
    index = placeholders.PlaceholderIndex()
    art = _files(state.wheel_dir, _HS_WHEEL_ART_EXTS)
    videos = _files(state.video_dir, _HS_VIDEO_EXTS) if not state.video_problem else {}
    stills = _files(state.video_dir, STILL_EXTS) if not state.video_problem else {}

    def real(paths: Optional[list[Path]]) -> bool:
        return any(not index.is_placeholder(p) for p in paths or ())

    raw = _raw_game_names(system, config.databases_dir)
    described: list[str] = []
    for key, e in entries.items():
        clone = (e.cloneof or "").strip()
        is_clone = bool(clone) and clone.lower() != key.lower()
        if e.enabled == "No" or (parents_only and is_clone) or config.is_ignored(key, system):
            continue
        name = raw.get(key, key)
        game = GameState(system, name, titleart.display_title(e.description or "", key), media_stem(name),
                         clone if is_clone else "", (e.year or "").strip(), (e.manufacturer or "").strip())
        low = game.stem.lower()
        if art.get(low):
            game.wheel = "yes" if real(art[low]) else "drawn"
        if real(videos.get(low)):
            game.video = "yes"
        elif real(stills.get(low)):
            game.video = "still"
        elif parent_videos and is_clone and (real(videos.get(media_stem(clone).lower()))
                                             or real(stills.get(media_stem(clone).lower()))):
            game.video = "parent"
        elif videos.get(low) or stills.get(low):
            game.video = "placeholder"
        game.hidden = state.wheels_only and game.wheel == "no"
        state.games.append(game)
        described.append(e.description or "")
    # Different games with one title (two makers' "Electronic Football") get
    # titles that tell them apart, so their drawn pictures do too.
    same: dict[str, list[int]] = {}
    for i, game in enumerate(state.games):
        same.setdefault(game.title.lower(), []).append(i)
    for group in (g for g in same.values() if len(g) > 1):
        titles = titleart.tell_apart([described[i] for i in group], state.games[group[0]].title)
        for i, title in zip(group, titles):
            state.games[i].title = title
    if not state.games:
        state.problem = "HyperSpin lists no games on it"
    return state


def resolve_wheels(config: Config, systems: Iterable[str] = (), all_systems: bool = False) -> list[str]:
    """Wheel names for ``--system`` / ``--all``.  ``--all`` is every wheel
    switched on in the Main Menu except SpinDoctor's own Custom Wheels, whose
    media is copied from the games' own wheels."""
    from ._wheels import synthetic_names
    from .health import _hidden_main_menu_wheels, _main_menu_wheels

    mm = config.databases_dir / "Main Menu" / "Main Menu.xml"
    menu = _main_menu_wheels(mm)
    synthetic = {s.lower() for s in synthetic_names(config)}
    if all_systems:
        hidden = _hidden_main_menu_wheels(mm)
        wheels = [w for w in menu if w not in hidden and w.lower() not in synthetic]
        if not wheels:
            raise GenMediaError("No wheels found in HyperSpin's Main Menu.xml. Check hyperspin_dir.")
        return wheels
    by_low = {w.lower(): w for w in menu}
    out: list[str] = []
    for name in systems:
        low = name.strip().lower()
        if low in synthetic:
            raise GenMediaError(f"{name!r} is one of SpinDoctor's Custom Wheels: its media comes from "
                                "the games' own wheels. Make it there, then rebuild the wheel.")
        hit = by_low.get(low)
        if hit is None:
            if not (config.databases_dir / name / f"{name}.xml").is_file():
                raise GenMediaError(f"No wheel named {name!r} on the Main Menu.")
            hit = name
        if hit not in out:
            out.append(hit)
    if not out:
        raise GenMediaError("Name a wheel with --system, or use --all.")
    return out


def matching(games: Iterable[GameState], patterns: Iterable[str]) -> list[GameState]:
    """The games whose name or title matches one of *patterns* (``*`` and ``?``,
    any case); all of them without patterns."""
    wanted = [p.strip().lower() for p in patterns if p.strip()]
    if not wanted:
        return list(games)
    return [g for g in games
            if any(fnmatch.fnmatchcase(text, p) for p in wanted
                   for text in (g.name.lower(), g.title.lower()))]


# ─── wheel pictures ───────────────────────────────────────────────────────────

@dataclass
class DrawJob:
    game: GameState
    source: Optional[Path] = None   # a picture already on the PC to copy; None = draw the title
    note: str = ""


def typical_size(folder: Path, default: tuple[int, int] = titleart.DEFAULT_SIZE) -> tuple[int, int]:
    """The usual size of the wheel pictures in *folder*, which HyperSpin shows
    at their natural size; *default* with fewer than five to go by."""
    from .fileinfo import _png_dimensions

    index = placeholders.PlaceholderIndex()
    widths, heights = [], []
    for paths in list(_files(folder, (".png",)).values())[:150]:
        if index.is_placeholder(paths[0]):
            continue
        try:
            w, h = _png_dimensions(paths[0])
        except (OSError, ValueError):
            continue
        widths.append(w)
        heights.append(h)
    if len(widths) < 5:
        return default
    w = sorted(widths)[len(widths) // 2]
    h = sorted(heights)[len(heights) // 2]
    return min(800, max(160, w)), min(400, max(60, h))


class LocalPictures:
    """Wheel pictures already on the PC that belong to a game under another
    file: its parent's, one saved under nearly the same name, or the same game
    on another wheel.

    The same game elsewhere needs the same database name, year and maker, so
    the NES and Genesis games of one title don't get each other's logo."""

    def __init__(self, config: Config, systems: Optional[Iterable[str]] = None):
        self.config = config
        self._systems = list(systems) if systems is not None else None
        self._art: dict[str, dict[str, list[Path]]] = {}
        self._index: dict[str, placeholders.PlaceholderIndex] = {}
        self._games: dict[str, dict] = {}
        self._spare: dict[str, dict[str, list[Path]]] = {}

    def _wheels(self) -> list[str]:
        if self._systems is None:
            try:
                self._systems = resolve_wheels(self.config, all_systems=True)
            except GenMediaError:
                self._systems = []
        return self._systems

    def _pictures(self, system: str) -> dict[str, list[Path]]:
        if system not in self._art:
            index = placeholders.PlaceholderIndex()
            found = _files(self.config.media_dir / system / "Images" / "Wheel", (".png",))
            self._art[system] = {stem: keep for stem, keep in
                                 ((s, [p for p in ps if not index.is_placeholder(p)])
                                  for s, ps in found.items()) if keep}
        return self._art[system]

    def _entries(self, system: str) -> dict:
        if system not in self._games:
            try:
                entries = load_database(system, self.config.databases_dir).games()
            except Exception:  # noqa: BLE001 - a broken database has no games to offer
                entries = {}
            self._games[system] = {name.lower(): e for name, e in entries.items()}
        return self._games[system]

    def _spares(self, system: str) -> dict[str, list[Path]]:
        """This wheel's pictures that belong to no game of it, by normalized name."""
        if system not in self._spare:
            known = {media_stem(n) for n in self._entries(system)}
            out: dict[str, list[Path]] = {}
            for stem, paths in self._pictures(system).items():
                if stem not in known:
                    out.setdefault(normalize(stem), []).extend(paths)
            self._spare[system] = out
        return self._spare[system]

    def find(self, game: GameState) -> tuple[Optional[Path], str]:
        """``(picture, where it's from)``, or ``(None, "")``."""
        own = self._pictures(game.system)
        if game.clone_of:
            hit = own.get(media_stem(game.clone_of).lower())
            if hit:
                return hit[0], f"its parent's, {game.clone_of}"
        spares = self._spares(game.system)
        for key in (normalize(game.name), normalize(game.title)):
            hit = spares.get(key) if key else None
            if hit and len(hit) == 1:
                return hit[0], f"saved as {hit[0].name}"
        if game.year and game.manufacturer:
            low = game.stem.lower()
            for system in self._wheels():
                if system == game.system or low not in self._pictures(system):
                    continue
                e = self._entries(system).get(game.name.strip().lower())
                if (e is not None and (e.year or "").strip() == game.year
                        and (e.manufacturer or "").strip().lower() == game.manufacturer.lower()):
                    return self._pictures(system)[low][0], f"from the {system} wheel"
        return None, ""


def plan_wheel_pictures(
    state: WheelState, *, games: Iterable[str] = (), show_hidden: bool = False, redraw: bool = False,
    local: Optional[LocalPictures] = None,
) -> tuple[list[DrawJob], int]:
    """``(jobs, left hidden)`` for one wheel.

    A game that isn't on the wheel because it has no picture would appear once
    it gets one, so it is left out unless *show_hidden*.  *redraw* makes drawn
    titles again (another style); real pictures are never made again."""
    jobs: list[DrawJob] = []
    kept_hidden = 0
    for game in matching(state.games, games):
        if game.wheel == "yes" or (game.wheel == "drawn" and not redraw):
            continue
        if game.hidden and not show_hidden:
            kept_hidden += 1
            continue
        source, note = local.find(game) if local is not None else (None, "")
        jobs.append(DrawJob(game, source, note))
    return jobs, kept_hidden


# ─── staging ──────────────────────────────────────────────────────────────────

@dataclass
class StageItem:
    system: str
    game: str
    title: str
    media: str          # "wheel", "video" or "still"
    kind: str           # "drawn", "copied", "recorded", "clip" or "picture"
    file: str           # below the staging folder, with / separators
    note: str = ""


class Stage:
    """One staged batch: ``stage.json``, the files as they'd lie in ``Media``,
    and ``review.html``."""

    def __init__(self, folder: Path, data: dict):
        self.folder = folder
        self.data = data
        self.items = [StageItem(**row) for row in data.get("items", [])]
        self._unsaved = 0

    @classmethod
    def create(cls, root: Path, what: str) -> "Stage":
        folder = unique_path(root / f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')} {what}")
        folder.mkdir(parents=True)
        stage = cls(folder, {"what": what, "made": datetime.now().isoformat(timespec="seconds"),
                             "put_in": "", "items": []})
        stage.save()
        return stage

    @classmethod
    def load(cls, folder: Path) -> "Stage":
        try:
            return cls(folder, json.loads((folder / STAGE_FILE).read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError) as exc:
            raise GenMediaError(f"{folder} is not a staging folder: {exc}") from exc

    @property
    def name(self) -> str:
        return self.folder.name

    @property
    def put_in_at(self) -> str:
        return str(self.data.get("put_in") or "")

    def target(self, item: StageItem) -> Path:
        path = self.folder / item.file
        if not is_within(path, self.folder):
            raise GenMediaError(f"{item.file} is outside the staging folder")
        return path

    def new_item(self, system: str, game: str, title: str, media: str, kind: str, stem: str,
                 ext: str, note: str = "") -> StageItem:
        parts = ("Images", "Wheel") if media == "wheel" else ("Video",)
        rel = "/".join(("Media", system) + parts + (stem + ext,))
        return StageItem(system, game, title, media, kind, rel, note)

    def add(self, item: StageItem, *, data: Optional[bytes] = None, source: Optional[Path] = None) -> Path:
        """Write *item*'s file (unless it is there already) and remember it."""
        path = self.target(item)
        path.parent.mkdir(parents=True, exist_ok=True)
        if data is not None:
            atomic_write_bytes(path, data)
        elif source is not None:
            shutil.copy2(source, path)
        self.items = [i for i in self.items if i.file != item.file] + [item]
        self._unsaved += 1
        if self._unsaved >= 50:  # a wheel can have thousands of games
            self.save()
        return path

    def save(self) -> None:
        self.data["items"] = [asdict(i) for i in self.items]
        checkpoint(self.folder / STAGE_FILE, self.data)
        self._unsaved = 0

    def finish(self) -> None:
        """Save, mark the stand-ins for anyone copying the files by hand, and
        write the review page."""
        self.save()
        marked: dict[Path, list[placeholders.Placeholder]] = {}
        for item in self.items:
            path = self.target(item)
            if item.kind in STANDIN_KINDS and item.system != FRONTEND and path.is_file():
                marked.setdefault(path.parent, []).append(placeholders.describe(path, item.kind, item.game))
        suffix = "".join(c for c in self.name.split(" ")[0] if c.isdigit())
        for folder, entries in marked.items():
            placeholders.record(folder, entries, f"{placeholders.LIST_PREFIX}-{suffix}.json")
        atomic_write_bytes(self.folder / REVIEW_FILE, render_review(self).encode("utf-8"))


def stage_root(config: Config, custom: str = "") -> Path:
    """Where batches are staged: *custom*, else ``<output_dir>\\generated-media``,
    else ``~/.spindoctor/generated-media``."""
    if custom:
        return Path(custom)
    if config.output_dir:
        return Path(config.output_dir) / STAGE_DIR_NAME
    return CONFIG_DIR / STAGE_DIR_NAME


def list_stages(root: Path) -> list[Stage]:
    """Every staged batch, newest first."""
    if not root.is_dir():
        return []
    out = []
    for folder in sorted((d for d in root.iterdir() if (d / STAGE_FILE).is_file()), reverse=True):
        try:
            out.append(Stage.load(folder))
        except GenMediaError:
            continue
    return out


def find_stage(root: Path, name: str = "") -> Stage:
    """The batch called *name* (or at that path); the newest one that isn't
    put in yet without a name."""
    if name:
        for folder in (Path(name), root / name):
            if (folder / STAGE_FILE).is_file():
                return Stage.load(folder)
        raise GenMediaError(f"No staged batch named {name!r} in {root}.")
    for stage in list_stages(root):
        if stage.items and not stage.put_in_at:
            return stage
    raise GenMediaError(f"Nothing is waiting to be put in ({root}).")


_REVIEW_CSS = """
body{background:#1a1c22;color:#ddd;font:15px system-ui,Segoe UI,sans-serif;margin:24px}
h1{font-size:22px}h2{font-size:18px;margin-top:32px}
.grid{display:flex;flex-wrap:wrap;gap:14px}
.card{background:#262a33;border-radius:8px;padding:10px;width:320px}
.pic{background:repeating-conic-gradient(#3a3f4b 0 25%,#333843 0 50%) 0/20px 20px;border-radius:4px;
 display:flex;align-items:center;justify-content:center;min-height:120px}
img,video{max-width:100%;max-height:240px;display:block}
.name{font-weight:600;margin-top:8px;overflow-wrap:anywhere}.note{color:#9aa;font-size:13px}
"""


def render_review(stage: Stage) -> str:
    """A page of everything staged.  Local files only: no scripts, no links out."""
    from urllib.parse import quote

    said = {"drawn": "drawn title", "copied": "picture already on the PC", "recorded": "recorded from the game",
            "clip": "placeholder clip", "picture": "placeholder picture"}
    by_system: dict[str, list[StageItem]] = {}
    for item in stage.items:
        by_system.setdefault(item.system, []).append(item)
    parts = ["<!doctype html><meta charset=utf-8><title>", html.escape(stage.name), "</title><style>",
             _REVIEW_CSS, "</style><h1>", html.escape(stage.name), "</h1><p>", str(len(stage.items)),
             " file(s) made. Nothing is in HyperSpin yet: look through them, delete any file you "
             "don't want from this folder, then use <b>Put in</b>.</p>"]
    for system, items in by_system.items():
        parts += ["<h2>", html.escape(system), f" ({len(items)})</h2><div class=grid>"]
        for item in items:
            src = html.escape(quote(item.file), quote=True)
            ext = os.path.splitext(item.file)[1].lower()
            if ext == ".mp4":
                media = f'<video controls preload=metadata src="{src}"></video>'
            elif ext == ".flv":
                media = "<span class=note>Flash video: open it from the folder</span>"
            else:
                media = f'<img loading=lazy src="{src}" alt="">'
            note = said.get(item.kind, item.kind) + (f"; {item.note}" if item.note else "")
            parts += ["<div class=card><div class=pic>", media, "</div><div class=name>",
                      html.escape(item.title or item.game), "</div><div class=note>",
                      html.escape(f"{item.game} · {note}"), "</div></div>"]
        parts.append("</div>")
    return "".join(parts)


# ─── making pictures and placeholders ─────────────────────────────────────────

Progress = Callable[[int, int, str], None]


def make_wheel_pictures(stage: Stage, jobs: list[DrawJob], *, style: str = titleart.DEFAULT_STYLE,
                        size: Optional[tuple[int, int]] = None, font: Optional[Path] = None,
                        config: Optional[Config] = None, progress: Optional[Progress] = None) -> list[str]:
    """Stage a picture for every job; returns what went wrong."""
    sizes: dict[str, tuple[int, int]] = {}
    errors: list[str] = []
    for n, job in enumerate(jobs, 1):
        game = job.game
        if progress is not None:
            progress(n, len(jobs), game.title)
        kind = "copied" if job.source else "drawn"
        item = stage.new_item(game.system, game.name, game.title, "wheel", kind, game.stem, ".png", job.note)
        try:
            if job.source:
                stage.add(item, source=job.source)
                continue
            if size is None and game.system not in sizes:
                sizes[game.system] = (typical_size(config.media_dir / game.system / "Images" / "Wheel")
                                      if config is not None else titleart.DEFAULT_SIZE)
            stage.add(item, data=titleart.draw_title(game.title, style, size or sizes[game.system], font))
        except (OSError, titleart.TitleArtError) as exc:
            errors.append(f"{game.system} > {game.name}: {exc}")
    return errors


def plan_placeholders(state: WheelState, *, games: Iterable[str] = (), show_hidden: bool = False,
                      redo: bool = False) -> list[GameState]:
    """The games of one wheel that have neither a video nor a still.  Games
    HyperSpin hides get none unless *show_hidden*: nobody would see it."""
    if state.problem or state.video_problem:
        return []
    return [g for g in matching(state.games, games)
            if (g.video == "no" or (redo and g.video == "placeholder")) and (show_hidden or not g.hidden)]


def make_placeholders(stage: Stage, games: list[GameState], *, kind: str = "clip",
                      background: str = "blue", text: str = "", tools=None,
                      progress: Optional[Progress] = None) -> list[str]:
    """Stage a "No video found" clip (or a "No screenshot found" picture) with
    the title of every game; returns what went wrong."""
    from .clips import ClipError

    message = text or (NO_VIDEO_TEXT if kind == "clip" else NO_SCREENSHOT_TEXT)
    errors: list[str] = []
    for n, game in enumerate(games, 1):
        if progress is not None:
            progress(n, len(games), game.title)
        try:
            card = titleart.draw_card(message, game.title, background)
            if kind == "picture":
                stage.add(stage.new_item(game.system, game.name, game.title, "still", kind, game.stem,
                                         ".png"), data=card)
                continue
            item = stage.new_item(game.system, game.name, game.title, "video", kind, game.stem, ".mp4")
            _card_video(stage, item, card, tools.make_card_clip)
        except (OSError, titleart.TitleArtError, ClipError) as exc:
            errors.append(f"{game.system} > {game.name}: {exc}")
    return errors


def make_frontend_clip(stage: Stage, *, background: str = "blue", text: str = "", tools=None) -> StageItem:
    """Stage a new clip for HyperSpin's own ``No Video.flv``, which it plays
    for every game on every wheel that has no video."""
    stem, ext = os.path.splitext(NO_VIDEO_FILE)
    item = stage.new_item(FRONTEND, stem, NO_VIDEO_TEXT, "video", "clip", stem, ext,
                          "plays for every game without a video")
    _card_video(stage, item, titleart.draw_card(text or NO_VIDEO_TEXT, "", background), tools.make_card_flv)
    return item


def _card_video(stage: Stage, item: StageItem, card: bytes, make) -> None:
    out = stage.target(item)
    png = stage.folder / "card.png"
    atomic_write_bytes(png, card)
    try:
        make(png, out)
        stage.add(item)
    finally:
        try:
            png.unlink()
        except OSError:
            pass


# ─── a wheel's Main Menu video ───────────────────────────────────────────────

MAIN_MENU = "Main Menu"
MENU_CLIPS = 8


@dataclass
class MenuVideoJob:
    """The clips a wheel's Main Menu video is made from, or why it isn't made."""
    system: str
    clips: list[Path] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    why: str = ""


def _video_file(state: WheelState, game: GameState, index: placeholders.PlaceholderIndex) -> Optional[Path]:
    """*game*'s own video file (not a placeholder), or None."""
    for ext in _HS_VIDEO_EXTS:
        path = state.video_dir / (game.stem + ext)
        try:
            if path.is_file() and path.stat().st_size > 0 and not index.is_placeholder(path):
                return path
        except OSError:
            continue
    return None


def plan_menu_video(menu: WheelState, state: WheelState, games: Iterable[str] = (),
                    count: int = MENU_CLIPS) -> MenuVideoJob:
    """Which of *state*'s own videos make its Main Menu video: the games named
    (name or title, ``*`` and ``?``) in the order given, else *count* spread
    evenly over the wheel.  Stills, placeholders and parents' videos don't
    count.  Nothing when the Main Menu (*menu*) has a video for the wheel
    already, or fewer than 2 clips are found."""
    job = MenuVideoJob(state.system)
    entry = next((g for g in menu.games if g.name.lower() == state.system.lower()), None)
    if entry is None:
        job.why = "it isn't on the Main Menu"
    elif entry.video in ("yes", "still"):
        job.why = "the Main Menu has a video for it already"
    elif menu.video_problem or state.problem or state.video_problem:
        job.why = menu.video_problem or state.problem or state.video_problem
    if job.why:
        return job
    index = placeholders.PlaceholderIndex()
    have = [(g, p) for g in state.games if g.video == "yes" for p in [_video_file(state, g, index)] if p]
    wanted = [w.strip().lower() for w in games if w.strip()]
    if wanted:
        picked = []
        for pattern in wanted:
            picked += [(g, p) for g, p in have if (g, p) not in picked
                       and any(fnmatch.fnmatchcase(t, pattern) for t in (g.name.lower(), g.title.lower()))]
    elif len(have) <= count:
        picked = have
    else:
        step = len(have) / count        # more than 1, so no clip comes twice
        picked = [have[int(i * step)] for i in range(count)]
    if len(picked) < 2:
        job.why = f"{len(picked)} of its games ha{'s' if len(picked) == 1 else 've'} a video; it takes 2 or more"
        return job
    job.clips = [p for _g, p in picked]
    job.titles = [g.title for g, _p in picked]
    return job


def make_menu_video(stage: Stage, job: MenuVideoJob, *, tools, seconds: float = clips.MONTAGE_PIECE) -> StageItem:
    """Stage ``Media\\Main Menu\\Video\\<wheel>.mp4``, the clips of *job* one
    after another (:meth:`clips.Tools.make_montage`)."""
    item = stage.new_item(MAIN_MENU, job.system, job.system, "video", "montage", media_stem(job.system), ".mp4",
                          f"{len(job.clips)} clips: " + ", ".join(job.titles))
    tools.make_montage(job.clips, stage.target(item), seconds=seconds)
    stage.add(item)
    return item


# ─── putting it in ────────────────────────────────────────────────────────────

@dataclass
class PutIn:
    item: StageItem
    source: Path
    target: Path
    action: str         # "new", "replace" (a stand-in, or the Frontend clip) or "skip"
    why: str = ""


def plan_put_in(config: Config, stage: Stage, *, systems: Iterable[str] = (),
                games: Iterable[str] = ()) -> list[PutIn]:
    """What each staged file would do now.  A place filled since it was made
    is skipped."""
    wanted = {s.strip().lower() for s in systems}
    patterns = [p.strip().lower() for p in games if p.strip()]
    states: dict[str, WheelState] = {}
    by_name: dict[str, dict[str, GameState]] = {}
    out: list[PutIn] = []
    for item in stage.items:
        if wanted and item.system.lower() not in wanted:
            continue
        if patterns and not any(fnmatch.fnmatchcase(text, p) for p in patterns
                                for text in (item.game.lower(), item.title.lower())):
            continue
        source = stage.target(item)
        if not source.is_file():
            out.append(PutIn(item, source, Path(), "skip", "removed from the staging folder"))
            continue
        if item.system == FRONTEND:
            target = config.media_dir / FRONTEND / "Video" / source.name
            out.append(PutIn(item, source, target, "replace" if target.exists() else "new",
                             "the old clip is kept for undo" if target.exists() else ""))
            continue
        if item.system not in states:
            states[item.system] = wheel_state(config, item.system)
            by_name[item.system] = {g.name: g for g in states[item.system].games}
        out.append(_place(states[item.system], by_name[item.system].get(item.game), item, source))
    return out


def _place(state: WheelState, game: Optional[GameState], item: StageItem, source: Path) -> PutIn:
    def skip(why: str) -> PutIn:
        return PutIn(item, source, target, "skip", why)

    target = (state.wheel_dir if item.media == "wheel" else state.video_dir) / source.name
    if state.problem:
        return skip(state.problem)
    if game is None:
        return skip("the game isn't on the wheel any more")
    standin = item.kind in STANDIN_KINDS
    if item.media == "wheel":
        if game.wheel == "yes":
            return skip("it has a wheel picture now")
        if game.wheel == "drawn" and standin and _newer_there(source, target):
            return skip("a newer drawn picture is there")
        return PutIn(item, source, target, "replace" if game.wheel == "drawn" else "new")
    if state.video_problem:
        return skip(state.video_problem)
    if game.video == "yes":
        return skip("it has a video now")
    if game.video == "still" and item.media == "still":
        return skip("it has a still picture now")
    if standin and game.video in ("still", "parent"):
        return skip("it has a still picture now" if game.video == "still" else "it plays its parent's video")
    if game.video == "placeholder" and standin and _newer_there(source, target):
        return skip("a newer placeholder is there")
    return PutIn(item, source, target, "replace" if game.video == "placeholder" else "new")


def _newer_there(source: Path, target: Path) -> bool:
    """Whether the stand-in at *target* was made after the staged *source*:
    an older batch put in later must not replace it.  Staged files keep the
    time they were made, and put-in's copies keep it too."""
    try:
        return target.stat().st_mtime > source.stat().st_mtime
    except OSError:
        return False


def _slot(item: StageItem) -> tuple[str, str, str]:
    """The place in HyperSpin a staged file fills: the wheel picture, or the
    video (a still plays in the video's place)."""
    return item.system.lower(), item.game.lower(), "wheel" if item.media == "wheel" else "video"


def _better(item: StageItem, stage: Stage) -> tuple:
    """How good a file is for its place: real media over a stand-in, a video
    over a still, then the newest batch."""
    return (item.kind not in STANDIN_KINDS, item.media == "video",
            str(stage.data.get("made") or ""), stage.name)


def waiting_files(root: Path) -> dict[tuple[str, str, str], str]:
    """For every place a staged file not put in yet would fill (``(system,
    game, "wheel" or "video")``, lower case), the newest such batch's name."""
    out: dict[tuple[str, str, str], str] = {}
    for stage in list_stages(root):     # newest first
        if stage.put_in_at:
            continue
        for item in stage.items:
            out.setdefault(_slot(item), stage.name)
    return out


def plan_put_in_all(config: Config, stages: Iterable[Stage], *, systems: Iterable[str] = (),
                    games: Iterable[str] = ()) -> list[tuple[Stage, list[PutIn]]]:
    """Each batch's plan, with every place given the best of all the batches'
    files for it (see :func:`_better`); the others are left out, naming the
    batch whose file goes in.  So the order batches were made or put in no
    longer matters.  HyperSpin's own No Video clip goes in by itself."""
    systems, games = list(systems), list(games)
    plans = [(stage, plan_put_in(config, stage, systems=systems, games=games)) for stage in stages]
    best: dict[tuple[str, str, str], tuple[tuple, PutIn, Stage]] = {}
    for stage, plan in plans:
        for p in plan:
            if p.item.system == FRONTEND and p.action != "skip":
                p.action, p.why = "skip", "HyperSpin's own No Video clip is put in by itself"
            if p.action == "skip":
                continue
            rank = _better(p.item, stage)
            if _slot(p.item) not in best or rank > best[_slot(p.item)][0]:
                best[_slot(p.item)] = (rank, p, stage)
    for _stage, plan in plans:
        for p in plan:
            if p.action != "skip" and best[_slot(p.item)][1] is not p:
                p.action, p.why = "skip", f"the one from {best[_slot(p.item)][2].name} goes in"
    return plans


def put_in(config: Config, stage: Stage, plan: list[PutIn], manifest_dir: Optional[Path] = None):
    """Copy the planned files into HyperSpin's media.  Returns ``media-scan``'s
    :class:`~spindoctor.media_scan.ImportResult`; ``media-scan --undo`` (or
    :func:`undo_put_in`) takes the files out again and puts replaced ones back."""
    return put_in_many(config, [(stage, plan)], manifest_dir=manifest_dir,
                       source_dir=stage.folder, label=f"generate-media: {stage.name}")


def put_in_many(config: Config, plans: list[tuple[Stage, list[PutIn]]], *, manifest_dir: Optional[Path] = None,
                source_dir: Optional[Path] = None, label: str = "generate-media", mark_all: bool = False):
    """:func:`put_in` for several batches at once (from :func:`plan_put_in_all`),
    as one step that one undo takes back.  Batches a file came from are marked
    put in; with *mark_all*, every batch is, as long as anything went in (its
    places were filled by better files)."""
    from .media_scan import LocalMediaFile, MediaScanReport, ScanMatch, import_media

    report = MediaScanReport(source_dir=source_dir or (plans[0][0].folder if plans else Path()))
    frontend = False
    by_target: dict[Path, tuple[Stage, PutIn]] = {}
    for stage, plan in plans:
        for p in plan:
            if p.action == "skip":
                continue
            frontend = frontend or p.item.system == FRONTEND
            by_target[p.target] = (stage, p)
            report.matched.append(ScanMatch(
                local=LocalMediaFile(p.source, "wheel" if p.item.media == "wheel" else "video"),
                system=p.item.system, game_name=p.item.game, score=1.0, target_path=p.target, bucket="matched"))
    # Only HyperSpin's own clip may replace a file that isn't a stand-in.
    if frontend and len(report.matched) > 1:
        raise GenMediaError("HyperSpin's own No Video clip is put in by itself.")
    result = import_media(report, config, action="copy", overwrite=frontend, manifest_dir=manifest_dir,
                          label=label)
    marks: dict[Path, list[placeholders.Placeholder]] = {}
    came_from: dict[Path, Stage] = {}
    for _src, target in result.imported:
        stage, p = by_target[target]
        came_from[stage.folder] = stage
        item = p.item
        if item.system == FRONTEND:
            continue
        if item.kind in STANDIN_KINDS:
            marks.setdefault(target.parent, []).append(placeholders.describe(target, item.kind, item.game))
        if item.media != "wheel":
            # A stand-in under another extension (a .png beside the .mp4 that
            # came in) goes: HyperSpin could go on showing it.
            placeholders.remove(target.parent, ("clip", "picture"), [item.game], keep=[target])
    for folder, entries in marks.items():
        placeholders.record(folder, entries)
    if result.imported:
        done = [s for s, _p in plans] if mark_all else list(came_from.values())
        when = datetime.now().isoformat(timespec="seconds")
        for stage in done:
            stage.data["put_in"] = when
            stage.data["put_in_manifest"] = result.manifest_path.name if result.manifest_path else ""
            stage.save()
    return result


def last_put_in(manifest_dir: Optional[Path] = None) -> Optional[Path]:
    """The newest import manifest ``put_in`` wrote."""
    from .media_scan import list_manifests

    for path in reversed(list_manifests(manifest_dir)):
        try:
            label = json.loads(path.read_text(encoding="utf-8")).get("label", "")
        except (OSError, ValueError, AttributeError):
            continue
        if str(label).startswith("generate-media"):
            return path
    return None


def undo_put_in(manifest_dir: Optional[Path] = None) -> Optional[tuple[Path, dict]]:
    """Take back the newest :func:`put_in`: ``(manifest, summary)``, or None
    when there is none.  Its staged files stay, and can be put in again."""
    from .media_scan import undo_import

    manifest = last_put_in(manifest_dir)
    if manifest is None:
        return None
    try:
        folder = Path(json.loads(manifest.read_text(encoding="utf-8")).get("source_dir") or "")
    except (OSError, ValueError):
        folder = Path()
    summary = undo_import(manifest)
    if summary["errors"]:
        return manifest, summary
    # One batch (its folder is the source), or every batch a put-in of them all took files from.
    if (folder / STAGE_FILE).is_file():
        try:
            stages = [Stage.load(folder)]
        except GenMediaError:
            stages = []
    elif folder != Path():
        stages = [s for s in list_stages(folder) if s.data.get("put_in_manifest") == manifest.name]
    else:
        stages = []
    for stage in stages:
        stage.data["put_in"] = ""
        stage.data.pop("put_in_manifest", None)
        try:
            stage.save()
        except OSError:
            pass
    return manifest, summary


# ─── taking stand-ins out ─────────────────────────────────────────────────────

def standin_folders(config: Config, systems: Iterable[str]) -> list[tuple[str, Path]]:
    """``(system, folder)`` for every media folder of *systems* that can hold
    stand-ins, each folder once."""
    out: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for system in systems:
        ini = _read_rl_ini(Path(config.hyperspin_dir) / "Settings" / f"{system}.ini")
        redirect = ini.get("video defaults", {}).get("path", "").strip().strip('"').strip()
        folders = [config.media_dir / system / "Images" / "Wheel", config.media_dir / system / "Video"]
        if redirect:
            folders.append(Path(redirect))
        for folder in folders:
            if folder not in seen:
                seen.add(folder)
                out.append((system, folder))
    return out
