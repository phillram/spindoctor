"""The ffmpeg layer: what is asked of ffmpeg, what is read from its log, and
(when ffmpeg is installed) what really comes out."""
from __future__ import annotations

import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from spindoctor import _loopback, _win32, clips
from spindoctor.config import Config

LOG = """
Input #0, matroska,webm, from 'take.mkv':
  Duration: 00:00:{dur}, start: 0.000000, bitrate: 900 kb/s
  Stream #0:0: Video: h264 (High), yuv420p(progressive), 1280x720 [SAR 1:1 DAR 16:9], 30 fps
{body}
frame=  300 fps=0.0 q=-0.0 Lsize=N/A time=00:00:{dur} bitrate=N/A speed= 900x
"""


def _log(dur="10.00", body=""):
    return LOG.format(dur=dur, body=body)


def test_a_moving_picture_is_usable():
    a = clips.parse_analysis(_log(body="[cropdetect] x1:160 x2:1119 crop=960:720:160:0"))
    assert (a.seconds, a.width, a.height, a.crop) == (10.0, 1280, 720, (960, 720, 160, 0))
    assert a.verdict == "" and not a.is_black and not a.is_frozen


@pytest.mark.parametrize("body, verdict", [
    ("[blackdetect] black_start:0 black_end:9.5 black_duration:9.5", "the picture was black"),
    ("lavfi.freezedetect.freeze_start: 0.2", "the picture didn't move"),
    ("lavfi.freezedetect.freeze_start: 0\nlavfi.freezedetect.freeze_duration: 9\n"
     "lavfi.freezedetect.freeze_end: 9", "the picture didn't move"),
    ("[blackdetect] black_start:0 black_end:2 black_duration:2", ""),
    ("lavfi.freezedetect.freeze_start: 0\nlavfi.freezedetect.freeze_end: 3\n"
     "lavfi.freezedetect.freeze_start: 6", ""),
])
def test_black_and_frozen_pictures_are_not(body, verdict):
    assert clips.parse_analysis(_log(body=body)).verdict == verdict


def test_an_empty_log_is_nothing_recorded():
    assert clips.parse_analysis("").verdict == "nothing was recorded"
    assert clips.Analysis(problem="device busy").verdict == "device busy"


def test_a_tiny_crop_from_a_dark_scene_is_ignored():
    assert clips.parse_analysis(_log(body="crop=200:100:540:310")).crop is None


def test_a_tall_or_wide_game_is_not_a_dark_scene():
    # A handheld's portrait screen: full height, a fifth of the width.
    assert clips.parse_analysis(_log(body="crop=250:720:514:0")).crop == (250, 720, 514, 0)
    assert clips.parse_analysis(_log(body="crop=1280:200:0:260")).crop == (1280, 200, 0, 260)
    assert clips.parse_analysis(_log(body="crop=50:720:614:0")).crop is None   # a thin strip
    assert clips.plausible_crop(960, 720, 1280, 720) and not clips.plausible_crop(0, 720, 1280, 720)
    # Handhelds whose own edges stay dark: Pac-Man 25% x 80%, UFO Master-Blaster 9% x 100%, a card row 100% x 14%.
    assert clips.plausible_crop(320, 576, 1280, 720) and clips.plausible_crop(116, 720, 1280, 720)
    assert clips.plausible_crop(1280, 100, 1280, 720)
    assert not clips.plausible_crop(300, 400, 1280, 720)     # a third wide, 56% high: a dark scene


def _pgm(width, height, lit):
    """A black grey picture with *lit* pixels ``(x, y)`` at 200."""
    px = bytearray(width * height)
    for x, y in lit:
        px[y * width + x] = 200
    return b"P5\n# made by a test\n%d %d\n255\n" % (width, height) + bytes(px)


def test_pgm_pictures_are_read():
    assert clips.read_pgm(_pgm(4, 3, [(1, 1)]))[:2] == (4, 3)
    assert clips.read_pgm(b"P6\n4 3\n255\n" + bytes(36)) is None   # colour
    assert clips.read_pgm(b"P5\n4 3\n255\n" + bytes(5)) is None    # cut short
    assert clips.read_pgm(b"P5\n4 3\n65535\n" + bytes(24)) is None  # 16-bit


