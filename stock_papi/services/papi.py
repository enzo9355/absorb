"""Papi prompt construction and external summary orchestration."""

import re


def get_ai_insight_for_broadcast(name, data, bt, news, gemini_model):
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


class PapiService:
    def __init__(
        self,
        *,
        requests_module,
        openalice_url,
        openalice_token,
        search_stock,
        get_stock_name,
        twstock_codes,
        industry_map,
        analyze,
        system_cache,
        cache_expiry_seconds,
        line_store,
        load_sector_snapshot,
        safe_float,
        gemini_model,
        now,
        sleep,
        logger,
        build_prompt_fn,
        extract_stock_fn,
        match_sector_fn,
        gather_sector_data_fn,
        build_single_context_fn,
        build_sector_examples_fn,
    ):
        self.requests = requests_module
        self.openalice_url = openalice_url
        self.openalice_token = openalice_token
        self.search_stock = search_stock
        self.get_stock_name = get_stock_name
        self.twstock_codes = twstock_codes
        self.industry_map = industry_map
        self.analyze = analyze
        self.system_cache = system_cache
        self.cache_expiry_seconds = cache_expiry_seconds
        self.line_store = line_store
        self.load_sector_snapshot = load_sector_snapshot
        self.safe_float = safe_float
        self.gemini_model = gemini_model
        self.now = now
        self.sleep = sleep
        self.logger = logger
        self.build_prompt_fn = build_prompt_fn
        self.extract_stock_fn = extract_stock_fn
        self.match_sector_fn = match_sector_fn
        self.gather_sector_data_fn = gather_sector_data_fn
        self.build_single_context_fn = build_single_context_fn
        self.build_sector_examples_fn = build_sector_examples_fn


    def call_openalice(self, prompt):
        response = self.requests.post(
            self.openalice_url,
            headers={"Authorization": f"Bearer {self.openalice_token}"},
            json={"prompt": self.build_prompt_fn(prompt)},
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


    def extract_stock(self, prompt):
        """Extract a stock or market target from a natural-language Papi question."""
        prompt = str(prompt or "").strip()
        code_match = re.search(r"(?<!\d)(\d{4,5})(?!\d)", prompt)
        if code_match and code_match.group(1) in self.twstock_codes:
            code = code_match.group(1)
            return code, self.get_stock_name(code)

        name_matches = [
            (code, info.name) for code, info in self.twstock_codes.items()
            if info.name and info.name in prompt
        ]
        if name_matches:
            return max(name_matches, key=lambda item: len(item[1]))

        ticker_match = re.search(r"(?<![A-Z])([A-Z]{3,5})(?![A-Z])", prompt)
        if ticker_match and ticker_match.group(1) not in {"PAPI", "RSI", "MACD", "ETF"}:
            code, name = self.search_stock(ticker_match.group(1))
            if code:
                return code, name

        m = re.search(r"分析\s+(.+)", prompt)
        if m:
            keyword = m.group(1).strip()
            code, name = self.search_stock(keyword)
            if code:
                return code, name
        # Also try if the entire prompt is just a stock code or name
        code, name = self.search_stock(prompt)
        if code:
            return code, name
        if any(term in prompt for term in ("台股", "台灣股市", "大盤", "加權指數", "盤勢")):
            return "TAIEX", "台股大盤"
        return None, None


    def match_sector(self, prompt):
        """Try to match a Papi prompt to an self.industry_map category.

        Returns (category_name, stock_codes_list) or (None, None).
        """
        keywords = prompt.upper()
        best_cat = None
        best_len = 0
        for cat in self.industry_map:
            cat_upper = cat.upper()
            if cat_upper in keywords and len(cat_upper) > best_len:
                best_cat = cat
                best_len = len(cat_upper)
        if best_cat:
            return best_cat, self.industry_map[best_cat]
        return None, None


    def build_single_context(self, data):
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


    def gather_sector_data(self, codes, max_fresh=2, max_total=5):
        """Gather analysis data for a sector. Prioritize cache, analyze at most max_fresh new stocks.

        Returns a list of (code, data) tuples.
        """
        results = []
        fresh_count = 0
        now = self.now()

        # First pass: collect cached stocks
        for code in codes:
            if len(results) >= max_total:
                break
            if code in self.system_cache:
                cached_data, ts = self.system_cache[code]
                if now - ts < self.cache_expiry_seconds and cached_data:
                    results.append((code, cached_data))

        # Second pass: analyze a few uncached stocks if we need more
        if len(results) < max_total:
            for code in codes:
                if len(results) >= max_total or fresh_count >= max_fresh:
                    break
                if any(r[0] == code for r in results):
                    continue
                try:
                    data = self.analyze(code)
                    if data:
                        results.append((code, data))
                        fresh_count += 1
                except Exception:
                    continue

        return results


    def build_sector_examples(self, limit=3):
        if not self.line_store:
            return ""
        try:
            snapshot = self.load_sector_snapshot(self.line_store)
        except Exception:
            return ""
        items = []
        for category, signals in (snapshot or {}).get("sectors", {}).items():
            for item in signals or []:
                items.append((category, item))
        items.sort(key=lambda pair: self.safe_float(pair[1].get("score")), reverse=True)
        lines = []
        for category, item in items[:limit]:
            lines.append(
                f"- {item.get('name')} ({item.get('code')})：{category}，"
                f"AI 勝率 {int(self.safe_float(item.get('prob')))}%，"
                f"{item.get('trend', '中性')}，"
                f"外資5日 {int(self.safe_float(item.get('foreign_net_5'))):,}"
            )
        if not lines:
            return ""
        return "\n每日產業預測可舉例標的（只可從這裡挑，不要自己編）：\n" + "\n".join(lines)


    def build_prompt(self, prompt):
        data_context = ""

        # 1. Try individual stock first
        code, name = self.extract_stock_fn(prompt)
        if code:
            try:
                data = self.analyze(code)
            except Exception:
                data = None
            if data:
                data_context = f"""
    以下是 {name} ({code}) 的最新量化分析數據（來自我們的 LightGBM 模型與技術指標系統）：
    {self.build_single_context_fn(data)}
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
            cat, cat_codes = self.match_sector_fn(prompt)
            if cat and cat_codes:
                sector_data = self.gather_sector_data_fn(cat_codes)
                if sector_data:
                    stock_lines = "\n".join(
                        self.build_single_context_fn(d) for _, d in sector_data
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
            data_context = self.build_sector_examples_fn()
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


    def call_gemini(self, prompt):
        if not self.gemini_model:
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
                response = self.gemini_model.generate_content(self.build_prompt_fn(prompt), safety_settings=safety)
                summary = (getattr(response, "text", "") or "").strip()
                if not summary:
                    return None
                return summary
            except Exception as exc:
                self.logger.warning(f"Gemini API call failed (attempt {attempt + 1}/{max_retries}): {exc}")
                if attempt < max_retries - 1:
                    self.sleep(backoff)
                    backoff *= 2
                    continue
                self.logger.error(f"Gemini API call failed after {max_retries} attempts: {exc}", exc_info=True)
                raise
