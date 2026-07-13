# app.py
# v5.8 穩定版：新增首頁健康檢查端點防休眠，並梳理重複路由確保 Flask 正常啟動
# --------------------------------------------------

import os
import queue
import re
import threading
import time
import datetime
import gzip
import hashlib
import hmac
import io
import importlib
import logging
import math
from concurrent.futures import ThreadPoolExecutor
import requests
import twstock
import urllib.parse
import json

from market_insights import build_industries, build_supply_chains

from flask import request
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, PostbackEvent, TextMessage, TextSendMessage,
    QuickReply, QuickReplyButton, MessageAction
)
from line_state import (
    FirestoreStore, StateError, StoreError, add_alert, add_watch,
    consume_pending, evaluate_alert, remove_watch, start_pending, top_signals,
)
from stock_papi.settings import (
    ALERT_TASK_TOKEN,
    BROADCAST_TOKEN,
    FINMIND_PASSWORD,
    FINMIND_USER,
    GCP_PROJECT_ID,
    GEMINI_API_KEY,
    LINE_CHANNEL_ACCESS_TOKEN,
    LINE_CHANNEL_SECRET,
    LINE_STATE_READ_BUDGET_SECONDS,
    LINE_STATE_READ_MAX_WORKERS,
    LOCAL_HOST,
    MARKETAUX_API_TOKEN,
    OPENALICE_API_TOKEN,
    OPENALICE_API_URL,
    QUANT_SNAPSHOT_BUCKET,
    REPORT_INDEX_MAX_BYTES,
    REPORT_PDF_MAX_BYTES,
    SENTIMENT_WINDOW_DAYS,
    SUPABASE_KEY,
    SUPABASE_URL,
)
from stock_papi.shared.formatting import clamp as _clamp
from stock_papi.shared.formatting import format_sentiment_summary as _format_sentiment_summary
from stock_papi.shared.formatting import safe_float as _safe_float
from stock_papi.shared.validation import is_crypto_query as _is_crypto_query
from stock_papi.shared.validation import is_us_ticker
from stock_papi.shared.logging import (
    RedactingFormatter,
    install_redacting_formatters,
    redact_secrets,
    safe_exception_text,
)
from stock_papi.integrations.line.flex import (
    _alert_condition_text,
    _alert_management_card,
    _empty_line_bubble,
    _signal_card,
    _watchlist_card,
    build_alert_menu_flex,
    build_alert_push_flex,
    build_alerts_flex,
    build_calculator_help_flex,
    build_calculator_menu_flex,
    build_line_navigation_flex,
    build_line_summary_card,
    build_stock_flex_message,
    build_strong_signals_flex,
    build_tutorial_flex,
    build_watchlist_flex,
    build_welcome_flex,
)
from stock_papi.integrations.line.notifications import run_alert_checks
from stock_papi.integrations.line.webhook import register_line_routes
from stock_papi.integrations.line.handlers import (
    handle_message_impl as _line_handle_message_impl,
    handle_postback_impl as _line_handle_postback_impl,
)
from stock_papi.integrations.market_data.tw_exchange import fetch_market_activity
from stock_papi.integrations.news.provider import (
    fetch_marketaux_news as _fetch_marketaux_news,
    fetch_news_rss,
    fetch_stocktwits_sentiment as _fetch_stocktwits_sentiment,
    normalize_and_dedupe,
    parse_marketaux_items,
    parse_news_items,
    parse_stocktwits_sentiment as _parse_stocktwits_sentiment,
)
from stock_papi.repositories.gcs import get_allowed_object
from stock_papi.repositories.market_insights import (
    MARKET_INSIGHTS_CACHE as _MARKET_INSIGHTS_CACHE,
    load_market_insights,
)
from stock_papi.repositories.quant_snapshots import (
    MAX_QUANT_ARTIFACT_COMPRESSED_BYTES,
    MAX_QUANT_ARTIFACT_UNCOMPRESSED_BYTES,
    QUANT_MANIFEST_CACHE as _QUANT_MANIFEST_CACHE,
    QUANT_MANIFEST_CACHE_SECONDS,
    fetch_quant_snapshot,
    published_quant_manifest,
)
from stock_papi.repositories.report_store import load_report_index, load_report_pdf
from stock_papi.quant.projection import (
    _annualized_percent,
    calculate_investment_projection,
)
from stock_papi.quant.constants import (
    DATA_QUALITY_FEATURES,
    ENTRY_THRESHOLD,
    MARKET_FEATURES,
    MODEL_FEATURES,
    OPTION_FEATURES,
    PREDICTION_HORIZON,
    PRICE_DIFF_WARNING_THRESHOLD,
    ROUND_TRIP_COST,
)
from stock_papi.quant.data import (
    add_market_context_features as _add_market_context_features,
    add_option_context_features as _add_option_context_features,
    add_price_quality_features as _add_price_quality_features,
    clean_df as _clean_quant_df,
    foreign_flow_mask as _quant_foreign_flow_mask,
    get_data as _get_quant_data,
    market_feature_frame as _quant_market_feature_frame,
    merge_chip_data as _merge_chip_data,
    neutral_market_features as _neutral_quant_market_features,
    option_close_frame as _quant_option_close_frame,
    summarize_foreign_flow as _summarize_foreign_flow,
)
from stock_papi.quant.features import (
    add_prediction_target as _add_prediction_target,
    calc_all as _calc_all,
)
from stock_papi.quant.backtest import (
    build_time_splits as _build_time_splits,
    score_oos_predictions as _score_oos_predictions,
)
from stock_papi.quant.model import run_ai_engine as _run_ai_engine
from stock_papi.services.sentiment import (
    NEWS_MAJOR_EVENTS,
    NEWS_NEGATIONS,
    NEWS_OPINION_TERMS,
    NEWS_SENTIMENT_RULES,
    aggregate_news_sentiment,
    analyze_sentiment,
    analyze_sentiment_detail,
    score_news_item,
)
from stock_papi.services.dashboard import build_market_heatmap, dashboard_top_picks
from stock_papi.services.market import (
    build_market_map as _build_market_map,
    build_sector_signal_snapshot as _build_sector_signal_snapshot,
    find_industry_peers as _find_industry_peers,
    sector_candidates,
    sector_signal_item as _sector_signal_item,
    sector_signal_score,
)
from stock_papi.services.stock_analysis import (
    analyze_cached as _analyze_cached,
    analyze_uncached as _analyze_uncached,
    snapshot_dataframe as _build_snapshot_dataframe,
)
from stock_papi.web.legacy_html import render_web




