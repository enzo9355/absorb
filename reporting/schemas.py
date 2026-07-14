import datetime
import hashlib
import math
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPORT_TYPES = frozenset({"post_close", "pre_market", "weekly_model"})


@dataclass(frozen=True)
class ReportMetadataV2:
    report_type: str
    market: str
    source_market_date: datetime.date
    applicable_trading_date: datetime.date
    published_at: datetime.datetime
    forecast_start_date: datetime.date
    forecast_end_date: datetime.date
    backtest_as_of: datetime.date
    data_as_of: datetime.date
    source_manifest: str
    source_manifest_sha256: str
    model_versions: dict[str, int]
    title: str
    summary: tuple[str, ...]
    warnings: tuple[str, ...]
    content: dict[str, Any]

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "ReportMetadataV2":
        if not isinstance(document, dict) or document.get("schema_version") != 2:
            raise ValueError("report metadata v2 schema 不合法")
        try:
            source = datetime.date.fromisoformat(str(document["source_market_date"]))
            applicable = datetime.date.fromisoformat(str(document["applicable_trading_date"]))
            forecast_start = datetime.date.fromisoformat(str(document["forecast_start_date"]))
            forecast_end = datetime.date.fromisoformat(str(document["forecast_end_date"]))
            backtest_as_of = datetime.date.fromisoformat(str(document["backtest_as_of"]))
            data_as_of = datetime.date.fromisoformat(str(document["data_as_of"]))
            published = datetime.datetime.fromisoformat(
                str(document["published_at"]).replace("Z", "+00:00")
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("report metadata v2 日期不合法") from exc
        report_type = document.get("report_type")
        manifest = str(document.get("source_manifest") or "")
        manifest_sha = str(document.get("source_manifest_sha256") or "")
        model_versions = document.get("model_versions")
        title = document.get("title")
        summary = document.get("summary")
        warnings = document.get("warnings")
        content = document.get("content")
        if (
            report_type not in REPORT_TYPES
            or document.get("market") != "TW"
            or published.tzinfo is None
            or published.utcoffset() is None
            or source > applicable
            or forecast_start != applicable
            or forecast_end < forecast_start
            or backtest_as_of > source
            or data_as_of > source
            or re.fullmatch(
                r"quant/v1/manifests/TW-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\.json",
                manifest,
            )
            is None
            or re.fullmatch(r"[0-9a-f]{64}", manifest_sha) is None
            or not isinstance(model_versions, dict)
            or not model_versions
            or not all(
                isinstance(key, str)
                and 1 <= len(key) <= 100
                and type(value) is int
                and value >= 0
                for key, value in model_versions.items()
            )
            or not isinstance(title, str)
            or not 1 <= len(title) <= 200
            or not isinstance(summary, list)
            or len(summary) > 20
            or not all(isinstance(value, str) and len(value) <= 500 for value in summary)
            or not isinstance(warnings, list)
            or len(warnings) > 20
            or not all(isinstance(value, str) and len(value) <= 500 for value in warnings)
            or not isinstance(content, dict)
        ):
            raise ValueError("report metadata v2 schema 不合法")
        try:
            json.dumps(content, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("report metadata v2 content 不合法") from exc
        return cls(
            report_type=report_type,
            market="TW",
            source_market_date=source,
            applicable_trading_date=applicable,
            published_at=published,
            forecast_start_date=forecast_start,
            forecast_end_date=forecast_end,
            backtest_as_of=backtest_as_of,
            data_as_of=data_as_of,
            source_manifest=manifest,
            source_manifest_sha256=manifest_sha,
            model_versions=dict(model_versions),
            title=title,
            summary=tuple(summary),
            warnings=tuple(warnings),
            content=dict(content),
        )

    def to_document(self) -> dict[str, Any]:
        timestamp = self.published_at.astimezone(datetime.timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
        return {
            "schema_version": 2,
            "kind": "stock-papi-report",
            "report_type": self.report_type,
            "market": self.market,
            "source_market_date": self.source_market_date.isoformat(),
            "applicable_trading_date": self.applicable_trading_date.isoformat(),
            "published_at": timestamp,
            "forecast_start_date": self.forecast_start_date.isoformat(),
            "forecast_end_date": self.forecast_end_date.isoformat(),
            "backtest_as_of": self.backtest_as_of.isoformat(),
            "data_as_of": self.data_as_of.isoformat(),
            "source_manifest": self.source_manifest,
            "source_manifest_sha256": self.source_manifest_sha256,
            "model_versions": dict(self.model_versions),
            "title": self.title,
            "summary": list(self.summary),
            "warnings": list(self.warnings),
            "content": dict(self.content),
        }


@dataclass
class ReportSourceManifest:
    """已驗證的台股來源 manifest 摘要。"""

    schema_version: int
    market: str
    generated_at: str
    market_as_of: datetime.date
    universe_count: int
    symbol_count: int
    failure_count: int
    failure_rate: float
    coverage: float
    failed_symbols: list[str]
    manifest_path: str
    manifest_sha256: str


@dataclass
class StockSnapshot:
    """已通過 manifest 與 gzip 驗證的個股快照。"""

    symbol: str
    name: str
    market: str
    as_of: datetime.date
    model_version: str
    daily: list[dict[str, Any]]
    backtest: dict[str, Any]
    sha256: str
    size: int
    sample_data: bool = False

    @classmethod
    def from_document(cls, document: dict[str, Any], sha256: str, size: int) -> "StockSnapshot":
        """從已驗證的 JSON 文件建立股票快照。"""
        return cls(
            symbol=str(document["symbol"]),
            name=str(document.get("name") or document["symbol"]),
            market=str(document["market"]),
            as_of=datetime.date.fromisoformat(str(document["as_of"])),
            model_version=str(document.get("model_version") or "unknown"),
            daily=[dict(row) for row in document["daily"]],
            backtest=dict(document["backtest"]),
            sha256=sha256,
            size=size,
            sample_data=document.get("sample_data") is True,
        )

    @property
    def latest(self) -> dict[str, Any]:
        """回傳最後一筆有效日資料。"""
        return self.daily[-1]


@dataclass
class LoadedReportSource:
    """來源 manifest 與其列出的已驗證股票集合。"""

    manifest: ReportSourceManifest
    stocks: list[StockSnapshot]


@dataclass
class MarketSnapshot:
    """台股市場基準與全市場模型狀態。"""

    returns: dict[int, float | None]
    volatility_20d: float | None
    average_probability: float | None
    bullish_breadth: float | None
    ma60_breadth: float | None
    high_score_ratio: float | None
    advancing_count: int
    declining_count: int
    new_high_20d_count: int
    new_low_20d_count: int
    average_volume_ratio: float | None
    model_versions: dict[str, int]
    data_warning_ratio: float | None
    option_missing_ratio: float | None
    freshness_days: int
    changes: dict[str, float | int | None]


@dataclass
class IndustrySnapshot:
    """單一產業的近期報酬、模型狀態與輪動結果。"""

    name: str
    symbols: list[str]
    component_count: int
    coverage: float
    returns: dict[int, float | None]
    valid_samples: dict[int, int]
    relative_return_5d: float | None
    relative_return_20d: float | None
    rotation: str
    average_probability: float | None
    median_probability: float | None
    bullish_breadth: float | None
    high_score_ratio: float | None
    average_volume_ratio: float | None
    average_institution_ratio: float | None
    model_versions: dict[str, int]
    rank: int
    previous_rank: int | None
    rank_change: int | None
    probability_change: float | None
    previous_rotation: str | None
    rotation_changed: bool | None
    sample_quality: str
    near_boundary: bool
    signal_profile: str


@dataclass
class IndustryBacktestResult:
    """獨立、非重疊的產業投資組合回測結果。"""

    industry: str
    sufficient: bool
    start_date: datetime.date | None
    end_date: datetime.date | None
    rebalance_dates: list[datetime.date]
    period_returns: list[float]
    buy_hold_period_returns: list[float]
    market_period_returns: list[float]
    strategy_curve: list[float]
    buy_hold_curve: list[float]
    market_curve: list[float]
    drawdown_curve: list[float]
    valid_signals: int
    cumulative_return: float | None
    annualized_return: float | None
    annualized_volatility: float | None
    max_drawdown: float | None
    sharpe: float | None
    sortino: float | None
    win_rate: float | None
    average_positions: float | None
    cash_period_ratio: float | None
    buy_hold_return: float | None
    market_return: float | None
    excess_return: float | None
    coverage: float | None
    rebalance_periods: int
    entry_periods: int
    winning_periods: int
    losing_periods: int
    cash_periods: int
    sample_quality: str
    low_sample_warning: bool
    all_cash: bool
    strategy_status: str
    average_profit: float | None
    average_loss: float | None
    expected_return: float | None
    payoff_ratio: float | None
    profit_factor: float | None
    longest_winning_streak: int
    longest_losing_streak: int
    cost_sensitivity: dict[str, float | None]
    yearly_returns: dict[int, float]
    annualization_periods: float = 252 / 5


@dataclass
class ModelQualitySnapshot:
    """以所有可驗證歷史 OOS 五日結果 pooled 計算的模型品質。"""

    pooled_oos_samples: int
    direction_accuracy: float | None
    brier_score: float | None
    high_score_samples: int
    high_score_win_rate: float | None
    calibration_bins: list[dict[str, Any]]


@dataclass
class DailyIndustryReport:
    """PDF 與發布層共用的完整台股產業日報資料。"""

    source: LoadedReportSource
    report_date: datetime.date
    generated_at: datetime.datetime
    market: MarketSnapshot
    industries: list[IndustrySnapshot]
    backtests: list[IndustryBacktestResult]
    model_quality: ModelQualitySnapshot
    watchlist: list[dict[str, Any]]
    bullish_industries: list[IndustrySnapshot]
    weak_industries: list[IndustrySnapshot]
    comparison_available: bool
    new_high_score_symbols: list[str]
    exited_high_score_symbols: list[str]
    summary: list[str]
    warnings: list[str]

    @property
    def model_versions(self) -> dict[str, int]:
        """回傳報告涵蓋的模型版本分布。"""
        return self.market.model_versions


@dataclass
class ReportGenerationResult:
    """PDF 生成與驗證結果。"""

    success: bool
    report_date: datetime.date
    output_path: Path | None
    file_size: int
    sha256: str | None
    generated_at: datetime.datetime
    warnings: list[str] = field(default_factory=list)
    error_message: str | None = None
    page_count: int = 0

    @classmethod
    def from_path(
        cls,
        path: Path,
        report_date: datetime.date,
        *,
        page_count: int,
        warnings: list[str],
    ) -> "ReportGenerationResult":
        """由已驗證檔案建立成功結果。"""
        content = Path(path).read_bytes()
        return cls(
            success=True,
            report_date=report_date,
            output_path=Path(path),
            file_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            generated_at=datetime.datetime.now(datetime.timezone.utc),
            warnings=list(warnings),
            page_count=page_count,
        )

    @classmethod
    def failure(cls, report_date: datetime.date, message: str) -> "ReportGenerationResult":
        """建立不含正式輸出路徑的失敗結果。"""
        return cls(
            success=False,
            report_date=report_date,
            output_path=None,
            file_size=0,
            sha256=None,
            generated_at=datetime.datetime.now(datetime.timezone.utc),
            error_message=str(message),
        )


def finite_number(value: Any) -> float | None:
    """將有限數字轉為 float；布林、NaN 與 Infinity 回傳 None。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None
