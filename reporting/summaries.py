from .schemas import IndustrySnapshot, MarketSnapshot


def deterministic_summary(
    market: MarketSnapshot,
    industries: list[IndustrySnapshot],
    bullish: list[IndustrySnapshot],
    weak: list[IndustrySnapshot],
    warnings: list[str],
    *,
    comparison_available: bool,
    new_high_scores: list[str],
    exited_high_scores: list[str],
) -> list[str]:
    """只依已驗證輸入產生可稽核、使用絕對門檻的每日摘要。"""
    result = []
    if market.returns.get(5) is not None and market.bullish_breadth is not None:
        result.append(
            f"市場判讀：大盤近五日報酬 {market.returns[5]:.2%}，"
            f"站上 MA20 比例 {market.bullish_breadth:.1%}。"
        )
    if comparison_available:
        breadth_change = market.changes.get("bullish_breadth")
        if breadth_change is None:
            result.append("與前一交易日比較：市場廣度變化資料不足。")
        else:
            result.append(f"與前一交易日比較：多頭廣度變化 {breadth_change:+.1%}。")
        result.append(
            "高分標的變化：新進 "
            + ("、".join(new_high_scores) or "無")
            + "；退出 "
            + ("、".join(exited_high_scores) or "無")
            + "。"
        )
        movers = sorted(
            [item for item in industries if item.rank_change is not None],
            key=lambda item: abs(item.rank_change or 0),
            reverse=True,
        )[:3]
        probability_moves = sorted(
            [item for item in industries if item.probability_change is not None],
            key=lambda item: abs(item.probability_change or 0),
            reverse=True,
        )[:3]
        rotations = [item.name for item in industries if item.rotation_changed]
        result.append(
            "名次升降："
            + ("、".join(f"{item.name} {item.rank_change:+d}" for item in movers) or "無")
            + "。"
        )
        result.append(
            "機率變化："
            + (
                "、".join(
                    f"{item.name} {item.probability_change:+.1f} 個百分點"
                    for item in probability_moves
                )
                or "無"
            )
            + "。"
        )
        result.append("輪動階段變化：" + ("、".join(rotations) or "無") + "。")
    else:
        result.append("無前期報告可比較。")
    result.append(
        "模型偏多產業（>= 60%）："
        + ("、".join(item.name for item in bullish[:5]) or "無")
        + "。"
    )
    result.append(
        "模型偏弱產業（<= 45%）："
        + ("、".join(item.name for item in weak[:5]) or "無")
        + "。"
    )
    if warnings:
        result.append(f"當日主要風險與資料品質：共 {len(warnings)} 項警示，詳見市場與資料品質。")
    else:
        result.append("資料品質狀態：未偵測到跨股票市場因子不一致。")
    return result