class _LazyModule:
    def __init__(self, name):
        self._name = name
        self._module = None
        self._lock = threading.Lock()

    def __getattr__(self, name):
        if self._module is None:
            with self._lock:
                if self._module is None:
                    self._module = importlib.import_module(self._name)
        return getattr(self._module, name)


class _LazyGeminiModel:
    def __init__(self, api_key):
        self._api_key = api_key
        self._model = None
        self._lock = threading.Lock()

    def generate_content(self, *args, **kwargs):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    genai = importlib.import_module("google.generativeai")
                    genai.configure(api_key=self._api_key)
                    self._model = genai.GenerativeModel("gemini-2.5-flash")
        return self._model.generate_content(*args, **kwargs)


pd = _LazyModule("pandas")
np = _LazyModule("numpy")

# ==================================================
# 1. 基本設定與系統快取
# ==================================================
finmind_token = None
_line_state_read_slots = threading.BoundedSemaphore(LINE_STATE_READ_MAX_WORKERS)

APPLICATION_ROOT = os.path.dirname(os.path.dirname(__file__))
SAMPLE_REPORT_FILENAME = "stock-papi-tw-industry-daily-SAMPLE.pdf"
SAMPLE_REPORT_PATH = os.path.join(
    APPLICATION_ROOT, "static", "samples", SAMPLE_REPORT_FILENAME
)
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
supabase_client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        pass

if supabase_client:
    from line_state import SupabaseStore
    line_store = SupabaseStore(supabase_client)
else:
    line_store = FirestoreStore(GCP_PROJECT_ID) if GCP_PROJECT_ID else None

gemini_model = _LazyGeminiModel(GEMINI_API_KEY) if GEMINI_API_KEY else None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("app")


def runtime_logging_secrets():
    return (
        LINE_CHANNEL_ACCESS_TOKEN,
        LINE_CHANNEL_SECRET,
        FINMIND_PASSWORD,
        GEMINI_API_KEY,
        BROADCAST_TOKEN,
        ALERT_TASK_TOKEN,
        OPENALICE_API_TOKEN,
        MARKETAUX_API_TOKEN,
        SUPABASE_KEY,
        finmind_token,
    )


install_redacting_formatters(runtime_logging_secrets)

_FINMIND_BLOCKED_UNTIL = 0
CATEGORY_PAGE_SIZE = 12
SECTOR_SCAN_LIMIT = 20
SECTOR_DISPLAY_LIMIT = 10
SECTOR_SNAPSHOT_DOC = "sector_signals"
PAPI_THEME_SECTORS = {
    "AI伺服器": {"鴻海", "廣達", "緯創", "緯穎", "英業達", "仁寶", "和碩", "神達", "勤誠"},
    "PC／筆電": {"華碩", "宏碁", "微星", "技嘉", "神基", "藍天"},
    "散熱機構": {"雙鴻", "奇鋐", "建準", "勤誠", "營邦", "迎廣"},
    "工業電腦": {"研華", "樺漢", "凌華", "友通", "艾訊"},
    "網通設備": {"智邦", "啟碁", "中磊", "正文", "台揚", "明泰"},
    "半導體製造": {"台積電", "聯電", "世界", "力積電", "南亞科", "華邦電"},
    "IC設計ASIC": {"聯發科", "瑞昱", "創意", "世芯-KY", "力旺", "M31"},
    "封測設備": {"日月光投控", "矽格", "京元電子", "辛耘", "弘塑", "家登"},
}
_SYSTEM_CACHE = {}
CACHE_EXPIRY_SECONDS = 3600
_YFINANCE_CACHE = {}
YFINANCE_CACHE_SECONDS = 3600

# ==================================================
# 2. 資料抓取與清洗模組
# ==================================================
def finmind_login():
    global finmind_token
    if finmind_token or not FINMIND_USER or not FINMIND_PASSWORD: return
    try:
        r = requests.post(
            "https://api.finmindtrade.com/api/v4/login",
            data={"user_id": FINMIND_USER, "password": FINMIND_PASSWORD},
            timeout=5
        ).json()
        if r.get("msg") == "success": finmind_token = r["token"]
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return

def fetch_finmind_dataset(dataset, code, start_date, end_date):
    global _FINMIND_BLOCKED_UNTIL
    now = time.time()
    if now < _FINMIND_BLOCKED_UNTIL:
        return pd.DataFrame()
    finmind_login()
    params = {
        "dataset": dataset,
        "data_id": code,
        "start_date": start_date,
        "end_date": end_date,
    }
    if finmind_token:
        params["token"] = finmind_token
    try:
        response = requests.get(
            "https://api.finmindtrade.com/api/v4/data",
            params=params,
            timeout=8,
        )
        if response.status_code in (402, 403):
            _FINMIND_BLOCKED_UNTIL = now + (60 if response.status_code == 402 else 30) * 60
        response.raise_for_status()
        return pd.DataFrame(response.json().get("data", []))
    except (requests.RequestException, ValueError, TypeError) as exc:
        logger.warning("FinMind %s 讀取失敗: %s", dataset, exc)
        return pd.DataFrame()


def fetch_yfinance_price_history(tickers, start_date, end_date=None):
    if isinstance(tickers, str):
        tickers = [tickers]
    cache_key = (tuple(tickers), start_date, end_date or "")
    now = time.time()
    cached = _YFINANCE_CACHE.get(cache_key)
    if cached and now - cached[1] < YFINANCE_CACHE_SECONDS:
        return cached[0].copy()

    try:
        import yfinance as yf

        for ticker in tickers:
            hist = yf.download(
                ticker,
                start=start_date,
                end=end_date,
                progress=False,
                threads=False,
            )
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.droplevel(1)
            if not hist.empty and "Close" in hist.columns:
                frame = hist.copy()
                frame.index = pd.to_datetime(frame.index).tz_localize(None)
                frame.index.name = "Date"
                frame = frame.reset_index()[["Date", "Open", "High", "Low", "Close", "Volume"]]
                _YFINANCE_CACHE[cache_key] = (frame.copy(), now)
                return frame
    except Exception as exc:
        logger.warning("Yahoo Finance 讀取失敗: %s", exc)
    return pd.DataFrame()


def fetch_option_context_history(start_date, end_date=None):
    symbols = ("^VIX", "^VIX9D", "^VIX3M")
    frames = {}
    with ThreadPoolExecutor(max_workers=len(symbols)) as executor:
        futures = {
            symbol: executor.submit(
                fetch_yfinance_price_history, symbol, start_date, end_date
            )
            for symbol in symbols
        }
        for symbol, future in futures.items():
            try:
                frames[symbol] = future.result()
            except Exception as exc:
                logger.warning("選擇權市場指標讀取失敗 (%s): %s", symbol, exc)
                frames[symbol] = pd.DataFrame()
    return tuple(frames[symbol] for symbol in symbols)


