#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.research_scoreboard import (
    ResearchScoreRules,
    render_scoreboard_markdown,
    score_freqtrade_backtest,
)


def main() -> int:
    result_zip = _latest_backtest_zip(
        ROOT / "freqtrade_lab" / "user_data" / "backtest_results"
    )
    report_path = ROOT / "reports" / "freqtrade_lesson_05_research_scoreboard.md"
    rules = ResearchScoreRules()
    backtest = _load_freqtrade_backtest(result_zip)
    scores = score_freqtrade_backtest(backtest, rules)
    generated_at_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_scoreboard_markdown(
            scores=scores,
            rules=rules,
            source_name=str(result_zip.relative_to(ROOT)),
            generated_at_ms=generated_at_ms,
        ),
        encoding="utf-8",
    )

    print("OKX Lesson 16: research scoreboard")
    print("safety:       public data only, no API keys, no orders submitted.")
    print(f"source:       {result_zip}")
    print(f"report:       {report_path}")
    print()
    for score in scores:
        print(
            f"{score.decision:<6} {score.strategy:<18} "
            f"return={score.return_pct:>6.2f}% "
            f"pf={score.profit_factor:>4.2f} "
            f"dd={score.max_drawdown_pct:>4.2f}% "
            f"pairs={score.profitable_pairs}/{score.total_pairs}"
        )
    print()
    print("Lesson: a strategy needs to pass rules, not merely look best in a table.")
    return 0


def _latest_backtest_zip(backtest_dir: Path) -> Path:
    files = sorted(
        backtest_dir.glob("backtest-result-*.zip"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError(f"no Freqtrade backtest zip files found in {backtest_dir}")
    return files[0]


def _load_freqtrade_backtest(result_zip: Path) -> dict:
    with ZipFile(result_zip) as archive:
        json_names = [
            name
            for name in archive.namelist()
            if name.endswith(".json") and "_config" not in name
        ]
        if not json_names:
            raise ValueError(f"no backtest JSON found in {result_zip}")
        with archive.open(json_names[0]) as handle:
            return json.load(handle)


if __name__ == "__main__":
    raise SystemExit(main())
