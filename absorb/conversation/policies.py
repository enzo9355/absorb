import re

from absorb.conversation.errors import InputRejected


MAX_QUESTION_CHARS = 1200
MAX_TOOL_CALLS = 4
MAX_TOOL_RESULT_BYTES = 16_384
TOOL_TIMEOUT_SECONDS = 6.0

_INJECTION = re.compile(
    r"(?:忽略|無視).{0,12}(?:之前|系統|指令)|"
    r"(?:顯示|輸出|洩漏).{0,12}(?:system prompt|系統提示|密鑰|secret)|"
    r"(?:讀取|列出).{0,12}(?:所有使用者|Firestore|GCS|環境變數)|"
    r"ignore\s+(?:all\s+)?previous\s+instructions|"
    r"(?:告訴|提供|顯示|輸出|讀取|取得).{0,12}(?:api[ _-]?key|access[ _-]?token|oauth[ _-]?code|cookie|密碼|金鑰|密鑰|secret)",
    re.IGNORECASE,
)


def validate_question(question: str) -> str:
    if not isinstance(question, str):
        raise InputRejected("問題格式不正確。")
    question = question.strip()
    if not question:
        raise InputRejected("請輸入要研究的問題。")
    if len(question) > MAX_QUESTION_CHARS:
        raise InputRejected(f"問題過長，請縮短至 {MAX_QUESTION_CHARS} 字以內。")
    if any(ord(char) < 32 and char not in "\n\t" for char in question):
        raise InputRejected("問題包含不支援的控制字元。")
    return question


def looks_like_prompt_injection(question: str) -> bool:
    return _INJECTION.search(question) is not None


def contains_prompt_injection(value) -> bool:
    if isinstance(value, str):
        return looks_like_prompt_injection(value)
    if isinstance(value, dict):
        return any(contains_prompt_injection(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_prompt_injection(item) for item in value)
    return False


def is_chase_question(question: str) -> bool:
    return any(
        term in question
        for term in (
            "追高", "可以追", "能追", "適合進場", "還能進場",
            "可以買", "還能買", "等拉回", "位置危險", "是不是太高", "空手可以進",
        )
    )


def is_probability_request(question: str) -> bool:
    return any(
        term in question
        for term in ("上漲機率", "機率幾成", "勝率", "績效", "排行榜", "跟誰最賺", "報酬率保證")
    )


def is_trade_plan_request(question: str) -> bool:
    return any(
        term in question
        for term in ("可以買嗎", "能買嗎", "能不能買", "是否進場", "可否進場", "交易計畫",
                     "進場條件", "失效", "退出條件", "檢查退出", "暫不追價", "等待條件")
    )


def mentions_person_or_holdings(question: str) -> bool:
    lowered = question.lower()
    return any(term in question or term in lowered for term in (
        "pelosi", "佩洛西", "berkshire", "波克夏", "巴菲特", "buffett",
        "交易揭露", "持倉", "13f", "眾議院", "house", "揭露", "大咖", "人物",
    ))


def requires_tool_data(question: str, *, has_context=False) -> bool:
    current_data_terms = (
        "今天", "明天", "昨天", "現在", "最近", "目前", "最新",
        "轉強", "轉弱", "盤勢", "大盤", "預測", "模型準",
        "報告", "自選", "關注", "提醒",
        "可以買", "能買", "買嗎", "進場", "追", "買進",
        "賣出", "賣嗎", "持有", "加碼", "空手",
    )
    return any(term in question for term in current_data_terms) or (
        has_context and any(term in question for term in ("這個機率", "那", "這檔", "第二檔", "第一檔"))
    )
