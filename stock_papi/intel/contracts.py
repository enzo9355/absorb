"""Pure contracts for behavioral disclosure events and point-in-time selection."""

import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


UTC = datetime.timezone.utc
_PUBLIC_TIME_PRECISIONS = {"timestamp", "date", "unknown"}


def _parse_date(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO date")
    try:
        parsed = datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{label} must be an ISO date")
    return parsed


def _parse_aware_timestamp(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a timezone-aware timestamp")
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be a timezone-aware timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must be a timezone-aware timestamp")
    return parsed.astimezone(UTC)


def _timestamp(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _required_text(document, key):
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def validate_event(document):
    """Validate an event envelope and derive its conservative available_at."""
    if not isinstance(document, dict):
        raise ValueError("event must be a mapping")

    result = dict(document)
    for key in (
        "event_id", "event_version_id", "source_document_id", "source_row_id",
        "source_id", "revision_kind", "linkage_status", "mapping_status",
        "extraction_status", "review_status", "parser_version", "mapping_version",
        "classification_version",
    ):
        result[key] = _required_text(result, key)

    result["event_date"] = _parse_date(result.get("event_date"), "event_date").isoformat()
    if type(result.get("schema_version")) is not int or result["schema_version"] < 1:
        raise ValueError("schema_version must be a positive integer")
    if type(result.get("aggregation_eligibility")) is not bool:
        raise ValueError("aggregation_eligibility must be boolean")
    if not isinstance(result.get("raw_value"), dict) or not isinstance(
        result.get("normalized_payload"), dict
    ):
        raise ValueError("raw_value and normalized_payload must be mappings")

    precision = result.get("source_time_precision")
    if not isinstance(precision, str) or precision not in _PUBLIC_TIME_PRECISIONS:
        raise ValueError("source_time_precision is invalid")
    event_precision = result.get("event_time_precision")
    if not isinstance(event_precision, str) or event_precision not in _PUBLIC_TIME_PRECISIONS:
        raise ValueError("event_time_precision is invalid")
    event_at = result.get("event_at")
    if event_precision == "timestamp":
        result["event_at"] = _timestamp(_parse_aware_timestamp(event_at, "event_at"))
    elif event_at is not None:
        raise ValueError("event_at requires timestamp precision")
    timezone = result.get("source_timezone")
    if timezone is not None:
        if not isinstance(timezone, str) or not timezone:
            raise ValueError("source_timezone must be an IANA timezone")
        try:
            ZoneInfo(timezone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("source_timezone must be an IANA timezone") from exc
    public_bound = result.get("source_public_time_upper_bound")
    published_at = result.get("source_published_at")
    if precision == "date":
        public_date = _parse_date(result.get("source_public_date"), "source_public_date")
        if not isinstance(timezone, str) or not timezone:
            raise ValueError("date-only public time requires source_timezone")
        try:
            local_zone = ZoneInfo(timezone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("source_timezone must be an IANA timezone") from exc
        expected_bound = datetime.datetime.combine(
            public_date + datetime.timedelta(days=1), datetime.time.min, tzinfo=local_zone
        ).astimezone(UTC)
        if public_bound is not None and _parse_aware_timestamp(
            public_bound, "source_public_time_upper_bound"
        ) != expected_bound:
            raise ValueError("date-only public bound must be next local midnight")
        result["source_public_time_upper_bound"] = _timestamp(expected_bound)
    elif precision == "timestamp":
        if public_bound is None:
            if published_at is None:
                raise ValueError("timestamp precision requires public timestamp evidence")
            public_bound = published_at
        bound = _parse_aware_timestamp(public_bound, "source_public_time_upper_bound")
        if published_at is not None and bound < _parse_aware_timestamp(
            published_at, "source_published_at"
        ):
            raise ValueError("public upper bound precedes source_published_at")
        result["source_public_time_upper_bound"] = _timestamp(bound)
        if published_at is not None:
            result["source_published_at"] = _timestamp(
                _parse_aware_timestamp(published_at, "source_published_at")
            )
    elif public_bound is not None:
        raise ValueError("unknown public time precision cannot claim a time bound")

    observed_times = []
    for key in ("first_seen_at", "validated_at", "recorded_at"):
        parsed = _parse_aware_timestamp(result.get(key), key)
        result[key] = _timestamp(parsed)
        observed_times.append(parsed)
    if observed_times != sorted(observed_times):
        raise ValueError("first_seen_at, validated_at, recorded_at must be monotonic")

    required_times = list(observed_times)
    if result.get("source_public_time_upper_bound") is not None:
        required_times.append(_parse_aware_timestamp(
            result["source_public_time_upper_bound"], "source_public_time_upper_bound"
        ))
    mapping_known = result.get("required_mapping_known_at")
    if result.get("mapping_status") == "resolved":
        if mapping_known is None:
            raise ValueError("resolved mapping requires required_mapping_known_at")
        if not isinstance(result.get("instrument_id"), str) or not result["instrument_id"].strip():
            raise ValueError("resolved mapping requires instrument_id")
    elif result.get("instrument_id") is not None:
        raise ValueError("unresolved mapping cannot claim instrument_id")
    if mapping_known is not None:
        required_times.append(_parse_aware_timestamp(mapping_known, "required_mapping_known_at"))
        result["required_mapping_known_at"] = _timestamp(required_times[-1])
    review_known = result.get("required_relationship_or_review_known_at")
    if review_known is not None:
        parsed = _parse_aware_timestamp(review_known, "required_relationship_or_review_known_at")
        required_times.append(parsed)
        result["required_relationship_or_review_known_at"] = _timestamp(parsed)
    available = max(required_times)
    if result.get("available_at") is not None and _parse_aware_timestamp(
        result["available_at"], "available_at"
    ) != available:
        raise ValueError("available_at does not match required evidence times")
    result["available_at"] = _timestamp(available)
    if result["mapping_status"] != "resolved" and result["aggregation_eligibility"]:
        raise ValueError("unresolved mapping cannot be aggregation eligible")
    return result


def _reconstructed_available_at(event):
    evidence = event.get("reconstruction_evidence")
    if not isinstance(evidence, dict) or evidence.get("status") != "verified":
        return None
    if not isinstance(evidence.get("latency_policy_version"), str) or not all(
        evidence.get(field) is True
        for field in (
            "source_history_complete", "public_time_complete", "revision_history_complete",
            "mapping_history_complete", "universe_history_complete",
        )
    ):
        return None
    try:
        return _parse_aware_timestamp(event.get("research_available_at"), "research_available_at")
    except ValueError:
        return None


def select_event_versions(events, revision_links, cutoff, pit_mode):
    """Select versions known at a cutoff; never infer timing from event_date."""
    if not isinstance(pit_mode, str) or pit_mode not in {"actual_system", "reconstructed_public"}:
        raise ValueError("pit_mode is invalid")
    if not isinstance(events, (list, tuple)) or not isinstance(revision_links, (list, tuple)):
        raise ValueError("events and revision_links must be sequences")
    cutoff_at = _parse_aware_timestamp(cutoff, "cutoff")

    by_version = {}
    available_by_version = {}
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("event must be a mapping")
        version_id = _required_text(event, "event_version_id")
        event_id = _required_text(event, "event_id")
        if version_id in by_version:
            raise ValueError("event_version_id must be unique")
        if "aggregation_eligibility" in event and type(event["aggregation_eligibility"]) is not bool:
            raise ValueError("aggregation_eligibility must be boolean")
        try:
            available_at = (
                _parse_aware_timestamp(event.get("available_at"), "available_at")
                if pit_mode == "actual_system"
                else _reconstructed_available_at(event)
            )
        except ValueError:
            if pit_mode == "actual_system":
                raise
            available_at = None
        if available_at is None or available_at > cutoff_at:
            continue
        row = dict(event)
        row["event_id"] = event_id
        row["event_version_id"] = version_id
        by_version[version_id] = row
        available_by_version[version_id] = available_at

    active_links = []
    for link in revision_links:
        if not isinstance(link, dict):
            raise ValueError("revision link must be a mapping")
        known_at = _parse_aware_timestamp(link.get("known_at"), "revision link known_at")
        source_id = _required_text(link, "from_event_version_id")
        target_id = _required_text(link, "to_event_version_id")
        status = _required_text(link, "linkage_status")
        if status not in {"linked", "verified", "candidate", "unresolved"}:
            raise ValueError("revision link status is invalid")
        if known_at <= cutoff_at:
            active_links.append({
                **link,
                "from_event_version_id": source_id,
                "to_event_version_id": target_id,
                "linkage_status": status,
            })
    verified_pairs = {
        (link.get("from_event_version_id"), link.get("to_event_version_id"))
        for link in active_links
        if link.get("linkage_status") in {"linked", "verified"}
    }

    versions_by_event = {}
    for version_id, event in by_version.items():
        versions_by_event.setdefault(event["event_id"], []).append(version_id)

    selected = {}
    for versions in versions_by_event.values():
        latest = max(versions, key=lambda item: available_by_version[item])
        latest_at = available_by_version[latest]
        if sum(available_by_version[item] == latest_at for item in versions) > 1:
            raise ValueError("multiple event versions share the same availability time")
        latest_event = by_version[latest]
        supersedes = latest_event.get("supersedes_version_id")
        if supersedes is not None and (
            latest_event.get("linkage_status") not in {"linked", "verified"}
            or (supersedes, latest) not in verified_pairs
        ):
            for version_id in versions:
                row = dict(by_version[version_id])
                row["linkage_status"] = "unresolved"
                row["aggregation_eligibility"] = False
                selected[version_id] = row
        else:
            selected[latest] = by_version[latest]

    links_by_target = {}
    links_by_source = {}
    for link in active_links:
        source_id = _required_text(link, "from_event_version_id")
        target_id = _required_text(link, "to_event_version_id")
        if source_id in selected and target_id in selected:
            links_by_target.setdefault(target_id, []).append((source_id, link))
            links_by_source.setdefault(source_id, []).append((target_id, link))

    unresolved_ids = set()
    superseded_ids = set()
    for target_id, links in links_by_target.items():
        source_ids = {source_id for source_id, _ in links}
        statuses = {link.get("linkage_status") for _, link in links}
        if len(source_ids) != 1 or statuses - {"linked", "verified"}:
            unresolved_ids.add(target_id)
            unresolved_ids.update(source_ids)
        else:
            source_id = next(iter(source_ids))
            if source_id in selected and target_id in selected:
                selected[target_id]["event_id"] = selected[source_id]["event_id"]
            superseded_ids.update(source_ids)
    for source_id, links in links_by_source.items():
        target_ids = {target_id for target_id, _ in links}
        statuses = {link.get("linkage_status") for _, link in links}
        if len(target_ids) != 1 or statuses - {"linked", "verified"}:
            unresolved_ids.add(source_id)
            unresolved_ids.update(target_ids)

    for version_id in unresolved_ids:
        row = selected.get(version_id)
        if row is not None:
            row["linkage_status"] = "unresolved"
            row["aggregation_eligibility"] = False
    for version_id in superseded_ids - unresolved_ids:
        selected.pop(version_id, None)
    return sorted(selected.values(), key=lambda row: (row["event_id"], row["event_version_id"]))
