#!/usr/bin/env python3
"""將拆分的 CSS 原始檔串接為 static/app.css。

app.css 是產生檔，不要直接編輯；改 static/ 下的六個原始檔後重跑本腳本。
不使用打包工具，串接順序即為級聯順序。
"""

from __future__ import annotations

import sys
from pathlib import Path

SOURCES = (
    "tokens.css",
    "base.css",
    "pages.css",
    "layout.css",
    "components.css",
    "utilities.css",
)
BANNER = (
    "/* 產生檔，請勿直接編輯。\n"
    "   來源：" + " + ".join(SOURCES) + "\n"
    "   重建：python3 scripts/build_css.py */\n"
)


def render(static_root: Path) -> str:
    parts = [BANNER]
    for name in SOURCES:
        parts.append((static_root / name).read_text(encoding="utf-8").rstrip() + "\n")
    return "\n".join(parts)


def main() -> int:
    static_root = Path(__file__).resolve().parents[1] / "static"
    bundle = render(static_root)
    target = static_root / "app.css"
    check = "--check" in sys.argv
    current = target.read_text(encoding="utf-8") if target.exists() else ""
    if check:
        if current != bundle:
            print("app.css 與原始檔不同步，請執行 python3 scripts/build_css.py")
            return 1
        print("app.css 同步")
        return 0
    target.write_text(bundle, encoding="utf-8")
    print(f"已產生 {target} （{len(bundle)} bytes，來源 {len(SOURCES)} 檔）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
