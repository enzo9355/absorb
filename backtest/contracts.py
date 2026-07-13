"""回測六層共用的不可變資料契約。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence


def require_timezone(value: datetime, name: str) -> None:
    """拒絕沒有時區的時間，避免跨市場日期被靜默錯置。"""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} 必須帶有時區")


def require_finite(value: float, name: str, *, minimum: float | None = None) -> None:
    """驗證金額、價格與數量的基本數值邊界。"""
    if not math.isfinite(value) or (minimum is not None and value < minimum):
        raise ValueError(f"{name} 不合法")


def parse_timezone_datetime(value: str, name: str) -> datetime:
    """解析 JSON 時間字串並拒絕遺失時區的值。"""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} 格式不合法") from exc
    require_timezone(parsed, name)
    return parsed


def _json_value(value: object) -> object:
    """將快照內容轉為 JSON 可序列化的不可變純值。"""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        require_finite(value, "JSON float")
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise ValueError("快照內容包含不可 JSON 序列化的型別")


class TradingStatus(str, Enum):
    """市場資料是否可供實際成交。"""

    NORMAL = "NORMAL"
    SUSPENDED = "SUSPENDED"
    DELISTED = "DELISTED"
    MISSING = "MISSING"


class SignalAction(str, Enum):
    """訊號層可輸出的動作。"""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class OrderSide(str, Enum):
    """訂單方向。"""

    BUY = "BUY"
    SELL = "SELL"


class ExecutionStatus(str, Enum):
    """撮合結果是否真正成交。"""

    FILLED = "FILLED"
    REJECTED = "REJECTED"


class EventSeverity(str, Enum):
    """資料管線營運事件的告警分級。"""

    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class MarketBar:
    """帶有資訊可得時間與實際交易時間的單根行情。"""

    symbol: str
    market_time: datetime
    data_available_time: datetime
    tradable_at: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    status: TradingStatus = TradingStatus.NORMAL

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol 不可為空")
        for name in ("market_time", "data_available_time", "tradable_at"):
            require_timezone(getattr(self, name), name)
        if self.market_time > self.data_available_time:
            raise ValueError("market_time 不可晚於 data_available_time")
        for name in ("open_price", "high_price", "low_price", "close_price"):
            require_finite(getattr(self, name), name, minimum=0.0)
        require_finite(self.volume, "volume", minimum=0.0)
        if self.low_price > self.high_price:
            raise ValueError("low_price 不可高於 high_price")


@dataclass(frozen=True, slots=True)
class TimedObservation:
    """新聞、營收與籌碼等非價格資料的可得時間描述。"""

    symbol: str
    market_time: datetime
    published_at: datetime
    data_available_time: datetime
    source: str
    values: Mapping[str, float]
    carry_forward: bool = True

    def __post_init__(self) -> None:
        if not self.symbol or not self.source:
            raise ValueError("symbol 與 source 不可為空")
        for name in ("market_time", "published_at", "data_available_time"):
            require_timezone(getattr(self, name), name)
        if self.published_at > self.data_available_time:
            raise ValueError("published_at 不可晚於 data_available_time")
        frozen_values = {str(name): float(value) for name, value in self.values.items()}
        for name, value in frozen_values.items():
            require_finite(value, f"values[{name}]")
        object.__setattr__(self, "values", MappingProxyType(frozen_values))


@dataclass(frozen=True, slots=True)
class UniverseMembership:
    """Universe 成份的生效區間，保留 Phase 3 的存活者偏差處理入口。"""

    symbol: str
    effective_from: datetime
    effective_to: datetime | None
    data_available_time: datetime
    data_version: str = "unknown"

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol 不可為空")
        if not self.data_version:
            raise ValueError("data_version 不可為空")
        require_timezone(self.effective_from, "effective_from")
        require_timezone(self.data_available_time, "data_available_time")
        if self.effective_to is not None:
            require_timezone(self.effective_to, "effective_to")
            if self.effective_to < self.effective_from:
                raise ValueError("effective_to 不可早於 effective_from")


@dataclass(frozen=True, slots=True)
class DataGapMarker:
    """資料來源未覆蓋歷史 Universe、下市或交易狀態時的明確標記。"""

    kind: str
    symbol: str
    target_time: datetime
    reason: str

    def __post_init__(self) -> None:
        if not self.kind or not self.symbol or not self.reason:
            raise ValueError("DataGapMarker 必要欄位不可為空")
        require_timezone(self.target_time, "target_time")


@dataclass(frozen=True, slots=True)
class PointInTimeSnapshot:
    """可追溯單次計算上下文的 JSON 快照。"""

    generated_at: datetime
    cutoff_time: datetime
    model_version: str
    feature_version: str
    symbol_universe: tuple[str, ...]
    features_data: Mapping[str, object]
    data_available_time: datetime
    schema_version: str = "3.0"
    snapshot_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != "3.0":
            raise ValueError("Phase 3A 快照 schema_version 必須為 3.0")
        if self.snapshot_version < 1:
            raise ValueError("snapshot_version 必須大於零")
        for name in ("generated_at", "cutoff_time", "data_available_time"):
            require_timezone(getattr(self, name), name)
        if self.data_available_time > self.cutoff_time:
            raise ValueError("data_available_time 不可晚於 cutoff_time")
        if self.cutoff_time > self.generated_at:
            raise ValueError("cutoff_time 不可晚於 generated_at")
        if not self.model_version or not self.feature_version:
            raise ValueError("model_version 與 feature_version 不可為空")
        universe = tuple(sorted({str(symbol) for symbol in self.symbol_universe if symbol}))
        if len(universe) != len(self.symbol_universe):
            raise ValueError("symbol_universe 不可包含空值或重複標的")
        normalized_data = _json_value(self.features_data)
        if not isinstance(normalized_data, dict):
            raise ValueError("features_data 必須為物件")
        unknown_symbols = set(normalized_data) - set(universe)
        if unknown_symbols:
            raise ValueError("features_data 不可包含 Universe 外標的")
        object.__setattr__(self, "symbol_universe", universe)
        object.__setattr__(self, "features_data", MappingProxyType(normalized_data))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at.isoformat(),
            "cutoff_time": self.cutoff_time.isoformat(),
            "model_version": self.model_version,
            "feature_version": self.feature_version,
            "symbol_universe": list(self.symbol_universe),
            "features_data": _json_value(self.features_data),
            "data_available_time": self.data_available_time.isoformat(),
            "snapshot_version": self.snapshot_version,
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, object]) -> "PointInTimeSnapshot":
        try:
            return cls(
                schema_version=str(document["schema_version"]),
                generated_at=parse_timezone_datetime(str(document["generated_at"]), "generated_at"),
                cutoff_time=parse_timezone_datetime(str(document["cutoff_time"]), "cutoff_time"),
                model_version=str(document["model_version"]),
                feature_version=str(document["feature_version"]),
                symbol_universe=tuple(document["symbol_universe"]),  # type: ignore[arg-type]
                features_data=document["features_data"],  # type: ignore[arg-type]
                data_available_time=parse_timezone_datetime(
                    str(document["data_available_time"]), "data_available_time"
                ),
                snapshot_version=int(document.get("snapshot_version", 1)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("快照 JSON schema 不合法") from exc


@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    """正式 manifest 與歷史版本鏈的節點。"""

    manifest_id: str
    generated_at: datetime
    snapshot_path: str
    snapshot_sha256: str
    snapshot_size: int
    symbol_count: int
    manifest_path: str
    previous_manifest_path: str | None
    schema_version: str = "3.0"
    manifest_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != "3.0":
            raise ValueError("manifest schema_version 必須為 3.0")
        if self.manifest_version < 1:
            raise ValueError("manifest_version 必須大於零")
        if not self.manifest_id or not self.snapshot_path or not self.manifest_path:
            raise ValueError("manifest 路徑與識別欄位不可為空")
        require_timezone(self.generated_at, "generated_at")
        if len(self.snapshot_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.snapshot_sha256
        ):
            raise ValueError("snapshot_sha256 不合法")
        if self.snapshot_size <= 0 or self.symbol_count < 0:
            raise ValueError("manifest 大小或標的數不合法")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "generated_at": self.generated_at.isoformat(),
            "snapshot_path": self.snapshot_path,
            "snapshot_sha256": self.snapshot_sha256,
            "snapshot_size": self.snapshot_size,
            "symbol_count": self.symbol_count,
            "manifest_path": self.manifest_path,
            "previous_manifest_path": self.previous_manifest_path,
            "manifest_version": self.manifest_version,
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, object]) -> "SnapshotManifest":
        try:
            previous = document.get("previous_manifest_path")
            snapshot_sha256 = document.get("snapshot_sha256")
            if snapshot_sha256 is None:
                snapshot_sha256 = document["sha256"]
            return cls(
                schema_version=str(document["schema_version"]),
                manifest_id=str(document["manifest_id"]),
                generated_at=parse_timezone_datetime(str(document["generated_at"]), "generated_at"),
                snapshot_path=str(document["snapshot_path"]),
                snapshot_sha256=str(snapshot_sha256),
                snapshot_size=int(document["snapshot_size"]),
                symbol_count=int(document["symbol_count"]),
                manifest_path=str(document["manifest_path"]),
                previous_manifest_path=str(previous) if previous else None,
                manifest_version=int(document.get("manifest_version", 1)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("manifest JSON schema 不合法") from exc


@dataclass(frozen=True, slots=True)
class Manifest:
    """多快照發布情境可使用的通用 manifest 結構。"""

    manifest_version: int
    generated_at: datetime
    snapshots: Mapping[str, Mapping[str, str]]
    previous_manifest_path: str | None

    def __post_init__(self) -> None:
        if self.manifest_version < 1:
            raise ValueError("manifest_version 必須大於零")
        require_timezone(self.generated_at, "generated_at")
        snapshots: dict[str, Mapping[str, str]] = {}
        for symbol, item in self.snapshots.items():
            if not isinstance(item, Mapping):
                raise ValueError("snapshots 的各標的內容必須為物件")
            snapshots[str(symbol)] = MappingProxyType(
                {str(name): str(value) for name, value in item.items()}
            )
        for symbol, item in snapshots.items():
            if not symbol or not item.get("path") or not item.get("sha256"):
                raise ValueError("snapshots 必須包含 path 與 sha256")
        object.__setattr__(self, "snapshots", MappingProxyType(snapshots))

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest_version": self.manifest_version,
            "generated_at": self.generated_at.isoformat(),
            "snapshots": _json_value(self.snapshots),
            "previous_manifest_path": self.previous_manifest_path,
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, object]) -> "Manifest":
        try:
            snapshots = document["snapshots"]
            if not isinstance(snapshots, Mapping):
                raise TypeError("snapshots 必須為物件")
            previous = document.get("previous_manifest_path")
            return cls(
                manifest_version=int(document["manifest_version"]),
                generated_at=parse_timezone_datetime(str(document["generated_at"]), "generated_at"),
                snapshots=snapshots,  # type: ignore[arg-type]
                previous_manifest_path=str(previous) if previous else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("通用 manifest JSON schema 不合法") from exc


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """快照驗證結果與檢查時間。"""

    is_valid: bool
    errors: list[str]
    checked_at: datetime

    def __post_init__(self) -> None:
        require_timezone(self.checked_at, "checked_at")


@dataclass(frozen=True, slots=True)
class PipelineEvent:
    """可被日誌與通知管道傳遞的結構化營運事件。"""

    event_id: str
    event_type: str
    severity: EventSeverity
    timestamp: datetime
    details: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.event_id or not self.event_type:
            raise ValueError("event_id 與 event_type 不可為空")
        try:
            severity = EventSeverity(self.severity)
        except (TypeError, ValueError) as exc:
            raise ValueError("severity 不合法") from exc
        require_timezone(self.timestamp, "timestamp")
        normalized_details = _json_value(self.details)
        if not isinstance(normalized_details, dict):
            raise ValueError("details 必須為 JSON 物件")
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "details", MappingProxyType(normalized_details))

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "severity": self.severity.value,
            "timestamp": self.timestamp.isoformat(),
            "details": _json_value(self.details),
        }


@dataclass(frozen=True, slots=True)
class SessionTimes:
    """缺失日補值時使用的交易時段時間。"""

    market_time: datetime
    data_available_time: datetime
    tradable_at: datetime

    def __post_init__(self) -> None:
        for name in ("market_time", "data_available_time", "tradable_at"):
            require_timezone(getattr(self, name), name)
        if self.market_time > self.data_available_time:
            raise ValueError("market_time 不可晚於 data_available_time")


@dataclass(frozen=True, slots=True)
class FeatureRow:
    """在特定截止時間可取得的特徵列。"""

    symbol: str
    feature_time: datetime
    data_available_time: datetime
    source_available_through: datetime
    feature_version: str
    values: Mapping[str, float]

    def __post_init__(self) -> None:
        if not self.symbol or not self.feature_version:
            raise ValueError("symbol 與 feature_version 不可為空")
        for name in ("feature_time", "data_available_time", "source_available_through"):
            require_timezone(getattr(self, name), name)
        if self.source_available_through > self.data_available_time:
            raise ValueError("特徵使用了尚不可得的資料")
        frozen_values = {str(name): float(value) for name, value in self.values.items()}
        for name, value in frozen_values.items():
            require_finite(value, f"values[{name}]")
        object.__setattr__(self, "values", MappingProxyType(frozen_values))


@dataclass(frozen=True, slots=True)
class FeatureFrame:
    """Feature Layer 的純資料輸出，不依賴 pandas。"""

    rows: tuple[FeatureRow, ...]

    def __post_init__(self) -> None:
        if tuple(sorted(self.rows, key=lambda row: row.data_available_time)) != self.rows:
            raise ValueError("FeatureFrame 必須依 data_available_time 排序")


@dataclass(frozen=True, slots=True)
class Signal:
    """訊號層輸出，刻意不包含任何成交價格或持倉狀態。"""

    symbol: str
    signal_time: datetime
    data_available_time: datetime
    action: SignalAction
    signal_value: float
    target_weight: float
    model_version: str
    feature_version: str

    def __post_init__(self) -> None:
        if not self.symbol or not self.model_version or not self.feature_version:
            raise ValueError("訊號必要識別欄位不可為空")
        require_timezone(self.signal_time, "signal_time")
        require_timezone(self.data_available_time, "data_available_time")
        if self.data_available_time > self.signal_time:
            raise ValueError("訊號不可早於資料可得時間")
        require_finite(self.signal_value, "signal_value")
        require_finite(self.target_weight, "target_weight", minimum=0.0)
        if self.target_weight > 1.0:
            raise ValueError("Phase 2A 不允許超過 100% 的目標權重")


@dataclass(frozen=True, slots=True)
class Order:
    """由訊號轉出的訂單，不包含執行層結果。"""

    symbol: str
    order_time: datetime
    signal_time: datetime
    data_available_time: datetime
    side: OrderSide
    requested_quantity: float
    volatility: float
    reason: str

    def __post_init__(self) -> None:
        if not self.symbol or not self.reason:
            raise ValueError("訂單必要識別欄位不可為空")
        for name in ("order_time", "signal_time", "data_available_time"):
            require_timezone(getattr(self, name), name)
        if not self.data_available_time <= self.signal_time <= self.order_time:
            raise ValueError("訂單時間順序不合法")
        require_finite(self.requested_quantity, "requested_quantity", minimum=0.0)
        if self.requested_quantity == 0:
            raise ValueError("requested_quantity 必須大於零")
        require_finite(self.volatility, "volatility", minimum=0.0)


@dataclass(frozen=True, slots=True)
class TradeExecution:
    """Execution Layer 的成交結果，Portfolio 只接受這個物件更新帳戶。"""

    symbol: str
    side: OrderSide
    order_time: datetime
    signal_time: datetime
    fill_time: datetime
    reference_price: float
    fill_price: float
    requested_quantity: float
    filled_quantity: float
    commission: float
    tax: float
    slippage: float
    notional: float
    status: ExecutionStatus = ExecutionStatus.FILLED

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol 不可為空")
        for name in ("order_time", "signal_time", "fill_time"):
            require_timezone(getattr(self, name), name)
        if self.fill_time <= self.order_time:
            raise ValueError("成交時間必須晚於下單時間")
        for name in (
            "reference_price",
            "fill_price",
            "requested_quantity",
            "filled_quantity",
            "commission",
            "tax",
            "slippage",
            "notional",
        ):
            require_finite(getattr(self, name), name, minimum=0.0)
        if self.status is ExecutionStatus.FILLED:
            if not 0.0 < self.filled_quantity <= self.requested_quantity:
                raise ValueError("成交數量不合法")
        elif (
            self.filled_quantity != 0.0
            or self.fill_price != 0.0
            or self.commission != 0.0
            or self.tax != 0.0
            or self.slippage != 0.0
            or self.notional != 0.0
        ):
            raise ValueError("拒絕訂單不可包含成交成本或數量")


@dataclass(frozen=True, slots=True)
class PortfolioState:
    """不可為負的現金帳戶與多頭持倉快照。"""

    cash: float
    positions: Mapping[str, float]
    average_costs: Mapping[str, float]
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    cumulative_costs: float
    updated_at: datetime

    def __post_init__(self) -> None:
        require_timezone(self.updated_at, "updated_at")
        for name in ("cash", "equity", "cumulative_costs"):
            require_finite(getattr(self, name), name, minimum=0.0)
        require_finite(self.realized_pnl, "realized_pnl")
        require_finite(self.unrealized_pnl, "unrealized_pnl")
        positions = {str(symbol): float(quantity) for symbol, quantity in self.positions.items()}
        costs = {str(symbol): float(cost) for symbol, cost in self.average_costs.items()}
        if set(positions) != set(costs):
            raise ValueError("positions 與 average_costs 必須對應")
        for symbol, quantity in positions.items():
            require_finite(quantity, f"positions[{symbol}]", minimum=0.0)
            if quantity == 0:
                raise ValueError("positions 不可保存零部位")
            require_finite(costs[symbol], f"average_costs[{symbol}]", minimum=0.0)
        object.__setattr__(self, "positions", MappingProxyType(positions))
        object.__setattr__(self, "average_costs", MappingProxyType(costs))


@dataclass(frozen=True, slots=True)
class DailyLedger:
    """每日收盤後的帳戶估值，用於績效分析。"""

    valuation_time: datetime
    cash: float
    equity: float
    gross_equity: float
    realized_pnl: float
    unrealized_pnl: float
    cumulative_costs: float

    def __post_init__(self) -> None:
        require_timezone(self.valuation_time, "valuation_time")
        for name in ("cash", "equity", "gross_equity", "cumulative_costs"):
            require_finite(getattr(self, name), name, minimum=0.0)
        require_finite(self.realized_pnl, "realized_pnl")
        require_finite(self.unrealized_pnl, "unrealized_pnl")


@dataclass(frozen=True, slots=True)
class ExecutionCostConfig:
    """手續費、稅、流動性與滑價的可注入設定。"""

    commission_rate: float = 0.0
    commission_discount: float = 1.0
    minimum_commission: float = 0.0
    sell_tax_rate: float = 0.0
    per_share_commission: float = 0.0
    participation_rate: float = 0.1
    base_slippage: float = 0.0
    impact_coefficient: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "commission_rate",
            "commission_discount",
            "minimum_commission",
            "sell_tax_rate",
            "per_share_commission",
            "base_slippage",
            "impact_coefficient",
        ):
            require_finite(getattr(self, name), name, minimum=0.0)
        require_finite(self.participation_rate, "participation_rate", minimum=0.0)
        if self.participation_rate > 1.0:
            raise ValueError("participation_rate 不可超過 1")


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """調度器的日頻、多頭、現金帳戶設定。"""

    initial_cash: float
    requested_quantity: float = 1.0
    risk_free_rate: float = 0.0
    trading_days_per_year: int = 252

    def __post_init__(self) -> None:
        require_finite(self.initial_cash, "initial_cash", minimum=0.0)
        if self.initial_cash == 0:
            raise ValueError("initial_cash 必須大於零")
        require_finite(self.requested_quantity, "requested_quantity", minimum=0.0)
        if self.requested_quantity == 0:
            raise ValueError("requested_quantity 必須大於零")
        require_finite(self.risk_free_rate, "risk_free_rate")
        if self.trading_days_per_year <= 0:
            raise ValueError("trading_days_per_year 必須大於零")


class MarketDataSource(Protocol):
    """Data Layer 的市場資料來源介面。"""

    def bars_until(self, symbol: str, cutoff: datetime) -> list[MarketBar]:
        ...

    def get_trading_status(self, symbol: str, target_date: datetime) -> TradingStatus:
        ...


class UniverseSource(Protocol):
    """Universe 的 point-in-time 成份介面。"""

    def get_active_symbols(self, target_date: datetime) -> list[str]:
        ...


class FeatureBuilder(Protocol):
    """Feature Layer 的計算介面。"""

    def build(
        self,
        bars: Sequence[MarketBar],
        observations: Sequence[TimedObservation],
        cutoff: datetime,
    ) -> FeatureFrame:
        ...


class SignalProvider(Protocol):
    """Signal Layer 的模型或既有 OOS 訊號介面。"""

    def generate(self, features: FeatureFrame) -> tuple[Signal, ...]:
        ...


class ExecutionModel(Protocol):
    """Execution Layer 只產生成交，不得接受 Portfolio。"""

    def execute(self, order: Order, bar: MarketBar) -> TradeExecution | None:
        ...