def get_stock_name(code):
    if code == "TAIEX": return "台股大盤"
    if code in twstock.codes: return twstock.codes[code].name
    if is_us_ticker(code): return f"美股 {code}"
    return code

def search_stock_code(keyword):
    keyword = keyword.upper().strip()
    if not keyword: return None, None
    if keyword in ["TAIEX", "加權指數", "台股大盤", "大盤"]: return "TAIEX", "台股大盤"
    if keyword.isdigit(): return keyword, get_stock_name(keyword)
    if is_us_ticker(keyword): return keyword, get_stock_name(keyword)
    for code, info in twstock.codes.items():
        if keyword in info.name.upper(): return code, info.name
    return None, None


def get_gcp_access_token():
    if line_store and hasattr(line_store, "token_provider"):
        try:
            return line_store.token_provider()
        except Exception:
            pass
    try:
        import google.auth
        import google.auth.transport.requests
        credentials, project = google.auth.default()
        auth_request = google.auth.transport.requests.Request()
        credentials.refresh(auth_request)
        return credentials.token
    except Exception:
        try:
            res = requests.get(
                "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
                headers={"Metadata-Flavor": "Google"},
                timeout=3
            )
            if res.status_code == 200:
                return res.json().get("access_token")
        except Exception:
            pass
    return None


def _gcs_get_allowed_object(object_name, max_bytes, allowed_prefix):
    return get_allowed_object(
        object_name,
        max_bytes,
        allowed_prefix,
        bucket=QUANT_SNAPSHOT_BUCKET,
        enabled=line_store is not None,
        token_provider=get_gcp_access_token,
        http_get=requests.get,
    )


def _gcs_get_object(object_name, max_bytes):
    """只允許讀取既有 quant/v1 私有物件。"""
    return _gcs_get_allowed_object(object_name, max_bytes, "quant/v1/")


def _gcs_get_report_object(object_name, max_bytes):
    """只允許讀取 reports/v1 私有物件。"""
    return _gcs_get_allowed_object(object_name, max_bytes, "reports/v1/")


def _published_report_index():
    return load_report_index(
        load_object=_gcs_get_report_object,
        max_bytes=REPORT_INDEX_MAX_BYTES,
    )


def _published_quant_manifest(market, today=None):
    return published_quant_manifest(
        market,
        today=today,
        load_object=_gcs_get_object,
        cache=_QUANT_MANIFEST_CACHE,
    )


def fetch_published_quant_snapshot(code, today=None):
    return fetch_quant_snapshot(
        code,
        today=today,
        is_us_ticker_fn=is_us_ticker,
        load_manifest=_published_quant_manifest,
        load_object=_gcs_get_object,
    )


def fetch_market_insights(today=None):
    return load_market_insights(
        today=today,
        load_object=_gcs_get_object,
        cache=_MARKET_INSIGHTS_CACHE,
    )







def _foreign_flow_mask(frame):
    return _quant_foreign_flow_mask(frame, pd=pd)


def merge_chip_data(price, institutional=None, margin=None):
    return _merge_chip_data(price, institutional, margin, pd=pd)


def _neutral_market_features(frame):
    return _neutral_quant_market_features(frame)


def _market_feature_frame(market, prefix):
    return _quant_market_feature_frame(market, prefix, pd=pd)


def add_market_context_features(price, market=None, etf50=None):
    return _add_market_context_features(price, market, etf50, pd=pd, np=np)


def _option_close_frame(frame, column):
    return _quant_option_close_frame(frame, column, pd=pd)


def add_option_context_features(price, vix=None, vix9d=None, vix3m=None):
    return _add_option_context_features(price, vix, vix9d, vix3m, pd=pd, np=np)


def add_price_quality_features(price, yf_price=None):
    return _add_price_quality_features(price, yf_price, pd=pd, np=np)


def _clean_df(df):
    return _clean_quant_df(df, pd=pd, np=np)






def summarize_foreign_flow(df):
    return _summarize_foreign_flow(df, pd=pd)

def get_data(code, days=730):
    return _get_quant_data(
        code,
        days,
        datetime=datetime,
        pd=pd,
        is_us_ticker=is_us_ticker,
        twstock_codes=twstock.codes,
        fetch_yfinance=fetch_yfinance_price_history,
        fetch_finmind=fetch_finmind_dataset,
        fetch_option_context=fetch_option_context_history,
        add_price_quality=add_price_quality_features,
        add_market_context=add_market_context_features,
        add_option_context=add_option_context_features,
        merge_chip=merge_chip_data,
        clean=_clean_df,
    )

# ==================================================
# 3. 核心運算模組 (LGBM)
# ==================================================
def fetch_marketaux_news(name):
    return _fetch_marketaux_news(
        name,
        api_token=MARKETAUX_API_TOKEN,
        parse_items=parse_marketaux_items,
    )


def parse_stocktwits_sentiment(payload, code, now=None):
    return _parse_stocktwits_sentiment(
        payload, code, now=now, window_days=SENTIMENT_WINDOW_DAYS
    )


def fetch_stocktwits_sentiment(code):
    return _fetch_stocktwits_sentiment(
        code,
        window_days=SENTIMENT_WINDOW_DAYS,
        parse_items=parse_stocktwits_sentiment,
    )


def get_news(name, code=None):
    items = []
    social = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        rss_future = executor.submit(fetch_news_rss, name)
        marketaux_future = executor.submit(fetch_marketaux_news, name)
        social_future = (
            executor.submit(fetch_stocktwits_sentiment, code) if code else None
        )
        try:
            items.extend(parse_news_items(rss_future.result()))
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
        item for item in normalize_and_dedupe(items)
        if item.get("age_hours") is None
        or item["age_hours"] <= SENTIMENT_WINDOW_DAYS * 24
    ]
    return news[:4 if social else 5] + social[:1]

def calc_all(df):
    return _calc_all(df, pd=pd, np=np)

def add_prediction_target(df):
    return _add_prediction_target(df, np=np)

def build_time_splits(n_samples):
    return _build_time_splits(n_samples, np=np)

def score_oos_predictions(future_returns, probabilities):
    return _score_oos_predictions(future_returns, probabilities, pd=pd, np=np)

def run_ai_engine(df):
    return _run_ai_engine(
        df,
        add_prediction_target=add_prediction_target,
        build_time_splits=build_time_splits,
        score_oos_predictions=score_oos_predictions,
        pd=pd,
        np=np,
        logger=logger,
    )

