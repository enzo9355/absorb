"""Same-session TWSE institutional amounts, retaining the exact source evidence."""

import datetime as dt
import hashlib
import json
import re

SOURCE_URL = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
MAX_BYTES = 100_000
FIELDS = ["單位名稱", "買進金額", "賣出金額", "買賣差額"]
LABELS = (
    "自營商(自行買賣)", "自營商(避險)", "投信",
    "外資及陸資(不含外資自營商)", "外資自營商", "合計",
)


def parse_twse_flows(raw, target_date):
    target = dt.date.fromisoformat(str(target_date))
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("institutional response size is invalid")
    body = raw.decode("utf-8-sig")
    payload = json.loads(body)
    title = f"{target.year - 1911}年{target.month:02d}月{target.day:02d}日 三大法人買賣金額統計表"
    if (not isinstance(payload, dict) or payload.get("stat") != "OK"
            or payload.get("date") != target.strftime("%Y%m%d")
            or payload.get("title") != title or payload.get("fields") != FIELDS):
        raise ValueError("institutional source identity does not match")
    rows = payload.get("data")
    if not isinstance(rows, list) or len(rows) != len(LABELS):
        raise ValueError("institutional rows are incomplete")
    amounts = {}
    for row in rows:
        if (not isinstance(row, list) or len(row) != 4
                or row[0] not in LABELS or row[0] in amounts):
            raise ValueError("institutional row identity is invalid")
        if any(not isinstance(value, str) or len(value) > 32 or re.fullmatch(r"-?(?:0|[1-9]\d{0,2}(?:,\d{3})*|[1-9]\d*)", value) is None
               for value in row[1:]):
            raise ValueError("institutional amount is invalid")
        buy, sell, net = (int(value.replace(",", "")) for value in row[1:])
        if buy < 0 or sell < 0 or buy - sell != net:
            raise ValueError("institutional row does not reconcile")
        amounts[row[0]] = (buy, sell, net)
    # Foreign dealers are already included in dealer amounts, per TWSE's notes.
    if any(sum(amounts[label][i] for label in LABELS[:4]) != amounts["合計"][i]
           for i in range(3)):
        raise ValueError("institutional totals do not reconcile")
    return {
        "as_of": target.isoformat(), "unit": "TWD_million", "scope": "TWSE",
        "foreign_net": amounts[LABELS[3]][2] / 1_000_000,
        "investment_trust_net": amounts["投信"][2] / 1_000_000,
        "dealer_net": (amounts[LABELS[0]][2] + amounts[LABELS[1]][2]) / 1_000_000,
        "source": SOURCE_URL + f"?dayDate={target:%Y%m%d}&type=day&response=json",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_body": raw.decode("utf-8"),
    }


def validate_twse_flows(document, target_date):
    if not isinstance(document, dict) or not isinstance(document.get("source_body"), str):
        raise ValueError("institutional evidence is missing")
    expected = parse_twse_flows(document["source_body"].encode("utf-8"), target_date)
    if document != expected:
        raise ValueError("institutional evidence or amounts differ")
    return expected


def fetch_twse_flows(target_date, *, http_get=None):
    import requests

    target = dt.date.fromisoformat(str(target_date))
    with (http_get or requests.get)(
        SOURCE_URL, params={"dayDate": target.strftime("%Y%m%d"), "type": "day", "response": "json"},
        timeout=(5, 15), allow_redirects=False, stream=True,
    ) as response:
        if response.status_code != 200:
            raise ValueError("institutional source HTTP failure")
        raw = bytearray()
        for chunk in response.iter_content(8192):
            raw.extend(chunk)
            if len(raw) > MAX_BYTES:
                raise ValueError("institutional response exceeds size limit")
    return parse_twse_flows(bytes(raw), target)
