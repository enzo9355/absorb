"""Deterministic descriptive features over versioned event and market inputs."""

import datetime
import hashlib
import json
import math
import re
from decimal import Decimal, InvalidOperation

from stock_papi.intel.contracts import (
    _parse_aware_timestamp,
    _parse_date,
    select_event_versions,
    validate_event,
)
from stock_papi.intel.identity import resolve_instrument


FEATURE_SET_VERSION = "behavioral-intel-features-v1"
_COVERAGE_REQUIREMENTS = {
    "discovery_complete": "source_unavailable",
    "acquisition_complete": "source_unavailable",
    "parsing_complete": "schema_error",
    "mapping_complete": "ambiguous_mapping",
    "revision_resolution_complete": "unresolved_revision",
    "economic_dedup_complete": "ambiguous_economic_duplicate",
}


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, value is not None
    result = float(value)
    return (result, False) if math.isfinite(result) else (None, True)


def _decimal(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value) is None:
        return None
    try:
        result = Decimal(value)
    except InvalidOperation:
        return None
    return result if result.is_finite() and result >= 0 else None


def _decimal_text(value):
    return format(value.normalize(), "f")


def _master_records(master):
    records = master.get("records") if isinstance(master, dict) else master
    if not isinstance(records, (list, tuple)) or any(not isinstance(row, dict) for row in records):
        raise ValueError("master must contain versioned mapping records")
    return records


def _instrument_record(records, instrument_id, at_date, cutoff):
    matching = []
    for row in records:
        if row.get("instrument_id") != instrument_id:
            continue
        known = _parse_aware_timestamp(row.get("known_from"), "known_from")
        start = _parse_date(row.get("effective_from"), "effective_from")
        end = _parse_date(row["effective_to"], "effective_to") if row.get("effective_to") else None
        if end is not None and end <= start:
            raise ValueError("master effective interval must be [from,to)")
        if known <= cutoff and start <= at_date and (end is None or at_date < end):
            matching.append((row, known))
    superseded = {
        row.get("supersedes_version_id")
        for row, _ in matching
        if isinstance(row.get("supersedes_version_id"), str)
    }
    active = [(row, known) for row, known in matching if row.get("record_version_id") not in superseded]
    if not active:
        return None
    newest = max(known for _, known in active)
    latest = [row for row, known in active if known == newest]
    if len(latest) != 1:
        return None
    row = latest[0]
    if not all(_text(row.get(key)) for key in ("record_version_id", "source_ref")):
        return None
    return row


def _snapshot(snapshot, cutoff, missing_reason="source_unavailable"):
    if not isinstance(snapshot, dict):
        return None, [missing_reason]
    if (
        snapshot.get("verified") is not True
        or re.fullmatch(r"[0-9a-f]{64}", str(snapshot.get("artifact_sha256") or "")) is None
        or re.fullmatch(r"quant/v1/[A-Za-z0-9._/-]+", _text(snapshot.get("manifest_ref"))) is None
        or ".." in _text(snapshot.get("manifest_ref")).split("/")
        or snapshot.get("market") not in {"US", "TW"}
        or not _text(snapshot.get("symbol"))
        or not _text(snapshot.get("adjustment_basis"))
        or not _text(snapshot.get("calendar_version"))
    ):
        return None, ["schema_error"]
    try:
        as_of = _parse_date(snapshot.get("as_of"), "market as_of")
        available_at = _parse_aware_timestamp(snapshot.get("available_at"), "market available_at")
    except ValueError:
        return None, ["schema_error"]
    if as_of > cutoff.date() or available_at > cutoff:
        return None, ["source_unavailable"]
    daily = snapshot.get("daily")
    if not isinstance(daily, list):
        return None, ["schema_error"]
    bars = []
    previous_date = None
    invalid = False
    for row in daily:
        if not isinstance(row, dict):
            return None, ["schema_error"]
        try:
            day = _parse_date(str(row.get("Date") or "").split("T", 1)[0], "bar Date")
        except ValueError:
            return None, ["schema_error"]
        if previous_date is not None and day <= previous_date:
            return None, ["schema_error"]
        if day > as_of or day > cutoff.date():
            return None, ["schema_error"]
        normalized = {"date": day.isoformat()}
        for key in ("Open", "High", "Low", "Close", "Volume"):
            number, bad = _number(row.get(key))
            invalid = invalid or bad
            normalized[key] = number
        if normalized["Volume"] is not None and normalized["Volume"] < 0:
            invalid = True
        for key in ("Open", "High", "Low", "Close"):
            if normalized[key] is not None and normalized[key] <= 0:
                invalid = True
        bars.append(normalized)
        previous_date = day
    if invalid:
        return None, ["schema_error"]
    if not bars or bars[-1]["date"] != as_of.isoformat():
        return None, ["insufficient_history"]
    return {
        "snapshot": snapshot,
        "bars": bars,
        "as_of": as_of,
        "available_at": available_at,
    }, []


