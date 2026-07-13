"""External news and social-sentiment provider adapters."""

import datetime
from email.utils import parsedate_to_datetime
import re
import urllib.parse

import requests
from defusedxml import ElementTree as ET

from stock_papi.shared.validation import is_us_ticker


def fetch_news_rss(name):
    q = urllib.parse.quote(f"{name} 股票")
    url = f"https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    return requests.get(url, timeout=5).text


def parse_news_items(xml, now=None):
    root = ET.fromstring(xml)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    now = (
        now.replace(tzinfo=datetime.timezone.utc)
        if now.tzinfo is None
        else now.astimezone(datetime.timezone.utc)
    )
    items = []
    for node in root.findall(".//item")[:20]:
        title = (node.findtext("title") or "").strip()
        if not title:
            continue
        source = (node.findtext("source") or "").strip() or None
        published_text = (node.findtext("pubDate") or "").strip()
        published_at = age_hours = None
        if published_text:
            try:
                published = parsedate_to_datetime(published_text)
                published = (
                    published.replace(tzinfo=datetime.timezone.utc)
                    if published.tzinfo is None
                    else published.astimezone(datetime.timezone.utc)
                )
                published_at = published.isoformat()
                age_hours = max(0.0, (now - published).total_seconds() / 3600)
            except (TypeError, ValueError, OverflowError):
                pass
        items.append({
            "title": title,
            "normalized_title": title,
            "link": (node.findtext("link") or "").strip(),
            "source": source,
            "published_at": published_at,
            "age_hours": age_hours,
            "parse_flags": {
                "missing_source": source is None,
                "missing_published_at": published_at is None,
            },
            "duplicate_count": 0,
        })
    return items


def parse_marketaux_items(payload, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    now = (
        now.replace(tzinfo=datetime.timezone.utc)
        if now.tzinfo is None
        else now.astimezone(datetime.timezone.utc)
    )
    items = []
    for article in payload.get("data", [])[:20]:
        title = str(article.get("title") or "").strip()
        if not title:
            continue
        source = str(article.get("source") or "").strip() or None
        published_at = age_hours = None
        published_text = str(article.get("published_at") or "").strip()
        if published_text:
            try:
                published = datetime.datetime.fromisoformat(
                    published_text.replace("Z", "+00:00")
                )
                published = (
                    published.replace(tzinfo=datetime.timezone.utc)
                    if published.tzinfo is None
                    else published.astimezone(datetime.timezone.utc)
                )
                published_at = published.isoformat()
                age_hours = max(0.0, (now - published).total_seconds() / 3600)
            except (TypeError, ValueError, OverflowError):
                pass
        external_scores = []
        for entity in article.get("entities") or []:
            try:
                external_scores.append(float(entity["sentiment_score"]))
            except (KeyError, TypeError, ValueError):
                continue
        items.append({
            "title": title,
            "normalized_title": title,
            "link": str(article.get("url") or "").strip(),
            "source": source,
            "published_at": published_at,
            "age_hours": age_hours,
            "parse_flags": {
                "missing_source": source is None,
                "missing_published_at": published_at is None,
            },
            "duplicate_count": 0,
            "provider": "marketaux",
            "external_sentiment_score": (
                sum(external_scores) / len(external_scores)
                if external_scores else None
            ),
        })
    return items


def fetch_marketaux_news(name, *, api_token, parse_items=parse_marketaux_items):
    if not api_token:
        return []
    try:
        response = requests.get(
            "https://api.marketaux.com/v1/news/all",
            params={
                "api_token": api_token,
                "search": name,
                "language": "zh",
                "limit": 3,
            },
            timeout=5,
        )
        response.raise_for_status()
        return parse_items(response.json())
    except (requests.RequestException, AttributeError, TypeError, ValueError):
        return []


def parse_stocktwits_sentiment(payload, code, now=None, *, window_days=30):
    if not isinstance(payload, dict):
        return []
    now = now or datetime.datetime.now(datetime.timezone.utc)
    now = (
        now.replace(tzinfo=datetime.timezone.utc)
        if now.tzinfo is None
        else now.astimezone(datetime.timezone.utc)
    )
    cutoff = now - datetime.timedelta(days=window_days)
    bullish = bearish = 0
    newest = None
    for message in payload.get("messages") or []:
        if not isinstance(message, dict):
            continue
        try:
            published = datetime.datetime.fromisoformat(
                str(message.get("created_at") or "").replace("Z", "+00:00")
            )
            published = (
                published.replace(tzinfo=datetime.timezone.utc)
                if published.tzinfo is None
                else published.astimezone(datetime.timezone.utc)
            )
        except (TypeError, ValueError, OverflowError):
            continue
        if published < cutoff or published > now:
            continue
        sentiment = (((message.get("entities") or {}).get("sentiment") or {}).get("basic"))
        if sentiment == "Bullish":
            bullish += 1
        elif sentiment == "Bearish":
            bearish += 1
        else:
            continue
        newest = max(newest, published) if newest else published

    sample_size = bullish + bearish
    if not sample_size:
        return []
    title = f"{code} StockTwits 近 30 日多方 {bullish}、空方 {bearish}"
    return [{
        "title": title,
        "normalized_title": title,
        "link": f"https://stocktwits.com/symbol/{code}",
        "source": "StockTwits",
        "published_at": newest.isoformat(),
        "age_hours": max(0.0, (now - newest).total_seconds() / 3600),
        "parse_flags": {"missing_source": False, "missing_published_at": False},
        "duplicate_count": 0,
        "provider": "stocktwits",
        "external_sentiment_score": (bullish - bearish) / sample_size,
        "social_sample_size": sample_size,
    }]


def fetch_stocktwits_sentiment(code, *, window_days=30, parse_items=None):
    if not is_us_ticker(code):
        return []
    try:
        response = requests.get(
            "https://api.stocktwits.com/api/2/streams/symbol/"
            f"{urllib.parse.quote(str(code).upper())}.json",
            headers={"User-Agent": "Stock-Papi/1.0 sentiment"},
            timeout=3,
        )
        response.raise_for_status()
        if parse_items is not None:
            return parse_items(response.json(), str(code).upper())
        return parse_stocktwits_sentiment(
            response.json(), str(code).upper(), window_days=window_days
        )
    except (requests.RequestException, AttributeError, TypeError, ValueError):
        return []


def normalize_and_dedupe(items):
    kept = []
    by_title = {}
    for original in items:
        item = dict(original)
        title = " ".join(str(item.get("title", "")).split())
        source = item.get("source")
        suffix = f" - {source}" if source else ""
        if suffix and title.casefold().endswith(suffix.casefold()):
            title = title[:-len(suffix)].rstrip()
        key = re.sub(r"[\W_]+", "", title.casefold())
        if not key:
            continue
        if key in by_title:
            by_title[key]["duplicate_count"] += 1
            continue
        item["normalized_title"] = title
        item["duplicate_count"] = int(item.get("duplicate_count", 0))
        by_title[key] = item
        kept.append(item)
    return kept
