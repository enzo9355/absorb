"""自動部署流程的判斷邏輯（scripts/ci/）。

這些函式決定「要不要把流量切到新版」。它們判斷錯的代價是把設定錯誤的
revision 推上線，所以這裡守的是 fail-closed：任何無法確定的情況都必須
當成不通過，而不是放行。

最重要的一條是 test_ci_gate_matches_the_powershell_gate ——
CI 與 PowerShell 是同一個服務的兩條上線路徑，環境變數檢查一旦分岔，
就會出現「PowerShell 擋得住、CI 擋不住」的破口，而且沒人會發現，
因為兩邊各自都是綠的。
"""

import json
import re
import unittest
from pathlib import Path

from scripts.ci.cloud_run import (
    FORBIDDEN_ENVIRONMENT,
    REQUIRED_ENVIRONMENT,
    assert_env,
    serving,
    tag_url,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy_observation_production.ps1"


def _revision(environment):
    return {"spec": {"containers": [{"env": [
        {"name": name, "value": value} for name, value in environment.items()
    ]}]}}


def _valid_environment():
    return dict(REQUIRED_ENVIRONMENT)


class CiGateMatchesPowerShellTests(unittest.TestCase):
    def test_ci_gate_matches_the_powershell_gate(self):
        """兩條上線路徑的環境變數檢查必須逐字相同。

        PowerShell 那支是原本唯一的上線路徑，它的 Assert-ObservationEnvironment
        是既有事實；CI 是後來加的，所以以 PowerShell 為準。
        任何一邊加了旗標而另一邊沒加，這條就紅。
        """
        source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
        block = re.search(
            r"\$Expected = \[ordered\]@\{(.*?)\}", source, re.DOTALL
        )
        self.assertIsNotNone(block, "找不到 PowerShell 的 $Expected 區塊")
        declared = dict(
            re.findall(r"(\w+)\s*=\s*'([^']*)'", block.group(1))
        )
        self.assertEqual(
            declared, REQUIRED_ENVIRONMENT,
            "CI 與 PowerShell 的必要環境變數不一致 —— 兩邊都要改",
        )

        prefixes = re.search(
            r"foreach \(\$PrefixName in @\((.*?)\)\)", source, re.DOTALL
        )
        self.assertIsNotNone(prefixes, "找不到 PowerShell 的 preview prefix 清單")
        self.assertEqual(
            set(re.findall(r"'([^']+)'", prefixes.group(1))),
            set(FORBIDDEN_ENVIRONMENT),
            "CI 與 PowerShell 的 preview prefix 禁用清單不一致",
        )


class AssertEnvironmentTests(unittest.TestCase):
    def test_a_correct_revision_passes(self):
        assert_env(_revision(_valid_environment()))

    def test_every_required_flag_is_actually_checked(self):
        """逐一把每個旗標改錯，每一個都必須被擋下來。

        只測「全對會過」會讓漏檢查某個旗標的實作也通過。
        """
        for name in REQUIRED_ENVIRONMENT:
            with self.subTest(flag=name):
                environment = _valid_environment()
                environment[name] = "wrong"
                with self.assertRaises(SystemExit) as caught:
                    assert_env(_revision(environment))
                self.assertIn(name, str(caught.exception))

    def test_a_missing_flag_is_rejected(self):
        for name in REQUIRED_ENVIRONMENT:
            with self.subTest(flag=name):
                environment = _valid_environment()
                del environment[name]
                with self.assertRaises(SystemExit):
                    assert_env(_revision(environment))

    def test_preview_prefix_blocks_promotion(self):
        for name in FORBIDDEN_ENVIRONMENT:
            with self.subTest(prefix=name):
                environment = _valid_environment()
                environment[name] = "previews/whatever"
                with self.assertRaises(SystemExit) as caught:
                    assert_env(_revision(environment))
                self.assertIn(name, str(caught.exception))

    def test_a_flag_sourced_from_a_secret_is_not_accepted_as_correct(self):
        """值來自 secretKeyRef 時沒有字面 value，不能當成通過。"""
        revision = _revision(_valid_environment())
        for item in revision["spec"]["containers"][0]["env"]:
            if item["name"] == "ABSORB_PREDICTION_MODE":
                del item["value"]
                item["valueFrom"] = {"secretKeyRef": {"name": "x", "key": "y"}}
        with self.assertRaises(SystemExit):
            assert_env(revision)

    def test_a_revision_without_containers_is_rejected(self):
        with self.assertRaises(SystemExit):
            assert_env({"spec": {"containers": []}})


class RollbackTargetTests(unittest.TestCase):
    def test_the_single_full_traffic_revision_is_the_rollback_target(self):
        service = {"status": {"traffic": [
            {"revisionName": "rev-a", "percent": 100},
            {"revisionName": "rev-b", "percent": 0, "tag": "ci-abc"},
        ]}}
        self.assertEqual(serving(service), "rev-a")

    def test_a_split_or_absent_assignment_yields_no_rollback_target(self):
        """流量不是單一 revision 拿滿時，回空字串而不是猜一個。

        猜錯的回滾會把流量送到一個從來沒服務過的 revision。
        呼叫端收到空字串會明說「沒有可回滾的目標」並失敗。
        """
        for traffic in (
            [{"revisionName": "a", "percent": 50},
             {"revisionName": "b", "percent": 50}],
            [],
            [{"revisionName": "a", "percent": 100},
             {"revisionName": "b", "percent": 100}],
        ):
            with self.subTest(traffic=traffic):
                self.assertEqual(serving({"status": {"traffic": traffic}}), "")


class CandidateUrlTests(unittest.TestCase):
    def test_the_tagged_url_is_returned(self):
        service = {"status": {"traffic": [
            {"revisionName": "a", "percent": 100},
            {"revisionName": "b", "percent": 0, "tag": "ci-abc",
             "url": "https://ci-abc---svc.run.app"},
        ]}}
        self.assertEqual(tag_url(service, "ci-abc"), "https://ci-abc---svc.run.app")

    def test_a_missing_tag_fails_rather_than_falling_back(self):
        """找不到候選網址就失敗 —— 退回用正式網址做煙霧測試等於沒測。"""
        service = {"status": {"traffic": [
            {"revisionName": "a", "percent": 100,
             "url": "https://svc.run.app"},
        ]}}
        with self.assertRaises(SystemExit):
            tag_url(service, "ci-abc")


class SmokeTargetsTests(unittest.TestCase):
    def test_fail_closed_routes_are_not_smoke_tested(self):
        """/reports 與 /us 沒有報告時本來就回 503，不能拿來擋部署。

        把它們列進煙霧測試會讓「今天還沒發報告」變成「不准部署」——
        於是最需要上線的修復反而上不去。
        """
        from scripts.ci.smoke import REQUIRED_OK

        self.assertNotIn("/reports", REQUIRED_OK)
        self.assertNotIn("/us", REQUIRED_OK)
        self.assertIn("/healthz", REQUIRED_OK)
        self.assertIn("/dashboard", REQUIRED_OK)


if __name__ == "__main__":
    unittest.main()
