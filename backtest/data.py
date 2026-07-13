"""Data Layer：市場資料的時間治理與狀態標記。"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Iterable, Sequence

from .contracts import (
    DataGapMarker,
    MarketBar,
    SessionTimes,
    TradingStatus,
    UniverseMembership,
    require_timezone,
)


def normalize_bars(bars: Iterable[MarketBar]) -> tuple[MarketBar, ...]:
    """依資料可得時間排序並拒絕同一標的的重複時點。"""
    normalized = tuple(sorted(bars, key=lambda bar: (bar.market_time, bar.symbol)))
    seen: set[tuple[str, datetime]] = set()
    for bar in normalized:
        key = (bar.symbol, bar.market_time)
        if key in seen:
            raise ValueError("同一 symbol 與 market_time 不可重複")
        seen.add(key)
    return normalized


def bars_available_until(
    bars: Sequence[MarketBar], cutoff: datetime
) -> tuple[MarketBar, ...]:
    """只保留 cutoff 時已可取得的行情，避免 Feature Layer 看到未來列。"""
    require_timezone(cutoff, "cutoff")
    return tuple(
        bar
        for bar in normalize_bars(bars)
        if bar.market_time <= cutoff and bar.data_available_time <= cutoff
    )


def forward_fill_missing_bars(
    symbol: str,
    bars: Sequence[MarketBar],
    sessions: Sequence[SessionTimes],
) -> tuple[MarketBar, ...]:
    """以前一個已知收盤價補上缺失交易日，並固定標記為停牌且零成交量。"""
    if not symbol:
        raise ValueError("symbol 不可為空")
    current = {bar.market_time: bar for bar in normalize_bars(bars) if bar.symbol == symbol}
    result: list[MarketBar] = []
    previous: MarketBar | None = None
    for session in sorted(sessions, key=lambda item: item.market_time):
        bar = current.get(session.market_time)
        if bar is None:
            if previous is None:
                raise ValueError("第一個交易時段缺少可供 forward fill 的價格")
            bar = MarketBar(
                symbol=symbol,
                market_time=session.market_time,
                data_available_time=session.data_available_time,
                tradable_at=session.tradable_at,
                open_price=previous.close_price,
                high_price=previous.close_price,
                low_price=previous.close_price,
                close_price=previous.close_price,
                volume=0.0,
                status=TradingStatus.SUSPENDED,
            )
        result.append(bar)
        previous = bar
    return tuple(result)


class InMemoryMarketDataSource:
    """供單元測試與 Shadow 模式使用的純記憶體資料來源。"""

    def __init__(self, bars: Sequence[MarketBar]) -> None:
        self._bars = normalize_bars(bars)
        self._gap_markers: list[DataGapMarker] = []

    def bars_until(self, symbol: str, cutoff: datetime) -> list[MarketBar]:
        return list(
            bar
            for bar in bars_available_until(self._bars, cutoff)
            if bar.symbol == symbol
        )

    @property
    def gap_markers(self) -> tuple[DataGapMarker, ...]:
        return tuple(self._gap_markers)

    def get_trading_status(self, symbol: str, target_date: datetime) -> TradingStatus:
        """回傳已知交易狀態；缺資料時明確標記並採目前仍存活的保守 fallback。"""
        require_timezone(target_date, "target_date")
        matching = [
            bar
            for bar in self._bars
            if bar.symbol == symbol and bar.market_time.date() == target_date.date()
        ]
        if matching:
            return matching[-1].status
        marker = DataGapMarker(
            kind="TRADING_STATUS",
            symbol=symbol,
            target_time=target_date,
            reason="資料源沒有歷史停牌或下市狀態，暫以目前活躍股處理",
        )
        self._gap_markers.append(marker)
        logging.getLogger(__name__).warning("%s", marker.reason)
        return TradingStatus.NORMAL


class StaticUniverseSource:
    """以生效區間保存的 point-in-time Universe 實作。"""

    def __init__(self, memberships: Sequence[UniverseMembership]) -> None:
        self._memberships = tuple(memberships)

    def get_active_symbols(self, target_date: datetime) -> list[str]:
        require_timezone(target_date, "target_date")
        members = {
            item.symbol
            for item in self._memberships
            if item.data_available_time <= target_date
            and item.effective_from <= target_date
            and (item.effective_to is None or target_date <= item.effective_to)
        }
        return sorted(members)

    def members_at(self, cutoff: datetime) -> list[str]:
        """保留 Phase 2A 的舊名稱，避免既有 adapter 失效。"""
        return self.get_active_symbols(cutoff)


class CurrentUniverseFallback:
    """沒有歷史成分資料時，明確警告並回傳當前活躍股票池。"""

    def __init__(self, current_symbols: Sequence[str]) -> None:
        self._current_symbols = tuple(sorted({str(symbol) for symbol in current_symbols if symbol}))
        self._gap_markers: list[DataGapMarker] = []

    @property
    def gap_markers(self) -> tuple[DataGapMarker, ...]:
        return tuple(self._gap_markers)

    def get_active_symbols(self, target_date: datetime) -> list[str]:
        require_timezone(target_date, "target_date")
        marker = DataGapMarker(
            kind="UNIVERSE_MEMBERSHIP",
            symbol="*",
            target_time=target_date,
            reason="歷史 Universe 資料未提供，暫使用當前股票池，結果可能有生存者偏差",
        )
        self._gap_markers.append(marker)
        logging.getLogger(__name__).warning("%s", marker.reason)
        return list(self._current_symbols)
