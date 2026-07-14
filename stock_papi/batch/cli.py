"""Stock Papi 本機批次狀態 CLI。"""

import argparse
import json
from pathlib import Path

from stock_papi.batch.runtime import JOB_TYPES, job_namespace


def render_status(root):
    rows = []
    for job_type in JOB_TYPES:
        path = job_namespace(root, job_type).status
        if not path.exists():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rows.append(f"{job_type}: INVALID")
            continue
        details = document.get("details") if isinstance(document.get("details"), dict) else {}
        date_value = details.get("report_date") or details.get("source_market_date") or document.get("target_date")
        error = document.get("error") or "-"
        rows.append(
            f"{job_type}: stage={document.get('stage', 'unknown')} "
            f"date={date_value or '-'} error={error}"
        )
    return "\n".join(rows) if rows else "尚無 pipeline status。"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Stock Papi batch operations")
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("status", help="顯示所有 batch job 狀態")
    status.add_argument("--root", default=r"D:\StockPapiData")
    args = parser.parse_args(argv)
    if args.command == "status":
        print(render_status(Path(args.root)))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
