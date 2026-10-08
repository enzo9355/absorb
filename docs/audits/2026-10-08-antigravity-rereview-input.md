請依前次技術討論複核下列修正，使用繁體中文在 1200 字內回覆。你只做唯讀靜態審查，不使用工具、不修改、不部署。BASE 是 fa1cf7c，以下是目前工作分支的新差異。修正前 145 項測試共 14 個失敗／subtests；修正後 145 項全部通過；node --check static/app.js 與 git diff --check 通過。專案 README 的完整 unittest discover 正在執行，尚未宣稱通過。
已於本機合成資料瀏覽器實測：『根據台積電最新資料，目前價格與均線如何？』保留收盤／均線並附確定過期警示；『2330 和 AAPL 最新資料日與過期狀態？』列出兩檔日期／來源。你未親自重跑或看畫面，請保持這個限制。
請重點檢查：純日期與混合分析不再互相吞沒；逐檔市場行事曆；一成功一失敗、全失敗、不同日期不假裝單一日期；citation 僅指向成功觀察；grounded 成功與 fallback 均有確定時效；null list 防禦及 publication validator 拒絕非字串 daily_focus；quote unknown 標籤；official status 比較日期。不要重新提出已撤回的 market fallback 或動機推論。
只列有具體 trigger 與源碼依據的可操作 P1/P2，區分本次回歸與基底問題。若仍有問題，提出最小可行修正；若無，說明是否可進入下一步驗收。此為完整交付前的程式複核，不是正式部署許可。

