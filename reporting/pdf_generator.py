import hashlib
import os
from pathlib import Path
from xml.sax.saxutils import escape

from . import REPORT_GENERATOR_VERSION, REPORT_SCHEMA_VERSION, git_commit_sha
from .charts import (
    backtest_chart,
    market_quality_chart,
    return_ranking_chart,
    rotation_chart,
)
from .config import ReportConfig
from .industry_analytics import ROTATION_LABELS
from .schemas import DailyIndustryReport, ReportGenerationResult


DISCLAIMER = (
    "本報告內容僅供量化研究、資訊整理與教育參考，不構成任何證券買賣建議、投資顧問服務、邀約或收益保證。"
    "模型與回測結果均基於歷史資料，過去績效不代表未來結果。實際交易可能受到市場流動性、滑價、交易成本、"
    "資料延遲及模型失效等因素影響，使用者應自行評估投資風險。"
)


def _pct(value, digits=2, missing="資料不足"):
    return missing if value is None else f"{value:.{digits}%}"


def _number(value, digits=2, missing="資料不足"):
    return missing if value is None else f"{value:.{digits}f}"


def _delta(value, *, percent=False):
    if value is None:
        return "—"
    return f"{value:+.1%}" if percent else f"{value:+.1f}"


class DailyIndustryReportGenerator:
    """在 Windows 本地生成並驗證 Stock Papi 台股產業日報。"""

    def __init__(self, config: ReportConfig) -> None:
        self.config = config

    def _validate_fonts(self) -> None:
        title_font = self.config.title_font_path or self.config.bold_font_path
        for label, path in (
            ("REPORT_FONT_PATH", self.config.font_path),
            ("REPORT_FONT_BOLD_PATH", self.config.bold_font_path),
            ("REPORT_TITLE_FONT_PATH", title_font),
        ):
            if path is None or not Path(path).is_file() or not os.access(path, os.R_OK):
                raise ValueError(f"{label} 指定的中文字型不存在或不可讀")

    @staticmethod
    def _validate_content(report: DailyIndustryReport) -> None:
        if any(stock.sample_data for stock in report.source.stocks):
            return
        invalid = [
            stock.symbol
            for stock in report.source.stocks
            if not stock.name.strip()
            or stock.name.strip() == stock.symbol
            or "測試股票" in stock.name
        ]
        if invalid:
            raise ValueError("正式報告不得包含測試股票或缺少真實名稱：" + "、".join(invalid[:10]))

    def generate(
        self,
        report_data: DailyIndustryReport,
        output_path: Path,
    ) -> ReportGenerationResult:
        """以 temporary file 生成、驗證並原子替換一份正式 PDF。"""
        output = Path(output_path)
        temporary = output.with_suffix(output.suffix + ".tmp")
        try:
            self._validate_fonts()
            self._validate_content(report_data)
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary.unlink(missing_ok=True)
            self._build_pdf(report_data, temporary)
            with temporary.open("r+b") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            size = temporary.stat().st_size
            if not 0 < size <= self.config.max_pdf_bytes:
                raise ValueError("PDF 大小超出允許範圍")
            from pypdf import PdfReader

            reader = PdfReader(temporary)
            page_count = len(reader.pages)
            extracted = [page.extract_text() or "" for page in reader.pages]
            text = "\n".join(extracted)
            if (
                page_count < 1
                or any(len(item.strip()) < 30 for item in extracted)
                or "台股產業量化分析日報" not in text
                or "本報告內容僅供量化研究" not in text
            ):
                raise ValueError("PDF 頁面或繁體中文抽取驗證失敗")
            os.replace(temporary, output)
            warnings = list(report_data.warnings)
            if size > self.config.target_pdf_bytes:
                warnings.append("PDF 超過建議的 8 MB 目標。")
            return ReportGenerationResult.from_path(
                output,
                report_data.report_date,
                page_count=page_count,
                warnings=warnings,
            )
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            return ReportGenerationResult.failure(report_data.report_date, str(exc))

    def _build_pdf(self, report: DailyIndustryReport, target: Path) -> None:
        from reportlab.graphics.shapes import Drawing, Rect
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import (
            Image,
            LongTable,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )

        theme = self.config.theme
        is_sample = any(stock.sample_data for stock in report.source.stocks)
        title_font_path = self.config.title_font_path or self.config.bold_font_path
        font_key = hashlib.sha256(
            "|".join(
                str(item)
                for item in (
                    self.config.font_path,
                    self.config.bold_font_path,
                    title_font_path,
                )
            ).encode("utf-8")
        ).hexdigest()[:10]
        regular_font = f"StockPapiSans-{font_key}"
        bold_font = f"StockPapiSansBold-{font_key}"
        title_font = f"StockPapiSerif-{font_key}"
        for name, path in (
            (regular_font, self.config.font_path),
            (bold_font, self.config.bold_font_path),
            (title_font, title_font_path),
        ):
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(path)))

        styles = getSampleStyleSheet()
        body = ParagraphStyle(
            "StockPapiBody",
            parent=styles["BodyText"],
            fontName=regular_font,
            fontSize=theme.body_font_size,
            leading=theme.body_font_size * 1.5,
            textColor=colors.HexColor(theme.text),
            spaceAfter=4,
        )
        small = ParagraphStyle(
            "StockPapiSmall",
            parent=body,
            fontSize=theme.small_font_size,
            leading=theme.small_font_size * 1.45,
            textColor=colors.HexColor(theme.muted),
        )
        heading = ParagraphStyle(
            "StockPapiHeading",
            parent=body,
            fontName=title_font,
            fontSize=theme.heading_font_size,
            leading=theme.heading_font_size * 1.2,
            textColor=colors.HexColor(theme.text),
            spaceBefore=8,
            spaceAfter=6,
            keepWithNext=True,
        )
        subheading = ParagraphStyle(
            "StockPapiSubheading",
            parent=body,
            fontName=bold_font,
            fontSize=11,
            leading=15,
            spaceBefore=6,
            spaceAfter=4,
            keepWithNext=True,
        )
        cover_title = ParagraphStyle(
            "StockPapiCover",
            parent=heading,
            fontSize=27,
            leading=34,
            alignment=TA_CENTER,
        )
        centered = ParagraphStyle("StockPapiCentered", parent=body, alignment=TA_CENTER)
        kpi = ParagraphStyle(
            "StockPapiKpi", parent=body, fontName=bold_font, fontSize=12, leading=15, alignment=TA_CENTER
        )

        margin = theme.margin_mm * mm
        document = SimpleDocTemplate(
            str(target),
            pagesize=A4,
            leftMargin=margin,
            rightMargin=margin,
            topMargin=18 * mm,
            bottomMargin=16 * mm,
            title="Stock Papi 台股產業量化分析日報",
            author="Stock Papi",
            subject=f"TW {report.report_date.isoformat()}",
        )

        def page_decor(canvas, doc):
            canvas.saveState()
            width, height = A4
            canvas.setFillColor(colors.HexColor(theme.background))
            canvas.rect(0, 0, width, height, fill=1, stroke=0)
            canvas.setFillColor(colors.HexColor(theme.text))
            canvas.setFont(bold_font, 8)
            canvas.drawString(margin, height - 10 * mm, "Stock Papi")
            canvas.setFont(regular_font, 7)
            canvas.setFillColor(colors.HexColor(theme.muted))
            canvas.drawRightString(
                width - margin, height - 10 * mm, f"報告日 {report.report_date.isoformat()}"
            )
            canvas.setStrokeColor(colors.HexColor(theme.line))
            canvas.line(margin, 13 * mm, width - margin, 13 * mm)
            canvas.drawString(margin, 8 * mm, "量化研究與教育參考")
            if is_sample:
                canvas.setFillColor(colors.HexColor(theme.warning))
                canvas.setFont(bold_font, 8)
                canvas.drawCentredString(width / 2, 8 * mm, "SAMPLE / TEST DATA")
            canvas.setFillColor(colors.HexColor(theme.muted))
            canvas.setFont(regular_font, 7)
            canvas.drawRightString(width - margin, 8 * mm, f"第 {doc.page} 頁")
            canvas.restoreState()

        def paragraph(text, style=body):
            return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)

        def section(title):
            return [Spacer(1, 3 * mm), paragraph(title, heading)]

        def table(data, widths=None, repeat=True, header_color=None):
            converted = [
                [cell if hasattr(cell, "wrap") else paragraph(cell, small) for cell in row]
                for row in data
            ]
            component = LongTable(converted, colWidths=widths, repeatRows=1 if repeat else 0)
            component.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_color or theme.apricot)),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(theme.text)),
                ("FONTNAME", (0, 0), (-1, 0), bold_font),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor(theme.surface)),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor(theme.line)),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            return component

        def kpi_cards(items):
            cards = []
            for label, value in items:
                card = Table(
                    [[paragraph(label, small)], [paragraph(value, kpi)]],
                    colWidths=[40 * mm],
                )
                card.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(theme.surface)),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(theme.line)),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]))
                cards.append(card)
            rows = [cards[index:index + 4] for index in range(0, len(cards), 4)]
            return Table(rows, colWidths=[42 * mm] * 4, hAlign="LEFT")

        def progress(label, value, color):
            safe = 0 if value is None else max(0.0, min(1.0, value))
            drawing = Drawing(165 * mm, 5 * mm)
            drawing.add(Rect(0, 0, 165 * mm, 3.5 * mm, fillColor=colors.HexColor(theme.line), strokeColor=None))
            drawing.add(Rect(0, 0, 165 * mm * safe, 3.5 * mm, fillColor=colors.HexColor(color), strokeColor=None))
            return [paragraph(f"{label}：{_pct(value, 1)}", small), drawing]

        manifest = report.source.manifest
        story = [Spacer(1, 18 * mm)]
        if is_sample:
            story += [
                paragraph("SAMPLE / TEST DATA - 不得正式發布", centered),
                paragraph("不得作為正式投資或模型結果", centered),
                Spacer(1, 4 * mm),
            ]
        story += [paragraph("Stock Papi", centered), Spacer(1, 4 * mm)]
        story += [paragraph("台股產業量化分析日報", cover_title), Spacer(1, 6 * mm)]
        cover_rows = [
            ["報告交易日", report.report_date.isoformat()],
            ["市場", "台股（TW）"],
            ["資料截止日", manifest.market_as_of.isoformat()],
            ["模型版本", "、".join(report.model_versions) or "unknown"],
            ["台股標的總數", str(manifest.universe_count)],
            ["有效股票數", str(manifest.symbol_count)],
            ["發布資料覆蓋率", _pct(manifest.coverage)],
            ["失敗標的數", str(manifest.failure_count)],
        ]
        cover_table = Table(
            [[paragraph(a, small), paragraph(b, body)] for a, b in cover_rows],
            colWidths=[48 * mm, 86 * mm],
        )
        cover_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(theme.surface)),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(theme.line)),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor(theme.line)),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story += [cover_table, Spacer(1, 6 * mm), paragraph("每日研究摘要", heading)]
        story += [paragraph(f"• {item}") for item in report.summary]
        story += [
            paragraph(
                "高機率與低機率名單使用互斥絕對門檻：>= 60% 為模型偏多，<= 45% 為模型偏弱，其餘為中性。",
                small,
            ),
            Spacer(1, 4 * mm),
            paragraph(DISCLAIMER, small),
        ]

        story += section("市場與資料品質")
        market = report.market
        story += [kpi_cards([
            ("市場 1 日報酬", _pct(market.returns[1])),
            ("市場 5 日報酬", _pct(market.returns[5])),
            ("市場 20 日報酬", _pct(market.returns[20])),
            ("市場 60 日報酬", _pct(market.returns[60])),
            ("市場波動率", _pct(market.volatility_20d)),
            ("上漲／下跌家數", f"{market.advancing_count}／{market.declining_count}"),
            ("20 日新高／新低", f"{market.new_high_20d_count}／{market.new_low_20d_count}"),
            ("量能相對 20 日平均", _number(market.average_volume_ratio) + " 倍" if market.average_volume_ratio is not None else "資料不足"),
        ])]
        story += [Spacer(1, 3 * mm)]
        story += progress("站上 MA20 比例", market.bullish_breadth, theme.mint)
        story += progress("站上 MA60 比例", market.ma60_breadth, theme.apricot)
        story += progress("模型高分比例", market.high_score_ratio, theme.lavender)
        story += [Image(market_quality_chart(report, self.config), width=168 * mm, height=58 * mm)]
        market_rows = [
            ["資料品質指標", "目前", "與前一交易日變化"],
            ["發布資料覆蓋率", _pct(manifest.coverage), "—"],
            ["失敗率", _pct(manifest.failure_rate), "—"],
            ["資料品質警示比例", _pct(market.data_warning_ratio), "—"],
            ["選擇權資料缺失比例", _pct(market.option_missing_ratio), "—"],
            ["多頭廣度", _pct(market.bullish_breadth), _delta(market.changes.get("bullish_breadth"), percent=True)],
            ["資料新鮮度", f"{market.freshness_days} 日", "—"],
        ]
        story += [table(market_rows, [70 * mm, 42 * mm, 55 * mm])]
        story += [
            paragraph("資料品質警示分類：" + ("；".join(report.warnings) or "未偵測到跨股票市場因子不一致。")),
            paragraph("模型版本分布：" + "、".join(f"{key}（{value}）" for key, value in market.model_versions.items())),
            paragraph("失敗標的：" + ("、".join(manifest.failed_symbols[:30]) or "無")),
        ]

        story += section("產業五日上漲機率排名")
        story += [paragraph(
            "排名依產業有效成分股最新五日上漲機率等權平均，由高至低排序；不代表近期實際報酬或回測績效排名。",
            small,
        )]
        selected = []
        for item in report.industries[:10] + list(reversed(report.industries[-5:])):
            if item.name not in {entry.name for entry in selected}:
                selected.append(item)
        ranking_rows = [["目前排名", "產業", "五日上漲機率", "前日排名", "排名變化", "機率變化", "有效／總數", "樣本品質"]]
        for item in selected:
            ranking_rows.append([
                str(item.rank), item.name,
                _number(item.average_probability, 1) + "%" if item.average_probability is not None else "資料不足",
                str(item.previous_rank) if item.previous_rank is not None else "—",
                f"{item.rank_change:+d}" if item.rank_change is not None else "—",
                _delta(item.probability_change),
                f"{item.valid_samples[5]}／{item.component_count}", item.sample_quality,
            ])
        story += [table(ranking_rows, [14 * mm, 33 * mm, 25 * mm, 18 * mm, 18 * mm, 20 * mm, 20 * mm, 22 * mm])]
        movers = sorted(
            [item for item in report.industries if item.rank_change is not None],
            key=lambda item: abs(item.rank_change or 0),
            reverse=True,
        )[:5]
        changed = [item for item in report.industries if item.rotation_changed]
        story += [paragraph("名次變化最大", subheading)]
        story += [paragraph(
            "、".join(f"{item.name}（{item.rank_change:+d}）" for item in movers)
            if movers else "無前期報告可比較。"
        )]
        story += [paragraph("輪動階段改變", subheading)]
        story += [paragraph(
            "、".join(
                f"{item.name}（{ROTATION_LABELS.get(item.previous_rotation or 'insufficient')} → {ROTATION_LABELS[item.rotation]}）"
                for item in changed
            ) if changed else ("無階段改變。" if report.comparison_available else "無前期報告可比較。")
        )]
        small_samples = [item for item in report.industries if item.sample_quality != "一般樣本"]
        story += [paragraph(
            "樣本不足警示：" + ("、".join(f"{item.name}（{item.sample_quality}）" for item in small_samples[:20]) or "無")
        )]
        story += [Image(return_ranking_chart(report, self.config), width=168 * mm, height=76 * mm)]

        story += section("產業輪動")
        story += [Image(rotation_chart(report, self.config), width=168 * mm, height=77 * mm)]
        story += [
            paragraph("X 軸：20 日相對大盤報酬（產業等權報酬減市場報酬）；Y 軸：5 日相對大盤報酬（產業等權報酬減市場報酬）。", small),
            paragraph(
                "四象限定義：領先＝20 日與 5 日皆優於市場；改善＝20 日落後、5 日轉強；衰退＝20 日領先、5 日轉弱；落後＝20 日與 5 日皆落後。",
                small,
            ),
            paragraph(
                f"接近分界：任一軸落在 -{self.config.rotation_neutral_threshold_pct:.2f}% 至 +{self.config.rotation_neutral_threshold_pct:.2f}% 中性帶。",
                small,
            ),
        ]
        for key in ("leading", "improving", "weakening", "lagging"):
            names = [item.name for item in report.industries if item.rotation == key]
            story += [paragraph(f"今日{ROTATION_LABELS[key]}產業：" + ("、".join(names) or "無"))]
        divergences = [item.name for item in report.industries if "分歧" in item.signal_profile]
        story += [paragraph("訊號分歧產業：" + ("、".join(divergences) or "無"))]

        story += section("整體模型品質")
        quality = report.model_quality
        story += [kpi_cards([
            ("pooled OOS 樣本數", str(quality.pooled_oos_samples) if quality.pooled_oos_samples else "資料不足"),
            ("五日方向準確率", _pct(quality.direction_accuracy)),
            ("Brier Score", _number(quality.brier_score, 4)),
            ("高分訊號勝率", _pct(quality.high_score_win_rate)),
        ])]
        calibration_rows = [["機率分桶", "樣本數", "平均模型機率", "實際上漲率"]]
        for item in quality.calibration_bins:
            calibration_rows.append([
                item["range"], str(item["samples"]),
                _pct(item["average_probability"], 1), _pct(item["actual_up_rate"], 1),
            ])
        story += [table(calibration_rows, [42 * mm] * 4)]
        story += [paragraph("模型版本：" + "、".join(report.model_versions))]

        story += section("產業策略回測")
        story += [paragraph(
            "成本口徑：每次五日完整持有扣除 0.585%；產業買進持有與市場基準均未扣成本。低樣本 Sharpe 與勝率僅供參考，不用於排序推薦產業。",
            small,
        )]
        main_backtests = report.backtests[:10]
        period_rows = [["產業", "策略狀態", "樣本品質", "再平衡期數", "進場期數", "獲利／虧損／空手", "平均持股數"]]
        return_rows = [["產業", "策略累積報酬（已扣成本）", "產業買進持有（未扣成本）", "市場基準（未扣成本）"]]
        risk_rows = [["產業", "最大回撤", "Sharpe", "勝率", "樣本警示"]]
        for result in main_backtests:
            period_rows.append([
                result.industry, result.strategy_status, result.sample_quality,
                str(result.rebalance_periods), str(result.entry_periods),
                f"{result.winning_periods}／{result.losing_periods}／{result.cash_periods}",
                _number(result.average_positions, 1, "—"),
            ])
            warning = "＊" if result.low_sample_warning else ""
            return_rows.append([
                result.industry,
                _pct(result.cumulative_return, missing="—"),
                _pct(result.buy_hold_return, missing="—"),
                _pct(result.market_return, missing="—"),
            ])
            risk_rows.append([
                result.industry,
                _pct(result.max_drawdown, missing="—"),
                _number(result.sharpe, missing="—") + warning,
                (_pct(result.win_rate, 1, "—") + f"（{result.winning_periods}／{result.entry_periods}）{warning}")
                if result.win_rate is not None else "—",
                "低樣本" if result.low_sample_warning else "無",
            ])
        story += [table(period_rows, [26 * mm, 22 * mm, 22 * mm, 21 * mm, 19 * mm, 34 * mm, 24 * mm])]
        story += [Spacer(1, 3 * mm), table(return_rows, [25 * mm, 48 * mm, 48 * mm, 48 * mm])]
        story += [Spacer(1, 3 * mm), table(risk_rows, [30 * mm, 30 * mm, 30 * mm, 48 * mm, 32 * mm])]
        representatives = [
            item for item in report.backtests
            if item.sample_quality in {"中等樣本", "較完整樣本"} and not item.all_cash
        ][:2]
        if representatives:
            for result in representatives:
                story += [Spacer(1, 3 * mm), Image(backtest_chart(result, self.config), width=168 * mm, height=93 * mm)]
        else:
            story += [paragraph("無中等以上樣本的代表性產業圖；低樣本結果不作推薦排序。")]

        story += section("量化觀察名單")
        story += [
            paragraph("新進高分：" + ("、".join(report.new_high_score_symbols) or ("無" if report.comparison_available else "無前期資料"))),
            paragraph("退出高分：" + ("、".join(report.exited_high_score_symbols) or ("無" if report.comparison_available else "無前期資料"))),
            paragraph("外資近五日淨買賣超（股）：來源原始買進股數減賣出股數，未換算為張。", small),
        ]
        watch_rows = [["股票", "五日上漲機率／前日／變化", "高分變化", "技術狀態", "產業", "外資 5 日（股）", "風險提示"]]
        for item in report.watchlist:
            if item["new_high_score"]:
                score_change = "新進高分"
            elif item["exited_high_score"]:
                score_change = "退出高分"
            elif not report.comparison_available:
                score_change = "無前期資料"
            else:
                score_change = "維持"
            watch_rows.append([
                f"{item['symbol']}\n{item['name']}",
                f"{item['probability']:.1f}%／"
                f"{_number(item['previous_probability'], 1, '—')}"
                f"／{_delta(item['probability_change'])}",
                score_change,
                item["trend"],
                "、".join(item["industries"]) or "未分類",
                _number(item["foreign_net_5"], 0, "資料不足"),
                "、".join(item["risks"]),
            ])
        story += [table(watch_rows, [24 * mm, 34 * mm, 20 * mm, 21 * mm, 26 * mm, 24 * mm, 21 * mm])]

        story += section("附錄：完整產業表")
        appendix_rows = [["排名", "產業", "機率／變化", "前日／排名變化", "輪動／前日／訊號", "階段變化", "有效／總數", "樣本品質"]]
        for item in report.industries:
            appendix_rows.append([
                str(item.rank), item.name,
                (_number(item.average_probability, 1) + "%／" + _delta(item.probability_change)) if item.average_probability is not None else "資料不足",
                f"{item.previous_rank or '—'}／{item.rank_change if item.rank_change is not None else '—'}",
                f"{ROTATION_LABELS[item.rotation]}／{ROTATION_LABELS.get(item.previous_rotation or 'insufficient')}／{item.signal_profile}",
                "是" if item.rotation_changed else "否" if item.rotation_changed is not None else "—",
                f"{item.valid_samples[5]}／{item.component_count}", item.sample_quality,
            ])
        story += [table(appendix_rows, [10 * mm, 31 * mm, 23 * mm, 22 * mm, 29 * mm, 17 * mm, 19 * mm, 19 * mm])]

        story += section("附錄：完整回測樣本表")
        full_backtest_rows = [["產業", "起訖日", "再平衡", "進場", "獲利", "虧損", "空手", "樣本品質", "最大回撤"]]
        for result in report.backtests:
            full_backtest_rows.append([
                result.industry,
                f"{result.start_date or '—'} 至 {result.end_date or '—'}",
                str(result.rebalance_periods), str(result.entry_periods),
                str(result.winning_periods), str(result.losing_periods), str(result.cash_periods),
                result.sample_quality, _pct(result.max_drawdown, missing="—"),
            ])
        story += [table(full_backtest_rows, [25 * mm, 35 * mm, 16 * mm, 14 * mm, 14 * mm, 14 * mm, 14 * mm, 21 * mm, 18 * mm])]

        story += section("方法論、限制與免責聲明")
        methodology = [
            f"source manifest：{manifest.manifest_path}；SHA-256：{manifest.manifest_sha256[:16]}。",
            f"report schema version：{REPORT_SCHEMA_VERSION}；report generator version：{REPORT_GENERATOR_VERSION}；Git commit SHA：{git_commit_sha()}。",
            f"generated_at：{report.generated_at.isoformat().replace('+00:00', 'Z')}；data_as_of：{manifest.market_as_of.isoformat()}。",
            f"model versions：{'、'.join(report.model_versions)}；universe count：{manifest.universe_count}；effective symbol count：{manifest.symbol_count}；coverage：{manifest.coverage:.2%}。",
            f"sample/test flag：{str(is_sample).lower()}。本報告為自動生成、未經人工分析師覆核。",
            "資料來源：本地量化流程發布的 TW schema v2 manifest 與其列出的 content-addressed gzip 股票物件。",
            "模型目標：LightGBM binary classifier 預測未來五個交易日方向；TimeSeriesSplit 保留五日 gap。",
            "整體模型品質使用所有可驗證歷史 OOS AI_P 與其後五日實際方向 pooled calculation，不平均個股 accuracy。",
            "產業策略：AI_P >= 60、五日持有、每五個交易日再平衡、禁止重疊、成分股等權。",
            "交易成本：每個完整持有部位扣除 0.585%；產業買進持有與市場基準未扣交易成本。",
            "產業／題材分類可能重疊，同一股票可同時出現在多個主題產業。",
            "look-ahead bias 防範：報酬只使用當時訊號與其後五個交易日價格，未實現期間不納入。",
            "限制：目前成分股集合仍可能受 survivorship bias 影響；回測未完整模擬流動性、滑價、漲跌停與停牌限制。",
        ]
        story += [paragraph(f"• {item}") for item in methodology]
        story += [Spacer(1, 5 * mm), paragraph(DISCLAIMER, body)]
        document.build(story, onFirstPage=page_decor, onLaterPages=page_decor)
