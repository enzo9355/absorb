"""FinMind, Yahoo Finance and ticker lookup adapters."""


def finmind_login(current_token, user, password, requests_module):
    if current_token or not user or not password:
        return current_token
    try:
        payload = requests_module.post(
            "https://api.finmindtrade.com/api/v4/login",
            data={"user_id": user, "password": password},
            timeout=5,
        ).json()
        if payload.get("msg") == "success":
            return payload["token"]
    except (requests_module.RequestException, KeyError, TypeError, ValueError):
        pass
    return current_token


def fetch_finmind_dataset(
    dataset,
    code,
    start_date,
    end_date,
    *,
    blocked_until,
    now,
    login,
    token,
    requests_module,
    pd,
    logger,
):
    timestamp = now()
    if timestamp < blocked_until:
        return pd.DataFrame(), blocked_until
    login()
    params = {
        "dataset": dataset,
        "data_id": code,
        "start_date": start_date,
        "end_date": end_date,
    }
    current_token = token()
    if current_token:
        params["token"] = current_token
    try:
        response = requests_module.get(
            "https://api.finmindtrade.com/api/v4/data",
            params=params,
            timeout=8,
        )
        if response.status_code in (402, 403):
            blocked_until = timestamp + (
                60 if response.status_code == 402 else 30
            ) * 60
        response.raise_for_status()
        return pd.DataFrame(response.json().get("data", [])), blocked_until
    except (requests_module.RequestException, ValueError, TypeError) as exc:
        logger.warning("FinMind %s 讀取失敗: %s", dataset, exc)
        return pd.DataFrame(), blocked_until


def fetch_yfinance_price_history(
    tickers,
    start_date,
    end_date,
    *,
    cache,
    cache_seconds,
    now,
    pd,
    logger,
):
    if isinstance(tickers, str):
        tickers = [tickers]
    cache_key = (tuple(tickers), start_date, end_date or "")
    timestamp = now()
    cached = cache.get(cache_key)
    if cached and timestamp - cached[1] < cache_seconds:
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
                frame = frame.reset_index()[
                    ["Date", "Open", "High", "Low", "Close", "Volume"]
                ]
                cache[cache_key] = (frame.copy(), timestamp)
                return frame
    except Exception as exc:
        logger.warning("Yahoo Finance 讀取失敗: %s", exc)
    return pd.DataFrame()


def fetch_option_context_history(
    start_date, end_date, fetch_history, executor_factory, pd, logger
):
    symbols = ("^VIX", "^VIX9D", "^VIX3M")
    frames = {}
    with executor_factory(max_workers=len(symbols)) as executor:
        futures = {
            symbol: executor.submit(fetch_history, symbol, start_date, end_date)
            for symbol in symbols
        }
        for symbol, future in futures.items():
            try:
                frames[symbol] = future.result()
            except Exception as exc:
                logger.warning("選擇權市場指標讀取失敗 (%s): %s", symbol, exc)
                frames[symbol] = pd.DataFrame()
    return tuple(frames[symbol] for symbol in symbols)


def get_stock_name(code, stock_codes, is_us_ticker):
    if code == "TAIEX":
        return "台股大盤"
    if code in stock_codes:
        return stock_codes[code].name
    if is_us_ticker(code):
        return f"美股 {code}"
    return code


def search_stock_code(keyword, stock_codes, is_us_ticker, resolve_name):
    keyword = keyword.upper().strip()
    if not keyword:
        return None, None
    if keyword in ["TAIEX", "加權指數", "台股大盤", "大盤"]:
        return "TAIEX", "台股大盤"
    if keyword.isdigit():
        return keyword, resolve_name(keyword)
    if is_us_ticker(keyword):
        return keyword, resolve_name(keyword)
    for code, info in stock_codes.items():
        if keyword in info.name.upper():
            return code, info.name
    return None, None
