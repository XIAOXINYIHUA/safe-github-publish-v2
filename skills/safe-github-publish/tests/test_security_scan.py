from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "security_scan.py"
SPEC = importlib.util.spec_from_file_location("security_scan", SCRIPT)
assert SPEC and SPEC.loader
security_scan = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = security_scan
SPEC.loader.exec_module(security_scan)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class WorktreeScanTests(unittest.TestCase):
    def test_safe_placeholder_and_example_env_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".env.example").write_text('API_KEY="your-api-key"\n', encoding="utf-8")
            self.assertEqual(security_scan.scan(root)["findings"], [])

    def test_provider_tokens_and_unquoted_assignment_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payloads = [
                "github_" + "pat_" + "A" * 32,
                "glpat-" + "B" * 24,
                "AK" + "IA" + "C" * 16,
                "AIza" + "D" * 35,
                "npm_" + "E" * 36,
                "sk-ant-" + "api-" + "F" * 40,
                "sk-" + "9aBc" * 10,
                "1234567890:AA" + "H" * 33,
                "api_key=" + "S" * 24,
            ]
            (root / "config.txt").write_text("\n".join(payloads), encoding="utf-8")
            rules = {item["rule"] for item in security_scan.scan(root)["findings"]}
            self.assertTrue(
                {
                    "github-token", "gitlab-token", "aws-access-key", "google-api-key",
                    "npm-token", "anthropic-token", "openai-style-token",
                    "telegram-bot-token", "credential-assignment",
                }.issubset(rules)
            )

    def test_prefixed_env_and_quoted_keys_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            value = "Zq8" + "vN3pL7wR2tY6"
            samples = {
                "config.json": '{"api_key": "' + value + '"}',
                "settings.ini": "OPENAI_API_KEY=" + value,
                "docker-compose.yml": "services:\n  db:\n    environment:\n      - MYSQL_ROOT_PASSWORD=" + value,
                "aws.py": 'AWS_SECRET_ACCESS_KEY = "' + value * 2 + '"',
                "db.php": "'password' => '" + value + "'",
                # 前面的界面文案被跳过后，同一行后面的真实值仍要命中
                "minified.json": '{"password": "Enter your password", "api_key": "' + value + '"}',
            }
            for name, content in samples.items():
                (root / name).write_text(content + "\n", encoding="utf-8")
            hits = {(i["path"], i["rule"], i["severity"]) for i in security_scan.scan(root)["findings"]}
            for name in samples:
                self.assertIn((name, "credential-assignment", "high"), hits, name)

    def test_code_expressions_placeholders_and_prose_are_not_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lines = [
                'api_key = os.getenv("API_KEY")',
                'password = os.environ["DB_PASSWORD"]',
                'password = os.environ.get("DB_PASSWORD", "")',
                "    password: Optional[str] = None",
                "  password: process.env.DB_PASSWORD,",
                "  apiKey: process.env.API_KEY!,",
                'password = request.form["password"]',
                "PASSWORD=$DB_PASSWORD",
                '"password": "Enter your password",',
                '"forgot_password": "忘记密码了吗请点击这里",',
                "DATABASE_URL=postgres://app:${DB_PASS}@db:5432/app",
                'SECRET = "github_" + "pat_" + "R" * 32',
            ]
            (root / "app.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertEqual(security_scan.scan(root)["findings"], [])

    def test_unquoted_values_in_source_code_are_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "client.py").write_text(
                "payload = {'password': password, 'secretKey': secret_key}\n"
                "connect(admin_api_key=admin_api_key, webhook_secret=webhook_secret)\n"
                'normalized_password = u"".join(chars)\n'
                'OPENAI_API_KEY = "sk-proj-..."\n',
                encoding="utf-8")
            # 带前缀的字符串字面量仍是字面量
            (root / "literal.py").write_text('DB_PASSWORD = b"' + "Zq8" + "vN3pL7wR2tY6" + '"\n', encoding="utf-8")
            hits = {(i["path"], i["rule"]) for i in security_scan.scan(root)["findings"]}
            self.assertEqual(hits, {("literal.py", "credential-assignment")})

    def test_sensitive_file_names_are_classified(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".npmrc").write_text("registry=https://registry.npmjs.org\n", encoding="utf-8")
            (root / ".env.production").write_text("MODE=production\n", encoding="utf-8")
            (root / "app.tfstate").write_text("{}\n", encoding="utf-8")
            (root / ".DS_Store").write_bytes(b"\x00\x01")
            findings = security_scan.scan(root)["findings"]
            by_path = {(i["path"], i["rule"], i["severity"]) for i in findings}
            self.assertIn((".npmrc", "auth-config-file", "medium"), by_path)
            self.assertIn((".env.production", "private-env-file", "high"), by_path)
            self.assertIn(("app.tfstate", "terraform-state", "high"), by_path)
            self.assertIn((".DS_Store", "os-junk-file", "medium"), by_path)

    def test_lockfile_integrity_hashes_are_not_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = json.dumps({
                "name": "x", "version": "1.0.0",
                "dependencies": {"left-pad": {"integrity": "sha512-" + "a" * 86,
                                               "resolved": "https://registry.npmjs.org/left-pad/-/left-pad-1.0.0.tgz"}},
            })
            (root / "package-lock.json").write_text(content, encoding="utf-8")
            findings = security_scan.scan(root)["findings"]
            # integrity 哈希不触发 credential-assignment / high-entropy；strict 规则仍应运行
            self.assertNotIn("credential-assignment", {i["rule"] for i in findings})
            self.assertNotIn("high-entropy-secret", {i["rule"] for i in findings})

    def test_high_entropy_secret_in_assignment_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "app.py").write_text('api_secret = "qW7nR2xV9mLpK4jH6tZb8Yc3Ds5Fg1Nh"\n', encoding="utf-8")
            rules = {i["rule"] for i in security_scan.scan(root)["findings"]}
            self.assertIn("high-entropy-secret", rules)

    def test_jpeg_with_exif_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe1\x12\x34Exif\x00\x00" + b"\x00" * 64)
            findings = security_scan.scan(root)["findings"]
            self.assertIn({"severity": "medium", "rule": "image-exif-metadata", "path": "photo.jpg", "scope": "worktree"}, findings)

    def test_internal_ip_in_docker_compose_exempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "docker-compose.yml").write_text("networks:\n  default:\n    subnet: 10.0.0.0/24\n", encoding="utf-8")
            (root / "notes.txt").write_text("vpn gateway 10.20.30.40\n", encoding="utf-8")
            rules = {(i["path"], i["rule"]) for i in security_scan.scan(root)["findings"]}
            self.assertIn(("notes.txt", "internal-ip"), rules)
            self.assertNotIn(("docker-compose.yml", "internal-ip"), rules)

    def test_slug_like_sk_value_is_not_flagged_as_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "docs.md").write_text(
                "our frontend id is sk-frontend-project-2026 here\n", encoding="utf-8")
            rules = {i["rule"] for i in security_scan.scan(root)["findings"]}
            self.assertNotIn("openai-style-token", rules)

    def test_git_ignored_file_is_not_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            git(root, "init", "-q")
            git(root, "config", "user.email", "t@example.com")
            git(root, "config", "user.name", "t")
            (root / ".gitignore").write_text("ignored.env\n", encoding="utf-8")
            (root / "ignored.env").write_text("github_" + "pat_" + "F" * 32, encoding="utf-8")
            self.assertEqual(security_scan.scan(root)["findings"], [])


