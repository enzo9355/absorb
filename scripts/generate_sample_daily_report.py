"""Generate a clearly labelled synthetic daily report for visual verification."""

import argparse
import hashlib
import json
import math
import tempfile
from pathlib import Path

from pypdf import PdfReader

from reporting.config import ReportConfig
from reporting.industry_analytics import build_daily_report
from reporting.pdf_generator import DailyIndustryReportGenerator
from reporting.source_loader import load_report_source
from tests.report_fixtures import stock_document, write_quant_publish


SAMPLE_SPECS = (
    ("2330", 100.0, 76.0, 0.0030),
    ("2454", 130.0, 68.0, 0.0020),
    ("2317", 90.0, 72.0, 0.0010),
    ("6669", 160.0, 64.0, 0.0004),
    ("2881", 70.0, 57.0, -0.0005),
    ("2882", 75.0, 53.0, -0.0010),
    ("2308", 110.0, 61.0, 0.0002),
    ("1519", 80.0, 49.0, -0.0020),
)


def build_documents() -> list[dict]:
    """Build deterministic SAMPLE / TEST DATA stock artifacts."""
    documents = []
    for symbol, base, probability, trend in SAMPLE_SPECS:
        document = stock_document(symbol, start_price=base, ai_probability=probability)
        for index, row in enumerate(document["daily"]):
            close = base * (1 + trend * index + 0.012 * math.sin(index / 4))
            row.update(
                Close=round(close, 4),
                MA20=round(base * (1 + trend * max(0, index - 9)), 4),
                MA60=round(base * (1 + trend * max(0, index - 29)), 4),
                RET_1=trend,
                RET_5=trend * 5,
                RET_20=trend * 20,
                MARKET_RET_1=0.0006,
                MARKET_RET_5=0.003,
                MARKET_RET_20=0.012,
                MARKET_VOL_20=0.011,
                RSI=74.0 if symbol == "2330" else 42.0 if symbol == "1519" else 58.0,
                ForeignNet=-800.0 if symbol in {"2882", "1519"} else 1200.0,
                VOL_RATIO=0.7 if symbol == "2308" else 1.25,
            )
        document["latest"] = document["daily"][-1]
        documents.append(document)
    return documents


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate SAMPLE / TEST DATA PDF")
    parser.add_argument("--font-path", type=Path, required=True)
    parser.add_argument("--font-bold-path", type=Path, required=True)
    parser.add_argument("--title-font-path", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/pdf/stock-papi-tw-industry-daily-SAMPLE-2026-07-03.pdf"),
    )
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_quant_publish(root, build_documents())
        source = load_report_source(root)
        industry_map = {
            "全市場": [item[0] for item in SAMPLE_SPECS],
            "ETF專區": ["0050"],
            "半導體": ["2330", "2454"],
            "AI 伺服器": ["2317", "6669"],
            "金融": ["2881", "2882"],
            "綠能": ["2308", "1519"],
            "AI 題材": ["2330", "2317", "6669"],
        }
        config = ReportConfig(
            font_path=args.font_path,
            bold_font_path=args.font_bold_path,
            title_font_path=args.title_font_path,
            min_backtest_periods=2,
        )
        report = build_daily_report(source, industry_map, config)
        result = DailyIndustryReportGenerator(config).generate(report, args.output)
    if not result.success:
        raise RuntimeError(result.error_message or "sample PDF generation failed")
    reader = PdfReader(args.output)
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    required = (
        "SAMPLE / TEST DATA",
        "不得正式發布",
        "不得作為正式投資或模型結果",
        "台股產業量化分析日報",
        "本報告內容僅供量化研究",
    )
    if not all(text in extracted for text in required):
        raise RuntimeError("sample PDF text extraction validation failed")
    print(json.dumps({
        "path": str(args.output.resolve()),
        "pages": len(reader.pages),
        "size": args.output.stat().st_size,
        "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "sample": True,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