def test_sparse_details_on_black_count_as_the_picture():
    # A score of a few lit pixels in the top row and LEDs in the bottom row:
    # cropdetect's row averages call those rows black and cut them off.
    lit = [(40, 0), (41, 0), (40, 59), (60, 59)] + [(x, y) for x in range(30, 70) for y in range(20, 40)]
    w, h, px = clips.read_pgm(_pgm(100, 60, lit))
    assert clips.content_box(w, h, px) == (30, 0, 70, 60)
    assert clips.content_box(w, h, bytes(len(px))) is None
    # One stray pixel in a column doesn't widen the picture.
    w, h, px = clips.read_pgm(_pgm(100, 60, lit + [(95, 30)]))
    assert clips.content_box(w, h, px) == (30, 0, 70, 60)


def test_a_crop_is_read_from_the_brightest_picture():
    # The picture is 40 of 100 columns, all 60 rows: in a 1280x720 take that's 512 wide.
    lit = [(x, y) for x in range(30, 70) for y in list(range(0, 60, 3)) + [59]]
    assert clips.crop_from_max_frame(_pgm(100, 60, lit), 1280, 720) == (512, 720, 384, 0)
    # Edges between the small picture's pixels round outward, to even numbers.
    assert clips.crop_from_max_frame(_pgm(100, 60, lit), 1000, 600) == (400, 600, 300, 0)
    tall = [(x, y) for x in range(45, 55) for y in range(60)]   # a portrait game, a tenth of the width
    w, h, x, y = clips.crop_from_max_frame(_pgm(100, 60, tall), 1280, 720)
    assert (h, y) == (720, 0) and 128 <= w <= 160
    full = [(x, y) for x in range(100) for y in range(60)]
    assert clips.crop_from_max_frame(_pgm(100, 60, full), 1280, 720) is None    # no bars
    assert clips.crop_from_max_frame(_pgm(100, 60, [(50, 30), (51, 30)]), 1280, 720) is None   # a dot
    assert clips.crop_from_max_frame(b"not a picture", 1280, 720) is None


def test_the_brightest_picture_is_asked_for_only_with_a_file():
    plain = clips.analyse_command("ffmpeg", Path("take.mkv"))
    graph = plain[plain.index("-filter_complex") + 1]
    assert "mpdecimate" in graph and "showinfo" in graph and "lagfun" not in graph
    assert "freezedetect" not in graph and plain.count("-map") == 2
    both = clips.analyse_command("ffmpeg", Path("take.mkv"), Path("take.max.pgm"))
    graph = both[both.index("-filter_complex") + 1]
    assert "cropdetect" in graph and "lagfun=decay=1" in graph and "format=gray" in graph
    assert both[-1] == "take.max.pgm" and both.count("-map") == 3


def test_black_is_judged_strictly_enough_for_handhelds():
    # ffmpeg's 0.98 makes a few lit LEDs on a black screen a black picture.
    graph = clips.analyse_command("ffmpeg", Path("take.mkv"))
    probe = ",".join(clips.probe_command("ffmpeg", "gdigrab"))
    for text in (graph[graph.index("-filter_complex") + 1], probe):
        assert f"pic_th={clips.BLACK_PICTURE:g}" in text and clips.BLACK_PICTURE >= 0.999


def _shown(*times):
    return "\n".join(f"[Parsed_showinfo_6 @ 000001c0] n:{i:4d} pts:{int(t * 10):7d} pts_time:{t:g}   duration:1"
                      for i, t in enumerate(times))


def test_a_small_change_now_and_then_is_movement():
    # Something changed at least every 2 s: a ball, a few LEDs. Not frozen.
    a = clips.parse_analysis(_log(body=_shown(0, 1.5, 3, 4.2, 5.9, 7.5, 9)))
    assert a.frozen == 0 and a.verdict == ""
    # Changed only at the start: frozen from there to the end.
    a = clips.parse_analysis(_log(body=_shown(0, 0.3)))
    assert a.frozen == 9.7 and a.verdict == "the picture didn't move"
    # The change log wins over freezedetect's averages when both are there.
    a = clips.parse_analysis(_log(body=_shown(0, 1, 2, 3, 4, 5, 6, 7, 8, 9) + "\nlavfi.freezedetect.freeze_start: 0"))
    assert a.frozen == 0


def test_frozen_seconds_counts_only_long_gaps():
    assert clips.frozen_seconds([0, 1, 2], 10) == 8.0              # 2 s to the end
    assert clips.frozen_seconds([0, 5, 6], 10) == 5.0 + 4.0
    assert clips.frozen_seconds([0, 1.9, 3.8, 5.7, 7.6, 9.5], 10) == 0.0
    assert clips.frozen_seconds([], 10) == 10.0


