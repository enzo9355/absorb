import math


def safe_float(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def clamp(value, low, high):
    return max(low, min(high, value))


def _format_ratio_percent(value):
    try:
        if value is None:
            return "資料不足"
        return f"{round(float(value) * 100)}%"
    except (TypeError, ValueError):
        return "資料不足"


def format_sentiment_summary(data):
    data = data if isinstance(data, dict) else {}
    try:
        news_count = data.get("news_count", len(data.get("news", []) or []))
        parts = [f"{int(news_count)} 則"]
    except (TypeError, ValueError):
        parts = ["資料不足"]
    try:
        source_count = int(
            data.get("news_publisher_count") or data.get("news_source_count") or 0
        )
    except (TypeError, ValueError):
        source_count = 0
    try:
        social_sample_size = int(data.get("social_sample_size") or 0)
    except (TypeError, ValueError):
        social_sample_size = 0
    if source_count:
        parts.append(f"{source_count} 個來源")
    if social_sample_size:
        parts.append(f"社群 {social_sample_size} 則")
    parts.extend([
        f'正面 {_format_ratio_percent(data.get("news_positive_ratio"))}',
        f'負面 {_format_ratio_percent(data.get("news_negative_ratio"))}',
    ])
    if data.get("news_momentum_data_sufficient"):
        try:
            parts.append(f'動能 {float(data.get("news_momentum", 0)):+.0f}')
        except (TypeError, ValueError):
            parts.append('動能 資料不足')
    try:
        disagreement = data.get("news_disagreement", 0)
        if isinstance(disagreement, (int, float)) and disagreement > 0:
            parts.append(f'分歧 {float(disagreement):.0f}')
    except (TypeError, ValueError):
        pass
    parts.append(f'可信度{data.get("news_confidence", "低")}')
    return "｜".join(parts)
