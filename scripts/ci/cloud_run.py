"""讀 Cloud Run 的 describe JSON，回答部署流程要問的問題。

寫成腳本而不是塞在 YAML 裡的一行 shell，理由有兩個：
一是這些判斷有邏輯（fail-closed 的環境變數檢查尤其），塞在 YAML 裡沒人看得懂
也沒法測；二是可以直接寫測試（tests/test_ci_deploy_helpers.py）。

每個子命令在無法確定答案時都**失敗**，不是回空值 —— 部署流程裡
「不確定」必須當成「不通過」。
"""

import json
import sys


# 與 deploy_observation_production.ps1 的 Assert-ObservationEnvironment 一致。
# 兩邊都改才算改，只改一邊就會出現「PowerShell 擋得住、CI 擋不住」的破口。
REQUIRED_ENVIRONMENT = {
    "ABSORB_PREDICTION_MODE": "research",
    "ABSORB_OBSERVATION_ENABLED": "true",
    "ABSORB_PREDICTION_PROBABILITY_ENABLED": "false",
    "ABSORB_PREDICTION_RANKING_ENABLED": "false",
    "ABSORB_PREDICTION_STRONG_ACTIONS_ENABLED": "false",
    "ABSORB_PREDICTION_PERFORMANCE_ENDORSEMENT_ENABLED": "false",
}
FORBIDDEN_ENVIRONMENT = (
    "ABSORB_PREVIEW_CANDIDATE_PREFIX",
    "PREVIEW_CANDIDATE_PREFIX",
)


def _load(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def _traffic(service):
    entries = (service.get("status") or {}).get("traffic") or []
    return [entry for entry in entries if isinstance(entry, dict)]


def serving(service):
    """回傳目前收 100% 流量的 revision；沒有明確的單一 revision 就回空字串。

    回空字串是刻意的：呼叫端會把它解讀成「沒有可回滾的目標」，
    那比回一個猜的 revision 安全。
    """
    full = [
        entry.get("revisionName")
        for entry in _traffic(service)
        if entry.get("percent") == 100 and entry.get("revisionName")
    ]
    return full[0] if len(full) == 1 else ""


def latest(service):
    revision = (service.get("status") or {}).get("latestCreatedRevisionName")
    if not revision:
        raise SystemExit("找不到最新建立的 revision")
    return revision


def tag_url(service, tag):
    urls = [
        entry.get("url")
        for entry in _traffic(service)
        if entry.get("tag") == tag and entry.get("url")
    ]
    if len(urls) != 1:
        raise SystemExit(f"找不到 tag {tag} 對應的唯一網址")
    return urls[0]


def service_url(service):
    url = (service.get("status") or {}).get("url")
    if not url:
        raise SystemExit("找不到服務的正式網址")
    return url


def _environment_map(revision):
    containers = (
        ((revision.get("spec") or {}).get("containers")) or []
    )
    if not containers:
        raise SystemExit("revision 沒有容器定義")
    mapping = {}
    for item in containers[0].get("env") or []:
        if not isinstance(item, dict) or "name" not in item:
            continue
        # value 缺席代表值來自 secret/config map —— 當成「不是我們要的字面值」
        mapping[item["name"]] = item.get("value")
    return mapping


def assert_env(revision):
    environment = _environment_map(revision)
    problems = []
    for name, expected in REQUIRED_ENVIRONMENT.items():
        actual = environment.get(name)
        if actual != expected:
            problems.append(f"{name} 應為 {expected!r}，實際是 {actual!r}")
    for name in FORBIDDEN_ENVIRONMENT:
        if name in environment:
            problems.append(f"正式 revision 不得殘留 preview prefix：{name}")
    if problems:
        raise SystemExit(
            "Observation 環境檢查未通過：\n  - " + "\n  - ".join(problems)
        )
    return "Observation 環境檢查通過"


def main(argv):
    if len(argv) < 3:
        raise SystemExit(
            "用法：cloud_run.py "
            "{serving|latest|tag-url|service-url|assert-env} <json> [tag]"
        )
    command, path = argv[1], argv[2]
    document = _load(path)
    if command == "serving":
        print(serving(document))
    elif command == "latest":
        print(latest(document))
    elif command == "tag-url":
        if len(argv) < 4:
            raise SystemExit("tag-url 需要 tag 參數")
        print(tag_url(document, argv[3]))
    elif command == "service-url":
        print(service_url(document))
    elif command == "assert-env":
        print(assert_env(document))
    else:
        raise SystemExit(f"未知的子命令：{command}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
