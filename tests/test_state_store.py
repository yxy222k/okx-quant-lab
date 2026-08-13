from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.state_store import (
    load_ledger,
    load_versioned_json,
    save_json_atomic,
    save_ledger_atomic,
    save_text_atomic,
)


class AtomicWriteTest(unittest.TestCase):
    def test_failed_save_leaves_previous_file_intact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            save_json_atomic(path, {"cash": 100.0}, schema_version=1)

            with self.assertRaises(TypeError):
                save_json_atomic(path, {"bad": object()}, schema_version=1)

            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["cash"], 100.0)
            self.assertEqual(list(Path(tmp).iterdir()), [path])  # tmp file cleaned up

    def test_save_creates_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deep" / "nested" / "state.json"
            save_text_atomic(path, "hello")
            self.assertEqual(path.read_text(encoding="utf-8"), "hello")

    def test_schema_version_requires_dict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TypeError):
                save_json_atomic(Path(tmp) / "x.json", [1, 2], schema_version=1)


class VersionedLoadTest(unittest.TestCase):
    def test_roundtrip_strips_schema_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            save_json_atomic(path, {"cash": 5.0}, schema_version=1)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["schema_version"], 1)

            data = load_versioned_json(path, current_version=1)
            self.assertEqual(data, {"cash": 5.0})

    def test_legacy_file_without_version_loads_as_version_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(json.dumps({"cash": 7.0}), encoding="utf-8")
            data = load_versioned_json(path, current_version=1)
            self.assertEqual(data, {"cash": 7.0})

    def test_migration_steps_run_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(json.dumps({"cash": 7.0}), encoding="utf-8")
            data = load_versioned_json(
                path,
                current_version=2,
                migrations={
                    0: lambda d: {**d, "deploy_timestamp_ms": 0},
                    1: lambda d: {**d, "note": "v2"},
                },
            )
            self.assertEqual(
                data, {"cash": 7.0, "deploy_timestamp_ms": 0, "note": "v2"}
            )

    def test_newer_file_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(
                json.dumps({"schema_version": 99, "cash": 1.0}), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                load_versioned_json(path, current_version=1)


class LedgerFormatTest(unittest.TestCase):
    def test_ledger_roundtrip_and_legacy_bare_list(self) -> None:
        rows = [{"id": "a"}, {"id": "b"}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            save_ledger_atomic(path, rows)
            self.assertEqual(load_ledger(path), rows)

            legacy = Path(tmp) / "legacy.json"
            legacy.write_text(json.dumps(rows), encoding="utf-8")
            self.assertEqual(load_ledger(legacy), rows)


if __name__ == "__main__":
    unittest.main()