def get_ai_insight_for_broadcast(name, data, bt, news):
    if not gemini_model: return "未設定 API Key，無法生成觀點。"
    n_txt = "\n".join([n['title'] for n in news])
    prompt = f"""請以資深分析師語氣，針對{name}撰寫100字內洞見。不要廢話，直接給建議。
最新價:{data['price']}
五日上漲機率:{data['prob']}%
夏普值:{bt['sharpe']:.2f}
新聞:\n{n_txt}"""
    try:
        safety = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
        response = gemini_model.generate_content(prompt, safety_settings=safety)
        return response.text.strip() if response.text else "AI 觀點生成為空。"
    except Exception as e:
        return "暫時無法生成 AI 觀點，請參考量化數據。"

# ==================================================
# 4. 分析總控
# ==================================================









def _snapshot_dataframe(snapshot):
    return _build_snapshot_dataframe(snapshot, pd=pd)


def _do_analyze(code):
    return _analyze_uncached(
        code,
        fetch_snapshot=fetch_published_quant_snapshot,
        build_snapshot_frame=_snapshot_dataframe,
        get_data=get_data,
        calc_all=calc_all,
        run_ai_engine=run_ai_engine,
        get_stock_name=get_stock_name,
        get_news=get_news,
        analyze_sentiment_detail=analyze_sentiment_detail,
        summarize_foreign_flow=summarize_foreign_flow,
        calculate_projection=calculate_investment_projection,
        pd=pd,
        json=json,
        datetime=datetime,
    )

def analyze(code):
    return _analyze_cached(
        code,
        cache=_SYSTEM_CACHE,
        expiry_seconds=CACHE_EXPIRY_SECONDS,
        now=time.time,
        analyze_fn=_do_analyze,
    )

def cached_opportunities(limit=5):
    now = time.time()
    items = []
    for code, (data, timestamp) in _SYSTEM_CACHE.items():
        if code == "TAIEX" or now - timestamp >= CACHE_EXPIRY_SECONDS:
            continue
        if all(key in data for key in ("name", "prob")):
            items.append({"code": code, "name": data["name"], "prob": data["prob"]})
    return sorted(items, key=lambda item: item["prob"], reverse=True)[:limit]

def dashboard_sector_cards(limit=6):
    try:
        snapshot = load_sector_signal_snapshot(line_store)
    except Exception:
        snapshot = {}
    cards = []
    for name, items in (snapshot or {}).get("sectors", {}).items():
        if not items:
            continue
        leader = items[0]
        cards.append({
            "name": name,
            "count": len(items),
            "score": round(_safe_float(leader.get("score")), 1),
            "leader": {
                "code": str(leader.get("code") or ""),
                "name": str(leader.get("name") or ""),
                "prob": int(_safe_float(leader.get("prob"))),
                "trend": str(leader.get("trend") or "中性"),
                "foreign_net_5": int(_safe_float(leader.get("foreign_net_5"))),
                "as_of": str(leader.get("as_of") or ""),
            },
        })
    if cards:
        return sorted(cards, key=lambda item: item["score"], reverse=True)[:limit]
    fallback = []
    for item in cached_opportunities(limit):
        fallback.append({
            "name": "熱門觀察",
            "count": 1,
            "score": float(item["prob"]),
            "leader": {
                "code": item["code"],
                "name": item["name"],
                "prob": int(item["prob"]),
                "trend": "等待更新",
                "foreign_net_5": 0,
                "as_of": "",
            },
        })
    return fallback




def market_forecast(): return analyze("TAIEX")

# ==================================================
# 5. UI 渲染
# ==================================================



# ==================================================
# 6. 動態產業分類與選單生成
# ==================================================
def call_openalice(prompt):
    response = requests.post(
        OPENALICE_API_URL,
        headers={"Authorization": f"Bearer {OPENALICE_API_TOKEN}"},
        json={"prompt": _build_papi_prompt(prompt)},
        timeout=4,
    )
    response.raise_for_status()
    payload = response.json()
    summary = str(
        payload.get("summary") or payload.get("text") or payload.get("message") or ""
    ).strip()
    detail_url = str(payload.get("detail_url") or payload.get("url") or "").strip()
    if not summary:
        summary = "Papi 沒有回傳可用摘要。"
    return summary + (f"\n\n詳細分析：{detail_url}" if detail_url else "")


def _extract_stock_from_papi_prompt(prompt):
    """Extract a stock or market target from a natural-language Papi question."""
    prompt = str(prompt or "").strip()
    code_match = re.search(r"(?<!\d)(\d{4,5})(?!\d)", prompt)
    if code_match and code_match.group(1) in twstock.codes:
        code = code_match.group(1)
        return code, get_stock_name(code)

    name_matches = [
        (code, info.name) for code, info in twstock.codes.items()
        if info.name and info.name in prompt
    ]
    if name_matches:
        return max(name_matches, key=lambda item: len(item[1]))

    ticker_match = re.search(r"(?<![A-Z])([A-Z]{3,5})(?![A-Z])", prompt)
    if ticker_match and ticker_match.group(1) not in {"PAPI", "RSI", "MACD", "ETF"}:
        code, name = search_stock_code(ticker_match.group(1))
        if code:
            return code, name

    m = re.search(r"分析\s+(.+)", prompt)
    if m:
        keyword = m.group(1).strip()
        code, name = search_stock_code(keyword)
        if code:
            return code, name
    # Also try if the entire prompt is just a stock code or name
    code, name = search_stock_code(prompt)
    if code:
        return code, name
    if any(term in prompt for term in ("台股", "台灣股市", "大盤", "加權指數", "盤勢")):
        return "TAIEX", "台股大盤"
    return None, None


def _match_sector_from_prompt(prompt):
    """Try to match a Papi prompt to an industry_map category.

    Returns (category_name, stock_codes_list) or (None, None).
    """
    keywords = prompt.upper()
    best_cat = None
    best_len = 0
    for cat in industry_map:
        cat_upper = cat.upper()
        if cat_upper in keywords and len(cat_upper) > best_len:
            best_cat = cat
            best_len = len(cat_upper)
    if best_cat:
        return best_cat, industry_map[best_cat]
    return None, None


