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


def _dashed_line(draw, start, end, fill, width=4, dash=24, gap=16):
    x1, y1 = start
    x2, y2 = end
    if x1 == x2:
        for y in range(y1, y2, dash + gap):
            draw.line((x1, y, x2, min(y + dash, y2)), fill=fill, width=width)
    else:
        for x in range(x1, x2, dash + gap):
            draw.line((x, y1, min(x + dash, x2), y2), fill=fill, width=width)


def draw_menu(path, font_path, serif_font_path=None):
    font_path = Path(font_path)
    if not font_path.is_file():
        raise SystemExit(f"font missing: {font_path}")
    serif_font_path = Path(serif_font_path) if serif_font_path else None
    if not serif_font_path or not serif_font_path.is_file():
        serif_font_path = font_path

    width, height = 2500, 1686
    paper = "#F0ECE3"
    ink = "#17151A"
    brick = "#8A2F18"
    rule = "#8A8377"
    image = Image.new("RGB", (width, height), paper)
    draw = ImageDraw.Draw(image)

    font_label = ImageFont.truetype(str(serif_font_path), 116)
    font_hint = ImageFont.truetype(str(font_path), 34)
    font_code = ImageFont.truetype(str(font_path), 42)

    tiles = [
        (0, 0, 833, 843, "01", "看大盤", "市場報酬、廣度與風險"),
        (833, 0, 834, 843, "02", "看產業", "實際報酬與市場廣度"),
        (1667, 0, 833, 843, "03", "查自選", "你的關注清單"),
        (0, 843, 833, 843, "04", "設提醒", "價格與趨勢通知"),
        (833, 843, 834, 843, "05", "查股票", "價格、均線與風險事件"),
        (1667, 843, 833, 843, "06", "市場觀察", "完整市場與事件頁面"),
    ]
    draw.rectangle((0, 0, width, 14), fill=ink)
    draw.rectangle((1667, 14, width, 843), fill=ink)
    for x, y, tile_width, tile_height, code, label, hint in tiles:
        selected = code == "03"
        fill = ink if selected else paper
        text_color = paper if selected else ink
        eyebrow_color = paper if selected else brick
        draw.rectangle((x, y, x + tile_width - 1, y + tile_height - 1), fill=fill)
        draw.text((x + 64, y + 76), code, font=font_code, fill=eyebrow_color)
        draw.text((x + 64, y + 270), label, font=font_label, fill=text_color)
        draw.text((x + 64, y + 520), hint, font=font_hint, fill=text_color)

    _dashed_line(draw, (833, 14), (833, height), rule)
    _dashed_line(draw, (1667, 14), (1667, height), rule)
    _dashed_line(draw, (0, 843), (width, 843), rule)

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
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="line-stock-bot-498908")
    parser.add_argument("--region", default="asia-east1")
    parser.add_argument("--service", default="line-stock-bot")
    parser.add_argument("--base-url")
    parser.add_argument("--font", type=Path, default=root / "taipei_sans.ttf")
    parser.add_argument(
        "--serif-font",
        type=Path,
        default=root / "assets" / "fonts" / "NotoSerifTC-Black.otf",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    png = root / "assets" / "rich-menu.png"
    draw_menu(png, args.font, args.serif_font)

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