class HistoryScanTests(unittest.TestCase):
    def test_secret_in_removed_file_history_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            git(root, "init", "-q")
            git(root, "config", "user.email", "t@example.com")
            git(root, "config", "user.name", "t")
            secret = "github_" + "pat_" + "K" * 32
            (root / "leaked.txt").write_text(secret + "\n", encoding="utf-8")
            git(root, "add", "leaked.txt")
            git(root, "commit", "-q", "-m", "add secret")
            (root / "leaked.txt").unlink()
            git(root, "add", "-A")
            git(root, "commit", "-q", "-m", "remove file")

            result = security_scan.scan(root, scan_history_flag=True)
            history_findings = [i for i in result["findings"] if i.get("scope") == "history"]
            self.assertTrue(history_findings, "历史中已删除的密钥必须被 --scan-history 命中")
            self.assertEqual(history_findings[0]["path"], "leaked.txt")
            self.assertTrue(history_findings[0].get("commit"))
            self.assertTrue(result["history_scanned"])

            result_no_history = security_scan.scan(root, scan_history_flag=False)
            self.assertFalse(result_no_history["history_scanned"])

    def test_secret_in_removed_non_ascii_file_history_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            git(root, "init", "-q")
            git(root, "config", "user.email", "t@example.com")
            git(root, "config", "user.name", "t")
            (root / "配置.py").write_text("github_" + "pat_" + "C" * 32 + "\n", encoding="utf-8")
            git(root, "add", "配置.py")
            git(root, "commit", "-q", "-m", "add secret")
            (root / "配置.py").unlink()
            git(root, "add", "-A")
            git(root, "commit", "-q", "-m", "remove file")

            result = security_scan.scan(root, scan_history_flag=True)
            history_paths = {i["path"] for i in result["findings"] if i.get("scope") == "history"}
            self.assertEqual(history_paths, {"配置.py"})

    def test_quoted_diff_path_is_decoded(self) -> None:
        # 路径含引号/反斜杠时即使 quotePath=false，git 仍输出 C 风格转义
        lines = [
            "commit 0123456789abcdef",
            "--- /dev/null",
            '+++ "b/\\"\\351\\205\\215\\347\\275\\256\\".md"',
            "@@ -0,0 +1 @@",
            "+" + "github_" + "pat_" + "E" * 32,
        ]
        findings = security_scan.Findings()
        security_scan._scan_diff(iter(lines), findings, scope="history")
        self.assertEqual([(i["path"], i["line"]) for i in findings.items], [('"配置".md', 1)])

    def test_staged_secret_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            git(root, "init", "-q")
            git(root, "config", "user.email", "t@example.com")
            git(root, "config", "user.name", "t")
            (root / "README.md").write_text("hello\n", encoding="utf-8")
            git(root, "add", "README.md")
            git(root, "commit", "-q", "-m", "init")
            (root / "cfg.ini").write_text("aws_access_key = AKIA" + "Z" * 16 + "\n", encoding="utf-8")
            git(root, "add", "cfg.ini")

            result = security_scan.scan(root, staged_flag=True)
            staged = [i for i in result["findings"] if i.get("scope") == "staged"]
            self.assertTrue(staged)
            self.assertEqual(staged[0]["path"], "cfg.ini")

    def test_staged_secret_in_non_ascii_file_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            git(root, "init", "-q")
            git(root, "config", "user.email", "t@example.com")
            git(root, "config", "user.name", "t")
            (root / "README.md").write_text("hello\n", encoding="utf-8")
            git(root, "add", "README.md")
            git(root, "commit", "-q", "-m", "init")
            (root / "密钥.txt").write_text("github_" + "pat_" + "D" * 32 + "\n", encoding="utf-8")
            git(root, "add", "密钥.txt")

            result = security_scan.scan(root, staged_flag=True)
            staged = [i["path"] for i in result["findings"] if i.get("scope") == "staged"]
            self.assertEqual(staged, ["密钥.txt"])