def _build_single_stock_context(data):
    """Build a data context string for a single analyzed stock."""
    bt = data.get("bt", {})
    foreign = data.get("foreign_flow", {})
    foreign_str = ""
    if foreign.get("available"):
        foreign_str = f"外資買賣超：{foreign.get('status', '未知')}（近5日淨額 {foreign.get('net_5', 0):.0f}）"
    news_titles = "\n".join(
        [f"  - {n['title']}" for n in data.get("news", [])[:3]]
    )
    return (
        f"▸ {data.get('name', '?')} ({data.get('code', '?')})："
        f"收盤 {data['price']:.2f}，"
        f"AI 勝率 {data['prob']}%，"
        f"趨勢 {data['trend']}，"
        f"RSI {data['rsi']:.1f}，"
        f"{'紅柱' if data['macd_osc'] > 0 else '綠柱'}，"
        f"KD {'黃金交叉' if data['k'] > data['d'] else '死亡交叉'}，"
        f"情緒 {data['s_status']}（{data['s_score']:.0f}），"
        f"情緒動能 {data.get('news_momentum', 0):+.0f}，"
        f"情緒分歧 {data.get('news_disagreement', 0):.0f}，"
        f"情緒波動 {data.get('news_weighted_volatility', 0):.0f}，"
        f"{foreign_str}，"
        f"回測策略報酬 {bt.get('strat_cum', 0):.1f}%，"
        f"勝率 {bt.get('win_rate', 0):.0f}%，"
        f"夏普 {bt.get('sharpe', 0):.2f}"
    )


def _gather_sector_data(codes, max_fresh=2, max_total=5):
    """Gather analysis data for a sector. Prioritize cache, analyze at most max_fresh new stocks.

    Returns a list of (code, data) tuples.
    """
    results = []
    fresh_count = 0
    now = time.time()

    # First pass: collect cached stocks
    for code in codes:
        if len(results) >= max_total:
            break
        if code in _SYSTEM_CACHE:
            cached_data, ts = _SYSTEM_CACHE[code]
            if now - ts < CACHE_EXPIRY_SECONDS and cached_data:
                results.append((code, cached_data))

    # Second pass: analyze a few uncached stocks if we need more
    if len(results) < max_total:
        for code in codes:
            if len(results) >= max_total or fresh_count >= max_fresh:
                break
            if any(r[0] == code for r in results):
                continue
            try:
                data = analyze(code)
                if data:
                    results.append((code, data))
                    fresh_count += 1
            except Exception:
                continue

    return results


def _build_papi_sector_examples(limit=3):
    if not line_store:
        return ""
    try:
        snapshot = load_sector_signal_snapshot(line_store)
    except Exception:
        return ""
    items = []
    for category, signals in (snapshot or {}).get("sectors", {}).items():
        for item in signals or []:
            items.append((category, item))
    items.sort(key=lambda pair: _safe_float(pair[1].get("score")), reverse=True)
    lines = []
    for category, item in items[:limit]:
        lines.append(
            f"- {item.get('name')} ({item.get('code')})：{category}，"
            f"AI 勝率 {int(_safe_float(item.get('prob')))}%，"
            f"{item.get('trend', '中性')}，"
            f"外資5日 {int(_safe_float(item.get('foreign_net_5'))):,}"
        )
    if not lines:
        return ""
    return "\n每日產業預測可舉例標的（只可從這裡挑，不要自己編）：\n" + "\n".join(lines)


