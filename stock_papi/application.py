# app.py
# v5.8 穩定版：新增首頁健康檢查端點防休眠，並梳理重複路由確保 Flask 正常啟動
# --------------------------------------------------

import os
import queue
import threading
import time
import datetime
import logging
from concurrent.futures import ThreadPoolExecutor
import requests
import twstock
import json

from market_insights import build_industries, build_supply_chains

# Compatibility export: legacy tests still patch app.render_template.
from flask import render_template, request
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, PostbackEvent, TextMessage, TextSendMessage,
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
from stock_papi.runtime import (
    _LazyGeminiModel,
    _LazyModule,
    get_gcp_access_token as _runtime_get_gcp_access_token,
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
    find_matching_alert as _line_find_matching_alert,
    handle_message_impl as _line_handle_message_impl,
    handle_postback_impl as _line_handle_postback_impl,
    require_same_pending as _line_require_same_pending,
    resolve_postback_stock as _line_resolve_postback_stock,
)
from stock_papi.integrations.line.presentation import (
    _build_sector_signal_row as _line_build_sector_signal_row,
    _build_stock_row as _line_build_stock_row,
    build_category_quick_reply as _line_build_category_quick_reply,
    build_industry_carousel as _line_build_industry_carousel,
    build_projection_flex as _line_build_projection_flex,
    build_sector_signal_carousel as _line_build_sector_signal_carousel,
)
from stock_papi.integrations.line.state import (
    get_line_state as _line_get_state,
    get_line_state_bounded as _line_get_state_bounded,
    load_sector_signal_snapshot as _line_load_sector_signal_snapshot,
    refresh_sector_signals as _line_refresh_sector_signals,
    save_sector_signal_snapshot as _line_save_sector_signal_snapshot,
    store_error_text as _line_store_error_text,
    update_line_state as _line_update_state,
    _system_document_url as _line_system_document_url,
)
from stock_papi.integrations.market_data.tw_exchange import fetch_market_activity
from stock_papi.integrations.market_data.provider import (
    fetch_finmind_dataset as _provider_fetch_finmind_dataset,
    fetch_option_context_history as _provider_fetch_option_context_history,
    fetch_yfinance_price_history as _provider_fetch_yfinance_price_history,
    finmind_login as _provider_finmind_login,
    get_stock_name as _provider_get_stock_name,
    search_stock_code as _provider_search_stock_code,
)
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
from stock_papi.services.dashboard import (
    build_market_heatmap,
    cached_opportunities as _dashboard_cached_opportunities,
    dashboard_sector_cards as _dashboard_sector_cards,
    dashboard_top_picks,
)
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
from stock_papi.services.papi import (
    PapiService,
    get_ai_insight_for_broadcast as _get_ai_insight_for_broadcast,
)
from stock_papi.services.news import get_news as _get_news
from stock_papi.services.market_insights import (
    market_insights_payload as _market_insights_payload,
)
from stock_papi.web.legacy_html import render_web








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
    finmind_token = _provider_finmind_login(
        finmind_token, FINMIND_USER, FINMIND_PASSWORD, requests
    )

def fetch_finmind_dataset(dataset, code, start_date, end_date):
    global _FINMIND_BLOCKED_UNTIL
    frame, _FINMIND_BLOCKED_UNTIL = _provider_fetch_finmind_dataset(
        dataset,
        code,
        start_date,
        end_date,
        blocked_until=_FINMIND_BLOCKED_UNTIL,
        now=time.time,
        login=finmind_login,
        token=lambda: finmind_token,
        requests_module=requests,
        pd=pd,
        logger=logger,
    )
    return frame


def fetch_yfinance_price_history(tickers, start_date, end_date=None):
    return _provider_fetch_yfinance_price_history(
        tickers,
        start_date,
        end_date,
        cache=_YFINANCE_CACHE,
        cache_seconds=YFINANCE_CACHE_SECONDS,
        now=time.time,
        pd=pd,
        logger=logger,
    )


def fetch_option_context_history(start_date, end_date=None):
    return _provider_fetch_option_context_history(
        start_date,
        end_date,
        fetch_yfinance_price_history,
        ThreadPoolExecutor,
        pd,
        logger,
    )


def get_stock_name(code):
    return _provider_get_stock_name(code, twstock.codes, is_us_ticker)

def search_stock_code(keyword):
    return _provider_search_stock_code(
        keyword, twstock.codes, is_us_ticker, get_stock_name
    )


def get_gcp_access_token():
    return _runtime_get_gcp_access_token(line_store, requests)


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
    return _get_news(
        name,
        code,
        ThreadPoolExecutor,
        fetch_news_rss,
        parse_news_items,
        fetch_marketaux_news,
        fetch_stocktwits_sentiment,
        normalize_and_dedupe,
        SENTIMENT_WINDOW_DAYS,
    )

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
    return _get_ai_insight_for_broadcast(
        name, data, bt, news, gemini_model
    )

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
    return _dashboard_cached_opportunities(
        _SYSTEM_CACHE, time.time, CACHE_EXPIRY_SECONDS, limit=limit
    )

