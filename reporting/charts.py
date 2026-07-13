import io

from .config import ReportConfig
from .schemas import DailyIndustryReport, IndustryBacktestResult


def _plot_modules(font_path):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.font_manager import FontProperties

    plt.rcParams["axes.unicode_minus"] = False
    return plt, FontProperties(fname=str(font_path))


def _png(fig, plt) -> io.BytesIO:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=180, bbox_inches="tight", facecolor="#fffaf4")
    plt.close(fig)
    buffer.seek(0)
    return buffer


def market_quality_chart(report: DailyIndustryReport, config: ReportConfig) -> io.BytesIO:
    """以兩張小圖呈現市場報酬與廣度，避免固定表格留下空白。"""
    plt, font = _plot_modules(config.font_path)
    fig, (returns_axis, breadth_axis) = plt.subplots(
        1, 2, figsize=(config.theme.chart_width_in, 2.4), facecolor=config.theme.surface
    )
    periods = (1, 5, 20, 60)
    returns = [report.market.returns.get(period) for period in periods]
    return_values = [value * 100 if value is not None else 0 for value in returns]
    returns_axis.bar(
        [f"{period}日" for period in periods],
        return_values,
        color=[config.theme.up if value >= 0 else config.theme.down for value in return_values],
    )
    returns_axis.axhline(0, color=config.theme.line, linewidth=0.8)
    returns_axis.set_title("市場近期報酬", fontproperties=font, fontsize=10)
    returns_axis.set_ylabel("%", fontproperties=font, fontsize=8)

    breadth_labels = ["MA20", "MA60", "高分訊號"]
    breadth = [
        report.market.bullish_breadth,
        report.market.ma60_breadth,
        report.market.high_score_ratio,
    ]
    breadth_values = [value * 100 if value is not None else 0 for value in breadth]
    breadth_axis.barh(
        breadth_labels,
        breadth_values,
        color=[config.theme.mint, config.theme.apricot, config.theme.lavender],
    )
    breadth_axis.set_xlim(0, 100)
    breadth_axis.set_title("市場廣度與模型高分", fontproperties=font, fontsize=10)
    breadth_axis.set_xlabel("%", fontproperties=font, fontsize=8)
    for index, value in enumerate(breadth_values):
        breadth_axis.text(value + 1, index, f"{value:.1f}%", fontproperties=font, fontsize=7)
    for axis in (returns_axis, breadth_axis):
        axis.set_facecolor(config.theme.surface)
        axis.tick_params(labelsize=7, colors=config.theme.muted)
        axis.grid(alpha=0.15)
        for label in axis.get_xticklabels() + axis.get_yticklabels():
            label.set_fontproperties(font)
    fig.tight_layout()
    return _png(fig, plt)


def rotation_chart(report: DailyIndustryReport, config: ReportConfig) -> io.BytesIO:
    """繪製含四象限背景、中性帶與樣本泡泡圖例的產業輪動圖。"""
    plt, font = _plot_modules(config.font_path)
    fig, axis = plt.subplots(
        figsize=(config.theme.chart_width_in, config.theme.chart_height_in),
        facecolor=config.theme.surface,
    )
    axis.set_facecolor(config.theme.surface)
    colors = {
        "leading": config.theme.up,
        "improving": config.theme.apricot,
        "weakening": config.theme.lavender,
        "lagging": config.theme.down,
    }
    plotted = [
        item for item in report.industries
        if item.coverage >= config.min_industry_coverage
        and item.relative_return_5d is not None
        and item.relative_return_20d is not None
    ]
    values = [
        abs(value * 100)
        for item in plotted
        for value in (item.relative_return_20d or 0, item.relative_return_5d or 0)
    ]
    limit = max(0.5, max(values, default=0.5) * 1.25)
    axis.set_xlim(-limit, limit)
    axis.set_ylim(-limit, limit)
    axis.axvspan(0, limit, ymin=0.5, ymax=1, color=config.theme.mint, alpha=0.10)
    axis.axvspan(-limit, 0, ymin=0.5, ymax=1, color=config.theme.apricot, alpha=0.10)
    axis.axvspan(0, limit, ymin=0, ymax=0.5, color=config.theme.lavender, alpha=0.10)
    axis.axvspan(-limit, 0, ymin=0, ymax=0.5, color=config.theme.down, alpha=0.06)
    neutral = config.rotation_neutral_threshold_pct
    axis.axvspan(-neutral, neutral, color=config.theme.line, alpha=0.18)
    axis.axhspan(-neutral, neutral, color=config.theme.line, alpha=0.18)
    offsets = ((5, 6), (-8, 6), (5, -10), (-8, -10))
    for index, item in enumerate(plotted):
        x = item.relative_return_20d * 100
        y = item.relative_return_5d * 100
        axis.scatter(
            x,
            y,
            s=max(35, item.valid_samples.get(5, 0) * 10),
            color=colors[item.rotation],
            alpha=0.82,
            edgecolors=config.theme.text,
            linewidths=0.4,
        )
        axis.annotate(
            item.name,
            (x, y),
            xytext=offsets[index % len(offsets)],
            textcoords="offset points",
            fontproperties=font,
            fontsize=6.5,
            color=config.theme.text,
        )
    for samples in (2, 5, 10):
        axis.scatter([], [], s=samples * 10, color=config.theme.mint, alpha=0.5, label=f"{samples} 檔")
    axis.legend(prop=font, fontsize=6, frameon=False, title="有效樣本", title_fontproperties=font)
    axis.axhline(0, color=config.theme.line, linewidth=1)
    axis.axvline(0, color=config.theme.line, linewidth=1)
    quadrant_positions = {
        "改善": (-limit * 0.92, limit * 0.86),
        "領先": (limit * 0.65, limit * 0.86),
        "落後": (-limit * 0.92, -limit * 0.92),
        "衰退": (limit * 0.65, -limit * 0.92),
    }
    for label, (x, y) in quadrant_positions.items():
        axis.text(x, y, label, fontproperties=font, fontsize=8, color=config.theme.muted)
    axis.set_xlabel("20 日相對大盤報酬（%）", fontproperties=font, color=config.theme.text)
    axis.set_ylabel("5 日相對大盤報酬（%）", fontproperties=font, color=config.theme.text)
    axis.set_title("產業輪動象限", fontproperties=font, color=config.theme.text, fontsize=13)
    axis.tick_params(colors=config.theme.muted, labelsize=7)
    axis.grid(alpha=0.15)
    fig.tight_layout()
    return _png(fig, plt)


