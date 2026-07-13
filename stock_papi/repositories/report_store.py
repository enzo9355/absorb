import hashlib
import hmac

from reporting.web import validate_report_index, validate_report_metadata


def load_report_index(*, load_object, max_bytes):
    content = load_object("reports/v1/index-TW.json", max_bytes)
    return None if content is None else validate_report_index(content)


def load_report_pdf(item, *, load_object):
    content = load_object(f"reports/v1/{item['pdf_path']}", item["pdf_size"])
    if (
        content is None
        or len(content) != item["pdf_size"]
        or not hmac.compare_digest(
            hashlib.sha256(content).hexdigest(), item["pdf_sha256"]
        )
    ):
        return None
    return content


def load_report_metadata(item, *, load_object, max_bytes=2 * 1024 * 1024):
    content = load_object(f"reports/v1/{item['metadata']}", max_bytes)
    return None if content is None else validate_report_metadata(content, item)
