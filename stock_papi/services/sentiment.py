import math

from stock_papi.settings import SENTIMENT_WINDOW_DAYS


NEWS_NEGATIONS = ("不", "未", "無", "難")
NEWS_MAJOR_EVENTS = ("財報", "營收", "財測", "法說", "政策", "違約", "訴訟", "併購")
NEWS_OPINION_TERMS = ("傳聞", "預估", "預測", "看好", "看壞", "可能", "有望")
NEWS_SENTIMENT_RULES = (
    ("營收創新高", 1, 0.5), ("上修財測", 1, 0.5),
    ("獲利創高", 1, 0.5), ("下修財測", -1, 0.5),
    ("重大虧損", -1, 0.5), ("遭降評", -1, 0.5),
    ("看好", 1, 0.2), ("成長", 1, 0.2), ("突破", 1, 0.2),
    ("新高", 1, 0.2), ("獲利", 1, 0.2), ("買超", 1, 0.2),
    ("看壞", -1, 0.2), ("下修", -1, 0.2), ("衰退", -1, 0.2),
    ("虧損", -1, 0.2), ("違約", -1, 0.2), ("降評", -1, 0.2),
    ("賣超", -1, 0.2),
)


def score_news_item(news):
    item = dict(news)
    title = str(item.get("normalized_title") or item.get("title") or "")
    is_social = item.get("provider") == "stocktwits"
    matched_phrases = []
    matched_positive = []
    matched_negative = []
    matched_negations = []
    raw_score = 0.0
    for phrase, sign, value in NEWS_SENTIMENT_RULES:
        if phrase not in title:
            continue
        negated = next(
            (f"{negation}{phrase}" for negation in NEWS_NEGATIONS
             if f"{negation}{phrase}" in title),
            None,
        )
        raw_score += -sign * value if negated else sign * value
        target = (
            matched_phrases if value >= 0.5
            else matched_positive if sign > 0
            else matched_negative
        )
        target.append(phrase)
        if negated:
            matched_negations.append(negated)

    if is_social:
        try:
            external_score = float(item.get("external_sentiment_score") or 0.0)
        except (TypeError, ValueError):
            external_score = 0.0
        raw_score = max(-1.0, min(1.0, external_score)) * 0.6
    raw_score = max(-1.0, min(1.0, raw_score))
    event_type = (
        "opinion" if is_social
        else "major" if any(term in title for term in NEWS_MAJOR_EVENTS)
        else "opinion" if any(term in title for term in NEWS_OPINION_TERMS)
        else "normal"
    )
    age_hours = item.get("age_hours")
    time_weight = (
        1.0 if age_hours is not None and age_hours <= 24
        else 0.75 if age_hours is not None and age_hours <= 72
        else 0.5 if age_hours is not None and age_hours <= 168
        else 0.25
    )
    source_weight = 0.6 if is_social else 1.0 if item.get("source") else 0.75
    event_weight = {"major": 1.3, "normal": 1.0, "opinion": 0.7}[event_type]
    engagement_weight = (
        min(1.0, 0.7 + math.log1p(max(0, int(item.get("social_sample_size") or 0))) / 12)
        if is_social else 1.0
    )
    item.update({
        "raw_score": raw_score,
        "direction": (
            "positive" if raw_score > 0.1
            else "negative" if raw_score < -0.1
            else "neutral"
        ),
        "matched_phrases": matched_phrases,
        "matched_positive_terms": matched_positive,
        "matched_negative_terms": matched_negative,
        "matched_negations": matched_negations,
        "event_type": event_type,
        "time_weight": time_weight,
        "source_weight": source_weight,
        "event_weight": event_weight,
        "engagement_weight": engagement_weight,
        "final_weight": time_weight * source_weight * event_weight * engagement_weight,
    })
    return item


