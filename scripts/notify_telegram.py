#!/usr/bin/env python3
"""Forward stdin to Telegram — the delivery step Hermes used to do for cron.

Sends only when stdin has non-blank content, so a quiet --watchdog run sends
nothing. Long text is split at Telegram's 4096-character message limit.
Never fails the cron line: problems go to stderr (the log) and exit 0.

Config: ~/.config/okx/telegram.env (mode 600) with TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import stat
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_ENV_PATH = Path.home() / ".config" / "okx" / "telegram.env"
MAX_MESSAGE = 4096


def load_config(path: Path = DEFAULT_ENV_PATH) -> tuple[str, str]:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise ValueError(f"{path} is readable by group/others (mode {oct(mode)}); chmod 600 it")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip()
    return values["TELEGRAM_BOT_TOKEN"], values["TELEGRAM_CHAT_ID"]


def split_message(text: str, limit: int = MAX_MESSAGE) -> list[str]:
    """Chunks of at most `limit` chars, breaking at line ends where possible."""
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:  # a single over-long line: hard split
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            chunks.append(current)
            current = ""
        current += line
    if current.strip():
        chunks.append(current)
    return [chunk.rstrip("\n") for chunk in chunks]


def send(token: str, chat_id: str, text: str, attempts: int = 3) -> None:
    # The token is part of the URL: never let it reach an error message.
    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=urlencode({"chat_id": chat_id, "text": text,
                        "disable_web_page_preview": "true"}).encode("utf-8"),
        method="POST",
    )
    last = ""
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("ok"):
                return
            last = f"API error: {payload.get('description')}"
        except HTTPError as error:
            last = f"HTTP {error.code}"
            if error.code != 429 and error.code < 500:
                break
        except (TimeoutError, URLError, OSError) as error:
            last = type(error).__name__
        if attempt < attempts - 1:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"telegram send failed: {last}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prefix", default="", help="first line of every message, e.g. [grid]")
    args = parser.parse_args()

    text = sys.stdin.read()
    if not text.strip():
        return 0
    try:
        token, chat_id = load_config()
        for chunk in split_message(text.strip("\n"), MAX_MESSAGE - len(args.prefix) - 1):
            send(token, chat_id, f"{args.prefix}\n{chunk}" if args.prefix else chunk)
    except Exception as error:  # delivery must never break the cron line
        print(f"notify_telegram: {type(error).__name__}: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
