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
import copy
from concurrent.futures import ThreadPoolExecutor
from html import escape
import requests
import twstock
import urllib.parse
import json

from market_insights import build_industries, build_supply_chains

from flask import Flask, request, abort, render_template, jsonify, redirect, url_for
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, PostbackEvent, TextMessage, TextSendMessage, FlexSendMessage,
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
from stock_papi.web.routes.reports import register_report_routes
from stock_papi.web.routes.dashboard import register_dashboard_page
from stock_papi.web.routes.system import register_system_routes
from stock_papi.web.routes.market import register_market_routes


def redact_secrets(text: str, extra_secrets: list[str] | None = None) -> str:
    def _redact_key_value(match):
        quote = match.group(2) or ""
        if quote:
            return f"{match.group(1)}{quote}********{quote}"
        return f"{match.group(1)}********"

    redacted = str(text)
    redacted = re.sub(
        r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=-]+",
        r"\1 ********",
        redacted,
    )
    redacted = re.sub(
        (
            r"(?i)([\"']?\b(?:access_token|refresh_token|id_token|api_token|"
            r"client_secret|api_key|api-key|apikey|password|passwd|secret|"
            r"token|pwd)\b[\"']?\s*(?::=|[:=])\s*)"
            r"(?:([\"'])(.*?)\2|([^\"'\s,;&}]+))"
        ),
        _redact_key_value,
        redacted,
    )
    for secret in extra_secrets or []:
        secret_text = str(secret)
        if len(secret_text) >= 8:
            redacted = re.sub(re.escape(secret_text), "********", redacted)
    return redacted


def safe_exception_text(exc: Exception, extra_secrets: list[str] | None = None) -> str:
    return redact_secrets(str(exc), extra_secrets=extra_secrets)


class RedactingFormatter(logging.Formatter):
    def __init__(
        self,
        fmt=None,
        datefmt=None,
        style="%",
        validate=True,
        *,
        defaults=None,
        secrets_provider=None,
        original_formatter=None,
    ):
        super().__init__(
            fmt=fmt,
            datefmt=datefmt,
            style=style,
            validate=validate,
            defaults=defaults,
        )
        self._secrets_provider = secrets_provider or (lambda: ())
        self._original_formatter = original_formatter

    def format(self, record):
        record_copy = copy.copy(record)
        formatted = (
            self._original_formatter.format(record_copy)
            if self._original_formatter
            else super().format(record_copy)
        )
        if record.levelno < logging.WARNING:
            return formatted
        return redact_secrets(formatted, self._get_extra_secrets())

    def _get_extra_secrets(self):
        try:
            return [secret for secret in (self._secrets_provider() or []) if secret]
        except Exception:
            return []


def _iter_existing_loggers():
    yield logging.getLogger()
    for logger_ref in logging.Logger.manager.loggerDict.values():
        if isinstance(logger_ref, logging.Logger):
            yield logger_ref


def _install_redacting_formatter(handler, secrets_provider=None):
    current = handler.formatter or logging.Formatter()
    if isinstance(current, RedactingFormatter):
        return
    handler.setFormatter(
        RedactingFormatter(
            secrets_provider=secrets_provider,
            original_formatter=current,
        )
    )


def install_redacting_formatters(secrets_provider=None):
    for log in _iter_existing_loggers():
        for handler in log.handlers:
            _install_redacting_formatter(handler, secrets_provider)


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

app = Flask("app", root_path=os.path.dirname(os.path.dirname(__file__)))
app.config["MAX_CONTENT_LENGTH"] = 1_000_000
SAMPLE_REPORT_FILENAME = "stock-papi-tw-industry-daily-SAMPLE.pdf"
SAMPLE_REPORT_PATH = os.path.join(app.root_path, "static", "samples", SAMPLE_REPORT_FILENAME)
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