def test_volume_and_gain():
    a = clips.parse_analysis("mean_volume: -34.1 dB\nmax_volume: -31.0 dB")
    assert (a.mean_db, a.peak_db) == (-34.1, -31.0) and a.has_sound
    assert clips.gain_db(-34.1, -31.0) == 14.1
    assert clips.gain_db(-30.0, -4.0) == 3.0        # the peak stays under -1 dB
    assert clips.gain_db(-10.0, -1.0) == -10.0
    assert clips.gain_db(None, None) == 0.0
    silent = clips.parse_analysis("mean_volume: -inf dB")
    assert not silent.has_sound and silent.mean_db == -120.0


@pytest.mark.parametrize("mode, crop, want", [
    ("auto", (960, 720, 160, 0), (960, 720, 160, 0)),
    ("auto", (1278, 718, 0, 0), None),
    ("auto", None, None),
    ("4:3", None, (960, 720, 160, 0)),
    ("full", (960, 720, 160, 0), None),
])
def test_choose_crop(mode, crop, want):
    assert clips.choose_crop(mode, clips.Analysis(width=1280, height=720, crop=crop)) == want
    assert clips.choose_crop(mode, clips.Analysis()) is None


def test_fit_size_keeps_the_shape_and_even_sides():
    assert clips.fit_size(960, 720) == (640, 480)
    assert clips.fit_size(1920, 1080) == (640, 360)
    assert clips.fit_size(448, 576) == (374, 480)
    assert clips.fit_size(1268, 944) == (640, 480)     # a crop a few lines off 4:3
    assert clips.fit_size(1276, 720) == (640, 360)
    assert clips.fit_size(1200, 720) == (640, 384)     # 5:3 stays 5:3
    assert clips.fit_size(0, 0) == clips.CLIP_SIZE


def test_commands_ask_for_what_hyperspin_plays():
    sound = clips.SoundFile(Path("s.raw"), "f32le", 48000, 2)
    cmd = clips.clip_command("ffmpeg", Path("t.mkv"), Path("o.mp4"), crop=(960, 720, 160, 0),
                             sound=sound, sound_skip=0.5, gain=3.5)
    text = " ".join(cmd)
    for part in ("-c:v libx264", "-profile:v main", "-pix_fmt yuv420p", "-c:a aac", "-movflags +faststart",
                 "crop=960:720:160:0", "scale=640:480", "fps=30", "volume=3.5dB", "-ss 0.500 -f f32le -ar 48000"):
        assert part in text
    assert "mp3" not in text
    silent = clips.clip_command("ffmpeg", Path("t.mkv"), Path("o.mp4"))
    assert "-c:a" not in silent and "-af" not in silent
    card = " ".join(clips.card_clip_command("ffmpeg", Path("c.png"), Path("o.mp4")))
    assert "-bf 0" in card and "anullsrc" in card
    flv = clips.card_flv_command("ffmpeg", Path("c.png"), Path("No Video.flv"))
    assert flv[flv.index("-c:v") + 1] == "flv" and "-an" in flv


def test_grabbing_the_screen():
    dd = clips.take_command("ffmpeg", "ddagrab", Path("t.mkv"), 35, (100, 50, 801, 601))
    assert any(a.startswith("ddagrab=") and "draw_mouse=0" in a for a in dd)
    assert "hwdownload,format=bgra,crop=800:600:100:50" in dd[dd.index("-vf") + 1]
    gdi = clips.take_command("ffmpeg", "gdigrab", Path("t.mkv"), 35)
    assert gdi[gdi.index("-f") + 1] == "gdigrab" and "hwdownload" not in gdi[gdi.index("-vf") + 1]
    for cmd in (dd, gdi, clips.probe_command("ffmpeg", "gdigrab")):
        assert "-nostdin" in cmd
        assert not any("://" in a for a in cmd)  # never a network address


def test_methods_are_read_from_ffmpegs_filters(monkeypatch):
    tools = clips.Tools("ffmpeg", "ffprobe")
    monkeypatch.setattr(tools, "_run", lambda cmd, timeout: subprocess.CompletedProcess(cmd, 0, " .. ddagrab |->V", ""))
    assert tools.methods() == ["ddagrab", "gdigrab"]
    old = clips.Tools("ffmpeg", "ffprobe", " .. scale V->V")
    assert old.methods() == ["gdigrab"]