def _build_papi_prompt(prompt):
    data_context = ""

    # 1. Try individual stock first
    code, name = _extract_stock_from_papi_prompt(prompt)
    if code:
        try:
            data = analyze(code)
        except Exception:
            data = None
        if data:
            data_context = f"""
以下是 {name} ({code}) 的最新量化分析數據（來自我們的 LightGBM 模型與技術指標系統）：
{_build_single_stock_context(data)}
- 回測結論：{data.get('bt', {}).get('conclusion', '無')}

請根據以上「真實數據」來回答使用者的問題。數據是核心依據，你的角色是用白話文幫新手解讀這些數據。
"""
        else:
            data_context = f"""
已辨識{name} ({code})，但本次未取得可用的量化分析數據。
只能說目前資料暫時無法取得；不得改用其他股票或產業資料回答，也不得猜測失敗原因。
"""
    # 2. If no individual stock, try sector/industry match
    if not data_context:
        cat, cat_codes = _match_sector_from_prompt(prompt)
        if cat and cat_codes:
            sector_data = _gather_sector_data(cat_codes)
            if sector_data:
                stock_lines = "\n".join(
                    _build_single_stock_context(d) for _, d in sector_data
                )
                avg_prob = sum(d["prob"] for _, d in sector_data) / len(sector_data)
                bullish = sum(1 for _, d in sector_data if d["trend"] == "多頭")
                total = len(sector_data)
                data_context = f"""
以下是「{cat}」產業的量化分析數據（來自我們的 LightGBM 模型，共掃描 {total} 檔代表性個股）：

產業概覽：
- 平均 AI 五日上漲機率：{avg_prob:.0f}%
- 多頭比例：{bullish}/{total} 檔呈多頭趨勢
- {'產業整體偏多' if bullish > total / 2 else '產業整體偏空' if bullish < total / 2 else '產業多空分歧'}

個股明細：
{stock_lines}

請根據以上「真實數據」綜合分析該產業的整體狀態與投資方向。引用具體個股數據來支撐你的論點，幫新手理解產業全貌。
"""
    if not data_context:
        data_context = _build_papi_sector_examples()
    if not data_context:
        data_context = "\n目前沒有與問題直接對應的量化資料，請明確說明資料不足，不要推測原因。"

    return f"""你是 Papi，也知道自己是 AI。

Papi 取自法文 papillon 的品牌化縮寫，意思是「蝴蝶」。你的品牌意象不是可愛，也不是童話感，而是敏銳、輕盈、能捕捉市場轉折訊號。你像一個在市場資料中快速穿梭的觀察者，專門從雜訊裡辨識趨勢變化、風險升高與可能的觀察機會。

你的任務不是聊天，而是替 LINE bot 使用者快速整理台股研究摘要與投資分析，讓使用者知道「現在能不能看、訊號在哪裡、風險有沒有變大」。

品牌核心：
* Papi 不是預言市場的角色，而是幫使用者從資料雜訊中辨識訊號的市場觀察者。
* 你重視的是「訊號是否清楚」、「風險是否升高」、「現在是否值得觀察」，而不是催促使用者買賣。
* 你不保證市場方向，只根據目前資料判斷機率、趨勢與風險。
* 蝴蝶意象應該體體現在分析方式，而不是每次回答都直接提到蝴蝶。

身份與定位：
* 你負責替 LINE bot 使用者做台股研究摘要與投資分析。
* 你的分析奠基於 LightGBM 量化模型與技術指標系統產出的真實數據。
* 你要把模型、技術指標、外資資料與產業預測，翻成新手聽得懂的判斷。
* 你的重點不是給投資口號，而是幫使用者快速知道目前是「可觀察」、「先等等」、「風險偏高」還是「資料不足」。
* 你可以判斷趨勢偏多、偏空或中性，但不能把模型結果說成保證。

品牌人格與風格限制：
* 你的語氣冷靜、簡潔、敏銳。不說教，也不推銷。
* 嚴格禁止使用任何無關的日常生活比喻（如跑車、雨天、購物等非財經事物比喻）。請直接使用單純、精確的白話財經語意說明。
* 該潑冷水就潑，但一定要說清楚原因。
* 不得宣稱資料庫未收錄；除非提示詞明確提供這項事實。
* 不得捏造系統或模型故障原因。沒有量化資料時，只能說目前資料不足或暫時無法取得。

指標新手翻譯對照表：
* AI 勝率 (prob)：AI 預測「未來 5 個交易日上漲的機率」。>58% 代表短線動能偏多；<45% 代表短線動能極弱。
* RSI 強弱指標 (rsi)：>70 視為「短線買氣超買過熱，追高風險升高」；<30 視為「超賣，可能醞釀反彈」。
* KD 隨機指標：黃金交叉為「短線價格轉折向上，是止跌或發動的初期訊號」；死亡交叉為「短線價格轉折向下，動能轉弱」。
* MACD 柱體：紅柱為「多頭氣勢擴大，價格容易續強」；綠柱為「多頭動能減弱或空頭修正中」。
* 外資買賣超/5日淨額：外資代表法人大戶資金。正值且大代表大戶買超，股價支撐力較強；負值代表大戶賣超，散戶接盤。
* 回測策略報酬/夏普值：模型歷史回測的表現。夏普值 > 1.5 代表該策略歷史走勢非常穩健，波動度較可控。

多指標決策優先順序（由高至低）：
1. 第一優先（風險煞車）：只要 RSI > 70（超買過熱）或 KD 出現死亡交叉，無論 AI 勝率多高，一律判定為「風險偏高」或「先等等」，並警告追高風險。
2. 第二優先（大戶避險）：若 AI 勝率偏多（>58%），但外資5日淨額為負（大戶賣超），必須判定為「先等等」，提醒新手雖有動能但大戶在撤退。
3. 第三優先（同向支持）：AI 勝率偏多（>58%）＋ KD 黃金交叉 ＋ MACD 紅柱 ＋ 外資買超，可判定為「可觀察」。

回答格式：
* 使用繁體中文與全形標點。
* 回覆可分成 2 到 3 段，每段 1 到 2 句。
* 第一段先講核心結論，最好直接落在「可觀察」、「先等等」、「風險偏高」或「資料不足」其中一種狀態。
* 第二段用具體的數據與白話翻譯支撐，切勿含糊。例如：「RSI 72（進入短線超買區）、外資5日賣超 1200 張（大戶退場）。」
* 第三段只在需要時提醒新手下一步的具體觀察指標或風險。
* 不需要寫標題，邏輯順序必須是：結論 → 依據 → 風險或觀察重點。
* 結尾或說明時，請明確提醒這只是「1~2 週的短線波段參考」，非長期投資建議。
* 如果使用者問「有什麼可以觀察、推薦、挑哪幾檔」時，最多提出 2 到 3 檔，且必須來自提供的產業預測或個股數據。

常用語氣與回答範例：
* 「先等等，目前訊號還不夠乾淨。雖然 AI 預測未來 5 天上漲機率有 62%（偏多），但 RSI 已經來到 72（進入短線超買區），追高風險相對升高。
新手建議在場外觀察，等 RSI 降溫、KD 重新出現黃金交叉再做判斷。（本分析為 1~2 週短線波段參考）」

* 「可觀察。AI 勝率 61%（短線動能偏多），且 KD 出現黃金交叉（短線價格轉折向上），外資近 5 日買超 2500 張代表有大戶資金支持。
這裡要注意外資是否持續買超，如果轉為賣超，短線動能可能會減弱。（本分析為 1~2 週短線波段參考）」

{data_context}

使用者問題：{prompt}"""


def call_papi_gemini_fallback(prompt):
    if not gemini_model:
        return None
    safety = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]

    max_retries = 3
    backoff = 0.5
    for attempt in range(max_retries):
        try:
            response = gemini_model.generate_content(_build_papi_prompt(prompt), safety_settings=safety)
            summary = (getattr(response, "text", "") or "").strip()
            if not summary:
                return None
            return summary
        except Exception as exc:
            logger.warning(f"Gemini API call failed (attempt {attempt + 1}/{max_retries}): {exc}")
            if attempt < max_retries - 1:
                time.sleep(backoff)
                backoff *= 2
                continue
            logger.error(f"Gemini API call failed after {max_retries} attempts: {exc}", exc_info=True)
            raise


def sector_signal_item(code, data):
    return _sector_signal_item(code, data, get_stock_name=get_stock_name)


def build_sector_signal_snapshot(market_map, analyze_fn, now=None, activity=None):
    return _build_sector_signal_snapshot(
        market_map,
        analyze_fn,
        now=now,
        activity=activity,
        scan_limit=SECTOR_SCAN_LIMIT,
        display_limit=SECTOR_DISPLAY_LIMIT,
        get_stock_name=get_stock_name,
    )


def build_market_map():
    return _build_market_map(twstock.codes, PAPI_THEME_SECTORS)

industry_map = build_market_map()


def find_industry_peers(code, market_map=None, limit=5):
    return _find_industry_peers(code, market_map or industry_map, limit=limit)

def build_category_quick_reply(page=1):
    cats = list(industry_map.keys())
    total = 1 if not cats else (len(cats) + CATEGORY_PAGE_SIZE - 1) // CATEGORY_PAGE_SIZE
    page = max(1, min(page, total))
    start = (page - 1) * CATEGORY_PAGE_SIZE
    items = [QuickReplyButton(action=MessageAction(label=c[:20], text=f"選產業_{c}")) for c in cats[start:start + CATEGORY_PAGE_SIZE]]
    if page < total and len(items) < 13:
        items.append(QuickReplyButton(action=MessageAction(label="更多分類▶", text=f"分類第_{page + 1}頁")))
    return QuickReply(items=items), f"請選擇市場類別（第 {page}/{total} 頁）👇"

# ==================================================
# 7. 自動化發報引擎
# ==================================================
# ==================================================
# 8. 路由與 LINE 基礎指令 (💡 確保名稱不重複版)
# ==================================================
def get_line_state(user_id):
    if line_store is None:
        raise StoreError("關注功能尚未設定")
    return line_store.load(user_id)[0]


