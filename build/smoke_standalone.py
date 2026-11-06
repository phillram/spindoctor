"""Smoke-test the standalone Windows EXEs, each copied alone into an empty folder.

Usage: python build/smoke_standalone.py DIST_DIR
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
DIST = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "dist"
ASSETS = ROOT / "spindoctor" / "assets"
sys.path.insert(0, str(ROOT))
from spindoctor._runtime import _child_pids, stop_worker  # noqa: E402

work = Path(tempfile.mkdtemp(prefix="v3-smoke-"))
results = {}


def isolate(name):
    folder = work / f"only-{name}"
    folder.mkdir()
    exe = folder / f"{name}.exe"
    shutil.copy2(DIST / f"{name}.exe", exe)
    return exe


def make_home(label):
    home = work / f"home-{label}"
    hs, roms, rl = home / "hs", home / "roms", home / "rl"
    for d in (hs / "Databases" / "Main Menu", roms, rl, home / ".spindoctor"):
        d.mkdir(parents=True)
    (hs / "Databases" / "Main Menu" / "Main Menu.xml").write_text("<menu/>", encoding="utf-8")
    (home / ".spindoctor" / "config.json").write_text(json.dumps({
        "hyperspin_dir": str(hs), "roms_dir": str(roms), "rocketlauncher_dir": str(rl),
    }), encoding="utf-8")
    # Strip PATH of anything SpinDoctor-ish so nothing can be found there.
    env = dict(os.environ, USERPROFILE=str(home), HOME=str(home), PYTHONIOENCODING="utf-8",
               PATH=os.environ.get("SystemRoot", r"C:\Windows") + r"\System32")
    return hs, env


def run(label, argv, env, expect=0, needle=None, cwd=None):
    r = subprocess.run([str(a) for a in argv], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=180, env=env, cwd=cwd, stdin=subprocess.DEVNULL)
    out = r.stdout + r.stderr
    ok = r.returncode == expect and (needle is None or needle in out)
    results[label] = {"exit": r.returncode, "ok": ok, "tail": out.strip()[-300:]}
    print(f"{'PASS' if ok else 'FAIL'} {label}: exit {r.returncode}", flush=True)
    if not ok:
        print(out[-2000:], flush=True)
    return out


def check_media(hs, label, wheel):
    video = hs / "Media" / "Main Menu" / "Video" / f"{wheel}.mp4"
    ok = video.exists() and video.read_bytes() == (ASSETS / f"video_{wheel}.mp4").read_bytes()
    results[label] = {"ok": ok}
    print(f"{'PASS' if ok else 'FAIL'} {label}", flush=True)


for name in ("spindoctor-cli", "spindoctor"):
    exe = isolate(name)
    hs, env = make_home(name)
    pre = [exe] if name == "spindoctor-cli" else [exe, "--run-tool", "spindoctor"]
    run(f"{name}: --version", [exe, "--version"], env, needle="version")
    run(f"{name}: cli --version", pre + ["--version"], env, needle="version")
    for tool in ("spindoctor-fav", "spindoctor-recent", "spindoctor-stats"):
        run(f"{name}: {tool} --help", [exe, "--run-tool", tool, "--help"], env, needle="usage")
    run(f"{name}: unknown tool", [exe, "--run-tool", "calc"], env, expect=2, needle="Unknown")
    run(f"{name}: bad cli command exit code", pre + ["no-such-command"], env, expect=2)
    run(f"{name}: mainmenu add Favorites", pre + ["mainmenu", "add", "Favorites", "--apply"], env)
    check_media(hs, f"{name}: embedded Favorites media installed", "Favorites")
    (hs / "Media" / "Main Menu" / "Video" / "Favorites.mp4").unlink()
    run(f"{name}: fav rebuild worker", [exe, "--run-tool", "spindoctor-fav", "rebuild", "--apply"], env)
    check_media(hs, f"{name}: fav worker reinstalled media", "Favorites")
    # Generated-BAT pattern: cmd must wait for the (possibly windowed) worker,
    # see its output and propagate its exit code.
    bat = exe.parent / "t.bat"
    bat.write_text(
        "@echo off\r\n"
        f'start "" /B /WAIT "{exe}" --run-tool spindoctor --version\r\n'
        "if errorlevel 1 exit /b 9\r\n"
        f'start "" /B /WAIT "{exe}" --run-tool calc\r\n'
        "exit /b %errorlevel%\r\n", encoding="utf-8")
    run(f"{name}: bat waits + propagates exit", ["cmd", "/c", bat], env, expect=2, needle="version")
    if name == "spindoctor":
        gui = subprocess.Popen([str(exe)], env=env)
        time.sleep(20)
        alive = gui.poll() is None
        stop_worker(gui, timeout=30)
        results["spindoctor: window stays open"] = {"ok": alive}
        print(f"{'PASS' if alive else 'FAIL'} spindoctor: window stays open", flush=True)
    # Stop must end the real worker behind the one-file launcher, and the
    # launcher must then remove its temporary extraction folder.
    temp = Path(tempfile.gettempdir())
    before = {p.name for p in temp.glob("_MEI*")}
    worker = subprocess.Popen([str(a) for a in pre + ["config", "init"]], stdin=subprocess.PIPE,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    time.sleep(10)
    stop_worker(worker, timeout=30)
    time.sleep(2)
    orphans = _child_pids(worker.pid, exe.name)
    leaked = sorted({p.name for p in temp.glob("_MEI*")} - before)
    ok = worker.poll() is not None and not orphans and not leaked
    results[f"{name}: Stop ends worker and cleans up"] = {"ok": ok, "orphans": orphans, "leaked": leaked}
    print(f"{'PASS' if ok else 'FAIL'} {name}: Stop ends worker and cleans up {orphans} {leaked}", flush=True)
    leftovers = sorted(p.name for p in exe.parent.iterdir() if p.name not in (exe.name, "t.bat"))
    results[f"{name}: no files created beside exe"] = {"ok": not leftovers, "extra": leftovers}
    print(f"{'FAIL' if leftovers else 'PASS'} {name}: no files beside exe {leftovers}", flush=True)

sizes = {p.name: p.stat().st_size for p in DIST.glob("*.exe")}
results["sizes"] = sizes
print(json.dumps(results, indent=2))
shutil.rmtree(work, ignore_errors=True)
failed = [k for k, v in results.items() if isinstance(v, dict) and v.get("ok") is False]
print("SIZES", sizes)
print("FAILED", failed)
raise SystemExit(1 if failed else 0)
