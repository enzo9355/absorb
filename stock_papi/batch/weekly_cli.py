"""Publish a weekly model report only when promoted evidence has changed."""

import argparse
import datetime
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Stock Papi weekly model report")
    parser.add_argument("--root", type=Path, default=Path(r"D:\StockPapiData"))
    parser.add_argument("--calendar-artifact", type=Path, action="append", required=True)
    args = parser.parse_args(argv)

    from reporting.publisher import publish_report_v2
    from reporting.web import validate_report_index, validate_report_metadata
    from stock_papi.batch.backtest_store import BacktestStore
    from stock_papi.batch.calendar import TradingCalendarSet
    from stock_papi.batch.prediction_ledger import PredictionLedger
    from stock_papi.batch.weekly_model import (
        WeeklyModelReportError,
        build_weekly_model_report,
    )

    documents = [
        json.loads(path.read_text(encoding="utf-8")) for path in args.calendar_artifact
    ]
    calendars = TradingCalendarSet.from_documents(documents)
    backtest = BacktestStore(args.root, "TW").load_latest()
    if backtest is None:
        raise ValueError("promoted TW backtest is unavailable")
    previous_sha = None
    publish = args.root / "publish" / "reports" / "v2"
    index_path = publish / "index-TW.json"
    if index_path.exists():
        reports = validate_report_index(index_path.read_bytes())
        previous = next(
            (item for item in reports if item.get("report_type") == "weekly_model"),
            None,
        )
        if previous is not None:
            metadata = validate_report_metadata(
                (publish / previous["metadata"]).read_bytes(), previous
            )
            previous_sha = metadata["content"].get("candidate_sha256")
    ledger = PredictionLedger(args.root, "TW", calendars)
    try:
        metadata = build_weekly_model_report(
            backtest,
            ledger,
            generated_at=datetime.datetime.now(datetime.timezone.utc),
            previous_candidate_sha256=previous_sha,
        )
    except WeeklyModelReportError as exc:
        if str(exc) == "no new promoted backtest":
            print(json.dumps({"published": False, "reason": str(exc)}))
            return 0
        raise
    latest = publish_report_v2(args.root, metadata)
    print(json.dumps({"published": True, "latest_path": str(latest)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
