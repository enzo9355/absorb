"""News-source orchestration independent of Flask and application globals."""


def get_news(
    name,
    code,
    executor_factory,
    fetch_rss,
    parse_rss,
    fetch_marketaux,
    fetch_social,
    normalize,
    sentiment_window_days,
):
    items = []
    social = []
    with executor_factory(max_workers=3) as executor:
        rss_future = executor.submit(fetch_rss, name)
        marketaux_future = executor.submit(fetch_marketaux, name)
        social_future = (
            executor.submit(fetch_social, code) if code else None
        )
        try:
            items.extend(parse_rss(rss_future.result()))
        except Exception:
            pass
        try:
            items.extend(marketaux_future.result())
        except Exception:
            pass
        if social_future:
            try:
                social = social_future.result()
            except Exception:
                pass
    news = [
        item for item in normalize(items)
        if item.get("age_hours") is None
            or item["age_hours"] <= sentiment_window_days * 24
    ]
    return news[:4 if social else 5] + social[:1]
