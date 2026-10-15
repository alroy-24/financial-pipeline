"""Stand in for Power Automate: copy report files into the landing folder with a date in front.

Useful for trying the pipeline before the flow is set up, or for replaying a day.

    python tools/simulate_delivery.py ../Data "C:/Users/you/OneDrive/FinancialReports"
    python tools/simulate_delivery.py ../Data landing --date 2026-10-04 --only 24   # an incomplete day
"""

import argparse
import shutil
from datetime import date
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path, help="folder with the day's .csv/.xlsx report files")
    parser.add_argument("landing", type=Path, help="the landing folder the loader reads")
    parser.add_argument("--date", type=date.fromisoformat, default=date.today(), help="arrival date (default: today)")
    parser.add_argument("--only", type=int, help="copy only the first N files")
    args = parser.parse_args()

    files = sorted(p for p in args.source.iterdir() if p.suffix.lower() in {".csv", ".xlsx"})[: args.only]
    args.landing.mkdir(parents=True, exist_ok=True)
    for path in files:
        shutil.copy2(path, args.landing / f"{args.date.isoformat()}_{path.name}")
    print(f"Copied {len(files)} file(s) into {args.landing} as {args.date.isoformat()}_<name>.")


if __name__ == "__main__":
    main()