DIFF:
diff --git a/static/app.js b/static/app.js
index 7143e42..a2416d6 100644
--- a/static/app.js
+++ b/static/app.js
@@ -128,3 +128,3 @@ function renderDashboard(data) {
   if (focus) {
-    const items = Array.isArray(data.daily_focus) ? data.daily_focus : [];
+    const items = Array.isArray(data.daily_focus) ? data.daily_focus.filter(text => typeof text === "string") : [];
     replaceContent(focus, items.length ? items.map((text, index) =>
diff --git a/stock_papi/application.py b/stock_papi/application.py
index 1335b0c..d21288e 100644
--- a/stock_papi/application.py
+++ b/stock_papi/application.py
@@ -10,2 +10,3 @@ import datetime
 import logging
+from dataclasses import replace
 from concurrent.futures import ThreadPoolExecutor
@@ -2194,4 +2195,27 @@ def _asksorb_grounded_answer(question, evidence, *, data_as_of, tools_used, cita
 
+def _observation_date_intent(question):
+    explicit_date = any(term in question for term in ("資料日", "資料截至", "過期", "更新時間"))
+    if not explicit_date and "最新資料" not in question:
+        return None
+    analysis = any(term in question.lower() for term in (
+        "價格", "價位", "收盤", "均線", "走勢", "表現", "報酬", "漲跌", "指標",
+        "量比", "成交", "籌碼", "風險事件", "摘要", "內容", "說明", "多少",
+        "幾元", "如何", "怎麼", "rsi", "macd", "ma20", "ma60",
+    ))
+    return "only" if explicit_date and not analysis else "mixed"
+
+
+def _with_observation_freshness(answer, date_answer):
+    if date_answer is None:
+        return answer
+    return replace(
+        answer, text=f"{answer.text}\n\n{date_answer.text}",
+        data_as_of=date_answer.data_as_of, data_quality=date_answer.data_quality,
+        stale=date_answer.stale, citations=date_answer.citations,
+        tools_used=tuple(dict.fromkeys(answer.tools_used + date_answer.tools_used)),
+    )
+
+
 def _observation_date_answer(question, *, market, data_as_of, tools_used, citations, subject=None):
-    if not any(term in question for term in ("資料日", "資料截至", "過期", "最新資料", "更新時間")):
+    if _observation_date_intent(question) is None:
         return None
@@ -2302,2 +2326,5 @@ def _observation_conversation(
         observations = []
+        stock_citations = []
+        date_answers = []
+        date_intent = _observation_date_intent(question)
         for entity in entities:
@@ -2307,29 +2334,50 @@ def _observation_conversation(
             )
-            if isinstance(data, dict):
-                observations.append(data)
-        if not observations:
-            return ConversationAnswer("已驗證的個股觀察資料暫時無法取得。")
-        data = observations[0]
-        stock_as_of = data.get("observation_as_of") or data.get("as_of")
-        stock_citations = []
-        symbol_text = re.fullmatch(r"[A-Z0-9.-]{1,16}", str(data.get("code") or ""))
-        if symbol_text:
-            stock_citations.append(
-                {
+            if not isinstance(data, dict):
+                if date_intent:
+                    date_answers.append(ConversationAnswer(
+                        f"{entity.get('name') or entity['symbol']}（{entity['symbol']}）：無已驗證觀察資料。",
+                        tools_used=("verified_observation_snapshot",),
+                    ))
+                continue
+            observations.append(data)
+            stock_as_of = data.get("observation_as_of") or data.get("as_of")
+            citations = []
+            if re.fullmatch(r"[A-Z0-9.-]{1,16}", str(data.get("code") or "")):
+                citations.append({
                     "label": f"{data.get('name') or data.get('code')}（{data.get('code')}）個股觀察",
-                    "url": f"/stock/{data.get('code')}",
-                    "date": stock_as_of,
+                    "url": f"/stock/{data.get('code')}", "date": stock_as_of,
                     "chapters": ["官方交易狀態"] if data.get("observation_kind") != "regular_price" else ["價格與均線", "籌碼觀察", "風險事件"],
-                }
+                })
+            stock_citations.extend(citations)
+            if date_intent:
+                date_answers.append(_observation_date_answer(
+                    question, market=data.get("market"), data_as_of=stock_as_of,
+                    tools_used=("verified_observation_snapshot",), citations=citations,
+                    subject=f"{data.get('name') or data.get('code')}（{data.get('code')}）",
+                ))
+        date_answer = None
+        if date_answers:
+            dates = {answer.data_as_of for answer in date_answers}
+            stale = any(answer.stale for answer in date_answers)
+            qualities = {answer.data_quality for answer in date_answers}
+            quality = "stale" if stale else "available" if qualities == {"available"} else (
+                "partial" if "available" in qualities else "unavailable")
+            date_answer = ConversationAnswer(
+                "\n".join(answer.text for answer in date_answers),
+                data_as_of=next(iter(dates)) if len(dates) == 1 else None,
+                data_quality=quality, stale=stale, citations=tuple(stock_citations),
+                tools_used=tuple(dict.fromkeys(tool for answer in date_answers for tool in answer.tools_used)),
             )
-        date_answer = _observation_date_answer(
-            question, market=data.get("market"), data_as_of=stock_as_of,
-            tools_used=("verified_observation_snapshot",), citations=stock_citations,
-            subject=f"{data.get('name') or data.get('code')}（{data.get('code')}）",
-        )
-        if date_answer is not None:
-            return date_answer
+            if date_intent == "only" or not observations:
+                return date_answer
+        if not observations:
+            return ConversationAnswer("已驗證的個股觀察資料暫時無法取得。")
+        dates = {data.get("observation_as_of") or data.get("as_of") for data in observations}
+        stock_as_of = next(iter(dates)) if len(dates) == 1 else None
+        evidence = {"stocks": observations}
+        if date_answer:
+            evidence["observation_freshness"] = date_answer.to_dict()
         generated = _asksorb_grounded_answer(
             question,
-            {"stocks": observations},
+            evidence,
             data_as_of=stock_as_of,
@@ -2339,22 +2387,20 @@ def _observation_conversation(
         if generated is not None:
-            return generated
-        trend = {
-            "above_ma20_ma60": "站上 MA20 與 MA60",
-            "above_ma20": "站上 MA20",
-            "below_ma60": "低於 MA60",
-            "mixed": "均線交錯",
-        }.get(data.get("trend_observation"), "資料不足")
-        events = "；".join(data.get("risk_events", [])[:3]) or "未觸發額外事件"
-        text = (
-            f"{data['name']}（{data['code']}）市場觀察："
-            f"最新收盤 {_observation_number(data.get('price'))}，"
-            f"均線狀態為{trend}，"
-            f"RSI {_observation_number(data.get('rsi'), 1)}，"
-            f"量比 {_observation_number(data.get('volume_ratio'))}。"
-            f"已觸發事件：{events}。\n\n"
-            f"資料截至：{stock_as_of or '未提供'}｜"
-            "內容只描述已發生資料。"
-        )
-        return ConversationAnswer(
-            text,
+            return _with_observation_freshness(generated, date_answer)
+        lines = []
+        for data in observations:
+            trend = {
+                "above_ma20_ma60": "站上 MA20 與 MA60", "above_ma20": "站上 MA20",
+                "below_ma60": "低於 MA60", "mixed": "均線交錯",
+            }.get(data.get("trend_observation"), "資料不足")
+            events = "；".join(data.get("risk_events", [])[:3]) or "未觸發額外事件"
+            quote_label = "最近可用收盤" if date_answer and date_answer.data_quality != "available" else "最新收盤"
+            lines.append(
+                f"{data['name']}（{data['code']}）市場觀察："
+                f"{quote_label} {_observation_number(data.get('price'))}，均線狀態為{trend}，"
+                f"RSI {_observation_number(data.get('rsi'), 1)}，量比 {_observation_number(data.get('volume_ratio'))}。"
+                f"已觸發事件：{events}。\n\n"
+                f"資料截至：{data.get('observation_as_of') or data.get('as_of') or '未提供'}｜內容只描述已發生資料。"
+            )
+        return _with_observation_freshness(ConversationAnswer(
+            "\n\n".join(lines),
             data_as_of=stock_as_of,
@@ -2362,3 +2408,4 @@ def _observation_conversation(
             tools_used=("verified_observation_snapshot",),
-        )
+            citations=tuple(stock_citations),
+        ), date_answer)
 
@@ -2378,7 +2425,10 @@ def _observation_conversation(
         )
-        if date_answer is not None:
+        if date_answer is not None and _observation_date_intent(question) == "only":
             return date_answer
+        evidence = {"market": "US", "report": report}
+        if date_answer:
+            evidence["observation_freshness"] = date_answer.to_dict()
         generated = _asksorb_grounded_answer(
             question,
-            {"market": "US", "report": report},
+            evidence,
             data_as_of=report.get("source_market_date"),
@@ -2388,5 +2438,5 @@ def _observation_conversation(
         if generated is not None:
-            return generated
+            return _with_observation_freshness(generated, date_answer)
         summary = "；".join(report.get("summary") or []) or report.get("title")
-        return ConversationAnswer(
+        return _with_observation_freshness(ConversationAnswer(
             f"美股市場實況：{summary}\n\n資料截至：{report.get('source_market_date') or '未提供'}｜內容只描述已發布資料。",
@@ -2396,3 +2446,3 @@ def _observation_conversation(
             citations=[us_citation] if us_citation else (),
-        )
+        ), date_answer)
 
@@ -2411,15 +2461,18 @@ def _observation_conversation(
     )
-    if date_answer is not None:
+    if date_answer is not None and _observation_date_intent(question) == "only":
         return date_answer
+    evidence = {
+        "market": snapshot.get("market", "TW"),
+        "observation_as_of": snapshot.get("observation_as_of"),
+        "market_observation": snapshot.get("market_observation", {}),
+        "industry_observations": list(snapshot.get("industry_observations") or [])[:10],
+        "daily_focus": list(snapshot.get("daily_focus") or [])[:8],
+        "stock_events": list(snapshot.get("stock_events") or [])[:12],
+        "data_quality": snapshot.get("data_quality", {}),
+    }
+    if date_answer:
+        evidence["observation_freshness"] = date_answer.to_dict()
     generated = _asksorb_grounded_answer(
         question,
-        {
-            "market": snapshot.get("market", "TW"),
-            "observation_as_of": snapshot.get("observation_as_of"),
-            "market_observation": snapshot.get("market_observation", {}),
-            "industry_observations": list(snapshot.get("industry_observations") or [])[:10],
-            "daily_focus": list(snapshot.get("daily_focus") or [])[:8],
-            "stock_events": list(snapshot.get("stock_events") or [])[:12],
-            "data_quality": snapshot.get("data_quality", {}),
-        },
+        evidence,
         data_as_of=snapshot.get("observation_as_of"),
@@ -2429,3 +2482,3 @@ def _observation_conversation(
     if generated is not None:
-        return generated
+        return _with_observation_freshness(generated, date_answer)
     industries = snapshot.get("industry_observations", [])
@@ -2452,3 +2505,3 @@ def _observation_conversation(
         )
-        return ConversationAnswer(
+        return _with_observation_freshness(ConversationAnswer(
             text,
@@ -2458,3 +2511,3 @@ def _observation_conversation(
             citations=[dashboard_citation] if dashboard_citation else (),
-        )
+        ), date_answer)
     if any(term in question for term in ("台股", "大盤", "市場", "盤勢", "今天")):
@@ -2477,3 +2530,3 @@ def _observation_conversation(
         )
-        return ConversationAnswer(
+        return _with_observation_freshness(ConversationAnswer(
             text,
@@ -2483,7 +2536,7 @@ def _observation_conversation(
             citations=[dashboard_citation] if dashboard_citation else (),
-        )
-    return ConversationAnswer(
+        ), date_answer)
+    return _with_observation_freshness(ConversationAnswer(
         "AI 預測研究中。你可以詢問市場實況、產業實際強弱、"
         "個股價格、均線、技術指標、籌碼或已觸發事件。"
-    )
+    ), date_answer)
 
diff --git a/stock_papi/batch/observation_products.py b/stock_papi/batch/observation_products.py
index a814985..fe23b1c 100644
--- a/stock_papi/batch/observation_products.py
+++ b/stock_papi/batch/observation_products.py
@@ -850,2 +850,3 @@ def validate_observation_dashboard(document):
         or not isinstance(document.get("daily_focus"), list)
+        or not all(isinstance(text, str) for text in document["daily_focus"])
         or not isinstance(document.get("data_quality"), dict)
diff --git a/stock_papi/web/routes/dashboard.py b/stock_papi/web/routes/dashboard.py
index 46b3de2..b8bfbd6 100644
--- a/stock_papi/web/routes/dashboard.py
+++ b/stock_papi/web/routes/dashboard.py
@@ -41,5 +41,5 @@ def register_dashboard_page(
         snapshot = {**snapshot, "daily_focus": [localize_us_key_event({"headline": text})["headline"]
-                                               for text in snapshot.get("daily_focus", [])]}
+                                               for text in (snapshot.get("daily_focus") or []) if isinstance(text, str)]}
         daily_cards = {kind: {**item, "summary": [localize_us_key_event({"headline": text})["headline"]
-                                                 for text in item.get("summary", [])]} if item else None
+                                                 for text in (item.get("summary") or []) if isinstance(text, str)]} if item else None
                        for kind, item in daily_cards.items()}
diff --git a/stock_papi/web/routes/reports.py b/stock_papi/web/routes/reports.py
index d17b9a5..9a9b8db 100644
--- a/stock_papi/web/routes/reports.py
+++ b/stock_papi/web/routes/reports.py
@@ -466,3 +466,3 @@ def register_report_routes(
         return [{**row, "summary": [localize_us_key_event({"headline": text})["headline"]
-                                    for text in row.get("summary", [])]}
+                                    for text in (row.get("summary") or []) if isinstance(text, str)]}
                 for row in rows if not selected_date or selected_date == row.get(
diff --git a/templates/stock_compare.html b/templates/stock_compare.html
index cd3467d..7aedec4 100644
--- a/templates/stock_compare.html
+++ b/templates/stock_compare.html
@@ -6,3 +6,3 @@
   <section class="panel comparison-table-wrap"><table class="comparison-table"><thead><tr><th>指標</th>{% for row in rows %}<th><a href="{{ url_for('stock_page', code=row.code) }}">{{ row.name }}<small>{{ row.code }}</small></a></th>{% endfor %}</tr></thead><tbody>
-    <tr><th>資料日</th>{% for row in rows %}<td>{{ row.get('as_of') or '資料不足' }}</td>{% endfor %}</tr>
+    <tr><th>資料日</th>{% for row in rows %}<td>{{ row.get('observation_as_of') or row.get('as_of') or '資料不足' }}</td>{% endfor %}</tr>
     <tr><th>最新收盤</th>{% for row in rows %}<td>{{ '%.2f'|format(row.get('price')) if row.get('price') is not none else '資料不足' }}</td>{% endfor %}</tr>
@@ -13,3 +13,3 @@
     <tr><th>近 5 日外資</th>{% for row in rows %}<td>{{ '%.0f'|format(row.get('foreign_net_5')) if row.get('foreign_net_5') is not none else '資料不足' }}</td>{% endfor %}</tr>
-    <tr><th>資料品質</th>{% for row in rows %}<td>{{ row.get('data_quality') or ('已驗證觀察' if row.get('as_of') else '資料不足') }}</td>{% endfor %}</tr>
+    <tr><th>資料品質</th>{% for row in rows %}<td>{{ row.get('data_quality') or ('已驗證觀察' if row.get('observation_as_of') or row.get('as_of') else '資料不足') }}</td>{% endfor %}</tr>
     <tr><th>產業關係</th>{% for row in rows %}<td><a href="{{ url_for('industry_relationships_page', focus=row.code) }}">查看已核對關係</a></td>{% endfor %}</tr>
diff --git a/templates/stock_detail.html b/templates/stock_detail.html
index bda20fc..f5865fb 100644
--- a/templates/stock_detail.html
+++ b/templates/stock_detail.html
@@ -24,3 +24,3 @@
 {% block content %}
-{% set quote_label = '最近可用收盤' if (observation_freshness|default({}, true)).get('status') in ['stale', 'updating'] else '最新收盤' %}
+{% set quote_label = '最新收盤' if (observation_freshness|default({}, true)).get('status') == 'current' else '最近可用收盤' %}
 <div class="page stock-page" data-stock-code="{{ d.code }}" data-stock-name="{{ d.name }}"{% if observation_kind == "regular_price" %} data-stock-price="{{ '%.2f'|format(d.price) }}"{% endif %}>
diff --git a/tests/test_observation_products.py b/tests/test_observation_products.py
index 8fd559e..502814b 100644
--- a/tests/test_observation_products.py
+++ b/tests/test_observation_products.py
@@ -231,2 +231,9 @@ def _walk_keys(value):
 class ObservationProductsTests(unittest.TestCase):
+    def test_daily_focus_rejects_non_string_items_at_publication_boundary(self):
+        for item in (None, 23, {}, ['nested']):
+            document = self.build()
+            document['daily_focus'] = [item]
+            with self.subTest(item=item), self.assertRaises(ValueError):
+                validate_observation_dashboard(document)
+
     def test_market_aggregation_uses_canonical_rows_and_ready_latest(self):
diff --git a/tests/test_observation_public_surfaces.py b/tests/test_observation_public_surfaces.py
index fe2e624..7e1a579 100644
--- a/tests/test_observation_public_surfaces.py
+++ b/tests/test_observation_public_surfaces.py
@@ -434,3 +434,5 @@ class ObservationPublicSurfaceTests(unittest.TestCase):
         self.assertIn('資料最新', answer.text)
-        self.assertEqual(answer.data_quality, 'available')
+        self.assertEqual(answer.data_quality, 'partial')
+        self.assertIn('2330', answer.text)
+        self.assertIn('無已驗證觀察資料', answer.text)
         self.assertFalse(answer.stale)
@@ -446,2 +448,61 @@ class ObservationPublicSurfaceTests(unittest.TestCase):
 
+    @patch.object(stock_app, 'asksorb_model', None)
+    @patch.object(stock_app, 'fetch_published_quant_snapshot', return_value=quant_snapshot())
+    @patch.object(stock_app, 'search_stock_code', return_value=('2330', '台積電'))
+    def test_latest_data_modifier_preserves_analysis_and_verified_freshness(self, search, fetch):
+        for question in ('根據台積電最新資料，目前價格與均線如何？',
+                         '台積電最新資料日那天收盤是多少？'):
+            with self.subTest(question=question):
+                answer = stock_app.run_absorb_conversation(principal='web:test', question=question)
+                self.assertIn('收盤', answer.text)
+                self.assertIn('均線狀態', answer.text)
+                self.assertIn('資料過期', answer.text)
+                self.assertTrue(answer.stale)
+                self.assertEqual(answer.citations[0]['date'], quant_snapshot()['as_of'])
+
+    @patch.object(stock_app, 'fetch_published_quant_snapshot', return_value=quant_snapshot())
+    @patch.object(stock_app, 'search_stock_code', return_value=('2330', '台積電'))
+    @patch.object(stock_app, '_asksorb_grounded_answer')
+    def test_mixed_date_analysis_keeps_grounding_and_deterministic_warning(self, grounded, search, fetch):
+        grounded.return_value = stock_app.ConversationAnswer('已驗證的均線分析。', data_quality='available')
+        answer = stock_app.run_absorb_conversation(principal='web:test', question='台積電資料日與均線如何？')
+        grounded.assert_called_once()
+        self.assertIn('已驗證的均線分析', answer.text)
+        self.assertIn('資料過期', answer.text)
+        self.assertTrue(answer.stale)
+        self.assertIn('observation_freshness', grounded.call_args.args[1])
+
+    @patch.object(stock_app, '_asksorb_grounded_answer')
+    @patch.object(stock_app, 'fetch_published_quant_snapshot')
+    @patch.object(stock_app, 'search_stock_code')
+    def test_multi_stock_date_lists_every_entity_without_llm_or_shared_date(self, search, fetch, grounded):
+        search.side_effect = lambda query: ('2330', '台積電') if '2330' in query else (
+            ('AAPL', 'Apple') if 'AAPL' in query else (None, None))
+        tw, us = quant_snapshot(), quant_snapshot('AAPL', 'US')
+        us['daily'] = us['daily'][:-1]
+        us['as_of'] = us['daily'][-1]['Date'][:10]
+        fetch.side_effect = lambda symbol: {'2330': tw, 'AAPL': us}[symbol]
+        answer = stock_app.run_absorb_conversation(principal='web:test', question='2330 和 AAPL 最新資料日與過期狀態？')
+        self.assertIn('2330', answer.text)
+        self.assertIn('AAPL', answer.text)
+        self.assertIn(tw['as_of'], answer.text)
+        self.assertIn(us['as_of'], answer.text)
+        self.assertEqual({item['url'] for item in answer.citations}, {'/stock/2330', '/stock/AAPL'})
+        self.assertIsNone(answer.data_as_of)
+        self.assertTrue(answer.stale)
+        grounded.assert_not_called()
+
+        fetch.side_effect = lambda symbol: tw if symbol == '2330' else None
+        answer = stock_app.run_absorb_conversation(principal='web:test', question='2330 和 AAPL 最新資料日？')
+        self.assertIn('AAPL', answer.text)
+        self.assertIn('無已驗證觀察資料', answer.text)
+        self.assertEqual([item['url'] for item in answer.citations], ['/stock/2330'])
+
+        fetch.side_effect = lambda symbol: None
+        answer = stock_app.run_absorb_conversation(principal='web:test', question='2330 和 AAPL 最新資料日？')
+        self.assertIn('2330', answer.text)
+        self.assertIn('AAPL', answer.text)
+        self.assertEqual(answer.data_quality, 'unavailable')
+        self.assertFalse(answer.citations)
+
     @patch.object(stock_app, "fetch_published_quant_snapshot")
diff --git a/tests/test_research_routes.py b/tests/test_research_routes.py
index 0e120a9..beade97 100644
--- a/tests/test_research_routes.py
+++ b/tests/test_research_routes.py
@@ -6,3 +6,5 @@ from flask import Flask
 from stock_papi.services import public_opinions
+from stock_papi.services.observation_view import build_stock_observation
 from stock_papi.web.routes.research import register_research_routes
+from tests.report_fixtures import status_stock_document
 
@@ -10,2 +12,14 @@ from stock_papi.web.routes.research import register_research_routes
 class ResearchRouteTests(unittest.TestCase):
+    def test_compare_preserves_official_status_observation_date(self):
+        official = build_stock_observation(status_stock_document())
+        app = Flask(__name__, template_folder=str(Path(__file__).parents[1] / 'templates'))
+        app.add_url_rule('/industries', 'industries_page', lambda: '')
+        app.add_url_rule('/stock/<code>', 'stock_page', lambda code: code)
+        register_research_routes(app, load_relationships=lambda: {}, load_events=lambda: [],
+                                 load_opinions=lambda: {}, stock_observation=lambda code: official,
+                                 get_stock_name=lambda code: code, allowed_symbols=[official['code'], '2330'])
+        response = app.test_client().get('/compare?symbols=' + official['code'] + ',2330')
+        self.assertEqual(response.status_code, 200)
+        self.assertIn(official['observation_as_of'], response.get_data(as_text=True))
+
     def test_relationship_links_and_compare_share_supported_markets(self):
diff --git a/tests/test_web_product.py b/tests/test_web_product.py
index a458a4b..a454c4f 100644
--- a/tests/test_web_product.py
+++ b/tests/test_web_product.py
@@ -51,2 +51,25 @@ def prediction_product(market="TW", symbol="2330", as_of="2026-07-15"):
 class WebProductTests(unittest.TestCase):
+    @patch.object(stock_app, 'fetch_published_quant_snapshot', return_value=quant_snapshot())
+    @patch.object(web_routes.system, '_next_session_for_market', side_effect=ValueError('calendar unavailable'))
+    def test_unknown_stock_freshness_never_labels_quote_latest(self, calendar, fetch):
+        html = stock_app.app.test_client().get('/stock/2330').get_data(as_text=True)
+        self.assertIn('data-freshness-status="unavailable"', html)
+        self.assertIn('最近可用收盤', html)
+        self.assertNotIn('最新收盤', html)
+
+    @patch.object(stock_app, '_published_report_index_v2')
+    @patch.object(stock_app, '_published_dashboard_snapshot')
+    def test_view_localization_handles_null_lists_without_mutating_sources(self, load_snapshot, load_index):
+        snapshot = observation_dashboard()
+        snapshot['daily_focus'] = None
+        load_snapshot.return_value = snapshot
+        load_index.return_value = [dict(product_mode='observation', report_type='post_close',
+                                       title='空摘要', summary=None, source_market_date='2026-07-15',
+                                       applicable_trading_date='2026-07-16')]
+        for path in ('/dashboard', '/reports', '/reports/us'):
+            with self.subTest(path=path):
+                self.assertEqual(stock_app.app.test_client().get(path).status_code, 200)
+        self.assertIsNone(snapshot['daily_focus'])
+        self.assertIsNone(load_index.return_value[0]['summary'])
+
     @patch.object(stock_app, '_published_report_index_v2')
