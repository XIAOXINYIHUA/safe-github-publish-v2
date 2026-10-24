from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "repo_lint.py"
SPEC = importlib.util.spec_from_file_location("repo_lint", SCRIPT)
assert SPEC and SPEC.loader
repo_lint = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = repo_lint
SPEC.loader.exec_module(repo_lint)


def write(root: Path, name: str, content: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


GOOD_README = """# Demo

一个演示项目。

## Quick start

```bash
pip install demo
```

## License

MIT（见 [LICENSE](LICENSE)）。

截图：![主界面](Docs/screen.png)
"""


class RepoLintTests(unittest.TestCase):
    def test_clean_repo_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root, "README.md", GOOD_README)
            write(root, "LICENSE", "MIT License\n")
            write(root, ".gitignore", "node_modules/\n")
            write(root, "Docs/screen.png", "\x89PNG\r\n\x1a\n")
            findings = repo_lint.lint(root)
            errors = [f for f in findings if f["severity"] == "error"]
            self.assertEqual(errors, [])

    def test_missing_readme_and_quick_start_are_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root, "LICENSE", "MIT\n")
            write(root, ".gitignore", "x\n")
            checks = {f["check"] for f in repo_lint.lint(root)}
            self.assertIn("readme-exists", checks)

            write(root, "README.md", "# Only title\n\n正文，无快速开始章节\n")
            checks = {f["check"] for f in repo_lint.lint(root)}
            self.assertIn("readme-quick-start", checks)

    def test_missing_license_and_gitignore_are_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            readme = GOOD_README.replace("MIT（见 [LICENSE](LICENSE)）。", "待定")
            write(root, "README.md", readme)
            write(root, "Docs/screen.png", "x")
            by_severity = {(f["check"], f["severity"]) for f in repo_lint.lint(root)}
            self.assertIn(("license-exists", "warn"), by_severity)
            self.assertIn(("gitignore-exists", "warn"), by_severity)

    def test_broken_link_and_case_mismatch_are_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            readme = GOOD_README.replace("(Docs/screen.png)", "(docs/screen.png)")
            readme += "另见 [贡献指南](CONTRIBUTING.md)。\n"
            write(root, "README.md", readme)
            write(root, "LICENSE", "MIT\n")
            write(root, ".gitignore", "x\n")
            write(root, "Docs/screen.png", "x")
            messages = " | ".join(f["message"] for f in repo_lint.lint(root))
            self.assertIn("大小写不匹配", messages)
            self.assertIn("CONTRIBUTING.md", messages)

    def test_invalid_mermaid_block_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            readme = GOOD_README + "\n```mermaid\njust some text\n```\n"
            write(root, "README.md", readme)
            write(root, "LICENSE", "MIT\n")
            write(root, ".gitignore", "x\n")
            checks = {f["check"] for f in repo_lint.lint(root) if f["severity"] == "error"}
            self.assertIn("mermaid-block", checks)

    def test_valid_mermaid_block_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            readme = GOOD_README + "\n```mermaid\nflowchart LR\n  A[User] --> B[App]\n```\n"
            write(root, "README.md", readme)
            write(root, "LICENSE", "MIT\n")
            write(root, ".gitignore", "x\n")
            write(root, "Docs/screen.png", "x")
            findings = repo_lint.lint(root)
            self.assertNotIn("mermaid-block", {f["check"] for f in findings})

    def test_mermaid_example_inside_outer_fence_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # 外层四反引号 markdown 块内的 ```mermaid 只是文档示例，不应按真块校验
            readme = GOOD_README + "\n````markdown\n```mermaid\nnot a real block\n```\n````\n"
            write(root, "README.md", readme)
            write(root, "LICENSE", "MIT\n")
            write(root, ".gitignore", "x\n")
            write(root, "Docs/screen.png", "x")
            findings = repo_lint.lint(root)
            self.assertNotIn("mermaid-block", {f["check"] for f in findings})

    def test_link_inside_code_fence_is_not_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            readme = GOOD_README + "\n```markdown\n示例：[不存在的文件](nope/missing.md)\n```\n"
            write(root, "README.md", readme)
            write(root, "LICENSE", "MIT\n")
            write(root, ".gitignore", "x\n")
            write(root, "Docs/screen.png", "x")
            findings = repo_lint.lint(root)
            self.assertNotIn("link-resolves", {f["check"] for f in findings})

    def test_parent_relative_link_in_nested_readme_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root, "LICENSE", "MIT\n")
            write(root, ".gitignore", "x\n")
            write(root, "skills/demo/README.md", "# Demo\n\n## Quick start\n\n```bash\nok\n```\n\nMIT 见 [LICENSE](../../LICENSE)。\n")
            findings = repo_lint.lint(root)
            self.assertNotIn("link-resolves", {f["check"] for f in findings if f["severity"] == "error"})

    def test_directory_link_with_trailing_slash_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root, "LICENSE", "MIT\n")
            write(root, ".gitignore", "x\n")
            write(root, "README.md", "# Demo\n\n## Quick start\n\n见 [文档目录](docs/)。\n")
            write(root, "docs/guide.md", "x")
            findings = repo_lint.lint(root)
            self.assertNotIn("link-resolves", {f["check"] for f in findings})

    def test_empty_section_is_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            readme = GOOD_README + "\n## Roadmap\n\n## Thanks\n\n- you\n"
            write(root, "README.md", readme)
            write(root, "LICENSE", "MIT\n")
            write(root, ".gitignore", "x\n")
            checks = {f["check"] for f in repo_lint.lint(root) if f["severity"] == "warn"}
            self.assertIn("readme-empty-section", checks)

    def test_multiple_h1_is_warning_and_badge_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            readme = GOOD_README + "# Second H1\n"
            readme += "\n".join(
                f"![b{i}](https://img.shields.io/badge/x-{i}-blue)" for i in range(7)
            ) + "\n"
            write(root, "README.md", readme)
            write(root, "LICENSE", "MIT\n")
            write(root, ".gitignore", "x\n")
            checks = {f["check"] for f in repo_lint.lint(root) if f["severity"] == "warn"}
            self.assertIn("readme-title", checks)
            self.assertIn("readme-badges", checks)

    def test_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root, "README.md", "# T\n\n正文\n")  # 无 quick start → error；缺 license/gitignore → warn
            result = subprocess.run([sys.executable, str(SCRIPT), str(root)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)

            # 阶段二：结构完整、链接可达，仅缺 LICENSE 文件与 .gitignore → 只有 warn
            readme = GOOD_README.replace("MIT（见 [LICENSE](LICENSE)）。", "License 待定。")
            write(root, "README.md", readme)
            write(root, "Docs/screen.png", "x")
            result = subprocess.run([sys.executable, str(SCRIPT), str(root)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)  # 缺 license + gitignore → warn

            write(root, "LICENSE", "MIT\n")
            write(root, ".gitignore", "x\n")
            result = subprocess.run([sys.executable, str(SCRIPT), str(root)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