def render_web(d):
    bt = d['bt']
    news_blocks = []
    direction_labels = {"positive": "正向", "negative": "負向", "neutral": "中性"}
    for n in d['news']:
        title = n.get("normalized_title") or n.get("title", "")
        source = n.get("source") or "來源未知"
        published = str(n.get("published_at") or "")[:10] or "時間未知"
        direction = direction_labels.get(n.get("direction"), "中性")
        news_blocks.append(
            f'<a href="{escape(str(n.get("link", "")), quote=True)}" target="_blank" rel="noopener noreferrer" class="news-link">'
            f'🔹 {escape(str(title))}<small style="display:block;color:#94a3b8;margin-top:4px;">'
            f'{escape(str(source))} · {escape(published)} · {direction}</small></a>'
        )
    news_html = "".join(news_blocks) if news_blocks else "暫無相關新聞或輿論"
    sentiment_summary = _format_sentiment_summary(d)
    
    html = f"""
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{d['name']} 分析報告</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@300;400;700&display=swap" rel="stylesheet">
<script src="https://unpkg.com/lightweight-charts@4.2.2/dist/lightweight-charts.standalone.production.js"></script>
<style>
    body {{ margin:0; background: linear-gradient(135deg, #0f2027, #203a43, #2c5364); background-attachment: fixed; color: #f1f1f1; font-family: 'Noto Sans TC', sans-serif; }}
    .wrap {{ max-width:920px; margin:auto; padding:30px 20px 60px; }}
    h1 {{ font-size:42px; margin-bottom:24px; font-weight: 700; text-shadow: 0 2px 10px rgba(0,0,0,0.5); }}
    .card {{ background: rgba(255, 255, 255, 0.05); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); border: 1px solid rgba(255, 255, 255, 0.15); box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3); border-radius: 20px; padding: 26px; margin-bottom: 24px; transition: transform 0.3s ease; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:20px; }}
    .small {{ font-size:17px; line-height:1.8; }}
    .highlight {{ color: #00f2fe; font-weight: bold; font-size: 1.1em; }}
    h2 {{ font-size: 22px; margin-top: 0; margin-bottom: 15px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 10px; }}
    .news-link {{ display: block; color: #e0e0e0; text-decoration: none; margin-bottom: 14px; line-height: 1.5; }}
    #tvchart {{ width: 100%; height: 450px; border-radius: 12px; overflow: hidden; margin-top: 10px; }}
</style>
</head>
<body>
<div class="wrap">
<h1>{d['name']} ({d['code']})</h1>

<div class="card small">
    💰 最新收盤：<span class="highlight">{d['price']:.2f}</span><br>
    📈 當前趨勢：{d['trend']}<br>
    🎯 五日上漲機率：<span class="highlight">{d['prob']}%</span>
</div>

<div class="card">
    <h2>📈 互動式技術線圖與預測軌跡</h2>
    <div id="tvchart"></div>
</div>

<div class="grid">
    <div class="card small" style="border-left: 4px solid #ff9800;">
        <h2 style="color: #ff9800; border-bottom: none; margin-bottom: 5px;">🤖 AI 決策核心邏輯</h2>
        <div style="font-size: 15px; color: #bbb; margin-bottom: 15px;">特徵權重解析 (Feature Importance)</div>
        <div style="background: rgba(0,0,0,0.3); padding: 15px; border-radius: 12px; margin-bottom: 10px;">🥇 <span style="color:#fff;">{bt['top_features'][0]}</span></div>
        <div style="background: rgba(0,0,0,0.3); padding: 15px; border-radius: 12px; margin-bottom: 10px;">🥈 <span style="color:#fff;">{bt['top_features'][1]}</span></div>
        <div style="background: rgba(0,0,0,0.3); padding: 15px; border-radius: 12px;">🥉 <span style="color:#fff;">{bt['top_features'][2]}</span></div>
    </div>
    <div class="card small">
        <h2>📑 指標摘要</h2>
        📈 趨勢判讀：{d['trend']}<br>
        🌊 均線狀態：{'站上 MA20 (支撐強)' if d['price'] > d['ma20'] else '跌破 MA20 (壓力大)'}<br>
        🌡 RSI 強弱：{'動能偏強' if d['rsi'] >= 55 else '中性' if d['rsi'] >= 45 else '動能偏弱'}<br>
        📊 MACD 柱狀：{'紅柱 (多頭動能)' if d['macd_osc'] > 0 else '綠柱 (空頭動能)'}<br>
        📉 KD 指標：{'黃金交叉' if d['k'] > d['d'] else '死亡交叉'}<br>
        🎯 五日上漲機率：<span class="highlight">{d['prob']}%</span>
    </div>
</div>

<div class="card small">
    <h2>📊 歷史回測報告 (近 {bt['days']} 交易日)</h2>
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 12px; margin-bottom: 20px;">
        <div style="background: rgba(0,0,0,0.25); padding: 15px; border-radius: 12px; text-align: center;"><div style="font-size: 13px; color: #aaa; margin-bottom: 5px;">AI 策略報酬</div><div class="highlight" style="font-size: 1.3em;">{bt['strat_cum']:.2f}%</div></div>
        <div style="background: rgba(0,0,0,0.25); padding: 15px; border-radius: 12px; text-align: center;"><div style="font-size: 13px; color: #aaa; margin-bottom: 5px;">買進持有報酬</div><div style="font-size: 1.3em; color: #ddd;">{bt['bh_cum']:.2f}%</div></div>
        <div style="background: rgba(0,0,0,0.25); padding: 15px; border-radius: 12px; text-align: center;"><div style="font-size: 13px; color: #aaa; margin-bottom: 5px;">五日方向準確率</div><div style="font-size: 1.3em; color: #ddd;">{bt['accuracy']:.1f}%</div></div>
        <div style="background: rgba(0,0,0,0.25); padding: 15px; border-radius: 12px; text-align: center;"><div style="font-size: 13px; color: #aaa; margin-bottom: 5px;">Brier Score</div><div style="font-size: 1.3em; color: #ddd;">{bt['brier']:.3f}</div></div>
        <div style="background: rgba(0,0,0,0.25); padding: 15px; border-radius: 12px; text-align: center;"><div style="font-size: 13px; color: #aaa; margin-bottom: 5px;">進場勝率</div><div style="font-size: 1.3em; color: #ddd;">{bt['win_rate']:.1f}%</div></div>
        <div style="background: rgba(0,0,0,0.25); padding: 15px; border-radius: 12px; text-align: center;"><div style="font-size: 13px; color: #aaa; margin-bottom: 5px;">交易次數</div><div style="font-size: 1.3em; color: #ddd;">{bt['trades']} 次</div></div>
        <div style="background: rgba(0,0,0,0.25); padding: 15px; border-radius: 12px; text-align: center;"><div style="font-size: 13px; color: #aaa; margin-bottom: 5px;">最大回檔</div><div style="font-size: 1.3em; color: #ff6b6b;">{bt['mdd']:.2f}%</div></div>
        <div style="background: rgba(0,0,0,0.25); padding: 15px; border-radius: 12px; text-align: center;"><div style="font-size: 13px; color: #aaa; margin-bottom: 5px;">夏普值</div><div style="font-size: 1.3em; color: #ddd;">{bt['sharpe']:.2f}</div></div>
    </div>
    <div style="background: rgba(0,242,254,0.05); border-left: 4px solid #00f2fe; padding: 18px; border-radius: 0 12px 12px 0;">
        <div style="font-weight: bold; margin-bottom: 10px; color: #00f2fe; font-size: 18px;">💡 資產管理評估</div>
        <div style="color: #e0e0e0; line-height: 1.6;">{bt['conclusion']}</div>
    </div>
</div>

<div class="card small">
    <h2>📰 相關即時新聞與輿論分析</h2>
    <div style="margin-bottom: 15px; background: rgba(255,255,255,0.05); padding: 15px; border-radius: 12px; border-left: 4px solid {'#ef5350' if d['s_score']<40 else '#26a69a'};">
        <span style="color: #aaa; font-size: 14px;">新聞／輿論情緒</span><br>
        <span style="font-size: 24px; font-weight: bold; color: {'#ef5350' if d['s_score']<40 else '#26a69a'};">{d['s_score']:.1f} ({d['s_status']})</span><br>
        <span style="color:#94a3b8;font-size:13px;">{sentiment_summary}</span>
    </div>
    {news_html}
</div>

<div class="card small" style="background: rgba(255, 255, 255, 0.08); border-top: 4px solid #6366f1;">
    <h2 style="color: #818cf8;">📖 新手投資小辭典 (給剛接觸股市的你)</h2>
    <div style="margin-bottom: 12px;"><strong>🔹 MA20 (月均線)：</strong>就像是過去一個月的「平均成本」。股價站在上面代表多數人賺錢（趨勢偏多），跌破代表多數人賠錢。</div>
    <div style="margin-bottom: 12px;"><strong>🔹 RSI (相對強弱)：</strong>用來判斷「是不是漲太多或跌太深」。超過 70 小心過熱，低於 30 代表可能跌過頭了。</div>
    <div style="margin-bottom: 12px;"><strong>🔹 MACD (動能指標)：</strong>紅柱代表「上漲力道變強」，綠柱代表「下跌力道變強」，就像是踩油門和煞車。</div>
    <div style="margin-bottom: 12px;"><strong>🔹 KD (隨機指標)：</strong>用來抓「轉折點」。黃金交叉（K往上穿過D）是起漲訊號，死亡交叉是下跌訊號。</div>
    <div style="margin-bottom: 12px;"><strong>🔹 夏普值 (Sharpe Ratio)：</strong>這就是「CP值」。數值越高，代表承擔一樣的風險下，能賺到的錢越多！</div>
    <div><strong>🔹 最大回檔 (MDD)：</strong>也就是「歷史最大跌幅」。最倒楣的情況下，你的資產會縮水多少百分比。</div>
</div>

</div>

<script>
    try {{
        const chartContainer = document.getElementById('tvchart');
        const chartOptions = {{
            width: chartContainer.clientWidth, height: 450,
            layout: {{ backgroundColor: 'transparent', textColor: '#d1d4dc' }},
            grid: {{ vertLines: {{ color: 'rgba(42, 46, 57, 0.15)' }}, horzLines: {{ color: 'rgba(42, 46, 57, 0.15)' }} }},
            timeScale: {{ timeVisible: true }}
        }};
        const chart = LightweightCharts.createChart(chartContainer, chartOptions);

        const candleS = chart.addCandlestickSeries({{ upColor: '#ef5350', downColor: '#26a69a', borderDownColor: '#26a69a', borderUpColor: '#ef5350', wickDownColor: '#26a69a', wickUpColor: '#ef5350' }});
        const cData = {d['candles']};
        candleS.setData(cData);

        chart.addLineSeries({{ color: '#00f2fe', lineWidth: 1, title: 'MA20' }}).setData({d['ma20_line']});
        chart.addLineSeries({{ color: '#ff9800', lineWidth: 2, lineStyle: 2, title: '5日預測' }}).setData({d['pred']});

        const probS = chart.addHistogramSeries({{ priceFormat: {{ type: 'volume' }}, priceScaleId: '' }});
        chart.priceScale('').applyOptions({{ scaleMargins: {{ top: 0.8, bottom: 0 }} }});
        probS.setData({d['prob_h']}.map(x=>({{ time: x.time, value: x.value, color: x.value >= 50 ? 'rgba(38,166,154,0.4)' : 'rgba(239,83,80,0.4)' }})));
        
        if (cData.length > 120) chart.timeScale().setVisibleLogicalRange({{ from: cData.length - 120, to: cData.length + 5 }});
        
        window.addEventListener('resize', () => {{ chart.resize(chartContainer.clientWidth, 450); }});
    }} catch (err) {{
        document.getElementById('tvchart').innerHTML = "<div style='color:#ff6b6b; padding:20px;'>圖表載入失敗：" + err.message + "</div>";
    }}
</script>
</body>
</html>
"""
    return html

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
@app.route("/broadcast_weekly", methods=["GET"])
def broadcast_weekly():
    if not BROADCAST_TOKEN:
        return "廣播功能未設定", 503
    if not hmac.compare_digest(request.args.get("token", ""), BROADCAST_TOKEN):
        return "身份驗證失敗", 403
    d = analyze("TAIEX")
    if not d: return "分析失敗", 500
    
    insight = get_ai_insight_for_broadcast("台股大盤", {"price": d['price'], "prob": d['prob']}, d['bt'], d['news'])
    
    url = f"{request.host_url}market".replace("http://", "https://")
    msg = f"🌞 周一 AI 投資晨報\n\n📊 大盤分析：\n{insight}\n\n🔗 點擊查看 AI 預測軌跡：\n{url}"
    try:
        line_bot_api.broadcast(TextSendMessage(text=msg))
        return f"廣播成功：{datetime.datetime.now()}", 200
    except Exception as e:
        return f"發送失敗：{str(e)}", 500

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