def test_a_failed_job_leaves_no_file_and_says_why(tmp_path, monkeypatch):
    tools = clips.Tools("ffmpeg", "ffprobe")
    out = tmp_path / "clip.mp4"

    def run(cmd, timeout):
        out.write_bytes(b"half a clip")
        return subprocess.CompletedProcess(cmd, 1, "", "warming up\nUnknown encoder 'libx264'\n")

    monkeypatch.setattr(tools, "_run", run)
    with pytest.raises(clips.ClipError, match="Unknown encoder"):
        tools.make_card_clip(tmp_path / "card.png", out)
    assert not out.exists()


def test_the_first_complaint_is_the_reason():
    assert clips.why_failed("ffmpeg version 8\n[in#0/gdigrab @ 01] Failed to capture image (error 5)\n"
                            "Error opening output files: Invalid argument\n") == "Failed to capture image (error 5)"
    assert clips.why_failed("one\ntwo\n") == "two" and clips.why_failed("") == ""


def test_missing_ffmpeg_says_where_to_put_it(monkeypatch):
    monkeypatch.setattr(clips, "_find_ffmpeg", lambda hint: (None, None))
    with pytest.raises(clips.ClipError, match="ffmpeg not found"):
        clips.find_tools(Config())


# ─── Windows sound and input, without Windows ────────────────────────────────

def _wave(tag, channels, rate, bits, sub=None):
    block = channels * bits // 8
    head = struct.pack("<HHIIHH", tag, channels, rate, rate * block, block, bits)
    if sub is None:
        return head + struct.pack("<H", 0)
    return head + struct.pack("<HHI", 22, bits, 3) + struct.pack("<H", sub) + bytes(14)


@pytest.mark.parametrize("wave, want", [
    (_wave(3, 2, 48000, 32), ("f32le", 48000, 2, 8)),
    (_wave(1, 2, 44100, 16), ("s16le", 44100, 2, 4)),
    (_wave(0xFFFE, 2, 48000, 32, sub=3), ("f32le", 48000, 2, 8)),
    (_wave(0xFFFE, 6, 48000, 24, sub=1), ("s24le", 48000, 6, 18)),
])
def test_sound_formats(wave, want):
    assert _loopback.sample_format(wave) == want


def test_unknown_sound_formats_are_refused():
    with pytest.raises(_loopback.SoundError):
        _loopback.sample_format(_wave(0x55, 2, 44100, 16))
    with pytest.raises(_loopback.SoundError):
        _loopback.sample_format(struct.pack("<HHIIHHH", 1, 2, 44100, 0, 3, 16, 0))


def test_silence_is_padded_only_when_it_is_really_missing():
    assert _loopback.missing_frames(1.0, 48000, 47000) == 0      # a late packet
    assert _loopback.missing_frames(2.0, 48000, 48000) == 48000  # nothing played for a second
    assert _loopback.missing_frames(1.0, 48000, 60000) == 0


def _raw(kind, device, body, pointer=8):
    head = struct.pack("<II", kind, 0) + struct.pack("<QQ" if pointer == 8 else "<II", device, 0)
    return head + body


@pytest.mark.parametrize("pointer", [4, 8])
def test_only_a_person_counts_as_using_the_pc(pointer):
    key = struct.pack("<4HII", 0x1E, 0, 0, 0x41, 0x100, 0)
    released = struct.pack("<4HII", 0x1E, 1, 0, 0x41, 0x101, 0)
    click = struct.pack("<HHHHIiiI", 0, 0, 0x0001, 0, 0, 0, 0, 0)
    moved = struct.pack("<HHHHIiiI", 0, 0, 0, 0, 0, 40, -3, 0)
    source = _win32.raw_input_source
    assert source(_raw(1, 0x10, key, pointer), pointer) == "keyboard"
    assert source(_raw(0, 0x10, click, pointer), pointer) == "mouse"
    assert source(_raw(1, 0, key, pointer), pointer) == ""          # sent by a program
    assert source(_raw(1, 0x10, released, pointer), pointer) == ""
    assert source(_raw(0, 0x10, moved, pointer), pointer) == ""     # light guns move by themselves
    assert source(b"\x01", pointer) == ""


@pytest.mark.skipif(sys.platform != "win32", reason="Windows calls")
def test_the_real_windows_calls_answer(tmp_path):
    assert _win32.idle_seconds() >= 0 and _win32.monitor_count() >= 0
    _win32.keep_display_on(True)
    _win32.keep_display_on(False)
    watcher = _win32.InputWatcher()
    assert watcher.used in ("", "keyboard", "mouse")
    watcher.close()
    assert not watcher.watching
    sound = _loopback.LoopbackRecorder(tmp_path / "s.raw")  # a PC may have no sound device
    started = sound.start()
    sound.stop()
    assert started == (not sound.error) and (started is False or sound.rate > 0)


