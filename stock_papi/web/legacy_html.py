"""Legacy standalone stock report HTML renderer."""

from html import escape

from stock_papi.shared.formatting import format_sentiment_summary as _format_sentiment_summary


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