def return_ranking_chart(report: DailyIndustryReport, config: ReportConfig) -> io.BytesIO:
    """繪製產業五日上漲機率前五與後五名。"""
    plt, font = _plot_modules(config.font_path)
    candidates = [item for item in report.industries if item.average_probability is not None]
    candidates.sort(key=lambda item: item.average_probability or 0.0)
    selected = candidates[:5] + candidates[-5:]
    unique = {item.name: item for item in selected}
    selected = sorted(unique.values(), key=lambda item: item.average_probability or 0.0)
    fig, axis = plt.subplots(
        figsize=(config.theme.chart_width_in, config.theme.chart_height_in),
        facecolor=config.theme.surface,
    )
    values = [item.average_probability or 0.0 for item in selected]
    axis.barh(
        range(len(selected)),
        values,
        color=[
            config.theme.up if value >= config.entry_threshold
            else config.theme.down if value <= config.weak_threshold
            else config.theme.lavender
            for value in values
        ],
    )
    axis.set_yticks(range(len(selected)))
    axis.set_yticklabels([item.name for item in selected], fontproperties=font, fontsize=7)
    axis.set_xlim(0, 100)
    axis.set_xlabel("五日上漲機率（%）", fontproperties=font)
    axis.set_title("產業五日上漲機率前五與後五", fontproperties=font, fontsize=13)
    axis.axvline(config.entry_threshold, color=config.theme.up, linewidth=1, linestyle="--")
    axis.axvline(config.weak_threshold, color=config.theme.down, linewidth=1, linestyle="--")
    axis.grid(axis="x", alpha=0.15)
    fig.tight_layout()
    return _png(fig, plt)


def backtest_chart(result: IndustryBacktestResult, config: ReportConfig) -> io.BytesIO:
    """以實際再平衡日期繪製單一代表產業的淨值與回撤。"""
    plt, font = _plot_modules(config.font_path)
    from matplotlib import dates as mdates

    fig, (equity, drawdown) = plt.subplots(
        2,
        1,
        figsize=(config.theme.chart_width_in, config.theme.chart_height_in + 0.7),
        gridspec_kw={"height_ratios": [3, 1]},
        facecolor=config.theme.surface,
    )
    labels = (
        (result.strategy_curve, "策略淨值", config.theme.up),
        (result.buy_hold_curve, "產業買進持有", config.theme.apricot),
        (result.market_curve, "市場基準", config.theme.lavender),
    )
    for curve, label, color in labels:
        equity.plot(result.rebalance_dates, curve, label=label, color=color, linewidth=1.5)
    equity.set_title(
        f"{result.industry}｜{result.start_date} 至 {result.end_date}｜"
        f"再平衡 {result.rebalance_periods}｜進場 {result.entry_periods}｜{result.sample_quality}",
        fontproperties=font,
        fontsize=9,
    )
    equity.legend(prop=font, fontsize=7, frameon=False)
    equity.grid(alpha=0.15)
    drawdown.fill_between(
        result.rebalance_dates,
        [value * 100 for value in result.drawdown_curve],
        color=config.theme.down,
        alpha=0.35,
    )
    drawdown.set_ylabel("回撤 %", fontproperties=font, fontsize=7)
    drawdown.grid(alpha=0.15)
    locator = mdates.AutoDateLocator(minticks=3, maxticks=7)
    formatter = mdates.ConciseDateFormatter(locator)
    for axis in (equity, drawdown):
        axis.xaxis.set_major_locator(locator)
        axis.xaxis.set_major_formatter(formatter)
        axis.tick_params(labelsize=7, colors=config.theme.muted)
    fig.tight_layout()
    return _png(fig, plt)
