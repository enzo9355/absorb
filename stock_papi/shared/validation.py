import hmac
import re
from urllib.parse import urlsplit


def constant_time_equals(supplied, expected):
    """Constant-time string compare that treats non-ASCII input as a mismatch.

    `hmac.compare_digest` raises TypeError on non-ASCII str, so feeding it a
    request-supplied credential turns a crafted header/cookie/query value into
    a 500 instead of a clean authentication failure. A non-ASCII value can
    never equal an ASCII secret, so reporting a mismatch is both correct and
    safe. Use this at every boundary where the compared value comes from a
    request; digest-vs-digest comparisons are ASCII by construction.
    """
    if not isinstance(supplied, str) or not isinstance(expected, str):
        return False
    if not supplied or not expected:
        return False
    if not supplied.isascii() or not expected.isascii():
        return False
    return hmac.compare_digest(supplied, expected)


def safe_external_https_url(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        return None
    if "\\" in value or any(ord(char) < 32 for char in value):
        return None
    try:
        parsed = urlsplit(value)
        _port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return value


def is_us_ticker(value):
    value = str(value or "").upper()
    return (
        value != "TAIEX"
        and len(value) <= 10
        and bool(re.fullmatch(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)?", value))
    )


def is_crypto_query(text):
    normalized = text.upper()
    return any(
        keyword in normalized
        for keyword in (
            "BTC", "ETH", "USDT", "USDC", "CRYPTO", "虛擬貨幣",
            "虛擬幣", "加密貨幣", "比特幣", "以太幣",
        )
    )
