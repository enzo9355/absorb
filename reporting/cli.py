import argparse
import datetime
import json
import os
import sys
from pathlib import Path

from .config import ReportConfig
from .industry_analytics import build_daily_report
from .pdf_generator import DailyIndustryReportGenerator
from .publisher import is_source_already_published, publish_report
from .source_loader import load_previous_report_source, load_report_source


def _write_json_atomic(path: Path, document: dict) -> None:
    content = json.dumps(
        document, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_industry_map(root: Path) -> dict[str, list[str]]:
    """透過既有本地 pipeline 取得唯一的 industry_map。"""
    from local_quant import load_stock_pipeline

    pipeline = load_stock_pipeline(root)
    return {str(name): [str(symbol) for symbol in symbols] for name, symbols in pipeline.industry_map.items()}


def _status(
    *,
    success: bool,
    report_date: str | None = None,
    pdf_path: str | None = None,
    pdf_sha256: str | None = None,
    pdf_size: int = 0,
    warnings: list[str] | None = None,
    error: Exception | None = None,
) -> dict:
    return {
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "success": success,
        "report_date": report_date,
        "pdf_path": pdf_path,
        "pdf_sha256": pdf_sha256,
        "pdf_size": pdf_size,
        "warnings": warnings or [],
        "error_type": type(error).__name__ if error else None,
        "error_message": str(error) if error else None,
    }


def main(argv: list[str] | None = None) -> int:
    """執行本地台股日報驗證、生成與正式發布。"""
    parser = argparse.ArgumentParser(description="Stock Papi 台股產業量化分析日報")
    parser.add_argument("--root", type=Path, default=Path(r"D:\StockPapiData"))
    parser.add_argument("--market", choices=("TW",), default="TW")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--font-path", type=Path)
    parser.add_argument("--font-bold-path", type=Path)
    parser.add_argument("--title-font-path", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report-date", type=datetime.date.fromisoformat)
    args = parser.parse_args(argv)
    root = args.root
    status_path = root / "logs" / "report-status.json"
    report_date = None
    try:
        config = ReportConfig(
            root=root,
            market=args.market,
            font_path=args.font_path or ReportConfig().font_path,
            bold_font_path=args.font_bold_path or ReportConfig().bold_font_path,
            title_font_path=args.title_font_path or ReportConfig().title_font_path,
        )
        source = load_report_source(
            root,
            market=args.market,
            report_date=args.report_date,
            config=config,
        )
        report_date = source.manifest.market_as_of.isoformat()
        previous_source = load_previous_report_source(
            root, source.manifest.market_as_of, market=args.market, config=config
        )
        report = build_daily_report(
            source,
            _load_industry_map(root),
            config,
            previous_source=previous_source,
        )
        if args.dry_run:
            status = _status(
                success=True,
                report_date=report_date,
                warnings=report.warnings + ["dry-run：未生成或發布 PDF。"],
            )
            _write_json_atomic(status_path, status)
            print(json.dumps(status, ensure_ascii=False))
            return 0
        if any(stock.sample_data for stock in source.stocks):
            raise ValueError("SAMPLE / TEST DATA 不得發布為正式日報")
        if is_source_already_published(root, source):
            status = _status(
                success=True,
                report_date=report_date,
                warnings=["相同來源 manifest 已發布，跳過重複生成。"],
            )
            _write_json_atomic(status_path, status)
            print(json.dumps(status, ensure_ascii=False))
            return 0

        output_dir = args.output_dir or (root / "reports" / args.market)
        filename = f"stock-papi-{args.market.lower()}-industry-daily-{report_date}.pdf"
        output = output_dir / ".staging" / filename
        generation = DailyIndustryReportGenerator(config).generate(report, output)
        if not generation.success:
            raise RuntimeError(generation.error_message or "PDF 生成失敗")
        try:
            publish_report(root, report, generation, config, archive_dir=output_dir)
        finally:
            output.unlink(missing_ok=True)
        final_pdf = output_dir / filename
        status = _status(
            success=True,
            report_date=report_date,
            pdf_path=str(final_pdf),
            pdf_sha256=generation.sha256,
            pdf_size=generation.file_size,
            warnings=generation.warnings,
        )
        _write_json_atomic(status_path, status)
        print(json.dumps(status, ensure_ascii=False))
        return 0
    except Exception as exc:
        status = _status(success=False, report_date=report_date, error=exc)
        try:
            _write_json_atomic(status_path, status)
        except OSError:
            pass
        print(json.dumps(status, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
