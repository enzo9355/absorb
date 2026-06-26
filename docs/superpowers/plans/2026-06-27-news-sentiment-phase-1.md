# News Sentiment Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three-label keyword sentiment result with a five-level, weighted, explainable news sentiment score while preserving the existing prediction probability.

**Architecture:** Keep the existing single-file Flask structure. Isolate network I/O in `fetch_news_rss()`, use four pure helpers for parsing, deduplication, item scoring, and aggregation, then reuse the existing LINE Flex builder and Jinja template for output.

**Tech Stack:** Python 3.10 standard library, requests, defusedxml, Flask/Jinja, unittest.

---

### Task 1: Parse RSS metadata and remove duplicates

**Files:**
- Modify: `app.py:436-443`
- Test: `tests/test_prediction_pipeline.py`

- [ ] **Step 1: Write failing parser and deduplication tests**

Add tests that pass XML directly to `parse_news_items()` and assert that source, UTC publication time, age, missing flags, normalized title, and `duplicate_count` are preserved. Include an item without source/date and two identical normalized titles.

```python
def test_parse_news_items_preserves_metadata_and_missing_flags(self):
    xml = """<rss><channel>
      <item><title>台積電營收創新高 - 財經報</title><link>https://a</link><source>財經報</source><pubDate>Fri, 27 Jun 2026 00:00:00 GMT</pubDate></item>
      <item><title>台積電營收創新高 - 財經報</title><link>https://b</link></item>
    </channel></rss>"""
    now = datetime.datetime(2026, 6, 27, 8, tzinfo=datetime.timezone.utc)

    items = stock_app.parse_news_items(xml, now=now)
    deduped = stock_app.normalize_and_dedupe(items)

    self.assertEqual(items[0]["source"], "財經報")
    self.assertEqual(items[0]["age_hours"], 8.0)
    self.assertTrue(items[1]["parse_flags"]["missing_source"])
    self.assertTrue(items[1]["parse_flags"]["missing_published_at"])
    self.assertEqual(len(deduped), 1)
    self.assertEqual(deduped[0]["duplicate_count"], 1)
```

- [ ] **Step 2: Run the parser test and verify RED**

Run:

```powershell
$env:PYTHONPATH='C:\Users\enzo\Documents\line bot\.deps'
& 'C:\Users\enzo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_prediction_pipeline.PredictionPipelineTests.test_parse_news_items_preserves_metadata_and_missing_flags -v
```

Expected: error because `parse_news_items` does not exist.

- [ ] **Step 3: Implement the minimum parser pipeline**

Add `email.utils.parsedate_to_datetime`, then implement:

```python
def fetch_news_rss(name):
    q = urllib.parse.quote(f"{name} 股票")
    url = f"https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    return requests.get(url, timeout=5).text

def parse_news_items(xml, now=None):
    root = ET.fromstring(xml)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    now = now.replace(tzinfo=datetime.timezone.utc) if now.tzinfo is None else now.astimezone(datetime.timezone.utc)
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
                published = published.replace(tzinfo=datetime.timezone.utc) if published.tzinfo is None else published.astimezone(datetime.timezone.utc)
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

def get_news(name):
    try:
        return normalize_and_dedupe(parse_news_items(fetch_news_rss(name)))[:5]
    except Exception:
        return []
```

- [ ] **Step 4: Run parser and XML security tests and verify GREEN**

Run the new parser test and `test_news_rejects_xml_entity_expansion`; expected: both pass.

### Task 2: Score individual items and aggregate five-level sentiment

**Files:**
- Modify: `app.py:658-703`
- Test: `tests/test_prediction_pipeline.py`

- [ ] **Step 1: Write failing score and aggregate tests**

Add focused tests for negation, event/time/source weights, five-level labels, and low-confidence empty input:

