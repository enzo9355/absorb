import os
import json
import hashlib
import subprocess
import sys
from pathlib import Path
import datetime
import requests

root = r"D:\StockPapiData"
bucket = "line-stock-bot-498908-quant-snapshots"
publish_root = Path(root) / "publish" / "quant" / "v1"
ADMIN_USER_ID = "U72f8c70881c4107fd03e506e97d3b75d"
PROJECT_ID = "line-stock-bot-498908"

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def get_clean_env():
    env = os.environ.copy()
    if "PYTHONPATH" in env:
        del env["PYTHONPATH"]
    return env

def get_line_token():
    cmd = [
        "gcloud.cmd", "secrets", "versions", "access", "latest",
        "--secret=stock-papi-line-channel-access-token", f"--project={PROJECT_ID}"
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=get_clean_env(), check=True)
        return res.stdout.decode("utf-8").strip()
    except Exception as e:
        print(f"Failed to fetch LINE token from Secret Manager: {e}")
        return None

def send_line_notification(message):
    token = get_line_token()
    if not token:
        print("Cannot send LINE notification: Token unavailable.")
        return
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    payload = {
        "to": ADMIN_USER_ID,
        "messages": [{"type": "text", "text": message}]
    }
    try:
        res = requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=payload)
        if res.status_code != 200:
            print(f"LINE API error: {res.status_code} - {res.text}")
        else:
            print("LINE notification sent successfully.")
    except Exception as e:
        print(f"Failed to send LINE notification: {e}")

def upload_file(source, destination, no_clobber=False):
    cmd = ["gcloud.cmd", "storage", "cp", "--quiet"]
    if no_clobber:
        cmd.append("--no-clobber")
    cmd.extend([str(source), destination])
    print(f"Uploading {source.name} -> {destination}...")
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=get_clean_env())
    if res.returncode != 0:
        err_msg = res.stderr.decode('utf-8', errors='ignore')
        print(f"Upload failed: {err_msg}")
        raise RuntimeError(f"Failed to upload {source.name}: {err_msg}")

def main():
    try:
        print("Starting python snapshot uploader...")
        insights_uploaded = False
        
        # 1. Upload Insights
        insights_latest = publish_root / "latest-insights.json"
        if insights_latest.is_file():
            with open(insights_latest, "r", encoding="utf-8") as f:
                insights = json.load(f)
            if insights.get("schema_version") == 1 and insights.get("kind") == "market-insights":
                obj_rel = insights["path"]
                obj_path = publish_root / obj_rel
                if obj_path.is_file():
                    if obj_path.stat().st_size == insights["size"] and sha256_file(obj_path) == insights["sha256"]:
                        upload_file(obj_path, f"gs://{bucket}/quant/v1/{obj_rel}", no_clobber=True)
                        upload_file(insights_latest, f"gs://{bucket}/quant/v1/latest-insights.json")
                        insights_uploaded = True
                        print("Insights uploaded successfully.")
                    else:
                        raise ValueError("Insights object validation failed (size/hash mismatch).")
                else:
                    raise FileNotFoundError("Insights object file missing.")
        
        # 2. Upload Markets (TW, US)
        uploaded_markets = []
        tw_stats = ""
        for market in ("TW", "US"):
            latest_path = publish_root / f"latest-{market}.json"
            if not latest_path.is_file():
                print(f"latest-{market}.json not found. Skipping.")
                continue
            
            with open(latest_path, "r", encoding="utf-8") as f:
                latest = json.load(f)
            
            if latest.get("schema_version") != 2 or latest.get("market") != market:
                raise ValueError(f"Invalid latest pointer for {market}")
            
            manifest_rel = latest["manifest"]
            manifest_path = publish_root / manifest_rel
            if not manifest_path.is_file():
                raise FileNotFoundError(f"Manifest file missing for {market}: {manifest_rel}")
            
            if sha256_file(manifest_path) != latest["manifest_sha256"]:
                raise ValueError(f"Manifest hash mismatch for {market}")
            
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
                
            if manifest.get("schema_version") != 2 or manifest.get("market") != market:
                raise ValueError(f"Invalid manifest schema/market for {market}")
            
            print(f"Validating objects for {market}...")
            valid_objs = []
            for symbol, entry in manifest["symbols"].items():
                obj_rel = entry["path"]
                obj_path = publish_root / obj_rel
                if not obj_path.is_file():
                    raise FileNotFoundError(f"Object missing: {obj_rel}")
                if obj_path.stat().st_size != entry["size"]:
                    raise ValueError(f"Object size mismatch: {obj_rel}")
                if sha256_file(obj_path) != entry["sha256"]:
                    raise ValueError(f"Object hash mismatch: {obj_rel}")
                valid_objs.append((obj_path, obj_rel))
            
            # Upload TW / US objects in batches of 50
            batch_size = 50
            for i in range(0, len(valid_objs), batch_size):
                batch = valid_objs[i:i+batch_size]
                cmd = ["gcloud.cmd", "storage", "cp", "--quiet", "--no-clobber"]
                for obj_path, _ in batch:
                    cmd.append(str(obj_path))
                cmd.append(f"gs://{bucket}/quant/v1/objects/")
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=get_clean_env())
                if res.returncode != 0:
                    raise RuntimeError(f"Batch upload failed for {market}: {res.stderr.decode('utf-8', errors='ignore')}")
            
            # Upload manifest and latest pointer
            upload_file(manifest_path, f"gs://{bucket}/quant/v1/{manifest_rel}", no_clobber=True)
            upload_file(latest_path, f"gs://{bucket}/quant/v1/latest-{market}.json")
            uploaded_markets.append(market)
            
            # Save stats for notification
            if market == "TW":
                tw_stats = f"TW 市場: {manifest['symbol_count']} 個股 (失敗: {manifest['failure_count']})\n資料日期 (as_of): {manifest['market_as_of']}"
            print(f"Market {market} uploaded successfully.")
            
        # 3. Write status log
        status = {
            "uploaded_at": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
            "markets": uploaded_markets,
            "market_insights": insights_uploaded,
            "bucket": bucket
        }
        status_path = Path(root) / "logs" / "upload-status.json"
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, separators=(",", ":"))
        
        # 4. Send Success LINE Notification
        msg = f"📊 Stock-Papi 數據自動上傳成功！\n\n{tw_stats}\nInsights 上傳: {'是' if insights_uploaded else '否'}\n上傳時間: {datetime.datetime.now(datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')}"
        send_line_notification(msg)
        print("Upload completed successfully!")
        
    except Exception as exc:
        msg = f"🚨 Stock-Papi 數據自動上傳失敗！\n\n錯誤原因: {str(exc)}\n時間: {datetime.datetime.now(datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')}"
        send_line_notification(msg)
        print(f"Upload failed: {exc}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
