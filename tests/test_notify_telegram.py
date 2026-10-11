from __future__ import annotations

import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import notify_telegram as mod


class SplitMessageTest(unittest.TestCase):
    def test_short_text_is_one_chunk(self) -> None:
        self.assertEqual(mod.split_message("a\nb\n", limit=100), ["a\nb"])

    def test_breaks_at_line_ends_within_the_limit(self) -> None:
        text = "".join(f"line {i:02d}\n" for i in range(10))  # 8 chars per line
        chunks = mod.split_message(text, limit=20)
        self.assertTrue(all(len(chunk) <= 20 for chunk in chunks))
        self.assertEqual("\n".join(chunks), text.rstrip("\n"))

    def test_over_long_line_is_hard_split(self) -> None:
        chunks = mod.split_message("x" * 25, limit=10)
        self.assertEqual(chunks, ["x" * 10, "x" * 10, "x" * 5])


class MainTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sent: list = []
        originals = (mod.send, mod.load_config, sys.stdin, sys.argv)
        mod.send = lambda token, chat_id, text: self.sent.append(text)
        mod.load_config = lambda: ("token", "chat")

        def restore():
            mod.send, mod.load_config, sys.stdin, sys.argv = originals
        self.addCleanup(restore)

    def _main(self, stdin: str, *argv: str) -> int:
        sys.stdin = io.StringIO(stdin)
        sys.argv = ["notify_telegram.py", *argv]
        return mod.main()

    def test_blank_input_sends_nothing(self) -> None:
        self.assertEqual(self._main("  \n\n"), 0)
        self.assertEqual(self.sent, [])

    def test_prefix_heads_the_message(self) -> None:
        self._main("BTC-USDT: BUY ... FILLED\n", "--prefix", "[grid]")
        self.assertEqual(self.sent, ["[grid]\nBTC-USDT: BUY ... FILLED"])

    def test_send_failure_never_fails_the_cron_line(self) -> None:
        def boom(token, chat_id, text):
            raise RuntimeError("telegram send failed: HTTP 502")
        mod.send = boom
        stderr, sys.stderr = sys.stderr, io.StringIO()
        try:
            self.assertEqual(self._main("something happened"), 0)
            self.assertIn("HTTP 502", sys.stderr.getvalue())
        finally:
            sys.stderr = stderr


if __name__ == "__main__":
    unittest.main()
