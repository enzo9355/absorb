class ReportError(RuntimeError):
    """日報流程的基礎例外。"""


class ReportSourceError(ReportError):
    """來源快照未通過完整性或安全驗證。"""


class ReportGenerationError(ReportError):
    """PDF 生成或驗證失敗。"""


class ReportPublishError(ReportError):
    """日報發布資料不完整或不一致。"""


class ReportWebError(ReportError):
    """雲端報告索引或 PDF 未通過驗證。"""