register_dashboard_page(app)
register_system_routes(app, search_stock=lambda query: search_stock_code(query))


register_report_routes(
    app,
    load_index=lambda: _published_report_index(),
    load_pdf=lambda item: load_report_pdf(
        item, load_object=_gcs_get_report_object
    ),
    sample_report_path=SAMPLE_REPORT_PATH,
    sample_report_filename=SAMPLE_REPORT_FILENAME,
    max_pdf_bytes=REPORT_PDF_MAX_BYTES,
)


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


register_market_routes(
    app,
    analyze=lambda code: analyze(code),
    dashboard_sector_cards=lambda: dashboard_sector_cards(),
    cached_opportunities=lambda: cached_opportunities(),
    build_market_heatmap=build_market_heatmap,
    dashboard_top_picks=dashboard_top_picks,
    industry_map=lambda: industry_map,
    market_insights_payload=lambda: market_insights_payload(),
    twstock_codes=lambda: twstock.codes,
    is_us_ticker=is_us_ticker,
    find_industry_peers=lambda code: find_industry_peers(code),
    get_stock_name=lambda code: get_stock_name(code),
)


@app.route("/callback", methods=["POST"])
def callback():
    try: handler.handle(request.get_data(as_text=True), request.headers.get("X-Line-Signature", ""))
    except InvalidSignatureError: abort(400)
    return "OK"


