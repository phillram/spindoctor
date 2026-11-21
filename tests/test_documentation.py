"""Keep current reference pages, local links and screenshot coverage aligned."""
import importlib.util
from pathlib import Path
import re
import shlex
from urllib.parse import unquote, urlsplit

import click

from spindoctor import gui
from spindoctor.cli import cli


ROOT = Path(__file__).resolve().parents[1]


def _generator():
    spec = importlib.util.spec_from_file_location(
        "command_reference", ROOT / "scripts" / "generate_command_reference.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _anchors(text):
    # GitHub heading slugs: punctuation removed, spaces become hyphens.
    result = set(re.findall(r'<a\s+id="([^"]+)"', text))
    counts = {}
    in_code = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        if in_code:
            continue
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*$", line)
        if match:
            title = re.sub(r"<[^>]*>", "", match[1]).lower()
            slug = re.sub(r"[^\w\- ]", "", title).replace(" ", "-")
            count = counts.get(slug, 0)
            counts[slug] = count + 1
            result.add(slug + ("-" + str(count) if count else ""))
    return result


def test_command_reference_is_current():
    assert (ROOT / "docs" / "commands.md").read_text(encoding="utf-8") == _generator().render()


def test_generator_never_calls_commands(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Documentation generation executed a command")

    monkeypatch.setattr(cli, "invoke", unexpected)
    result = _generator().render()
    assert "## `wheel-start`" in result
    assert "`ledblinky lwax cute`" in result
    assert "`toolkit idle-tour-settings`" in result


def test_cli_examples_use_current_commands_and_options():
    files = [ROOT / "README.md"] + sorted((ROOT / "docs").glob("*.md"))
    errors = []
    for source in files:
        if source.name in {"project-review.md", "commands.md"}:
            continue
        for line in source.read_text(encoding="utf-8").splitlines():
            if not line.startswith("spindoctor "):
                continue
            # Non-POSIX lexing preserves Windows path separators.
            args = [part.strip('"') for part in shlex.split(line, posix=False)][1:]
            command = cli
            while True:
                context = click.Context(command)
                try:
                    _, remaining, _ = command.make_parser(context).parse_args(args)
                except click.ClickException as error:
                    errors.append("{}: {}\n{}".format(source.name, line, error))
                    break
                if not isinstance(command, click.Group) or not remaining:
                    break
                name, *args = remaining
                command = command.get_command(context, name)
                if command is None:
                    errors.append("{}: unknown command in {}".format(source.name, line))
                    break
    assert not errors, "\n".join(errors)


def test_documentation_local_links():
    files = [ROOT / "README.md", ROOT / "build" / "README.md", ROOT / "scripts" / "README.md"]
    files += sorted((ROOT / "docs").glob("*.md"))
    files += [ROOT / "spindoctor" / "assets" / "archive" / "README.md"]
    files += sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md"))
    errors = []
    for source in files:
        text = source.read_text(encoding="utf-8")
        for target in re.findall(r"!?\[[^\]]*\]\(([^)\n]+)\)", text):
            url = urlsplit(target)
            if url.scheme or url.netloc:
                continue
            dest = (source.parent / unquote(url.path)).resolve() if url.path else source
            if not dest.exists():
                errors.append("{}: missing {}".format(source.relative_to(ROOT), target))
            elif url.fragment and dest.suffix == ".md":
                if unquote(url.fragment) not in _anchors(dest.read_text(encoding="utf-8")):
                    errors.append("{}: missing anchor {}".format(source.relative_to(ROOT), target))
    assert not errors, "\n".join(errors)


def test_every_gui_page_has_one_current_screenshot():
    pages = [page for _, group in gui._SIDEBAR_GROUPS for page in group]
    expected = {
        "{:02d}-{}.png".format(i, re.sub(r"[^a-z0-9]+", "-", page.lower()).strip("-"))
        for i, page in enumerate(pages, 1)
    }
    folder = ROOT / "docs" / "screenshots"
    assert {path.name for path in folder.glob("*.png")} == expected
    guide = (ROOT / "docs" / "gui.md").read_text(encoding="utf-8")
    for name in expected:
        assert guide.count("(screenshots/" + name + ")") == 1
        # IHDR is enough to ensure each committed file is a nonempty PNG.
        header = (folder / name).read_bytes()[:24]
        assert header[:8] == b"\x89PNG\r\n\x1a\n"
        assert int.from_bytes(header[16:20], "big") >= 720
        assert int.from_bytes(header[20:24], "big") >= 540
