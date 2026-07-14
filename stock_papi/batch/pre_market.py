"""Pre-market overlay pipeline that never mutates post-close core evidence."""

import datetime
import hashlib
import json
import os
from pathlib import Path

from stock_papi.batch.runtime import acquire_job_lock, job_namespace
from stock_papi.batch.status import PipelineStatusWriter
from stock_papi.integrations.market_data.overnight import (
    OvernightSourceError,
    validate_overnight_document,
)


class PreMarketPipelineError(RuntimeError):
    """盤後 base、overlay source 或 checkpoint 不合法。"""


def _canonical(document):
    try:
        return json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PreMarketPipelineError("pre-market document is invalid") from exc


def _write_atomic(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(_canonical(document))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class PreMarketPipeline:
    def __init__(
        self,
        root,
        *,
        applicable_trading_date,
        load_base,
        source_loaders,
        publish,
        notify,
        max_source_age=datetime.timedelta(hours=18),
    ):
        if (
            type(applicable_trading_date) is not datetime.date
            or not callable(load_base)
            or not isinstance(source_loaders, (list, tuple))
            or not all(callable(loader) for loader in source_loaders)
            or not callable(publish)
            or not callable(notify)
            or not isinstance(max_source_age, datetime.timedelta)
            or not datetime.timedelta(0) < max_source_age <= datetime.timedelta(days=2)
        ):
            raise ValueError("invalid pre-market pipeline configuration")
        self.root = Path(root)
        self.applicable_trading_date = applicable_trading_date
        self.load_base = load_base
        self.source_loaders = tuple(source_loaders)
        self.publish = publish
        self.notify = notify
        self.max_source_age = max_source_age

    def _base(self):
        receipt = self.load_base()
        if not isinstance(receipt, dict) or not isinstance(receipt.get("metadata"), dict):
            raise PreMarketPipelineError("verified post-close base is missing")
        metadata = receipt["metadata"]
        digest = receipt.get("metadata_sha256")
        if (
            metadata.get("schema_version") != 2
            or metadata.get("kind") != "stock-papi-report"
            or metadata.get("report_type") != "post_close"
            or metadata.get("market") != "TW"
            or metadata.get("applicable_trading_date")
            != self.applicable_trading_date.isoformat()
            or hashlib.sha256(_canonical(metadata)).hexdigest() != digest
            or not isinstance(metadata.get("content"), dict)
        ):
            raise PreMarketPipelineError("verified post-close base is invalid")
        return receipt

    def run(self, *, now=None):
        checked_at = now or datetime.datetime.now(datetime.timezone.utc)
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        base = self._base()
        base_metadata = base["metadata"]
        identity = {
            "applicable_trading_date": self.applicable_trading_date.isoformat(),
            "base_metadata_sha256": base["metadata_sha256"],
        }
        digest = hashlib.sha256(_canonical(identity)).hexdigest()[:8]
        run_id = f"{self.applicable_trading_date.strftime('%Y%m%d')}T000000Z-{digest}"
        current = job_namespace(self.root, "pre_market_update").checkpoint
        checkpoint_path = current.with_name(f"{run_id}.json")
        writer = PipelineStatusWriter(
            self.root,
            job_type="pre_market_update",
            run_id=run_id,
            target_date=self.applicable_trading_date,
        )
        with acquire_job_lock(
            self.root,
            "pre_market_update",
            self.applicable_trading_date,
            now=checked_at,
        ):
            if checkpoint_path.exists():
                try:
                    state = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise PreMarketPipelineError("pre-market checkpoint is invalid") from exc
                if any(state.get(key) != value for key, value in identity.items()):
                    raise PreMarketPipelineError("pre-market checkpoint identity mismatch")
                if state.get("status") == "completed":
                    return state
            else:
                state = {
                    "schema_version": 1,
                    "job_type": "pre_market_update",
                    "run_id": run_id,
                    **identity,
                    "completed_stages": [],
                    "outputs": {},
                    "status": "running",
                }

            def save():
                state["updated_at"] = checked_at.astimezone(
                    datetime.timezone.utc
                ).isoformat().replace("+00:00", "Z")
                _write_atomic(checkpoint_path, state)

            try:
                if "metadata" not in state["completed_stages"]:
                    available = []
                    unavailable = []
                    for index, loader in enumerate(self.source_loaders):
                        try:
                            document = loader()
                            if document is None:
                                raise OvernightSourceError("source unavailable")
                            available.append(
                                validate_overnight_document(
                                    document,
                                    now=checked_at,
                                    max_age=self.max_source_age,
                                )
                            )
                        except Exception as exc:
                            unavailable.append(
                                {"source_index": index, "error_type": type(exc).__name__}
                            )
                    signals = {item["signal"] for item in available}
                    if not available:
                        status = "insufficient"
                        message = "資料不足，維持盤後判斷"
                    elif signals == {"risk_on"}:
                        status, message = "risk_on", "隔夜風險偏正向"
                    elif signals == {"risk_off"}:
                        status, message = "risk_off", "隔夜風險偏保守"
                    else:
                        status, message = "mixed", "隔夜訊號分歧"
                    core = json.loads(_canonical(base_metadata["content"]).decode("utf-8"))
                    metadata = {
                        "schema_version": 2,
                        "report_type": "pre_market",
                        "market": "TW",
                        "source_market_date": base_metadata["source_market_date"],
                        "applicable_trading_date": base_metadata[
                            "applicable_trading_date"
                        ],
                        "published_at": checked_at.astimezone(
                            datetime.timezone.utc
                        ).isoformat().replace("+00:00", "Z"),
                        "forecast_start_date": base_metadata["forecast_start_date"],
                        "forecast_end_date": base_metadata["forecast_end_date"],
                        "backtest_as_of": base_metadata["backtest_as_of"],
                        "data_as_of": base_metadata["data_as_of"],
                        "source_manifest": base_metadata["source_manifest"],
                        "source_manifest_sha256": base_metadata[
                            "source_manifest_sha256"
                        ],
                        "model_versions": base_metadata["model_versions"],
                        "title": "Stock Papi 台股盤前快報",
                        "summary": [message],
                        "warnings": (
                            []
                            if not unavailable
                            else [f"{len(unavailable)} 個隔夜來源不可用"]
                        ),
                        "content": {
                            "core": core,
                            "base_metadata_sha256": base["metadata_sha256"],
                            "overnight_overlay": {
                                "status": status,
                                "message": message,
                                "available": available,
                                "unavailable": unavailable,
                                "as_of": checked_at.astimezone(
                                    datetime.timezone.utc
                                ).isoformat().replace("+00:00", "Z"),
                            },
                        },
                    }
                    state["outputs"]["metadata"] = metadata
                    state["completed_stages"].append("metadata")
                    save()
                    writer.record("aggregation", now=checked_at)
                metadata = state["outputs"]["metadata"]
                if "publish" not in state["completed_stages"]:
                    receipt = self.publish(metadata)
                    _canonical(receipt)
                    state["outputs"]["publish"] = receipt
                    state["completed_stages"].append("publish")
                    save()
                    writer.record("publish", now=checked_at)
                receipt = state["outputs"]["publish"]
                if "notify" not in state["completed_stages"]:
                    notification = self.notify(receipt)
                    _canonical(notification)
                    state["outputs"]["notify"] = notification
                    state["completed_stages"].append("notify")
                    save()
                    writer.record("notify", now=checked_at)
                state["status"] = "completed"
                save()
                writer.record("completed", now=checked_at)
                return state
            except Exception as exc:
                state["status"] = "failed"
                state["last_error_type"] = type(exc).__name__
                save()
                writer.record("failed", now=checked_at, error=exc)
                raise