def aggregate_news_sentiment(items):
    if not items:
        return {
            "score": 50.0,
            "status": "中性",
            "count": 0,
            "positive_ratio": 0.0,
            "negative_ratio": 0.0,
            "neutral_ratio": 0.0,
            "confidence_score": 0.0,
            "confidence": "低",
            "source_count": 0,
            "publisher_count": 0,
            "social_sample_size": 0,
            "weighted_volatility": 0.0,
            "momentum": 0.0,
            "momentum_data_sufficient": False,
            "disagreement": 0.0,
            "effective_sample_size": 0.0,
            "missing_metadata_ratio": 0.0,
            "extreme_score_flag": False,
            "window_days": SENTIMENT_WINDOW_DAYS,
            "items": [],
        }

    weights = [max(0.0, float(item["final_weight"])) for item in items]
    total_weight = sum(weights) or 1.0
    weighted_score = sum(
        item["raw_score"] * weight for item, weight in zip(items, weights)
    ) / total_weight
    score = max(0.0, min(100.0, 50.0 + 50.0 * weighted_score))
    status = (
        "極度偏多" if score >= 75
        else "偏多" if score >= 60
        else "中性" if score >= 40
        else "偏空" if score >= 25
        else "極度偏空"
    )
    count = len(items)
    positive_ratio = sum(item["direction"] == "positive" for item in items) / count
    negative_ratio = sum(item["direction"] == "negative" for item in items) / count
    fresh_ratio = sum(
        item.get("age_hours") is not None and item["age_hours"] <= 24
        for item in items
    ) / count
    source_ratio = sum(bool(item.get("source")) for item in items) / count
    source_count = len({item.get("provider") or "news" for item in items})
    publisher_count = len({item.get("source") for item in items if item.get("source")})
    social_sample_size = sum(
        max(0, int(item.get("social_sample_size") or 0)) for item in items
    )
    weighted_volatility = min(100.0, 100.0 * math.sqrt(sum(
        weight * (item["raw_score"] - weighted_score) ** 2
        for item, weight in zip(items, weights)
    ) / total_weight))
    positive_weight = sum(
        weight for item, weight in zip(items, weights)
        if item["direction"] == "positive"
    )
    negative_weight = sum(
        weight for item, weight in zip(items, weights)
        if item["direction"] == "negative"
    )
    directional_weight = positive_weight + negative_weight
    disagreement = (
        200.0 * min(positive_weight, negative_weight) / directional_weight
        if directional_weight else 0.0
    )
    squared_weight = sum(weight ** 2 for weight in weights)
    effective_sample_size = total_weight ** 2 / squared_weight if squared_weight else 0.0

    def window_score(predicate):
        selected = [
            (item, weight) for item, weight in zip(items, weights)
            if predicate(item.get("age_hours"))
        ]
        selected_weight = sum(weight for _item, weight in selected)
        if not selected_weight:
            return None
        return sum(
            item["raw_score"] * weight for item, weight in selected
        ) / selected_weight

    recent_score = window_score(lambda age: age is not None and age <= 24)
    prior_score = window_score(
        lambda age: age is not None and 24 < age <= SENTIMENT_WINDOW_DAYS * 24
    )
    momentum_data_sufficient = recent_score is not None and prior_score is not None
    momentum = (
        max(-100.0, min(100.0, 50.0 * (recent_score - prior_score)))
        if momentum_data_sufficient else 0.0
    )
    missing_metadata_ratio = sum(
        not item.get("source")
        or item.get("age_hours") is None
        or (item.get("parse_flags") or {}).get("missing_source", False)
        or (item.get("parse_flags") or {}).get("missing_published_at", False)
        for item in items
    ) / count
    confidence_score = 100 * (
        0.5 * min(count / 5, 1) + 0.3 * fresh_ratio + 0.2 * source_ratio
    )
    return {
        "score": score,
        "status": status,
        "count": count,
        "positive_ratio": positive_ratio,
        "negative_ratio": negative_ratio,
        "neutral_ratio": max(0.0, 1 - positive_ratio - negative_ratio),
        "confidence_score": confidence_score,
        "confidence": (
            "高" if confidence_score >= 75
            else "中" if confidence_score >= 45
            else "低"
        ),
        "source_count": source_count,
        "publisher_count": publisher_count,
        "social_sample_size": social_sample_size,
        "weighted_volatility": weighted_volatility,
        "momentum": momentum,
        "momentum_data_sufficient": momentum_data_sufficient,
        "disagreement": disagreement,
        "effective_sample_size": effective_sample_size,
        "missing_metadata_ratio": missing_metadata_ratio,
        "extreme_score_flag": score >= 80 or score <= 20,
        "window_days": SENTIMENT_WINDOW_DAYS,
        "items": items,
    }


def analyze_sentiment_detail(news_list):
    return aggregate_news_sentiment([score_news_item(item) for item in news_list])


def analyze_sentiment(news_list):
    detail = analyze_sentiment_detail(news_list)
    return detail["score"], detail["status"]

