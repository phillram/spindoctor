# Running and maintaining the tests

Install the project and test tools into a virtual environment:

```text
python -m pip install -e ".[all,dev]"
python -m pip install pytest-xdist ruff
```

## Feedback loops

Start with the files that own the behavior you changed:

```text
python -m pytest -q tests/test_backup.py
python -m ruff check .
```

For a complete serial run, including real Tk coverage:

```text
python -m pytest -q --durations=15
```

Windows CI runs non-GUI tests in parallel and GUI tests in the main
process. Use the same split locally:

```text
python -m pytest -q -n auto --ignore=tests/test_gui.py
python -m pytest -q tests/test_gui.py
```

On headless Linux, real Tk tests need a display. CI provides Tk and uses
`xvfb-run -a` around pytest. Do not treat a run that skips GUI integration
coverage as equivalent to a full display-enabled run.

Compare timings with the same interpreter, dependencies, display, and
worker count. Serial and parallel timings are different measurements.
Use pytest's duration report to distinguish fixture setup from test calls.

## Keep tests isolated and focused

- `tests/conftest.py` re-homes the process before importing SpinDoctor so
  tests cannot write into the developer's actual configuration directory.
  Tests that save configuration still need per-test isolation to avoid
  sharing state or override caches with neighboring tests.
- Request `config_home` when a test needs an isolated config directory
  path, or `isolated_config` when it only needs isolation. Neither creates
  the directory. Use `config_home_factory` for a custom root, and keep
  module-specific manifest paths and imported aliases in thin local
  adapters. The shared fixtures reset override caches on setup and teardown.
- `tests.helpers.build_nes_library` creates the same three-game on-disk
  library for editor and CLI tests. It also saves configuration, so callers
  must request config isolation first.
- The network guard rejects unexpected non-loopback DNS lookups. Stub the
  HTTP session or provider in tests that exercise network-facing code.
  Do not rely on a fake hostname failing to resolve: that adds delays and
  makes results depend on the machine's network.
- Stub background task starters when the task itself is outside a test's
  scope. Patching only a worker's callee can race with test teardown.
- Use small file payloads. When code only inspects file size, a truncated
  file can represent a large download without allocating a huge byte string.
- Test rate limiters and retry policies with controlled clocks. Other
  client tests should not pay real rate-limit or backoff delays.

## What to retain, consolidate, or move

Keep failure-injection, dry-run, preservation, collision, precedence, and
recovery cases even when their setup resembles a successful-path test.
Before deleting a duplicate, identify a keeper that exercises the same
entry point and transfer any unique assertions.

Use parametrization for cases with the same setup and assertions but
different inputs. Give cases descriptive IDs. Parametrization reduces
repeated code, not necessarily the number of collected tests; exposing
previously looped cases can increase that count.

Put regression tests beside their owning subsystem, not in a file named
after the PR or review that discovered them. Keep genuinely cross-operation
recovery contracts together.

Logic-only GUI tests should call real handlers on lightweight instances.
Retain real Tk coverage for construction, widget layout, button and event
wiring, variable traces, scrolling, text search, and font metrics. Avoid a
shared mutable GUI instance: saving construction time is not worth
order-dependent tests.

Dry-run tests need an actionable plan. Seed data that would actually move,
copy, or change under `--apply`, assert that the plan is nonempty, and compare
source, destination, and relevant configuration bytes before and after.
An unchanged filesystem proves little when there was nothing to do.
