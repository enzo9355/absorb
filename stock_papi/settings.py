import os


LINE_CHANNEL_ACCESS_TOKEN = (os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()
LINE_CHANNEL_SECRET = (os.getenv("LINE_CHANNEL_SECRET") or "").strip()
FINMIND_USER = (os.getenv("FINMIND_USER") or "").strip()
FINMIND_PASSWORD = (os.getenv("FINMIND_PASSWORD") or "").strip()
GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GCP_PROJECT_ID = (os.getenv("GCP_PROJECT_ID") or "").strip()
LOCAL_HOST = (os.getenv("HOST") or "127.0.0.1").strip()
BROADCAST_TOKEN = (os.getenv("BROADCAST_TOKEN") or "").strip()
ALERT_TASK_TOKEN = (os.getenv("ALERT_TASK_TOKEN") or "").strip()
OPENALICE_API_URL = (os.getenv("OPENALICE_API_URL") or "").strip()
OPENALICE_API_TOKEN = (os.getenv("OPENALICE_API_TOKEN") or "").strip()
MARKETAUX_API_TOKEN = (os.getenv("MARKETAUX_API_TOKEN") or "").strip()
QUANT_SNAPSHOT_BUCKET = (os.getenv("QUANT_SNAPSHOT_BUCKET") or "").strip()
SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip()
SUPABASE_KEY = (os.getenv("SUPABASE_KEY") or "").strip()

SENTIMENT_WINDOW_DAYS = 30
REPORT_PDF_MAX_BYTES = 15 * 1024 * 1024
REPORT_INDEX_MAX_BYTES = 1024 * 1024
LINE_STATE_READ_BUDGET_SECONDS = 0.25
LINE_STATE_READ_MAX_WORKERS = 4