def _price_values(snapshot, sector_snapshot, cutoff):
    stock, reasons = _snapshot(snapshot, cutoff, "source_unavailable")
    empty = {
        name: (None, [*reasons] if reasons else ["insufficient_history"], 0)
        for name in (
            "stock_return_5s", "stock_return_20s", "relative_return_vs_sector_5s",
            "volume_ratio_20s", "price_breakout_state", "drawdown_from_20s_high",
        )
    }
    if stock is None:
        return empty, None
    bars = stock["bars"]
    values = {}

    def result(name, value, why=(), sample_count=0):
        values[name] = (value, list(why), sample_count)

    def return_over(period):
        window = bars[-(period + 1):]
        if len(window) != period + 1 or any(bar["Close"] is None for bar in window):
            return None, ["insufficient_history"], len(window)
        start, end = window[0]["Close"], window[-1]["Close"]
        if start is None or end is None or start <= 0:
            return None, ["insufficient_history"], len(window)
        return end / start - 1, [], len(window)

    for name, period in (("stock_return_5s", 5), ("stock_return_20s", 20)):
        result(name, *return_over(period))

    relative, relative_reasons, count = return_over(5)
    benchmark, _ = _snapshot(sector_snapshot, cutoff, "benchmark_unavailable")
    if benchmark is None:
        result("relative_return_vs_sector_5s", None, ["benchmark_unavailable"], count)
    elif (
        benchmark["snapshot"]["market"] != stock["snapshot"]["market"]
        or benchmark["snapshot"]["adjustment_basis"] != stock["snapshot"]["adjustment_basis"]
    ):
        result("relative_return_vs_sector_5s", None, ["benchmark_unavailable"], count)
    elif relative_reasons:
        result("relative_return_vs_sector_5s", None, relative_reasons, count)
    else:
        stock_window = bars[-6:]
        benchmark_by_date = {bar["date"]: bar["Close"] for bar in benchmark["bars"]}
        benchmark_window = [benchmark_by_date.get(bar["date"]) for bar in stock_window]
        if len(stock_window) != 6 or any(value is None or value <= 0 for value in benchmark_window):
            result("relative_return_vs_sector_5s", None, ["insufficient_history"], len(stock_window))
        else:
            bench_return = benchmark_window[-1] / benchmark_window[0] - 1
            result("relative_return_vs_sector_5s", relative - bench_return, (), len(stock_window))

    volume_window = bars[-21:]
    if (
        len(volume_window) != 21
        or any(bar["Volume"] is None for bar in volume_window)
    ):
        result("volume_ratio_20s", None, ["insufficient_history"], len(volume_window))
    else:
        baseline = sum(bar["Volume"] for bar in volume_window[:-1]) / 20
        result(
            "volume_ratio_20s",
            volume_window[-1]["Volume"] / baseline if baseline > 0 else None,
            [] if baseline > 0 else ["insufficient_history"],
            len(volume_window),
        )

    breakout_window = bars[-21:]
    if (
        len(breakout_window) != 21
        or any(bar["Close"] is None for bar in breakout_window)
    ):
        result("price_breakout_state", "unknown", ["insufficient_history"], len(breakout_window))
    else:
        result(
            "price_breakout_state",
            "above_prior_high" if breakout_window[-1]["Close"] > max(
                bar["Close"] for bar in breakout_window[:-1]
            ) else "not_above_prior_high",
            (),
            len(breakout_window),
        )

    drawdown_window = bars[-20:]
    if (
        len(drawdown_window) != 20
        or drawdown_window[-1]["Close"] is None
        or any(bar["High"] is None for bar in drawdown_window)
        or max(bar["High"] for bar in drawdown_window) <= 0
    ):
        result("drawdown_from_20s_high", None, ["insufficient_history"], len(drawdown_window))
    else:
        result(
            "drawdown_from_20s_high",
            drawdown_window[-1]["Close"] / max(bar["High"] for bar in drawdown_window) - 1,
            (),
            len(drawdown_window),
        )
    return values, stock