class UnpushedScanTests(unittest.TestCase):
    def test_only_commits_missing_from_remotes_are_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            git(root, "init", "-q", "-b", "main")
            git(root, "config", "user.email", "t@example.com")
            git(root, "config", "user.name", "t")
            pushed_secret = "github_" + "pat_" + "P" * 32
            (root / "pushed.txt").write_text(pushed_secret + "\n", encoding="utf-8")
            git(root, "add", "pushed.txt")
            git(root, "commit", "-q", "-m", "already pushed")
            # 模拟该提交已存在于 remote（无需真实网络推送）
            head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, check=True).stdout.strip()
            git(root, "update-ref", "refs/remotes/origin/main", head)

            unpushed_secret = "github_" + "pat_" + "Q" * 32
            (root / "local.txt").write_text(unpushed_secret + "\n", encoding="utf-8")
            git(root, "add", "local.txt")
            git(root, "commit", "-q", "-m", "local only")

            full = security_scan.scan(root, scan_history_flag=True)
            unpushed = security_scan.scan(root, unpushed_flag=True)
            full_paths = {i["path"] for i in full["findings"] if i.get("scope") == "history"}
            unpushed_paths = {i["path"] for i in unpushed["findings"] if i.get("scope") == "history"}
            self.assertEqual(full_paths, {"pushed.txt", "local.txt"})
            self.assertEqual(unpushed_paths, {"local.txt"})


class BaselineTests(unittest.TestCase):
    def test_baseline_accepts_reviewed_finding_without_hiding_others(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "contact.md").write_text("联系: someone@example.org\n", encoding="utf-8")
            (root / "dev.txt").write_text("个人邮箱 other@example.org\n", encoding="utf-8")
            baseline = root / ".safe-publish-baseline.json"
            baseline.write_text(json.dumps({
                "version": 1,
                "entries": [{"rule": "email-address", "path": "contact.md", "line": 1, "reason": "公开联系方式", "date": "2026-10-24"}],
            }), encoding="utf-8")

            result = security_scan.scan(root, baseline_path=baseline)
            paths = [i["path"] for i in result["findings"]]
            self.assertNotIn("contact.md", paths)
            self.assertIn("dev.txt", paths)
            self.assertEqual(result["accepted"], 1)
            self.assertEqual(result["summary"]["medium"], 1)


class OutputSafetyTests(unittest.TestCase):
    def test_json_and_text_output_do_not_reveal_values_or_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            secret_value = "github_" + "pat_" + "G" * 32
            (root / "config.txt").write_text(secret_value, encoding="utf-8")

            text_result = subprocess.run(
                [sys.executable, str(SCRIPT), str(root)], capture_output=True, text=True,
                check=False, encoding="utf-8", errors="replace")
            json_result = subprocess.run(
                [sys.executable, str(SCRIPT), str(root), "--json"], capture_output=True, text=True,
                check=False, encoding="utf-8", errors="replace")

            self.assertEqual(text_result.returncode, 2)
            self.assertEqual(json_result.returncode, 2)
            self.assertNotIn(secret_value, text_result.stdout)
            self.assertNotIn(secret_value, json_result.stdout)
            payload = json.loads(json_result.stdout)
            self.assertNotIn(str(root), json_result.stdout)
            self.assertEqual(payload["summary"]["high"], 1)


if __name__ == "__main__":
    unittest.main()
