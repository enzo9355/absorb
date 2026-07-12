import math


def safe_float(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def clamp(value, low, high):
    return max(low, min(high, value))


def format_sentiment_summary(data):
    parts = [f'{data.get("news_count", len(data.get("news", [])))} 則']
    source_count = int(
        data.get("news_publisher_count") or data.get("news_source_count") or 0
    )
    social_sample_size = int(data.get("social_sample_size") or 0)
    if source_count:
        parts.append(f"{source_count} 個來源")
    if social_sample_size:
        parts.append(f"社群 {social_sample_size} 則")
    parts.extend([
        f'正面 {round(data.get("news_positive_ratio", 0) * 100)}%',
        f'負面 {round(data.get("news_negative_ratio", 0) * 100)}%',
    ])
    if data.get("news_momentum_data_sufficient"):
        parts.append(f'動能 {data.get("news_momentum", 0):+.0f}')
    if data.get("news_disagreement", 0) > 0:
        parts.append(f'分歧 {data.get("news_disagreement", 0):.0f}')
    parts.append(f'可信度{data.get("news_confidence", "低")}')
    return "｜".join(parts)
