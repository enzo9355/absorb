#!/usr/bin/env python3
"""Build the small PRESS BLOCK display-font subset.

The source font is the OFL Noto Serif TC variable TTF from Google Fonts.
Only static PRESS BLOCK heading characters are retained; dynamic market and
security names intentionally stay on the fallback stack.
"""

from __future__ import annotations

import argparse
from pathlib import Path


STATIC_TITLE_TEXT = (
    "台股今天怎麼了美股今天怎麼了為什麼會這樣市場實況美股市場實況"
    "產業觀察美股產業觀察市場觀察產業資料產業強弱與關注清單關注公司"
    "支持與反對證據個股與ETF五日模型情境市場廣度期間報酬走到極端的家數"
    "值得注意相對穩定轉弱尚未驗證波動與風險最新更新AI"
    "MARKETACTUALSMODELESTIMATEUSMARKETINDEXESTAIWANCAPITALIZATIONWEIGHTEDINDEX"
    "／·＋－%"
)
MAX_OUTPUT_BYTES = 80 * 1024


def build_font(source: Path, output: Path) -> None:
    try:
        from fontTools import subset
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "fontTools is required: python -m pip install fonttools brotli"
        ) from exc

    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.retain_gids = False

    font = subset.load_font(str(source), options)
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text=STATIC_TITLE_TEXT)
    subsetter.subset(font)
    output.parent.mkdir(parents=True, exist_ok=True)
    subset.save_font(font, str(output), options)

    size = output.stat().st_size
    if size > MAX_OUTPUT_BYTES:
        raise SystemExit(f"subset is {size} bytes; maximum is {MAX_OUTPUT_BYTES}")
    print(f"wrote {output} ({size} bytes)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="OFL Noto Serif TC source TTF")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("static/fonts/absorb-serif.woff2"),
        help="subset output path",
    )
    args = parser.parse_args()
    build_font(args.source, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
