import base64
import json
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


POWERSHELL = shutil.which("powershell.exe")


@unittest.skipUnless(POWERSHELL, "Windows PowerShell 5.1 is required")
class NativeProcessWrapperTests(unittest.TestCase):
    @staticmethod
    def helper_path():
        return (
            Path(__file__).parents[1] / "scripts" / "native_process.ps1"
        ).resolve()

    def write_harness(self, root, lines):
        harness = root / "harness.ps1"
        harness.write_text(
            "\n".join(
                (
                    "$ErrorActionPreference = 'Stop'",
                    "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)",
                    f". '{str(self.helper_path()).replace(chr(39), chr(39) * 2)}'",
                    *lines,
                )
            ),
            encoding="utf-8-sig",
        )
        return harness

    def run_powershell(self, harness):
        return subprocess.run(
            [
                POWERSHELL,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(harness),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def run_helper(
        self,
        command_body,
        *,
        allow_failure,
        max_output_chars=None,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = root / "fake-native.cmd"
            command.write_text(
                "@echo off\r\n" + command_body,
                encoding="ascii",
            )
            allow = " -AllowFailure" if allow_failure else ""
            maximum = (
                f" -MaxOutputChars {max_output_chars}"
                if max_output_chars is not None
                else ""
            )
            harness = self.write_harness(
                root,
                (
                    "$result = Invoke-NativeProcessCaptured "
                    f"-FilePath '{str(command).replace(chr(39), chr(39) * 2)}' "
                    f"-Arguments @(){maximum}{allow}",
                    "$result | ConvertTo-Json -Compress",
                ),
            )
            return self.run_powershell(harness)

    def redact(self, text):
        encoded = base64.b64encode(text.encode()).decode("ascii")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = self.write_harness(
                root,
                (
                    "$text = [Text.Encoding]::UTF8.GetString("
                    f"[Convert]::FromBase64String('{encoded}'))",
                    "Protect-NativeProcessText $text | ConvertTo-Json -Compress",
                ),
            )
            result = self.run_powershell(harness)
        self.last_redact_process = result
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def run_streaming(self, command_body, *, allow_failure, tail_line_count=20):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        command = root / "fake-native.cmd"
        command.write_text("@echo off\r\n" + command_body, encoding="ascii")
        log = root / "stream.log"
        allow = " -AllowFailure" if allow_failure else ""
        harness = self.write_harness(
            root,
            (
                "$result = Invoke-NativeProcessStreaming "
                f"-FilePath '{str(command).replace(chr(39), chr(39) * 2)}' "
                f"-Arguments @() -LogPath '{str(log).replace(chr(39), chr(39) * 2)}' "
                f"-TailLineCount {tail_line_count}{allow}",
                "$result | ConvertTo-Json -Compress",
            ),
        )
        return self.run_powershell(harness), log

    def test_redacts_supported_secret_formats_without_masking_normal_words(self):
        secret = "s3cr3t-" + "value"
        cases = (
            f"Authorization: Bearer {secret}",
            f'"authorization": "Bearer {secret}"',
            f"token={secret}",
            f"token: '{secret}'",
            f'"token":"{secret}"',
            f'"token": "{secret}"',
            "pass" + f"word={secret}",
            '"pass' + f'word":"{secret}"',
            f"cookie={secret}",
            f"secret={secret}",
            f"--token {secret}",
            "--pass" + f'word "{secret}"',
            f"--authorization '{secret}'",
            f"--cookie {secret}",
            f"--secret {secret}",
            f"https://example.invalid/data?token={secret}",
            f"https://example.invalid/data?ok=1&token={secret}",
        )

        for value in cases:
            with self.subTest(value=value.split(secret)[0]):
                redacted = self.redact(value)
                self.assertIn("[REDACTED]", redacted)
                self.assertNotIn(secret, redacted)

        self.assertEqual(self.redact("token_count=42"), "token_count=42")

    def test_redaction_truncates_pathologically_long_lines(self):
        redacted = self.redact("prefix " + ("x" * 20000))

        self.assertLessEqual(len(redacted), 16400)
        self.assertTrue(redacted.endswith("[TRUNCATED]"))

        secret = "y" * 20000
        redacted_secret = self.redact("token=" + secret)
        self.assertEqual(redacted_secret, "token=[REDACTED][TRUNCATED]")
        self.assertNotIn("y" * 100, redacted_secret)

    def test_redacts_composite_authorization_cookie_and_prefixed_keys(self):
        access_key = "AK" + "IAFAKEACCESS1234"
        signature = "sigv4-" + "credential"
        nonce = "digest-" + "nonce"
        response = "digest-" + "response"
        custom_key = "custom-" + "key"
        custom_second = "custom-" + "second"
        cookie = "session-" + "credential"
        csrf = "csrf-" + "credential"
        prefixed = "prefixed-" + "credential"
        cases = (
            (
                "aws_sigv4_header",
                "Authorization: AWS4-HMAC-SHA256 "
                f"Credential={access_key},SignedHeaders=host,"
                f"Signature={signature}",
                (access_key, signature),
            ),
            (
                "digest_header",
                'Authorization: Digest username="user", realm="x", '
                f'nonce="{nonce}", response="{response}"',
                (nonce, response),
            ),
            (
                "custom_header",
                f"Authorization: Custom key={custom_key}; second={custom_second}",
                (custom_key, custom_second),
            ),
            (
                "quoted_json_authorization",
                '"authorization": '
                f'"Custom key={custom_key}, second={custom_second}"',
                (custom_key, custom_second),
            ),
            (
                "prefixed_authorization_environment",
                "SERVICE_"
                "AUTHORIZATION=AWS4-HMAC-SHA256 "
                f"Credential={access_key},Signature={signature}",
                (access_key, signature),
            ),
            (
                "aws_sigv4_cli",
                "--authorization AWS4-HMAC-SHA256 "
                f"Credential={access_key},Signature={signature}",
                (access_key, signature),
            ),
            (
                "digest_cli",
                f'--authorization "Digest username=x, nonce={nonce}"',
                (nonce,),
            ),
            (
                "composite_cookie_cli",
                f"--cookie session={cookie}; csrf={csrf}",
                (cookie, csrf),
            ),
            (
                "quoted_composite_cookie_cli",
                f'--cookie "session={cookie}; csrf={csrf}"',
                (cookie, csrf),
            ),
            ("basic_header", f"Authorization: Basic {prefixed}", (prefixed,)),
            ("api_key_header", f"Authorization: ApiKey {prefixed}", (prefixed,)),
            ("basic_cli", f"--authorization Basic {prefixed}", (prefixed,)),
            (
                "quoted_basic_cli",
                f'--authorization "Basic {prefixed}"',
                (prefixed,),
            ),
            (
                "cookie_header",
                f"Cookie: session={cookie}; csrf={csrf}",
                (cookie, csrf),
            ),
            ("finmind_token", "FINMIND_" + f"TOKEN={prefixed}", (prefixed,)),
            (
                "line_channel_secret",
                "LINE_CHANNEL_" + f"SECRET={prefixed}",
                (prefixed,),
            ),
            (
                "service_password",
                "SERVICE_PASS" + f"WORD={prefixed}",
                (prefixed,),
            ),
            ("access_token", "ACCESS_" + f"TOKEN={prefixed}", (prefixed,)),
            ("client_secret", "CLIENT_" + f"SECRET={prefixed}", (prefixed,)),
            ("api_key", "API_" + f"KEY={prefixed}", (prefixed,)),
            (
                "service_cookie",
                "SERVICE_" + f"COOKIE={prefixed}",
                (prefixed,),
            ),
            (
                "service_authorization",
                "SERVICE_" + f"AUTHORIZATION=Basic {prefixed}",
                (prefixed,),
            ),
            (
                "service_api_key",
                "SERVICE_" + f"API_KEY={prefixed}",
                (prefixed,),
            ),
        )

        for label, value, secrets in cases:
            with self.subTest(label=label, surface="return"):
                redacted = self.redact(value)
                combined = (
                    redacted
                    + self.last_redact_process.stdout
                    + self.last_redact_process.stderr
                )
                self.assertIn("[REDACTED]", redacted)
                for original in secrets:
                    self.assertNotIn(original, combined)

        command_body = "".join(
            f"echo({value}\r\n>&2 echo({value}\r\n"
            for _, value, _ in cases
        ) + "exit /b 0\r\n"
        captured = self.run_helper(command_body, allow_failure=False)
        self.assertEqual(captured.returncode, 0, captured.stderr)
        captured_combined = captured.stdout + captured.stderr
        self.assertGreaterEqual(
            captured_combined.count("[REDACTED]"),
            len(cases) * 2,
        )
        for label, _, secrets in cases:
            with self.subTest(label=label, surface="stdout_stderr"):
                for original in secrets:
                    self.assertNotIn(original, captured_combined)

        for ordinary in (
            "token_count=42",
            "secret_count=3",
            "client_secret_count=7",
        ):
            with self.subTest(ordinary=ordinary):
                self.assertEqual(self.redact(ordinary), ordinary)

        failing_command_body = "".join(
            f"echo({value}\r\n>&2 echo({value}\r\n"
            for _, value, _ in cases
        ) + "exit /b 7\r\n"
        failed, log = self.run_streaming(
            failing_command_body,
            allow_failure=False,
            tail_line_count=len(cases) * 2,
        )
        self.assertNotEqual(failed.returncode, 0)
        combined = (
            failed.stdout
            + failed.stderr
            + log.read_text(encoding="utf-8-sig", errors="replace")
        )
        self.assertIn("exit code 7", failed.stdout + failed.stderr)
        self.assertGreaterEqual(combined.count("[REDACTED]"), len(cases) * 2)
        for label, _, secrets in cases:
            with self.subTest(label=label, surface="stream_log_exception"):
                for original in secrets:
                    self.assertNotIn(original, combined)

    def test_stderr_progress_with_zero_exit_is_success_and_redacted(self):
        result = self.run_helper(
            ">&2 echo Copying object token=live-secret\r\nexit /b 0\r\n",
            allow_failure=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(document["exit_code"], 0)
        self.assertIn("Copying object", document["text"])
        self.assertIn("[REDACTED]", document["text"])
        self.assertNotIn("live-secret", result.stdout + result.stderr)

    def test_captured_output_limit_is_bounded_at_line_boundary(self):
        result = self.run_helper(
            f"echo {'x' * 1023}\r\necho second-line\r\nexit /b 0\r\n",
            allow_failure=False,
            max_output_chars=1024,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertLessEqual(len(document["text"]), 1035)
        self.assertTrue(document["text"].endswith("[TRUNCATED]"))

    def test_nonzero_exit_is_failure_and_retains_redacted_stderr(self):
        sensitive_text = "pass" + "word=live-secret"
        captured = self.run_helper(
            f">&2 echo fatal {sensitive_text}\r\nexit /b 7\r\n",
            allow_failure=True,
        )

        self.assertEqual(captured.returncode, 0, captured.stderr)
        document = json.loads(captured.stdout.strip().splitlines()[-1])
        self.assertEqual(document["exit_code"], 7)
        self.assertIn("fatal", document["text"])
        self.assertIn("[REDACTED]", document["text"])
        self.assertNotIn("live-secret", captured.stdout + captured.stderr)

        failed = self.run_helper(
            f">&2 echo fatal {sensitive_text}\r\nexit /b 7\r\n",
            allow_failure=False,
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("exit code 7", failed.stdout + failed.stderr)
        self.assertNotIn("live-secret", failed.stdout + failed.stderr)

    def test_streaming_writes_redacted_output_before_process_exit(self):
        secret = "stream-" + "secret"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = root / "fake-native.cmd"
            command.write_text(
                "@echo off\r\n"
                f"echo first token={secret}\r\n"
                "ping -n 4 127.0.0.1 >nul\r\n"
                ">&2 echo progress\r\n"
                "exit /b 0\r\n",
                encoding="ascii",
            )
            log = root / "stream.log"
            harness = self.write_harness(
                root,
                (
                    "$result = Invoke-NativeProcessStreaming "
                    f"-FilePath '{str(command).replace(chr(39), chr(39) * 2)}' "
                    f"-Arguments @() -LogPath '{str(log).replace(chr(39), chr(39) * 2)}'",
                    "$result | ConvertTo-Json -Compress",
                ),
            )
            process = subprocess.Popen(
                [
                    POWERSHELL,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(harness),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if log.exists() and "first" in log.read_text(
                    encoding="utf-8-sig", errors="replace"
                ):
                    break
                time.sleep(0.05)
            else:
                process.kill()
                process.communicate()
                self.fail("streaming log did not receive the first line")

            self.assertIsNone(process.poll(), "child finished before log was updated")
            stdout, stderr = process.communicate(timeout=10)
            logged = log.read_text(encoding="utf-8-sig", errors="replace")

        self.assertEqual(process.returncode, 0, stderr)
        document = json.loads(stdout.strip().splitlines()[-1])
        self.assertEqual(document["exit_code"], 0)
        self.assertIn("first", logged)
        self.assertIn("progress", logged)
        self.assertIn("[REDACTED]", logged)
        self.assertNotIn(secret, logged + stdout + stderr)

    def test_streaming_nonzero_exit_is_failure_and_keeps_exit_code(self):
        secret = "stream-" + "secret"
        captured, log = self.run_streaming(
            f">&2 echo fatal --password {secret}\r\nexit /b 7\r\n",
            allow_failure=True,
        )

        self.assertEqual(captured.returncode, 0, captured.stderr)
        document = json.loads(captured.stdout.strip().splitlines()[-1])
        self.assertEqual(document["exit_code"], 7)
        self.assertIn("fatal", document["text"])
        self.assertNotIn(secret, log.read_text(encoding="utf-8-sig"))

        failed, _ = self.run_streaming(
            f">&2 echo fatal --password {secret}\r\nexit /b 7\r\n",
            allow_failure=False,
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("exit code 7", failed.stdout + failed.stderr)
        self.assertNotIn(secret, failed.stdout + failed.stderr)

    def test_streaming_keeps_only_a_bounded_tail_in_memory(self):
        secret = "stream-" + "secret"
        result, log = self.run_streaming(
            f"for /L %%i in (1,1,200) do @echo line %%i token={secret}\r\n"
            "exit /b 0\r\n",
            allow_failure=False,
            tail_line_count=5,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertLessEqual(len(document["text"].splitlines()), 5)
        self.assertIn("line 200", document["text"])
        logged = log.read_text(encoding="utf-8-sig")
        self.assertIn("line 1", logged)
        self.assertIn("line 200", logged)
        self.assertNotIn(secret, logged + result.stdout + result.stderr)

    def test_streaming_reports_start_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "stream.log"
            harness = self.write_harness(
                root,
                (
                    "Invoke-NativeProcessStreaming "
                    "-FilePath 'Z:\\missing\\native-command.exe' "
                    f"-LogPath '{str(log).replace(chr(39), chr(39) * 2)}'",
                ),
            )
            result = self.run_powershell(harness)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Native process start failed", result.stdout + result.stderr)

    def test_streaming_reports_log_write_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = root / "fake-native.cmd"
            command.write_text("@echo off\r\necho line\r\nexit /b 0\r\n", encoding="ascii")
            harness = self.write_harness(
                root,
                (
                    "Invoke-NativeProcessStreaming "
                    f"-FilePath '{str(command).replace(chr(39), chr(39) * 2)}' "
                    f"-LogPath '{str(root).replace(chr(39), chr(39) * 2)}'",
                ),
            )
            result = self.run_powershell(harness)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Native process log write failed", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
