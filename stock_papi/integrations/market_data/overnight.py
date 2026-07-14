"""Bounded overnight-source loading and freshness validation."""

import datetime
import json
from dataclasses import dataclass
from urllib.parse import urlsplit


class OvernightSourceError(ValueError):
    """隔夜來源 transport、schema 或 freshness 不合法。"""


@dataclass(frozen=True)
class OvernightSourceSpec:
    name: str
    url: str
    timeout_seconds: float
    max_bytes: int
    max_age: datetime.timedelta

    def __post_init__(self):
        parsed = urlsplit(self.url)
        if (
            not isinstance(self.name, str)
            or not 1 <= len(self.name) <= 80
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or type(self.timeout_seconds) not in (int, float)
            or not 0 < self.timeout_seconds <= 30
            or type(self.max_bytes) is not int
            or not 1 <= self.max_bytes <= 1024 * 1024
            or not isinstance(self.max_age, datetime.timedelta)
            or not datetime.timedelta(0) < self.max_age <= datetime.timedelta(days=2)
        ):
            raise OvernightSourceError("overnight source spec is invalid")


def validate_overnight_document(document, *, now, max_age, expected_source=None):
    if (
        not isinstance(now, datetime.datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or not isinstance(max_age, datetime.timedelta)
    ):
        raise OvernightSourceError("overnight validation time is invalid")
    if not isinstance(document, dict):
        raise OvernightSourceError("overnight source must be an object")
    try:
        as_of = datetime.datetime.fromisoformat(
            str(document["as_of"]).replace("Z", "+00:00")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise OvernightSourceError("overnight as_of is invalid") from exc
    source = document.get("source")
    signal = document.get("signal")
    summary = document.get("summary")
    attribution = document.get("attribution_url")
    parsed = urlsplit(str(attribution or ""))
    age = now.astimezone(datetime.timezone.utc) - as_of.astimezone(datetime.timezone.utc)
    if (
        as_of.tzinfo is None
        or as_of.utcoffset() is None
        or not isinstance(source, str)
        or not 1 <= len(source) <= 80
        or (expected_source is not None and source != expected_source)
        or signal not in {"risk_on", "risk_off", "neutral"}
        or not isinstance(summary, str)
        or not 1 <= len(summary) <= 300
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or age < datetime.timedelta(minutes=-5)
        or age > max_age
    ):
        raise OvernightSourceError("overnight source schema or freshness is invalid")
    return {
        "source": source,
        "as_of": as_of.astimezone(datetime.timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "signal": signal,
        "summary": summary,
        "attribution_url": attribution,
        "freshness_seconds": max(0, int(age.total_seconds())),
    }


def fetch_overnight_source(spec, *, fetch_bytes, now):
    if not isinstance(spec, OvernightSourceSpec) or not callable(fetch_bytes):
        raise OvernightSourceError("overnight fetch configuration is invalid")
    try:
        content = fetch_bytes(spec.url, spec.timeout_seconds, spec.max_bytes)
    except Exception as exc:
        raise OvernightSourceError("overnight source request failed") from exc
    if not isinstance(content, bytes) or not 0 < len(content) <= spec.max_bytes:
        raise OvernightSourceError("overnight source size is invalid")
    try:
        document = json.loads(content.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise OvernightSourceError("overnight source JSON is invalid") from exc
    return validate_overnight_document(
        document, now=now, max_age=spec.max_age, expected_source=spec.name
    )
