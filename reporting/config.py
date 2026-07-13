import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ReportTheme:
    """集中管理 Stock Papi PDF 視覺設定。"""

    background: str = "#f6efe6"
    surface: str = "#fffaf4"
    surface_secondary: str = "#fff4ea"
    line: str = "#dbcdbd"
    text: str = "#2a211b"
    muted: str = "#74685d"
    mint: str = "#7fd7c4"
    apricot: str = "#f4b58a"
    lavender: str = "#b8a6ea"
    up: str = "#d94b63"
    down: str = "#1f9a72"
    warning: str = "#c98542"
    margin_mm: float = 14.0
    chart_width_in: float = 7.0
    chart_height_in: float = 3.2
    body_font_size: float = 8.5
    small_font_size: float = 7.2
    heading_font_size: float = 18.0


def _environment_path(name: str) -> Path | None:
    value = (os.getenv(name) or "").strip()
    return Path(value) if value else None


@dataclass(frozen=True)
class ReportConfig:
    """日報驗證、分析、回測與輸出的集中設定。"""

    root: Path = Path(r"D:\StockPapiData")
    market: str = "TW"
    font_path: Path | None = field(default_factory=lambda: _environment_path("REPORT_FONT_PATH"))
    bold_font_path: Path | None = field(
        default_factory=lambda: _environment_path("REPORT_FONT_BOLD_PATH")
    )
    title_font_path: Path | None = field(
        default_factory=lambda: _environment_path("REPORT_TITLE_FONT_PATH")
    )
    theme: ReportTheme = field(default_factory=ReportTheme)
    prediction_horizon: int = 5
    entry_threshold: float = 60.0
    weak_threshold: float = 45.0
    rotation_neutral_threshold_pct: float = 0.20
    ma_near_threshold: float = 0.005
    round_trip_cost: float = 0.00585
    min_industry_coverage: float = 0.5
    min_backtest_periods: int = 12
    max_gzip_bytes: int = 10 * 1024 * 1024
    max_uncompressed_bytes: int = 50 * 1024 * 1024
    max_pdf_bytes: int = 15 * 1024 * 1024
    max_index_bytes: int = 1024 * 1024
    target_pdf_bytes: int = 8 * 1024 * 1024
    market_factor_tolerance: float = 0.02
    max_watchlist: int = 10
    index_history_days: int = 365

    def __post_init__(self) -> None:
        if self.market != "TW":
            raise ValueError("第一階段只支援 TW 日報")
        if (
            self.prediction_horizon != 5
            or self.entry_threshold != 60.0
            or self.weak_threshold != 45.0
        ):
            raise ValueError("日報不得改寫既有五日模型門檻")
        if self.round_trip_cost != 0.00585:
            raise ValueError("日報交易成本必須維持 0.585%")