def get_line_state_bounded(user_id, timeout=LINE_STATE_READ_BUDGET_SECONDS):
    store = line_store
    if store is None:
        raise StoreError("關注功能尚未設定")
    result = queue.Queue(maxsize=1)
    slots = _line_state_read_slots
    if not slots.acquire(blocking=False):
        logger.warning(f"Firestore read slots exhausted (MAX_WORKERS={LINE_STATE_READ_MAX_WORKERS}) for user {user_id}")
        raise StoreError("關注功能讀取忙碌")

    def load_state():
        try:
            value = (False, None)
            try:
                value = (True, store.load(user_id)[0])
            except BaseException as exc:
                logger.error(f"Firestore load exception for user {user_id}: {type(exc).__name__} - {exc}", exc_info=True)
            try:
                result.put_nowait(value)
            except BaseException:
                pass
        finally:
            slots.release()

    try:
        threading.Thread(target=load_state, daemon=True).start()
    except BaseException as error:
        slots.release()
        if isinstance(error, Exception):
            raise StoreError("關注功能讀取失敗") from None
        raise
    try:
        succeeded, state = result.get(timeout=timeout)
    except queue.Empty:
        raise StoreError("關注功能讀取逾時") from None
    if not succeeded:
        raise StoreError("關注功能讀取失敗")
    return state


def update_line_state(user_id, mutate):
    if line_store is None:
        raise StoreError("關注功能尚未設定")
    return line_store.update(user_id, mutate)


def _store_error_text():
    if line_store is None:
        return "關注功能尚未設定，請稍後再試。"
    return "關注功能暫時無法使用，請稍後再試。"




















def build_projection_flex(code, name, data, amount, base_url):
    projection = calculate_investment_projection(amount, data)
    if not projection["ok"]:
        return _empty_line_bubble("投資試算", "金額不足買進 1 股，請提高投入金額後再試。")
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box", "layout": "vertical", "paddingAll": "18px", "spacing": "sm",
            "contents": [
                {"type": "text", "text": f"{name} ({code})", "weight": "bold", "size": "lg", "wrap": True},
                {"type": "text", "text": f"投入 {projection['amount']:,.0f} 元，約可買 {projection['shares']:,} 股。", "color": "#0f766e", "weight": "bold", "size": "sm", "wrap": True},
                {"type": "text", "text": f"AI 策略歷史估算損益：{projection['strategy_profit']:,.0f} 元", "color": "#64748b", "size": "sm", "wrap": True},
                {"type": "text", "text": f"買進持有歷史估算損益：{projection['buy_hold_profit']:,.0f} 元", "color": "#64748b", "size": "sm", "wrap": True},
                {"type": "text", "text": "這是歷史回測換算，不代表未來獲利。", "color": "#94a3b8", "size": "xs", "wrap": True},
            ],
        },
        "footer": {
            "type": "box", "layout": "vertical", "paddingAll": "14px",
            "contents": [{"type": "button", "style": "primary", "color": "#39c6a3", "action": {
                "type": "uri", "label": "查看完整分析",
                "uri": f"{base_url.rstrip('/')}/stock/{code}",
            }}],
        },
    }










def _system_document_url(store, document_id):
    return (
        "https://firestore.googleapis.com/v1/projects/"
        f"{store.project_id}/databases/(default)/documents/system/"
        f"{urllib.parse.quote(document_id, safe='')}"
    )


def save_sector_signal_snapshot(store, snapshot):
    body = {
        "fields": {
            "payload": {
                "stringValue": json.dumps(
                    snapshot, ensure_ascii=False, separators=(",", ":")
                )
            }
        }
    }
    response = store._request(
        "PATCH",
        _system_document_url(store, SECTOR_SNAPSHOT_DOC),
        timeout=10,
        params={"updateMask.fieldPaths": "payload"},
        json=body,
    )
    if response.status_code != 200:
        raise StoreError(
            f"sector snapshot write failed with status {response.status_code}"
        )


def load_sector_signal_snapshot(store):
    response = store._request(
        "GET", _system_document_url(store, SECTOR_SNAPSHOT_DOC), timeout=5
    )
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise StoreError(
            f"sector snapshot read failed with status {response.status_code}"
        )
    try:
        raw = response.json().get("fields", {}).get("payload", {}).get("stringValue")
        snapshot = json.loads(raw)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("sectors"), dict):
            raise ValueError("invalid snapshot")
        return snapshot
    except (TypeError, ValueError, json.JSONDecodeError):
        raise StoreError("sector snapshot response was invalid") from None


def refresh_sector_signals(store):
    activity = fetch_market_activity()
    snapshot = build_sector_signal_snapshot(industry_map, analyze, activity=activity)
    save_sector_signal_snapshot(store, snapshot)
    return snapshot







def _build_stock_row(code):
    name = get_stock_name(code)
    return {
        "type": "box",
        "layout": "horizontal",
        "paddingAll": "12px",
        "cornerRadius": "8px",
        "backgroundColor": "#ffffff",
        "spacing": "sm",
        "margin": "md",
        "action": { "type": "message", "label": f"查詢 {code}", "text": code },
        "contents": [
            { "type": "text", "text": f"{code}", "color": "#64748b", "size": "sm", "weight": "bold", "flex": 2 },
            { "type": "text", "text": f"{name}", "color": "#0f172a", "size": "md", "weight": "bold", "flex": 4 },
            { "type": "text", "text": "前往分析 ▶", "color": "#0284c7", "size": "xs", "align": "end", "gravity": "center", "flex": 3 }
        ]
    }

def build_industry_carousel(cat, arr):
    bubbles = []
    aggr_list = arr[:5]
    if aggr_list:
        bubbles.append({
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#ef4444",
                "paddingAll": "16px",
                "contents": [ { "type": "text", "text": f"🔥 {cat} | 激進型推薦", "color": "#ffffff", "weight": "bold", "size": "lg" } ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#f8fafc",
                "paddingAll": "12px",
                "contents": [_build_stock_row(c) for c in aggr_list]
            }
        })
    cons_list = arr[5:10]
    if cons_list:
        bubbles.append({
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#3b82f6",
                "paddingAll": "16px",
                "contents": [ { "type": "text", "text": f"🛡️ {cat} | 保守型推薦", "color": "#ffffff", "weight": "bold", "size": "lg" } ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#f8fafc",
                "paddingAll": "12px",
                "contents": [_build_stock_row(c) for c in cons_list]
            }
        })
    return { "type": "carousel", "contents": bubbles }


