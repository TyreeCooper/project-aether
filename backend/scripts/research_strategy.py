"""Run Aether long-history strategy research from the command line."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.research import build_research_report, save_report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--symbol", default="BTCUSD")
    parser.add_argument("--output", default="strategy-research.json")
    args = parser.parse_args()

    report = asyncio.run(
        build_research_report(days=max(3, args.days), symbol=args.symbol)
    )
    output = Path(args.output)
    save_report(report, output)

    print(json.dumps({
        "output": str(output),
        "data_quality": report.get("data_quality"),
        "strategies": report.get("strategies"),
        "walk_forward_v3": report.get("walk_forward_v3"),
    }, indent=2))


if __name__ == "__main__":
    main()