def _coverage_reasons(coverage):
    if not isinstance(coverage, dict):
        return ["coverage_unknown"]
    reasons = []
    for key, reason in _COVERAGE_REQUIREMENTS.items():
        if coverage.get(key) is not True:
            reasons.append(reason)
    return sorted(set(reasons))


def _feature(instrument_id, cutoff, pit_mode, name, value, status, reasons, *, unit,
             sample_count, source_event_version_ids, coverage, mapping_version_ids,
             source_refs=(), source_available_through=None, window=None):
    return {
        "instrument_id": instrument_id,
        "decision_cutoff_at": cutoff.isoformat().replace("+00:00", "Z"),
        "pit_mode": pit_mode,
        "feature_set_version": FEATURE_SET_VERSION,
        "feature_name": name,
        "value": value,
        "unit": unit,
        "status": status,
        "reason_codes": sorted(set(reasons)),
        "window": window,
        "sample_count": sample_count,
        "coverage": dict(coverage) if isinstance(coverage, dict) else None,
        "source_event_version_ids": sorted(set(source_event_version_ids)),
        "mapping_version_ids": sorted(set(mapping_version_ids)),
        "source_refs": sorted(set(source_refs)),
        "source_available_through": source_available_through,
    }


def build_features(events, market_snapshot, master, coverage, cutoff, pit_mode):
    """Build cutoff-bound features from validated event envelopes and exact snapshots.

    ``events`` may be a sequence or ``{"events": ..., "revision_links": ...}``.
    ``market_snapshot`` holds exact, verified instrument and benchmark artifacts.
    """
    cutoff_at = _parse_aware_timestamp(cutoff, "cutoff")
    if isinstance(events, dict):
        event_rows = events.get("events")
        revision_links = events.get("revision_links", [])
    else:
        event_rows = events
        revision_links = []
    if not isinstance(event_rows, (list, tuple)) or not isinstance(revision_links, (list, tuple)):
        raise ValueError("events and revision_links must be sequences")
    validated = [validate_event(row) for row in event_rows]
    selected = select_event_versions(validated, revision_links, cutoff, pit_mode)
    records = _master_records(master)
    snapshots = market_snapshot if isinstance(market_snapshot, dict) else {}
    instruments = snapshots.get("instruments", {})
    benchmarks = snapshots.get("sector_benchmarks", {})
    if not isinstance(instruments, dict) or not isinstance(benchmarks, dict):
        raise ValueError("market_snapshot must contain instrument and benchmark mappings")

    base_reasons = _coverage_reasons(coverage)
    global_reasons = set()
    window_start = cutoff_at - datetime.timedelta(days=30)
    mapped_events = {}
    for row in selected:
        first_public = row.get("first_public_time_upper_bound")
        try:
            public_at = _parse_aware_timestamp(first_public, "first_public_time_upper_bound")
        except ValueError:
            global_reasons.add("coverage_unknown")
            continue
        if public_at > cutoff_at:
            global_reasons.add("schema_error")
            continue
        if public_at <= window_start:
            continue
        payload = row.get("normalized_payload")
        if not isinstance(payload, dict):
            global_reasons.add("schema_error")
            continue
        try:
            resolution = resolve_instrument(
                records,
                row.get("issuer_cik"),
                payload.get("security_title"),
                row.get("event_date"),
                cutoff,
            )
        except ValueError:
            resolution = {"status": "ambiguous_mapping", "reason_codes": ["ambiguous_mapping"]}
        if (
            resolution.get("status") != "resolved"
            or resolution.get("instrument_id") != row.get("instrument_id")
        ):
            global_reasons.add("ambiguous_mapping")
            continue
        instrument_id = resolution["instrument_id"]
        mapped_events.setdefault(instrument_id, []).append((row, resolution))

    instrument_ids = set(instruments) | set(mapped_events)
    result = []
    window_label = {
        "start_exclusive": window_start.isoformat().replace("+00:00", "Z"),
        "end_inclusive": cutoff_at.isoformat().replace("+00:00", "Z"),
        "basis": "first_public_time_upper_bound",
    }
    for instrument_id in sorted(instrument_ids):
        snapshot = instruments.get(instrument_id)
        try:
            snapshot_day = _parse_date(snapshot.get("as_of"), "market as_of") if isinstance(snapshot, dict) else cutoff_at.date()
            master_row = _instrument_record(records, instrument_id, snapshot_day, cutoff_at)
        except ValueError:
            master_row = None
        if master_row is None or str(master_row.get("asset_type") or "").upper() != "COMMON_EQUITY":
            local_reasons = set(base_reasons) | set(global_reasons) | {"ambiguous_mapping"}
            mapping_version_ids = []
            sector_id = None
        else:
            local_reasons = set(base_reasons) | set(global_reasons)
            mapping_version_ids = [master_row["record_version_id"]]
            sector_id = master_row.get("sector_benchmark_instrument_id")

        window_events = []
        window_unknown = False
        for row, resolution in mapped_events.get(instrument_id, []):
            mapping_version_ids.append(resolution["record_version_id"])
            first_public = row.get("first_public_time_upper_bound")
            try:
                public_at = _parse_aware_timestamp(first_public, "first_public_time_upper_bound")
            except ValueError:
                window_unknown = True
                continue
            if window_start < public_at <= cutoff_at:
                window_events.append((row, public_at))
        if window_unknown:
            local_reasons.add("coverage_unknown")

        unresolved_revisions = [
            row for row, _ in window_events
            if row.get("linkage_status") == "unresolved"
            or row.get("aggregation_eligibility") is not True
        ]
        if unresolved_revisions:
            local_reasons.add("unresolved_revision")

        eligible_rows = [
            (row, public_at) for row, public_at in window_events
            if row.get("aggregation_eligibility") is True
            and row.get("linkage_status") in {"not_applicable", "linked", "verified"}
            and row.get("mapping_status") == "resolved"
            and row.get("review_status") == "verified"
        ]
        purchases = []
        sales = []
        for row, public_at in eligible_rows:
            payload = row["normalized_payload"]
            if row.get("table_kind") != "non_derivative" or row.get("row_kind") != "transaction":
                continue
            if payload.get("transaction_code") == "P" and payload.get("acquired_disposed") == "A":
                purchases.append((row, public_at))
            elif payload.get("transaction_code") == "S" and payload.get("acquired_disposed") == "D":
                sales.append((row, public_at))

        duplicate = False
        seen = {}
        for row, _ in [*purchases, *sales]:
            payload = row["normalized_payload"]
            price = payload.get("price_per_share")
            if payload.get("price_status") != "value" or price is None:
                continue
            key = (
                row.get("instrument_id"), row.get("event_date"),
                payload.get("transaction_code"), payload.get("acquired_disposed"),
                payload.get("shares"), price, payload.get("price_currency"),
            )
            previous_source = seen.get(key)
            if previous_source is not None and previous_source != row.get("source_document_id"):
                duplicate = True
            seen[key] = row.get("source_document_id")
        if duplicate:
            local_reasons.add("ambiguous_economic_duplicate")

        source_ids = [row["event_version_id"] for row, _ in eligible_rows]
        public_through = max((public for _, public in eligible_rows), default=None)
        complete = not local_reasons
        for name, rows in (
            ("disclosed_purchase_count_30d", purchases),
            ("disclosed_sale_count_30d", sales),
        ):
            count_reason = list(local_reasons)
            if not rows and complete:
                count_reason.append("no_event_observed")
            result.append(_feature(
                instrument_id, cutoff_at, pit_mode, name,
                len(rows) if complete else None,
                "available" if complete else "partial",
                count_reason,
                unit="events", sample_count=len(rows),
                source_event_version_ids=[row["event_version_id"] for row, _ in rows],
                coverage=coverage, mapping_version_ids=mapping_version_ids,
                source_refs=[row.get("source_document_id", "") for row, _ in rows],
                source_available_through=public_through.isoformat().replace("+00:00", "Z") if public_through else None,
                window=window_label,
            ))

        owners = {
            row.get("economic_owner_group_id")
            for row, _ in purchases
            if isinstance(row.get("economic_owner_group_id"), str)
            and row.get("economic_owner_group_status") == "verified"
        }
        owners_complete = all(
            isinstance(row.get("economic_owner_group_id"), str)
            and row.get("economic_owner_group_status") == "verified"
            for row, _ in purchases
        )
        owner_reasons = list(local_reasons)
        if not owners_complete:
            owner_reasons.append("pending_validation")
        owner_value = len(owners) if complete and owners_complete else None
        result.append(_feature(
            instrument_id, cutoff_at, pit_mode, "independent_purchase_owner_count_30d",
            owner_value, "available" if owner_value is not None else "partial",
            owner_reasons,
            unit="owner_groups", sample_count=len(purchases),
            source_event_version_ids=[row["event_version_id"] for row, _ in purchases],
            coverage=coverage, mapping_version_ids=mapping_version_ids,
            source_refs=[row.get("source_document_id", "") for row, _ in purchases],
            source_available_through=public_through.isoformat().replace("+00:00", "Z") if public_through else None,
            window=window_label,
        ))

        amount = Decimal(0)
        amount_complete = all(
            row["normalized_payload"].get("price_status") == "value"
            and row["normalized_payload"].get("price_currency") == "USD"
            and _decimal(row["normalized_payload"].get("shares")) is not None
            and _decimal(row["normalized_payload"].get("price_per_share")) is not None
            for row, _ in purchases
        )
        if amount_complete:
            for row, _ in purchases:
                payload = row["normalized_payload"]
                amount += _decimal(payload["shares"]) * _decimal(payload["price_per_share"])
        amount_value = _decimal_text(amount) if complete and amount_complete else None
        amount_reasons = list(local_reasons)
        if not amount_complete:
            amount_reasons.append("amount_unavailable")
        result.append(_feature(
            instrument_id, cutoff_at, pit_mode, "disclosed_purchase_amount_30d",
            amount_value, "available" if amount_value is not None else "partial",
            amount_reasons,
            unit="USD", sample_count=len(purchases),
            source_event_version_ids=[row["event_version_id"] for row, _ in purchases],
            coverage=coverage, mapping_version_ids=mapping_version_ids,
            source_refs=[row.get("source_document_id", "") for row, _ in purchases],
            source_available_through=public_through.isoformat().replace("+00:00", "Z") if public_through else None,
            window=window_label,
        ))

        cluster_value = owner_value >= 3 if owner_value is not None else None
        result.append(_feature(
            instrument_id, cutoff_at, pit_mode, "purchase_cluster_30d",
            cluster_value, "available" if cluster_value is not None else "partial",
            owner_reasons,
            unit="boolean", sample_count=len(purchases),
            source_event_version_ids=[row["event_version_id"] for row, _ in purchases],
            coverage=coverage, mapping_version_ids=mapping_version_ids,
            source_refs=[row.get("source_document_id", "") for row, _ in purchases],
            source_available_through=public_through.isoformat().replace("+00:00", "Z") if public_through else None,
            window=window_label,
        ))

        latest_public = max((public for _, public in eligible_rows), default=None)
        age = (cutoff_at - latest_public).total_seconds() / 86400 if latest_public else None
        age_reasons = list(local_reasons)
        if latest_public is None and complete:
            age_reasons.append("no_event_observed")
        result.append(_feature(
            instrument_id, cutoff_at, pit_mode, "latest_disclosure_age_days",
            age if complete else None,
            "available" if complete and age is not None else ("unavailable" if complete else "partial"),
            age_reasons,
            unit="days", sample_count=len(eligible_rows),
            source_event_version_ids=[row["event_version_id"] for row, _ in eligible_rows],
            coverage=coverage, mapping_version_ids=mapping_version_ids,
            source_refs=[row.get("source_document_id", "") for row, _ in eligible_rows],
            source_available_through=latest_public.isoformat().replace("+00:00", "Z") if latest_public else None,
            window=window_label,
        ))

        sector_snapshot = benchmarks.get(sector_id) if isinstance(sector_id, str) else None
        market_values, stock = _price_values(snapshot, sector_snapshot, cutoff_at)
        for name, unit in (
            ("stock_return_5s", "return"), ("stock_return_20s", "return"),
            ("relative_return_vs_sector_5s", "return"), ("volume_ratio_20s", "ratio"),
            ("price_breakout_state", "state"), ("drawdown_from_20s_high", "return"),
        ):
            value, reasons, sample_count = market_values[name]
            if name == "relative_return_vs_sector_5s" and sector_id is None:
                reasons = ["ambiguous_mapping"]
                value = None
            market_ref = stock["snapshot"] if stock else None
            market_status = "available" if value is not None and value != "unknown" else "unavailable"
            result.append(_feature(
                instrument_id, cutoff_at, pit_mode, name, value,
                market_status, reasons,
                unit=unit, sample_count=sample_count,
                source_event_version_ids=[], coverage=coverage,
                mapping_version_ids=mapping_version_ids,
                source_refs=[market_ref.get("manifest_ref", "")] if market_ref else [],
                source_available_through=stock["as_of"].isoformat() if stock else None,
            ))
    return result