@app.route("/tasks/refresh-sector-signals", methods=["POST"])
def refresh_sector_signals_task():
    if not ALERT_TASK_TOKEN:
        return "產業預測排程尚未設定", 503
    if not hmac.compare_digest(
        request.headers.get("Authorization", ""),
        f"Bearer {ALERT_TASK_TOKEN}",
    ):
        return "身份驗證失敗", 403
    if line_store is None:
        return "關注功能尚未設定", 503
    try:
        snapshot = refresh_sector_signals(line_store)
    except Exception:
        return "產業預測排程執行失敗", 500
    return f"產業預測排程執行完成：{snapshot.get('as_of')}", 200


@app.route("/tasks/check-alerts", methods=["POST"])
def check_alerts_task():
    if not ALERT_TASK_TOKEN:
        return "提醒排程尚未設定", 503
    if not hmac.compare_digest(
        request.headers.get("Authorization", ""),
        f"Bearer {ALERT_TASK_TOKEN}",
    ):
        return "身份驗證失敗", 403
    if line_store is None:
        return "關注功能尚未設定", 503

    def push(user_id, contents):
        messages = contents if isinstance(contents, list) else [contents]
        messages = [
            FlexSendMessage(alt_text="股票提醒已觸發", contents=message)
            for message in messages
        ]
        line_bot_api.push_message(user_id, messages[0] if len(messages) == 1 else messages)

    try:
        run_alert_checks(
            line_store,
            analyze,
            push,
            datetime.date.today().isoformat(),
            request.host_url.replace("http://", "https://").rstrip("/"),
        )
    except Exception:
        return "提醒排程執行失敗", 500
    return "提醒排程執行完成", 200


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
    user_id = getattr(getattr(event, "source", None), "user_id", None)
    if not user_id:
        _reply_text(event, "無法識別 LINE 使用者，請從一對一聊天室操作。")
        return

    payload = getattr(getattr(event, "postback", None), "data", "")
    stock_match = re.fullmatch(r"(?:watch:(?:add|remove)|alert:menu|calc:menu|calc:custom):([A-Za-z0-9-]+)", payload)
    calc_amount_match = re.fullmatch(r"calc:amount:([A-Za-z0-9-]+):([0-9]+(?:\.[0-9]+)?)", payload)
    alert_start_match = re.fullmatch(
        r"alert:start:([A-Za-z0-9-]+):(price|price_above|price_below|probability)",
        payload,
    )
    alert_trend_match = re.fullmatch(
        r"alert:trend:([A-Za-z0-9-]+):(多頭|空頭)",
        payload,
    )
    alert_remove_match = re.fullmatch(r"alert:remove:([0-9a-fA-F]{32})", payload)

    if not any((stock_match, calc_amount_match, alert_start_match, alert_trend_match, alert_remove_match)):
        _reply_text(event, "無效的操作，請重新開啟功能選單。")
        return

    if alert_remove_match:
        alert_id = alert_remove_match.group(1)
        found = {"value": False}

        def delete_alert(state):
            alerts = state.get("alerts", [])
            found["value"] = any(item.get("id") == alert_id for item in alerts)
            state["alerts"] = [item for item in alerts if item.get("id") != alert_id]

        try:
            update_line_state(user_id, delete_alert)
            _reply_text(event, "提醒已移除。" if found["value"] else "找不到這筆提醒，可能已經移除。")
        except StoreError:
            _reply_text(event, _store_error_text())
        return

    match = stock_match or calc_amount_match or alert_start_match or alert_trend_match
    code, name = _resolve_postback_stock(match.group(1))
    if not code:
        _reply_text(event, "找不到這檔股票，請重新查詢後再操作。")
        return

    if payload == f"alert:menu:{code}":
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(
                alt_text=f"設定 {name} 提醒",
                contents=build_alert_menu_flex(code, name),
            ),
        )
        return

    if payload == f"calc:menu:{code}":
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(
                alt_text=f"{name} 投資試算",
                contents=build_calculator_menu_flex(code, name),
            ),
        )
        return

    if payload == f"calc:custom:{code}":
        _reply_text(event, f"請輸入：試算 {code} 100000\n把 100000 換成你的投入金額。")
        return

    if calc_amount_match:
        data = analyze(code)
        if not data:
            _reply_text(event, "查無資料，請稍後再試。")
            return
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(
                alt_text=f"{name} 投資試算",
                contents=build_projection_flex(code, name, data, calc_amount_match.group(2), _current_web_root()),
            ),
        )
        return

    try:
        if payload == f"watch:add:{code}":
            update_line_state(user_id, lambda state: add_watch(state, code, name))
            reply = f"已將 {name} ({code}) 加入關注。"
        elif payload == f"watch:remove:{code}":
            update_line_state(user_id, lambda state: remove_watch(state, code))
            reply = f"已將 {name} ({code}) 移除關注，相關提醒也已移除。"
        elif alert_start_match:
            kind = alert_start_match.group(2)

            def begin_alert(state):
                add_watch(state, code, name)
                start_pending(state, code, name, kind)

            update_line_state(user_id, begin_alert)
            label = {
                "price": "收盤價站上",
                "price_above": "收盤價站上",
                "price_below": "收盤價跌破",
            }.get(kind, "AI 勝率（1 到 99）")
            reply = f"請輸入 {name} 的{label}門檻數字，或輸入「取消」。"
        elif alert_trend_match:
            trend = alert_trend_match.group(2)
            created = {"value": False}

            def create_trend_alert(state):
                created["value"] = False
                add_watch(state, code, name)
                if _find_matching_alert(state.get("alerts", []), code, "trend", trend):
                    return
                add_alert(state, code, name, "trend", trend)
                created["value"] = True

            update_line_state(user_id, create_trend_alert)
            reply = (
                f"已建立 {name} 趨勢為{trend}時的提醒。"
                if created["value"]
                else f"{name} 趨勢為{trend}時的提醒已存在。"
            )
        else:
            _reply_text(event, "無效的操作，請重新開啟功能選單。")
            return
        _reply_text(event, reply)
    except StateError as error:
        _reply_text(event, str(error))
    except StoreError:
        _reply_text(event, _store_error_text())


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
    msg = event.message.text.strip()
    web_root = request.host_url.replace("http://", "https://").rstrip("/")
    user_id = getattr(getattr(event, "source", None), "user_id", None)
    current_state = None
    state_load_failed = False

    if line_store is not None and user_id:
        try:
            current_state = get_line_state_bounded(user_id)
        except StoreError:
            state_load_failed = True

    if current_state and current_state.get("pending"):
        expected_pending = dict(current_state["pending"])
        try:
            if msg == "取消":
                def cancel_pending(state):
                    _require_same_pending(state, expected_pending)
                    state["pending"] = None

                update_line_state(user_id, cancel_pending)
                _reply_text(event, "已取消提醒設定。")
            else:
                outcome = {"alert": None, "created": False, "expired": False}

                def finish_pending(state):
                    outcome.update(alert=None, created=False, expired=False)
                    _require_same_pending(state, expected_pending)
                    now = time.time()
                    if expected_pending["expires_at"] <= now:
                        state["pending"] = None
                        outcome["expired"] = True
                        return
                    preview_state = {
                        "pending": dict(expected_pending),
                        "alerts": [],
                    }
                    preview = consume_pending(preview_state, msg, now=now)
                    duplicate = _find_matching_alert(
                        state.get("alerts", []),
                        preview["code"],
                        preview["kind"],
                        preview["value"],
                    )
                    if duplicate:
                        state["pending"] = None
                        outcome["alert"] = duplicate
                        return
                    alert = consume_pending(state, msg, now=now)
                    outcome["alert"] = alert
                    outcome["created"] = True

                update_line_state(user_id, finish_pending)
                if outcome["expired"]:
                    _reply_text(event, "提醒設定已逾時，請重新設定。")
                else:
                    alert = outcome["alert"]
                    label = {
                        "price": "收盤價站上",
                        "price_above": "收盤價站上",
                        "price_below": "收盤價跌破",
                    }.get(alert["kind"], "AI 勝率")
                    reply = (
                        f"已建立 {alert['name']} 的{label}提醒。"
                        if outcome["created"]
                        else f"{alert['name']} 的{label}提醒已存在。"
                    )
                    _reply_text(event, reply)
        except StateError as error:
            _reply_text(event, str(error))
        except StoreError:
            _reply_text(event, _store_error_text())
        return

    papi_match = re.fullmatch(r"(?i)papi\s*(.+)", msg)
    if papi_match:
        prompt = papi_match.group(1).strip()
        if _is_crypto_query(prompt):
            _reply_text(event, "Papi 分析目前不支援虛擬貨幣。")
        elif OPENALICE_API_URL and OPENALICE_API_TOKEN:
            try:
                _reply_text(event, call_openalice(prompt))
            except (requests.RequestException, ValueError, TypeError):
                _reply_text(event, "Papi 分析服務暫時無法回應，請稍後再試。")
        else:
            try:
                reply = call_papi_gemini_fallback(prompt)
                _reply_text(event, reply or "Papi 分析服務尚未設定。")
            except Exception as exc:
                logger.error("Papi Gemini fallback failed: %s", exc)
                _reply_text(event, "Papi AI 摘要暫時失敗；你仍可直接輸入股票代號查看完整量化分析。")
        return

    calc_text = re.fullmatch(r"試算\s+([A-Za-z0-9-]+)\s+([0-9]+(?:\.[0-9]+)?)", msg)
    if calc_text:
        code, name = search_stock_code(calc_text.group(1))
        if not code:
            _reply_text(event, "找不到這檔股票，請重新查詢後再操作。")
            return
        data = analyze(code)
        if not data:
            _reply_text(event, "查無資料，請稍後再試。")
            return
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(
                alt_text=f"{name} 投資試算",
                contents=build_projection_flex(code, name, data, calc_text.group(2), web_root),
            ),
        )
        return
    if msg.startswith("試算"):
        _reply_text(event, "請用：試算 2330 100000，或先查詢股票後點選「投資試算」。")
        return

    if msg in ("大盤預測", "大盤", "今日盤勢"):
        data = analyze("TAIEX")
        if not data:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="大盤資料暫時無法取得，請稍後再試。"))
            return
        url = f"{web_root}/market"
        flex_content = build_stock_flex_message("TAIEX", "台股大盤 (加權指數)", data, url)
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="📊 台股大盤預測出爐，點擊查看！", contents=flex_content))
        
    elif msg in ("預測", "熱門產業"):
        qr, _ = build_category_quick_reply(1)
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="請選擇產業板塊", contents=build_welcome_flex(), quick_reply=qr))

    elif msg == "我的關注":
        if line_store is None:
            _reply_text(event, _store_error_text())
        elif not user_id:
            _reply_text(event, "無法識別 LINE 使用者，請從一對一聊天室操作。")
        elif state_load_failed:
            _reply_text(event, _store_error_text())
        else:
            line_bot_api.reply_message(
                event.reply_token,
                FlexSendMessage(
                    alt_text="我的關注",
                    contents=build_watchlist_flex(current_state, web_root),
                ),
            )

    elif msg == "強勢訊號":
        if line_store is None:
            _reply_text(event, _store_error_text())
        elif not user_id:
            _reply_text(event, "無法識別 LINE 使用者，請從一對一聊天室操作。")
        elif state_load_failed:
            _reply_text(event, _store_error_text())
        else:
            line_bot_api.reply_message(
                event.reply_token,
                FlexSendMessage(
                    alt_text="強勢訊號",
                    contents=build_strong_signals_flex(current_state, web_root),
                ),
            )

    elif msg == "提醒管理":
        if line_store is None:
            _reply_text(event, _store_error_text())
        elif not user_id:
            _reply_text(event, "無法識別 LINE 使用者，請從一對一聊天室操作。")
        elif state_load_failed:
            _reply_text(event, _store_error_text())
        else:
            line_bot_api.reply_message(
                event.reply_token,
                FlexSendMessage(
                    alt_text="提醒管理",
                    contents=build_alerts_flex(current_state),
                ),
            )

    elif msg == "完整分析":
        card = build_line_summary_card("量化分析總覽", ["從市場摘要、強勢訊號與產業雷達開始判讀。"], "開啟完整分析", f"{web_root}/dashboard")
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="開啟完整分析", contents=card))

    elif msg == "投資試算":
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="投資試算", contents=build_calculator_help_flex()))

    elif msg == "功能選單":
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="Stock Papi 功能選單", contents=build_line_navigation_flex(web_root)))
        
    elif msg.startswith("分類第_") and msg.endswith("頁"):
        try: p = int(msg.replace("分類第_", "").replace("頁", ""))
        except: p = 1
        qr, _ = build_category_quick_reply(p)
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="請選擇產業板塊", contents=build_welcome_flex(), quick_reply=qr))
        
    elif msg == "產業列表":
        lines = ["📚 產業分類總表\n"] + [f"{i}. {c}" for i, c in enumerate(industry_map.keys(), 1)]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(lines[:120])))
        
    elif msg.startswith("選產業_"):
        cat = msg.replace("選產業_", "")
        try:
            snapshot = load_sector_signal_snapshot(line_store) if line_store else None
        except StoreError:
            snapshot = None
        items = (snapshot or {}).get("sectors", {}).get(cat, [])
        if items:
            line_bot_api.reply_message(
                event.reply_token,
                FlexSendMessage(
                    alt_text=f"{cat} 每日產業預測",
                    contents=build_sector_signal_carousel(cat, items),
                ),
            )
        else:
            _reply_text(event, "產業資料尚未更新，請稍後再試。你也可以直接輸入股票代碼查詢個股。")
        
    elif msg == "免責聲明":
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="本系統資訊僅供研究參考，不構成投資建議，投資盈虧請自負。"))

    elif msg == "新手教學":
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="🎓 新手快速上手指南", contents=build_tutorial_flex()))
        
    else:
        code, name = search_stock_code(msg)
        if code:
            data = analyze(code)
            if not data:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="查無資料，請稍後再試。"))
                return
            url = f"{request.host_url}stock/{code}".replace("http://", "https://")
            watched = bool(
                current_state
                and any(item.get("code") == code for item in current_state.get("watchlist", []))
            )
            flex_content = build_stock_flex_message(code, name, data, url, watched=watched)
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text=f"📊 {name} ({code}) 預測出爐，點擊查看！", contents=flex_content))
        elif getattr(getattr(event, "source", None), "type", "user") == "user":
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請輸入股票代碼，或輸入：今日盤勢 / 我的關注 / 提醒管理 / 完整分析"))

if __name__ == "__main__":
    app.run(host=LOCAL_HOST, port=int(os.environ.get("PORT", 5000)))
