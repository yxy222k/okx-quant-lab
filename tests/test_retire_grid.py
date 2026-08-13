from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import io
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from okx_quant_lab.demo_grid import (
    DemoGridConfig,
    load_demo_grid_state,
    new_demo_grid_state,
    save_demo_grid_state,
)


STAMP_PATTERN = re.compile(r"\.retired\.(\d{8}T\d{6}Z)$")


def _forbidden(name: str):
    def _fail(*args, **kwargs):
        raise AssertionError(f"unexpected network-path call: {name}")

    return _fail


class _TickingDateTime:
    """Stand-in for retire_grid.datetime: now() yields pre-seeded instants.

    Lets the rerun test guarantee two DISTINCT second-resolution stamps even
    though both main() calls happen within the same wall-clock second.
    """

    _instants = iter(())

    @classmethod
    def seed(cls, instants) -> None:
        cls._instants = iter(instants)

    @classmethod
    def now(cls, tz=None):
        return next(cls._instants)


class RetireGridArchiveTest(unittest.TestCase):
    def _run_main(self, retire_grid, state_path: Path, ledger_path: Path) -> int:
        """Run retire_grid.main() with argv patched and network paths fenced."""
        argv = ["retire_grid.py", str(state_path), str(ledger_path)]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(
            retire_grid, "load_demo_credentials", _forbidden("load_demo_credentials")
        ), mock.patch.object(
            retire_grid, "fetch_instrument_spec", _forbidden("fetch_instrument_spec")
        ), mock.patch.object(
            retire_grid, "fetch_ticker", _forbidden("fetch_ticker")
        ), contextlib.redirect_stdout(io.StringIO()):
            return retire_grid.main()

    def test_archive_name_is_timestamped_and_state_preserved(self) -> None:
        import retire_grid

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "grid_state.json"
            ledger_path = Path(tmp) / "ledger.json"
            state = new_demo_grid_state(DemoGridConfig(), reference_price=100.0)
            self.assertEqual(sum(state.holdings), 0.0)  # precondition: no liquidation
            save_demo_grid_state(state_path, state)

            before = datetime.now(timezone.utc).replace(microsecond=0)
            rc = self._run_main(retire_grid, state_path, ledger_path)
            after = datetime.now(timezone.utc)

            self.assertEqual(rc, 0)
            self.assertFalse(state_path.exists(), "original state file must be gone")
            self.assertFalse(
                ledger_path.exists(), "zero holdings must not touch the ledger"
            )

            archives = [
                path
                for path in Path(tmp).iterdir()
                if ".retired." in path.name
            ]
            self.assertEqual(len(archives), 1)
            archive = archives[0]
            self.assertTrue(archive.name.startswith("grid_state.json.retired."))

            match = STAMP_PATTERN.search(archive.name)
            self.assertIsNotNone(match, f"no UTC stamp in {archive.name!r}")
            stamped = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(
                tzinfo=timezone.utc
            )
            self.assertGreaterEqual(stamped, before)
            self.assertLessEqual(stamped, after)

            # The archive is the intact state file, just renamed.
            archived = load_demo_grid_state(archive)
            self.assertEqual(archived.levels, state.levels)
            self.assertEqual(archived.cash, state.cash)

    def test_rerun_creates_second_archive_without_clobbering_first(self) -> None:
        import retire_grid

        first_instant = datetime(2026, 8, 13, 0, 0, 1, tzinfo=timezone.utc)
        second_instant = datetime(2026, 8, 13, 0, 0, 2, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "grid_state.json"
            ledger_path = Path(tmp) / "ledger.json"

            # Two distinguishable states: different reference prices give
            # different level ladders, so clobbering would be detectable.
            state_a = new_demo_grid_state(DemoGridConfig(), reference_price=100.0)
            state_b = new_demo_grid_state(DemoGridConfig(), reference_price=200.0)
            self.assertNotEqual(state_a.levels, state_b.levels)

            with mock.patch.object(retire_grid, "datetime", _TickingDateTime):
                _TickingDateTime.seed([first_instant, second_instant])

                save_demo_grid_state(state_path, state_a)
                self.assertEqual(self._run_main(retire_grid, state_path, ledger_path), 0)

                # Redeploy: a fresh state file appears at the same path, then
                # gets retired too. Before timestamping, the plain rename would
                # silently overwrite the first archive (POSIX rename semantics).
                save_demo_grid_state(state_path, state_b)
                self.assertEqual(self._run_main(retire_grid, state_path, ledger_path), 0)

            archives = sorted(
                path for path in Path(tmp).iterdir() if ".retired." in path.name
            )
            self.assertEqual(
                len(archives), 2, "second retirement must not clobber the first archive"
            )
            self.assertEqual(
                [path.name for path in archives],
                [
                    "grid_state.json.retired.20260813T000001Z",
                    "grid_state.json.retired.20260813T000002Z",
                ],
            )

            # Each archive still holds the state it was created from.
            self.assertEqual(load_demo_grid_state(archives[0]).levels, state_a.levels)
            self.assertEqual(load_demo_grid_state(archives[1]).levels, state_b.levels)
            self.assertFalse(state_path.exists())


if __name__ == "__main__":
    unittest.main()