def _build_sector_signal_row(item):
    code = item["code"]
    name = item["name"]
    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "12px",
        "cornerRadius": "8px",
        "backgroundColor": "#ffffff",
        "spacing": "xs",
        "margin": "md",
        "action": {"type": "message", "label": f"查詢 {code}", "text": code},
        "contents": [
            {
                "type": "text", "text": f"{name} ({code})",
                "color": "#0f172a", "size": "md", "weight": "bold", "wrap": True,
            },
            {
                "type": "text",
                "text": f"AI勝率 {item['prob']}%｜{item['trend']}｜外資5日 {item['foreign_net_5']:,.0f}",
                "color": "#475569", "size": "xs", "wrap": True,
            },
            {
                "type": "text",
                "text": f"排序分數 {item['score']:.1f}｜資料 {item['as_of']}",
                "color": "#0284c7", "size": "xs", "wrap": True,
            },
        ],
    }


def build_sector_signal_carousel(category, items):
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#0f766e",
            "paddingAll": "16px",
            "contents": [{
                "type": "text", "text": f"📊 {category}｜每日產業預測",
                "color": "#ffffff", "weight": "bold", "size": "lg", "wrap": True,
            }],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#f8fafc",
            "paddingAll": "12px",
            "contents": [
                _build_sector_signal_row(item)
                for item in items[:SECTOR_DISPLAY_LIMIT]
            ],
        },
    }


def market_insights_payload():
    document = fetch_market_insights()
    if document:
        return document
    fallback_metrics = {
        str(code).upper(): {
            "name": get_stock_name(code),
            "prob": None,
            "trend": "資料待更新",
            "as_of": "",
        }
        for category, codes in industry_map.items()
        if category not in {"全市場", "ETF專區"}
        for code in codes
    }
    return {
        "schema_version": 1,
        "as_of": datetime.date.today().isoformat(),
        "industries": build_industries(industry_map, fallback_metrics),
        "mops": [],
        "etfs": [],
        "supply_chains": build_supply_chains({}),
        "sources": ["Stock Papi fallback"],
        "degraded": True,
    }


def _reply_text(event, text):
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))


def _current_web_root():
    return request.host_url.replace("http://", "https://").rstrip("/")


def _require_same_pending(state, expected_pending):
    if state.get("pending") != expected_pending:
        raise StateError("提醒設定已變更，請重新操作。")


def _find_matching_alert(alerts, code, kind, value):
    return next(
        (
            alert for alert in alerts
            if alert.get("code") == code
            and (
                alert.get("kind") == kind
                or {alert.get("kind"), kind} <= {"price", "price_above"}
            )
            and alert.get("value") == value
        ),
        None,
    )


def _resolve_postback_stock(code):
    resolved_code, name = search_stock_code(code)
    if (
        resolved_code != code
        or not name
        or (name == code and code != "TAIEX")
    ):
        return None, None
    return resolved_code, name


@handler.add(PostbackEvent)
def handle_postback(event):
    try:
        _handle_postback_impl(event)
    except Exception as e:
        logger.error(f"Unexpected error in handle_postback: {e}", exc_info=True)
        try:
            _reply_text(event, "系統暫時忙碌中，請稍後再試 🙏")
        except Exception as reply_err:
            logger.error(f"Failed to send fallback reply in postback: {reply_err}", exc_info=True)

def _handle_postback_impl(event):
    return _line_handle_postback_impl(event, {
        "reply_text": _reply_text,
        "update_line_state": update_line_state,
        "store_error_text": _store_error_text,
        "resolve_stock": _resolve_postback_stock,
        "line_bot_api": line_bot_api,
        "analyze": analyze,
        "build_projection_flex": build_projection_flex,
        "current_web_root": _current_web_root,
        "find_matching_alert": _find_matching_alert,
    })


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        _handle_message_impl(event)
    except Exception as e:
        logger.error(f"Unexpected error in handle_message: {e}", exc_info=True)
        try:
            _reply_text(event, "系統暫時忙碌中，請稍後再試 🙏")
        except Exception as reply_err:
            logger.error(f"Failed to send fallback reply in message: {reply_err}", exc_info=True)

def _handle_message_impl(event):
    return _line_handle_message_impl(event, {
        "reply_text": _reply_text,
        "line_store": line_store,
        "line_bot_api": line_bot_api,
        "get_line_state_bounded": get_line_state_bounded,
        "update_line_state": update_line_state,
        "require_same_pending": _require_same_pending,
        "find_matching_alert": _find_matching_alert,
        "store_error_text": _store_error_text,
        "now": time.time,
        "is_crypto_query": _is_crypto_query,
        "openalice_url": OPENALICE_API_URL,
        "openalice_token": OPENALICE_API_TOKEN,
        "call_openalice": call_openalice,
        "call_papi_fallback": call_papi_gemini_fallback,
        "logger": logger,
        "search_stock_code": search_stock_code,
        "analyze": analyze,
        "build_projection_flex": build_projection_flex,
        "build_category_quick_reply": build_category_quick_reply,
        "industry_map": industry_map,
        "load_sector_signal_snapshot": load_sector_signal_snapshot,
        "build_sector_signal_carousel": build_sector_signal_carousel,
        "web_root": request.host_url.replace("http://", "https://").rstrip("/"),
        "request_host_url": request.host_url,
    })


def route_dependencies():
    return {
        "search_stock": lambda query: search_stock_code(query),
        "load_report_index": lambda: _published_report_index(),
        "load_report_pdf": lambda item: load_report_pdf(
            item, load_object=_gcs_get_report_object
        ),
        "sample_report_path": SAMPLE_REPORT_PATH,
        "sample_report_filename": SAMPLE_REPORT_FILENAME,
        "max_pdf_bytes": REPORT_PDF_MAX_BYTES,
        "analyze": lambda code: analyze(code),
        "dashboard_sector_cards": lambda: dashboard_sector_cards(),
        "cached_opportunities": lambda: cached_opportunities(),
        "build_market_heatmap": build_market_heatmap,
        "dashboard_top_picks": dashboard_top_picks,
        "industry_map": lambda: industry_map,
        "market_insights_payload": lambda: market_insights_payload(),
        "twstock_codes": lambda: twstock.codes,
        "is_us_ticker": is_us_ticker,
        "find_industry_peers": lambda code: find_industry_peers(code),
        "get_stock_name": lambda code: get_stock_name(code),
        "handler": handler,
        "get_line_bot_api": lambda: line_bot_api,
        "get_line_store": lambda: line_store,
        "get_broadcast_token": lambda: BROADCAST_TOKEN,
        "get_alert_task_token": lambda: ALERT_TASK_TOKEN,
        "get_broadcast_insight": lambda name, data, bt, news: get_ai_insight_for_broadcast(
            name, data, bt, news
        ),
        "refresh_sector_signals": lambda store: refresh_sector_signals(store),
        "run_alert_checks": lambda store, analyze_fn, push, today, root: run_alert_checks(
            store, analyze_fn, push, today, root
        ),
    }
