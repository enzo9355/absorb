import datetime
import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
