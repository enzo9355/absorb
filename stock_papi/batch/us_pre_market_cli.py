"""Authoritative US market pre-market observation batch pipeline."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import zoneinfo

from reporting.publisher import publish_report_v2
from stock_papi.batch.calendar import TradingCalendarSet
from stock_papi.integrations.market_data.us_calendar import get_us_calendar_documents

NEW_YORK = zoneinfo.ZoneInfo("America/New_York")


def _assert_post_close_base(
    base_meta: dict, target_market_date: datetime.date
) -> None:
    """Fail closed unless the bound post-close base applies to the target session.

    The report route rejects a pre-market report whose base post-close does not
    share its ``source_market_date`` and ``applicable_trading_date``, so a base
    that applies to another session can only ever publish an unservable report.
    """

    capability = base_meta.get("prediction_capability")
    if (
        base_meta.get("schema_version") != 2
        or base_meta.get("kind") not in {"absorb-report", "stock-papi-report"}
        or base_meta.get("product_mode") != "observation"
        or base_meta.get("report_type") != "post_close"
        or base_meta.get("market") != "US"
        or base_meta.get("applicable_trading_date")
        != target_market_date.isoformat()
        or base_meta.get("observation_start_date")
        != base_meta.get("source_market_date")
        or base_meta.get("observation_end_date")
        != base_meta.get("applicable_trading_date")
        or not isinstance(base_meta.get("content"), dict)
        or not isinstance(capability, dict)
    ):
        raise RuntimeError(
            "US pre-market post-close base does not apply to "
            f"{target_market_date.isoformat()}"
        )


def run_us_pre_market(
    root: Path | str,
    target_market_date: datetime.date,
    *,
    now: datetime.datetime | None = None,
) -> Path:
    root = Path(root)
    now = now or datetime.datetime.now(datetime.timezone.utc)

    # 1. Calendar & Date Semantics
    cal_docs = get_us_calendar_documents(target_market_date.year - 1, target_market_date.year + 1)
    calendars = TradingCalendarSet.from_documents(cal_docs)
    if not calendars.is_session(target_market_date):
        raise ValueError(f"Target pre-market date {target_market_date} is not a valid US trading session")

    # 2. Load latest US post-close pointer to bind pre-market base
    post_close_path = root / "publish" / "reports" / "v2" / "latest-US-post_close.json"
    if not post_close_path.exists():
        raise RuntimeError("US pre-market requires published US post-close base")

    post_close_ptr = json.loads(post_close_path.read_text(encoding="utf-8"))
    meta_rel = str(post_close_ptr.get("metadata") or "")
    if re.fullmatch(r"metadata/[0-9a-f]{64}\.json", meta_rel) is None:
        raise RuntimeError("US post-close base pointer is invalid")
    base_bytes = (root / "publish" / "reports" / "v2" / meta_rel).read_bytes()
    post_close_meta_sha = hashlib.sha256(base_bytes).hexdigest()
    if (
        meta_rel != f"metadata/{post_close_meta_sha}.json"
        or str(post_close_ptr.get("metadata_sha256") or "") != post_close_meta_sha
    ):
        raise RuntimeError("US post-close base metadata hash is not bound")
    base_meta = json.loads(base_bytes.decode("utf-8"))
    _assert_post_close_base(base_meta, target_market_date)

    content = {
        "base_metadata_sha256": post_close_meta_sha,
        "core": base_meta.get("content", {}),
        "overnight_overlay": {
            "status": "mixed",
            "message": f"美股 {target_market_date} 開盤前觀察",
            "as_of": target_market_date.isoformat(),
            "available": [],
            "unavailable": [],
        },
    }
    content_bytes = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    content_sha256 = hashlib.sha256(content_bytes).hexdigest()

    doc = {
        "schema_version": 2,
        "kind": "absorb-report",
        "product_mode": "observation",
        "market": "US",
        "report_type": "pre_market",
        "source_market_date": base_meta["source_market_date"],
        "applicable_trading_date": target_market_date.isoformat(),
        "published_at": now.isoformat().replace("+00:00", "Z"),
        "data_as_of": base_meta["data_as_of"],
        "forecast_start_date": target_market_date.isoformat(),
        "forecast_end_date": target_market_date.isoformat(),
        "observation_start_date": base_meta["source_market_date"],
        "observation_end_date": target_market_date.isoformat(),
        "source_manifest": base_meta["source_manifest"],
        "source_manifest_sha256": base_meta["source_manifest_sha256"],
        "model_versions": {},
        "title": f"ABSORB 美股盤前市場觀察報告 ({target_market_date})",
        "summary": [f"美股 {target_market_date} 開盤前市場觀察與前一交易日結構摘要。"],
        "warnings": [],
        "content": content,
        "content_sha256": content_sha256,
        "prediction_capability": base_meta["prediction_capability"],
    }

    res = publish_report_v2(root, doc)
    print(f"Published US pre-market report: {res}")
    return res


def main() -> None:
    parser = argparse.ArgumentParser(description="Run US pre-market observation batch pipeline")
    parser.add_argument("--root", required=True, help="Data root path")
    parser.add_argument("--target-market-date", required=True, help="Target date YYYY-MM-DD")
    args = parser.parse_args()

    target_date = datetime.date.fromisoformat(args.target_market_date)
    run_us_pre_market(Path(args.root), target_date)


if __name__ == "__main__":
    main()