```python
def test_score_news_item_handles_negation_and_weights(self):
    positive = stock_app.score_news_item({"title": "法人看好營收創新高", "source": "財經報", "age_hours": 2, "parse_flags": {}})
    negated = stock_app.score_news_item({"title": "法人不看好後市", "source": None, "age_hours": None, "parse_flags": {}})
    self.assertGreater(positive["raw_score"], 0)
    self.assertLessEqual(negated["raw_score"], 0)
    self.assertEqual(positive["event_type"], "major")
    self.assertGreater(positive["final_weight"], negated["final_weight"])

def test_aggregate_news_sentiment_returns_five_levels_and_confidence(self):
    result = stock_app.aggregate_news_sentiment([
        {"raw_score": 1.0, "final_weight": 1.0, "direction": "positive", "source": "A", "age_hours": 1}
    ] * 5)
    empty = stock_app.aggregate_news_sentiment([])
    self.assertEqual(result["status"], "極度偏多")
    self.assertEqual(result["confidence"], "高")
    self.assertEqual(empty["status"], "中性")
    self.assertEqual(empty["confidence"], "低")
```

- [ ] **Step 2: Run both tests and verify RED**

Expected: errors because `score_news_item` and `aggregate_news_sentiment` do not exist.

- [ ] **Step 3: Implement minimal scoring and aggregation**

Use module-level tuples for positive phrases, negative phrases, negations, major events, and opinion terms. `score_news_item()` returns the requested intermediate fields, clamps `raw_score` to `[-1, 1]`, applies the approved time/source/event weights, and calculates `final_weight`.

`aggregate_news_sentiment()` calculates:

```python
weighted_score = sum(item["raw_score"] * item["final_weight"] for item in items) / sum(item["final_weight"] for item in items)
score = max(0.0, min(100.0, 50.0 + 50.0 * weighted_score))
```

It returns `score`, `status`, `count`, positive/negative/neutral ratios, numeric `confidence_score`, and `confidence` (`高`/`中`/`低`). Keep `analyze_sentiment()` as the legacy tuple adapter.

The implementation must use these exact boundaries:

```python
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
    matched_phrases, matched_positive, matched_negative, matched_negations = [], [], [], []
    raw_score = 0.0
    for phrase, sign, value in NEWS_SENTIMENT_RULES:
        if phrase not in title:
            continue
        negated = next((f"{negation}{phrase}" for negation in NEWS_NEGATIONS if f"{negation}{phrase}" in title), None)
        raw_score += -sign * value if negated else sign * value
        (matched_phrases if value >= 0.5 else matched_positive if sign > 0 else matched_negative).append(phrase)
        if negated:
            matched_negations.append(negated)
    raw_score = max(-1.0, min(1.0, raw_score))
    event_type = "major" if any(term in title for term in NEWS_MAJOR_EVENTS) else "opinion" if any(term in title for term in NEWS_OPINION_TERMS) else "normal"
    age_hours = item.get("age_hours")
    time_weight = 1.0 if age_hours is not None and age_hours <= 24 else 0.75 if age_hours is not None and age_hours <= 72 else 0.5 if age_hours is not None and age_hours <= 168 else 0.25
    source_weight = 1.0 if item.get("source") else 0.75
    event_weight = {"major": 1.3, "normal": 1.0, "opinion": 0.7}[event_type]
    item.update({
        "raw_score": raw_score,
        "direction": "positive" if raw_score > 0.1 else "negative" if raw_score < -0.1 else "neutral",
        "matched_phrases": matched_phrases,
        "matched_positive_terms": matched_positive,
        "matched_negative_terms": matched_negative,
        "matched_negations": matched_negations,
        "event_type": event_type,
        "time_weight": time_weight,
        "source_weight": source_weight,
        "event_weight": event_weight,
        "final_weight": time_weight * source_weight * event_weight,
    })
    return item

def aggregate_news_sentiment(items):
    if not items:
        return {"score": 50.0, "status": "中性", "count": 0, "positive_ratio": 0.0, "negative_ratio": 0.0, "neutral_ratio": 0.0, "confidence_score": 0.0, "confidence": "低", "items": []}
    total_weight = sum(item["final_weight"] for item in items)
    score = max(0.0, min(100.0, 50.0 + 50.0 * sum(item["raw_score"] * item["final_weight"] for item in items) / total_weight))
    status = "極度偏多" if score >= 75 else "偏多" if score >= 60 else "中性" if score >= 40 else "偏空" if score >= 25 else "極度偏空"
    count = len(items)
    positive_ratio = sum(item["direction"] == "positive" for item in items) / count
    negative_ratio = sum(item["direction"] == "negative" for item in items) / count
    fresh_ratio = sum(item.get("age_hours") is not None and item["age_hours"] <= 24 for item in items) / count
    source_ratio = sum(bool(item.get("source")) for item in items) / count
    confidence_score = 100 * (0.5 * min(count / 5, 1) + 0.3 * fresh_ratio + 0.2 * source_ratio)
    return {"score": score, "status": status, "count": count, "positive_ratio": positive_ratio, "negative_ratio": negative_ratio, "neutral_ratio": 1 - positive_ratio - negative_ratio, "confidence_score": confidence_score, "confidence": "高" if confidence_score >= 75 else "中" if confidence_score >= 45 else "低", "items": items}
```

