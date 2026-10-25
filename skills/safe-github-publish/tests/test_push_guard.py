from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# 守卫随 plugin 发布；只复制 skill 目录时没有 hooks/，整组跳过
GUARD = Path(__file__).resolve().parents[3] / "hooks" / "push_guard.py"
if GUARD.is_file():
    SPEC = importlib.util.spec_from_file_location("push_guard", GUARD)
    assert SPEC and SPEC.loader
    push_guard = importlib.util.module_from_spec(SPEC)
    sys.modules[SPEC.name] = push_guard
    SPEC.loader.exec_module(push_guard)

SECRET = "github_" + "pat_" + "R" * 32


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def make_repo(root: Path) -> None:
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")


def commit_file(root: Path, name: str, content: str, message: str) -> None:
    (root / name).write_text(content, encoding="utf-8")
    git(root, "add", name)
    git(root, "commit", "-q", "-m", message)


def run_guard(command: str, cwd: Path, tool: str = "Bash") -> subprocess.CompletedProcess[str]:
    event = {"tool_name": tool, "tool_input": {"command": command}, "cwd": str(cwd)}
    return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", check=False)


@unittest.skipUnless(GUARD.is_file(), "守卫不在 skill 目录内")
class CommandParsingTests(unittest.TestCase):
    def kinds(self, command: str, posix: bool = True) -> list[tuple[str, str, str | None]]:
        base = Path("/base")
        return [(p.as_posix(), kind, remote)
                for p, kind, remote in push_guard.publish_targets(command, base, posix)]

    def test_publish_commands_are_classified(self) -> None:
        self.assertEqual(self.kinds("git push"), [("/base", "push", None)])
        self.assertEqual(self.kinds("git push -u public main"), [("/base", "push", "public")])
        self.assertEqual(self.kinds("git -c core.x=y push --force-with-lease origin"), [("/base", "push", "origin")])
        self.assertEqual(self.kinds("gh repo create demo --public --source=. --push"), [("/base", "full", None)])
        self.assertEqual(self.kinds("gh repo edit --visibility public --accept-visibility-change-consequences"),
                         [("/base", "full", None)])
        self.assertEqual(self.kinds("gh api -X PATCH repos/o/r -F private=false"), [("/base", "full", None)])
        self.assertEqual(self.kinds("gh release create v1.0.0"), [("/base", "default", None)])

    def test_non_publish_commands_are_ignored(self) -> None:
        for command in ['git commit -m "fix push; git push later"', "git stash push", "gh repo edit --visibility private",
                        "echo git push", "gh repo view"]:
            self.assertEqual(self.kinds(command), [], command)

    def test_directory_changes_are_tracked(self) -> None:
        self.assertEqual(self.kinds("cd sub && git push"), [("/base/sub", "push", None)])
        self.assertEqual(self.kinds("git -C ../other push origin"), [("/base/../other", "push", "origin")])
        self.assertEqual(self.kinds("Set-Location -Path sub; git push", posix=False), [("/base/sub", "push", None)])
        self.assertEqual(self.kinds("bash -c 'cd sub && git push'"), [("/base/sub", "push", None)])


@unittest.skipUnless(GUARD.is_file(), "守卫不在 skill 目录内")
class GuardTests(unittest.TestCase):
    def test_secret_in_unpushed_commit_is_blocked_without_leaking_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_repo(root)
            commit_file(root, "cfg.txt", SECRET + "\n", "add secret")
            result = run_guard("git push", root)
            self.assertEqual(result.returncode, 2)
            self.assertIn("github-token", result.stderr)
            self.assertNotIn(SECRET, result.stderr + result.stdout)

    def test_cd_into_repo_is_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            make_repo(repo)
            commit_file(repo, "cfg.txt", SECRET + "\n", "add secret")
            self.assertEqual(run_guard("cd repo && git push", root).returncode, 2)
            self.assertEqual(run_guard(f'git -C "{repo}" push', root).returncode, 2)
            self.assertEqual(run_guard("Set-Location repo; git push", root, tool="PowerShell").returncode, 2)

    def test_history_on_private_remote_is_scanned_for_new_remote_and_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_repo(root)
            commit_file(root, "cfg.txt", SECRET + "\n", "add secret")
            commit_file(root, "cfg.txt", "removed\n", "remove secret")
            # 密钥提交已在私有 origin 上（模拟远端跟踪分支，无需网络）
            git(root, "remote", "add", "origin", "https://example.invalid/private.git")
            git(root, "update-ref", "refs/remotes/origin/main", git(root, "rev-parse", "HEAD"))
            git(root, "remote", "add", "public", "https://example.invalid/public.git")

            self.assertEqual(run_guard("git push", root).returncode, 0)
            self.assertEqual(run_guard("git push origin main", root).returncode, 0)
            self.assertEqual(run_guard("git push public main", root).returncode, 2)
            self.assertEqual(run_guard("git push https://example.invalid/other.git main", root).returncode, 2)
            self.assertEqual(run_guard("gh repo edit --visibility public", root).returncode, 2)

    def test_baseline_change_in_unpushed_commit_asks_for_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_repo(root)
            commit_file(root, "contact.md", "someone@example.org\n", "init")
            git(root, "remote", "add", "origin", "https://example.invalid/o.git")
            git(root, "update-ref", "refs/remotes/origin/main", git(root, "rev-parse", "HEAD"))
            baseline = {"version": 1, "entries": [
                {"rule": "email-address", "path": "contact.md", "line": 1, "reason": "公开联系方式", "date": "2026-10-25"}]}
            commit_file(root, ".safe-publish-baseline.json", json.dumps(baseline), "add baseline")

            result = run_guard("git push", root)
            self.assertEqual(result.returncode, 0)
            output = json.loads(result.stdout)["hookSpecificOutput"]
            self.assertEqual(output["permissionDecision"], "ask")

    def test_non_publish_command_and_non_repo_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(run_guard("ls -la", root).returncode, 0)
            self.assertEqual(run_guard("git push", root).returncode, 0)

    def test_scanner_failure_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_repo(root)
            commit_file(root, "a.txt", "hello\n", "init")
            event = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push"}, "cwd": str(root)})
            with mock.patch.object(push_guard, "guard", side_effect=RuntimeError("boom")), \
                    mock.patch.object(sys, "stdin", io.StringIO(event)), \
                    mock.patch.object(sys, "stderr", io.StringIO()):
                self.assertEqual(push_guard.main(), 2)


if __name__ == "__main__":
    unittest.main()
