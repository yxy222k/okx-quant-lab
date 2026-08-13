from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.okx_demo_private import load_demo_credentials, sign


class DemoCredentialsTest(unittest.TestCase):
    def test_loads_valid_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.env"
            path.write_text(
                "# demo keys\n"
                "OKX_DEMO_API_KEY=key-123\n"
                "OKX_DEMO_SECRET_KEY=secret-456\n"
                "OKX_DEMO_PASSPHRASE=phrase\n",
                encoding="utf-8",
            )
            os.chmod(path, 0o600)

            credentials = load_demo_credentials(path)

        self.assertEqual(credentials.api_key, "key-123")
        self.assertEqual(credentials.secret_key, "secret-456")
        self.assertEqual(credentials.passphrase, "phrase")
        self.assertNotIn("key-123", credentials.masked_api_key)

    def test_rejects_loose_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.env"
            path.write_text(
                "OKX_DEMO_API_KEY=k\nOKX_DEMO_SECRET_KEY=s\nOKX_DEMO_PASSPHRASE=p\n",
                encoding="utf-8",
            )
            os.chmod(path, 0o644)

            with self.assertRaises(ValueError):
                load_demo_credentials(path)

    def test_rejects_missing_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.env"
            path.write_text("OKX_DEMO_API_KEY=k\n", encoding="utf-8")
            os.chmod(path, 0o600)

            with self.assertRaises(ValueError):
                load_demo_credentials(path)

    def test_rejects_missing_file(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_demo_credentials(Path("/nonexistent/demo.env"))


class SignatureTest(unittest.TestCase):
    def test_known_vector(self) -> None:
        signature = sign(
            secret_key="test-secret",
            timestamp="2026-01-01T00:00:00.000Z",
            method="GET",
            request_path="/api/v5/account/balance",
            body="",
        )

        self.assertEqual(signature, "qBkeiZJMgNXh3uuH2hnMO3K171nVvIz4R+enCDNli6o=")

    def test_signature_changes_with_inputs(self) -> None:
        base = sign("secret", "ts", "GET", "/path", "")
        self.assertNotEqual(base, sign("other", "ts", "GET", "/path", ""))
        self.assertNotEqual(base, sign("secret", "ts", "POST", "/path", ""))
        self.assertNotEqual(base, sign("secret", "ts", "GET", "/path", '{"a":1}'))


if __name__ == "__main__":
    unittest.main()
