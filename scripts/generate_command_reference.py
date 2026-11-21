"""Generate the compact command index from Click without executing commands."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from spindoctor.cli import cli


INTRO = """# Command reference

Generated from the current CLI. Use `spindoctor <command> --help` for argument
types, defaults and full behavior; use the [cheatsheet](cli-cheatsheet.md) for recipes.
Windows binary users substitute `spindoctor-cli` for `spindoctor`.

## Safety

- Cabinet writers generally preview until `--apply`. Preview can still populate
  caches or write explicitly requested reports; it is not a filesystem sandbox.
- Settings and list commands can save immediately, including `config`, `ignore`,
  `match`, `fav add/remove/sync` and `emulator-title set`. Check their help.
- `install-tools` writes helper files even without `--apply`; the flag gates
  cabinet registration. Undo, restore, scheduling and live Toolkit actions have
  command-specific gates, not one universal Apply policy.
- Toolkit shutdown/restart, exit-to-Windows, resolution and LED-board reset are
  **live actions**, not dry runs. Shutdown/restart force-close Windows apps.
- `curate --action delete`, orphan-media deletion, scrub and cleanup can remove
  data. An Apply flag does not promise undo.
- Keep an independent backup. Multi-file changes are not transactions; Stop,
  crashes and power loss can leave partial work. See [recovery](workflows.md#recovery-from-mistakes).

## Commands

Each entry lists its summary and accepted option names. Subcommands are indented.
Options belong to the command on that line, not its children.

"""


def render() -> str:
    lines = [INTRO]

    def walk(command, names, depth=0):
        context = click.Context(command, info_name=names[-1])
        summary = " ".join((command.help or "").split("\n\n")[0].split())
        flags = [
            "/".join(param.opts + param.secondary_opts)
            for param in command.params if isinstance(param, click.Option)
        ]
        flags.append("--help")
        args = [
            param.human_readable_name for param in command.params
            if isinstance(param, click.Argument)
        ]
        title = " ".join(names + args)
        if depth == 0:
            lines.append("## `{}`\n\n{}\n".format(" ".join(names), summary))
            if args:
                lines.append("Arguments: {}.\n".format(", ".join("`" + a + "`" for a in args)))
            lines.append("Options: {}.\n".format(", ".join("`" + f + "`" for f in flags)))
        else:
            lines.append("{}- `{}`: {} Options: {}.".format(
                "  " * (depth - 1), title, summary,
                ", ".join("`" + f + "`" for f in flags),
            ))
        if isinstance(command, click.Group):
            for name in command.list_commands(context):
                child = command.get_command(context, name)
                if child is not None and not child.hidden:
                    walk(child, names + [name], depth + 1)
        if depth == 0:
            lines.append("")

    for name in cli.list_commands(click.Context(cli)):
        command = cli.get_command(click.Context(cli), name)
        if command is not None and not command.hidden:
            walk(command, [name])
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = Path(__file__).resolve().parent.parent / "docs" / "commands.md"
    content = render()
    if args.check:
        if target.read_text(encoding="utf-8") != content:
            parser.exit(1, "Command reference is stale; run scripts/generate_command_reference.py\n")
        print("Command reference matches the CLI.")
    else:
        target.write_text(content, encoding="utf-8")
        print("Updated docs/commands.md")


if __name__ == "__main__":
    main()