@pytest.mark.skipif(sys.platform == "win32", reason="what happens off Windows")
def test_off_windows_it_says_so(tmp_path):
    for call in (_win32.idle_seconds, _win32.monitor_count, _win32.InputWatcher):
        with pytest.raises(_win32.UnsupportedPlatform):
            call()
    sound = _loopback.LoopbackRecorder(tmp_path / "s.raw")
    assert not sound.start() and "Windows" in sound.error


# ─── the real ffmpeg, where there is one ──────────────────────────────────────

_FFMPEG = shutil.which("ffmpeg")
real = pytest.mark.skipif(not (_FFMPEG and shutil.which("ffprobe")), reason="ffmpeg isn't installed")


def _made(tmp_path, source, name, seconds=4) -> Path:
    out = tmp_path / name
    subprocess.run([_FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", source, "-t", str(seconds),
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out)], check=True)
    return out


@real
def test_real_takes_are_judged(tmp_path):
    tools = clips.Tools(_FFMPEG, shutil.which("ffprobe"))
    moving = tools.analyse(_made(tmp_path, "testsrc2=s=960x720:r=30,pad=1280:720:160:0:black", "m.mkv"))
    assert moving.verdict == "" and clips.choose_crop("auto", moving) == (960, 720, 160, 0)
    assert tools.analyse(_made(tmp_path, "color=black:s=1280x720:r=30", "b.mkv")).is_black
    frozen = tools.analyse(_made(tmp_path, "smptebars=s=1280x720:r=30", "f.mkv"))
    assert frozen.is_frozen and not frozen.is_black
    # A handheld's small screen on black: 1.6% of the take is lit, and it moves.
    small = tools.analyse(_made(tmp_path, "testsrc2=s=120x120:r=30,pad=1280:720:580:300:black", "h.mkv"))
    assert small.verdict == "" and not small.is_black
    # A pinball's ball, one 12x12 LED crossing black: 0.016% of the take.
    ball = tools.analyse(_made(tmp_path, "color=black:s=1280x720:r=30[b];color=white:s=12x12:r=30[d];"
                                         "[b][d]overlay=x='mod(t*200,1200)':y=300[out0]", "p.mkv"))
    assert ball.verdict == "" and not ball.is_black
    # A score line on black above the game: cropdetect would cut it off, the brightest picture doesn't.
    scored = tools.analyse(_made(tmp_path, "testsrc2=s=640x600:r=30,pad=640:720:0:120:black,"
                                           "drawbox=x=300:y=10:w=40:h=6:color=white:t=fill,"
                                           "pad=1280:720:320:0:black", "s.mkv"))
    if " lagfun " in (tools._filters or ""):
        w, h, x, y = scored.crop
        assert y <= 10 and y + h >= 700 and 300 <= x <= 320 and 640 <= w <= 680
    assert not list(tmp_path.glob("*.pgm"))
    assert tools.analyse(tmp_path / "missing.mkv").verdict == "nothing was recorded"


@real
def test_real_clips_have_the_right_format(tmp_path):
    tools = clips.Tools(_FFMPEG, shutil.which("ffprobe"))
    take = _made(tmp_path, "testsrc2=s=960x720:r=30,pad=1280:720:160:0:black", "m.mkv")
    raw = tmp_path / "s.raw"
    subprocess.run([_FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:r=48000", "-t", "5",
                    "-af", "volume=-10dB", "-f", "f32le", "-ac", "2", str(raw)], check=True)
    sound = clips.SoundFile(raw, "f32le", 48000, 2)
    mean, peak = tools.volume(sound, 0.5, 4)
    out = tools.make_clip(take, tmp_path / "clip.mp4", crop=(960, 720, 160, 0), sound=sound,
                          sound_skip=0.5, gain=clips.gain_db(mean, peak))
    probe = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_entries",
                            "stream=codec_name,profile,width,height,pix_fmt", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True).stdout
    assert "h264,Main,640,480" in probe and "yuv420p" in probe and "aac" in probe
    done = tools._run([_FFMPEG, "-nostdin", "-i", str(out), "-af", "volumedetect", "-f", "null", "-"], 60)
    assert abs(clips.parse_analysis(done.stderr).mean_db - clips.MEAN_DB) < 1.5
    still = tools.make_still(take, tmp_path / "still.png", crop=(960, 720, 160, 0))
    assert still.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
