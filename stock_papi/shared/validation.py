import re
from urllib.parse import urlsplit


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
