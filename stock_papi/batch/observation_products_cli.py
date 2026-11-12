"""Create and locally promote verified Observation product candidates."""

import argparse
import datetime
import json
from pathlib import Path


def _calendars(paths):
    from stock_papi.batch.calendar import TradingCalendarSet

    return TradingCalendarSet.from_documents(
        [
            json.loads(Path(path).read_text(encoding="utf-8"))
            for path in paths
        ]
    )


def _resolve_validation_date(args, today):
    validation_date = args.source_validation_date
    if validation_date is None:
        return today
    wall_clock_today = today or datetime.date.today()
    if validation_date != args.source_market_date:
        raise ValueError(
            "source validation date must equal source market date"
        )
    if validation_date > wall_clock_today:
        raise ValueError("source validation date cannot be in the future")
    return validation_date


def build(args, *, today=None, load_market_index=None, market_index_optional=False, load_capital_flows=None):
    from reporting.cli import _load_industry_map
    from reporting.config import ReportConfig
    from reporting.observation_v2 import build_post_close_observation_metadata
    from reporting.source_loader import load_report_source_manifest
    from stock_papi.batch.observation_products import (
        build_observation_dashboard,
        write_observation_candidate,
    )
    from stock_papi.config.capabilities import PredictionCapabilityState

    source = load_report_source_manifest(
        args.root,
        args.source_manifest,
        args.source_manifest_sha256,
        market="TW",
        report_date=args.source_market_date,
        config=ReportConfig(root=args.root, market="TW"),
    )
    capability = PredictionCapabilityState.from_environment()
    market_index = None
    if load_market_index is not None:
        try:
            market_index = load_market_index(source.manifest.market_as_of)
        except Exception:
            if not market_index_optional:
                raise
            market_index = None
        if market_index is None:
            if not market_index_optional:
                raise ValueError("verified TAIEX actuals are unavailable")
    dashboard = build_observation_dashboard(
        source,
        _load_industry_map(args.root),
        capability,
        market_index=market_index,
        generated_at=datetime.datetime.fromisoformat(
            source.manifest.generated_at.replace("Z", "+00:00")
        ),
        today=today,
    )
    metadata = build_post_close_observation_metadata(
        dashboard,
        _calendars(args.calendar_artifact),
    )
    if load_capital_flows is not None:
        from requests import RequestException
        from stock_papi.services.institutional_flows import validate_twse_flows

        try:
            flows = load_capital_flows(source.manifest.market_as_of)
            metadata["content"]["capital_flows"] = validate_twse_flows(
                flows, source.manifest.market_as_of
            )
        except (ValueError, RequestException):
            metadata["warnings"].append("上市市場法人金額來源未通過同日核對，本次不提供法人金額")
    candidate = write_observation_candidate(args.root, metadata, dashboard)
    return {
        "mode": "observation-candidate",
        "candidate_path": str(candidate),
        "dashboard_path": str(candidate / "dashboard-snapshot.json"),
        "post_close_v2_path": str(candidate / "post-close-report-v2.json"),
        "observation_as_of": dashboard["observation_as_of"],
        "source_manifest": dashboard["source_manifest"],
        "source_manifest_sha256": dashboard["source_manifest_sha256"],
        "market_index_status": (
            "included"
            if market_index is not None
            else "unavailable"
            if load_market_index is not None
            else "not_requested"
        ),
    }


def main(argv=None, *, today=None):
    parser = argparse.ArgumentParser(description="ABSORB Observation products")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("build")
    create.add_argument(
        "--root", type=Path, default=Path(r"D:\AbsorbData")
    )
    create.add_argument(
        "--source-market-date",
        type=datetime.date.fromisoformat,
        required=True,
    )
    create.add_argument(
        "--source-validation-date",
        type=datetime.date.fromisoformat,
        default=None,
        help="Override the freshness validation date for an explicit historical run.",
    )
    create.add_argument("--source-manifest", required=True)
    create.add_argument("--source-manifest-sha256", required=True)
    market_index_group = create.add_mutually_exclusive_group()
    market_index_group.add_argument("--include-market-index", action="store_true")
    market_index_group.add_argument(
        "--include-market-index-if-available",
        action="store_true",
        help="Include verified TAIEX actuals when they are available; "
        "continue without market_index otherwise.",
    )
    create.add_argument(
        "--calendar-artifact", type=Path, action="append", required=True
    )
    promote = subparsers.add_parser("promote")
    promote.add_argument(
        "--root", type=Path, default=Path(r"D:\AbsorbData")
    )
    promote.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        from stock_papi.services.institutional_flows import fetch_twse_flows

        validation_date = _resolve_validation_date(args, today)
        load_market_index = None
        market_index_optional = False
        if args.include_market_index or args.include_market_index_if_available:
            import requests
            from stock_papi.services.market_index import fetch_twse_index_snapshot

            load_market_index = lambda target: fetch_twse_index_snapshot(
                target, http_get=requests.get
            )
            market_index_optional = args.include_market_index_if_available
        result = build(
            args,
            today=validation_date,
            load_market_index=load_market_index,
            market_index_optional=market_index_optional,
            load_capital_flows=fetch_twse_flows,
        )
    else:
        from stock_papi.batch.observation_products import (
            promote_observation_candidate,
        )

        result = {
            "mode": "observation-local-promotion",
            **promote_observation_candidate(args.root, args.candidate),
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