def dashboard_sector_cards(limit=6):
    return _dashboard_sector_cards(
        load_sector_signal_snapshot,
        line_store,
        cached_opportunities,
        _safe_float,
        limit=limit,
    )




def market_forecast(): return analyze("TAIEX")

# ==================================================
# 5. UI 渲染
# ==================================================



# ==================================================
# 6. 動態產業分類與選單生成
# ==================================================
def call_openalice(prompt):
    return _papi_service().call_openalice(prompt)


def _extract_stock_from_papi_prompt(prompt):
    return _papi_service().extract_stock(prompt)


def _match_sector_from_prompt(prompt):
    return _papi_service().match_sector(prompt)


def _build_single_stock_context(data):
    return _papi_service().build_single_context(data)


def _gather_sector_data(codes, max_fresh=2, max_total=5):
    return _papi_service().gather_sector_data(
        codes, max_fresh=max_fresh, max_total=max_total
    )


def _build_papi_sector_examples(limit=3):
    return _papi_service().build_sector_examples(limit=limit)


def _build_papi_prompt(prompt):
    return _papi_service().build_prompt(prompt)


def call_papi_gemini_fallback(prompt):
    return _papi_service().call_gemini(prompt)


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
    return _line_build_category_quick_reply(
        industry_map.keys(), CATEGORY_PAGE_SIZE, page=page
    )

# ==================================================
# 7. 自動化發報引擎
# ==================================================
# ==================================================
# 8. 路由與 LINE 基礎指令 (💡 確保名稱不重複版)
# ==================================================
def get_line_state(user_id):
    return _line_get_state(line_store, user_id)


def get_line_state_bounded(user_id, timeout=LINE_STATE_READ_BUDGET_SECONDS):
    return _line_get_state_bounded(
        line_store,
        user_id,
        timeout,
        _line_state_read_slots,
        logger,
        LINE_STATE_READ_MAX_WORKERS,
        queue,
        threading,
    )


def update_line_state(user_id, mutate):
    return _line_update_state(line_store, user_id, mutate)


def _store_error_text():
    return _line_store_error_text(line_store)




















def build_projection_flex(code, name, data, amount, base_url):
    return _line_build_projection_flex(code, name, data, amount, base_url)










def _system_document_url(store, document_id):
    return _line_system_document_url(store, document_id)


def save_sector_signal_snapshot(store, snapshot):
    return _line_save_sector_signal_snapshot(store, snapshot)


def load_sector_signal_snapshot(store):
    return _line_load_sector_signal_snapshot(store)


def refresh_sector_signals(store):
    return _line_refresh_sector_signals(
        store,
        fetch_market_activity,
        build_sector_signal_snapshot,
        save_sector_signal_snapshot,
        industry_map,
        analyze,
    )







def _build_stock_row(code):
    return _line_build_stock_row(code, get_stock_name)

def build_industry_carousel(cat, arr):
    return _line_build_industry_carousel(cat, arr, get_stock_name)


def _build_sector_signal_row(item):
    return _line_build_sector_signal_row(item)


def build_sector_signal_carousel(category, items):
    return _line_build_sector_signal_carousel(category, items, SECTOR_DISPLAY_LIMIT)


def market_insights_payload():
    return _market_insights_payload(
        fetch_market_insights,
        get_stock_name,
        industry_map,
        datetime.date.today,
        build_industries,
        build_supply_chains,
    )


def _reply_text(event, text):
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))


def _current_web_root():
    return request.host_url.replace("http://", "https://").rstrip("/")


def _require_same_pending(state, expected_pending):
    return _line_require_same_pending(state, expected_pending)


def _find_matching_alert(alerts, code, kind, value):
    return _line_find_matching_alert(alerts, code, kind, value)


def _resolve_postback_stock(code):
    return _line_resolve_postback_stock(code, search_stock_code)


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
def _papi_service():
    return PapiService(
        requests_module=requests,
        openalice_url=OPENALICE_API_URL,
        openalice_token=OPENALICE_API_TOKEN,
        search_stock=search_stock_code,
        get_stock_name=get_stock_name,
        twstock_codes=twstock.codes,
        industry_map=industry_map,
        analyze=analyze,
        system_cache=_SYSTEM_CACHE,
        cache_expiry_seconds=CACHE_EXPIRY_SECONDS,
        line_store=line_store,
        load_sector_snapshot=load_sector_signal_snapshot,
        safe_float=_safe_float,
        gemini_model=gemini_model,
        now=time.time,
        sleep=time.sleep,
        logger=logger,
        build_prompt_fn=_build_papi_prompt,
        extract_stock_fn=_extract_stock_from_papi_prompt,
        match_sector_fn=_match_sector_from_prompt,
        gather_sector_data_fn=_gather_sector_data,
        build_single_context_fn=_build_single_stock_context,
        build_sector_examples_fn=_build_papi_sector_examples,
    )
