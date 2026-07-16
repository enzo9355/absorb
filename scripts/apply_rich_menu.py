import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def cloud_run_info(project, region, service):
    raw = subprocess.check_output(
        [
            "gcloud",
            "run",
            "services",
            "describe",
            service,
            "--region",
            region,
            "--project",
            project,
            "--format",
            "json",
        ],
        text=True,
    )
    payload = json.loads(raw)
    envs = {
        item.get("name"): item.get("value")
        for item in payload["spec"]["template"]["spec"]["containers"][0].get("env", [])
    }
    return payload["status"]["url"].rstrip("/"), envs


def draw_menu(path, font_path, logo_path):
    width, height = 2500, 1686
    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)

    font_brand = ImageFont.truetype(str(font_path), 56)
    font_label = ImageFont.truetype(str(font_path), 140)
    font_hint = ImageFont.truetype(str(font_path), 46)
    font_code = ImageFont.truetype(str(font_path), 82)
    logo = Image.open(logo_path).convert("RGB").resize((88, 88), Image.Resampling.LANCZOS)
    image.paste(logo, (42, 12))
    draw.text((150, 24), "ABSORB", font=font_brand, fill="#122643")

    tiles = [
        (42, 132, "01", "看大盤", "市場報酬、廣度與風險"),
        (852, 132, "02", "看產業", "實際報酬與市場廣度"),
        (1662, 132, "03", "查自選", "你的關注清單"),
        (42, 884, "04", "設提醒", "價格與趨勢通知"),
        (852, 884, "05", "查股票", "價格、均線與風險事件"),
        (1662, 884, "06", "市場觀察", "完整市場與事件頁面"),
    ]
    for x, y, code, label, hint in tiles:
        draw.rounded_rectangle(
            [x, y, x + 790, y + 710],
            radius=46,
            fill="#ffffff" if code in {"01", "03", "05"} else "#eaf0f7",
            outline="#d9e0e8",
            width=5,
        )
        draw.rounded_rectangle(
            [x + 42, y + 92, x + 180, y + 200],
            radius=32,
            fill="#122643",
            outline="#122643",
            width=4,
        )
        draw.text((x + 68, y + 103), code, font=font_code, fill="#ffffff")
        draw.text((x + 84, y + 290), label, font=font_label, fill="#152033")
        draw.text((x + 84, y + 520), hint, font=font_hint, fill="#586579")

    image.save(path, "PNG", optimize=True)


def line_request(method, url, token, body=None, content_type="application/json"):
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise SystemExit(f"LINE API failed: {method} {url} {error.code} {detail}") from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="line-stock-bot-498908")
    parser.add_argument("--region", default="asia-east1")
    parser.add_argument("--service", default="line-stock-bot")
    parser.add_argument("--base-url")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    png = root / "assets" / "rich-menu.png"
    draw_menu(png, root / "taipei_sans.ttf", root / "static" / "brand" / "absorb-mark-128.png")

    if args.base_url:
        base_url, envs = args.base_url.rstrip("/"), {}
    else:
        base_url, envs = cloud_run_info(args.project, args.region, args.service)

    if args.dry_run:
        print(f"png={png} bytes={png.stat().st_size}")
        print(f"baseUrl={base_url}")
        print("dryRun=True")
        return

    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or envs.get("LINE_CHANNEL_ACCESS_TOKEN") or ""
    token = token.strip()
    if not token:
        raise SystemExit("LINE_CHANNEL_ACCESS_TOKEN missing")

    areas = [
        (0, 0, 833, 843, {"type": "uri", "uri": f"{base_url}/market"}),
        (833, 0, 834, 843, {"type": "uri", "uri": f"{base_url}/market-map"}),
        (1667, 0, 833, 843, {"type": "message", "text": "我的關注"}),
        (0, 843, 833, 843, {"type": "message", "text": "提醒管理"}),
        (833, 843, 834, 843, {"type": "message", "text": "2330"}),
        (1667, 843, 833, 843, {"type": "uri", "uri": f"{base_url}/dashboard"}),
    ]
    payload = {
        "size": {"width": 2500, "height": 1686},
        "selected": True,
        "name": "ABSORB main menu",
        "chatBarText": "ABSORB",
        "areas": [
            {"bounds": {"x": x, "y": y, "width": w, "height": h}, "action": action}
            for x, y, w, h, action in areas
        ],
    }

    _, content = line_request("POST", "https://api.line.me/v2/bot/richmenu", token, payload)
    rich_menu_id = json.loads(content)["richMenuId"]
    line_request(
        "POST",
        f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content",
        token,
        png.read_bytes(),
        "image/png",
    )
    line_request("POST", f"https://api.line.me/v2/bot/user/all/richmenu/{rich_menu_id}", token)
    _, current = line_request("GET", "https://api.line.me/v2/bot/user/all/richmenu", token)
    default_id = json.loads(current).get("richMenuId")

    print(f"png={png} bytes={png.stat().st_size}")
    print(f"richMenuId={rich_menu_id}")
    print(f"defaultRichMenuId={default_id}")
    print(f"defaultSet={default_id == rich_menu_id}")


if __name__ == "__main__":
    main()