- [ ] **Step 4: Run all sentiment tests and verify GREEN**

Run every `test_*sentiment*`, parser test, and the probability non-mutation test. Expected: all pass.

### Task 3: Thread fields into analysis, LINE, and Web

**Files:**
- Modify: `app.py:743-754`
- Modify: `app.py:1357-1410`
- Modify: `templates/stock_detail.html:46-67`
- Modify: `tests/test_prediction_pipeline.py`

- [ ] **Step 1: Write failing output tests**

Update sample payloads with `news_neutral_ratio`, `news_confidence`, and `news_confidence_score`. Assert LINE contains `12 則｜正面 58%｜負面 17%｜可信度中`; assert Web contains source, publication time, direction, and the same summary fields without exposing `matched_positive_terms`.

- [ ] **Step 2: Run output tests and verify RED**

Expected: assertions fail because the new summary and metadata are not rendered.

- [ ] **Step 3: Implement minimum output changes**

Thread the new aggregate fields through `_do_analyze()`. In the existing LINE Flex builder, keep the sentiment title row and add one small summary line. In `stock_detail.html`, extend the sentiment card and each news link with source, publication time, and direction. Do not add formatter wrappers.

- [ ] **Step 4: Run output tests and verify GREEN**

Expected: focused LINE/Web tests pass and external text escaping remains intact.

### Task 4: Documentation and full verification

**Files:**
- Modify: `README.md`
- Test: all tests

- [ ] **Step 1: Update README behavior notes**

Document five-level sentiment, source/time weighting, confidence, and the rule that sentiment does not modify five-day probability.

- [ ] **Step 2: Run full suite**

Run:

```powershell
$env:PYTHONPATH='C:\Users\enzo\Documents\line bot\.deps'
& 'C:\Users\enzo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -v
```

Expected: all tests pass. Existing `google.generativeai` and LINE SDK deprecation warnings may remain; no new warning is introduced by this feature.

- [ ] **Step 3: Verify diff and second review**

Run `git diff --check`, inspect the complete diff, then submit only the diff and test summary to `agy` using the approved external-review flow. Do not treat an empty `agy --print` response as a pass.

- [ ] **Step 4: Commit implementation**

```powershell
git add app.py templates/stock_detail.html tests/test_prediction_pipeline.py tests/test_line_flow.py tests/test_web_product.py README.md docs/superpowers/specs/2026-06-27-news-sentiment-phase-1-design.md docs/superpowers/plans/2026-06-27-news-sentiment-phase-1.md
git commit -m "feat: add weighted news sentiment scoring"
```
