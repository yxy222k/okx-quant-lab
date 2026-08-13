"""Atomic persistence with schema versioning for the lab's state files.

Every state writer in the package goes through save_text_atomic: the tmp +
os.replace dance means a crash or a concurrent reader never sees a torn
file, and the rename is the single commit point.

Versioning contract: JSON state dicts carry a "schema_version" key. Files
written before versioning existed have none and load as version 0. Loaders
pass their current version plus optional per-step migrations {from_version:
fn}; missing steps are treated as additive changes (the dataclass loaders
already default missing fields via .get) — the backfill_deploy_ts.py
one-shot script is the failure mode this replaces.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

SCHEMA_KEY = "schema_version"


def save_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def save_json_atomic(path: Path, obj, schema_version: int | None = None) -> None:
    """Serialize BEFORE touching the file, so a non-serializable payload can
    never destroy the previous good state."""
    if schema_version is not None:
        if not isinstance(obj, dict):
            raise TypeError("schema_version requires a dict payload")
        obj = {SCHEMA_KEY: schema_version, **obj}
    save_text_atomic(path, json.dumps(obj, indent=2))


def load_versioned_json(
    path: Path,
    current_version: int,
    migrations: dict[int, Callable[[dict], dict]] | None = None,
) -> dict:
    """Load a state dict, stepping legacy versions up through `migrations`.

    The schema_version key is stripped from the returned dict. A file newer
    than current_version is refused outright — silently reading half-understood
    state is how positions get corrupted.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object; wrap legacy payloads before loading")
    version = int(data.pop(SCHEMA_KEY, 0))
    if version > current_version:
        raise ValueError(
            f"{path} has schema_version {version}, newer than supported {current_version}"
        )

    migrations = migrations or {}
    while version < current_version:
        migrate = migrations.get(version)
        if migrate is None:
            # Additive change: loaders default the missing fields themselves.
            break
        data = migrate(data)
        version += 1
    return data


def save_ledger_atomic(path: Path, rows: list, schema_version: int = 1) -> None:
    """Ledgers are lists; wrap them so they can carry a schema version."""
    save_json_atomic(path, {"orders": rows}, schema_version=schema_version)


def load_ledger(path: Path) -> list:
    """Read a ledger written by save_ledger_atomic, or a legacy bare list."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):  # pre-versioning format
        return data
    return data["orders"]
