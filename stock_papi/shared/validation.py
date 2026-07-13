import re


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
