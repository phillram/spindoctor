# Testing

```text
python -m pip install -e ".[all,dev]"
python -m pip install pytest-xdist ruff
python -m pytest -q tests/test_backup.py
python -m ruff check .
git diff --check
```

Start with changed subsystems. For the Windows CI split:

```text
python -m pytest -q -n auto --ignore=tests/test_gui.py --durations=15
python -m pytest -q tests/test_gui.py --durations=15
```

For serial debugging: `python -m pytest -q --durations=15`.
Real Tk tests need a display; headless Linux CI uses Tk plus `xvfb-run -a`.
A run skipping GUI integration is not equivalent to display-enabled validation.
CI covers Linux Python 3.8/3.12, Windows 3.12 and a frozen Win7-compatible build.

## Isolation and useful coverage

- `tests/conftest.py` re-homes state before imports and blocks unexpected
  non-loopback DNS. Stub network clients and background starters explicitly.
- Use `config_home`, `isolated_config` or `config_home_factory` for per-test state;
  reset imported path aliases/override caches as needed.
- `tests.helpers.build_nes_library` saves config as well as sample files;
  request isolation first.
- Use small/sparse payloads and controlled clocks for retries/rate limits.
- Keep failure injection, collision, preservation, precedence and recovery cases.
  Parameterize shared setups without losing unique assertions.
- Dry-run tests need a nonempty actionable plan plus unchanged relevant bytes.
- Logic-only GUI tests can call real handlers on lightweight instances.
  Keep real Tk tests for construction, layout, events, traces, fonts and scrolling;
  do not share a mutable GUI across tests.

Compare timings with the same interpreter, workers, dependencies and display.
Build/install/smoke time is separate from pytest time; fewer collected tests
does not prove faster or better coverage.

## Documentation maintenance

```text
python scripts/generate_command_reference.py
python scripts/generate_command_reference.py --check
python -m pytest -q tests/test_documentation.py
```

The generator inspects Click definitions without executing command callbacks.
Documentation tests check the generated index, local links and all GUI screenshot
references. Regenerate every page image with the
[isolated Windows capture script](gui.md#refreshing-screenshots) after GUI changes.

For packaging, use the [standalone EXE smoke harness](../build/README.md).
It checks readiness and cleanup with bounded waits, not a long burn-in test.
