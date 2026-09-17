"""输入行即时宏扩展引擎 (MacroEngine)。

负责：
1. Shell 宏执行管道（!cmd 与 !!cmd），支持工作区相对路径、超时、退出码与输出流捕获；
2. Skill 展开宏（/skill:<name> [args]），剥离 YAML Frontmatter 并包装为标准 XML 格式；
3. Prompt 模板展开宏（/<template> [args]），支持 Bash 风格 shlex 引号分词与完整变量替换。
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from my_coding_agent.paths import AgentPaths

if TYPE_CHECKING:
    from my_agent_core.skills import SkillManager


class MacroEngine:
    """管理终端即时宏解析、Shell 命令执行与模板变量展开的核心引擎。"""

    def __init__(
        self,
        workspace: Path | str | None = None,
        paths: AgentPaths | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve() if workspace else Path.cwd()
        self.paths = paths or AgentPaths()

    def execute_shell(
        self,
        command: str,
        cwd: Path | str | None = None,
        exclude_from_context: bool = False,
        timeout: float | None = 60.0,
    ) -> dict[str, Any]:
        """同步执行外部 Shell 命令并捕获输出与退出码。

        Args:
            command: 待执行的命令行字符串
            cwd: 执行命令的工作目录（缺省为 workspace）
            exclude_from_context: 是否排除在模型上下文之外（!!cmd 静默探查标记）
            timeout: 命令执行超时时间（秒，缺省 60.0）

        Returns:
            字典结构：status, output, stdout, stderr, exit_code, exclude_from_context
        """
        cmd_str = command.strip()
        if not cmd_str:
            return {
                "status": "error",
                "output": "Empty command",
                "stdout": "",
                "stderr": "Empty command",
                "exit_code": -1,
                "exclude_from_context": exclude_from_context,
            }

        target_cwd = Path(cwd).resolve() if cwd else self.workspace

        try:
            # nosec B602
            proc = subprocess.run(
                cmd_str,
                shell=True,  # noqa: S602 # nosec B602
                cwd=str(target_cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""

            if stdout and stderr:
                output = f"{stdout}\n{stderr}" if not stdout.endswith("\n") else f"{stdout}{stderr}"
            elif stdout:
                output = stdout
            else:
                output = stderr

            return {
                "status": "ok" if proc.returncode == 0 else "error",
                "output": output,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": proc.returncode,
                "exclude_from_context": exclude_from_context,
            }
        except subprocess.TimeoutExpired as te:
            stdout_raw = te.stdout or ""
            stderr_raw = te.stderr or ""
            stdout = stdout_raw if isinstance(stdout_raw, str) else stdout_raw.decode("utf-8", errors="replace")
            stderr = stderr_raw if isinstance(stderr_raw, str) else stderr_raw.decode("utf-8", errors="replace")
            return {
                "status": "error",
                "output": f"Command timed out after {timeout} seconds",
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": -1,
                "exclude_from_context": exclude_from_context,
            }
        except Exception as exc:
            return {
                "status": "error",
                "output": str(exc),
                "stdout": "",
                "stderr": str(exc),
                "exit_code": -1,
                "exclude_from_context": exclude_from_context,
            }

    def expand_skill(
        self,
        skill_name: str,
        args: str = "",
        skills_dir: Path | str | None = None,
        skill_manager: SkillManager | None = None,
    ) -> str | None:
        """展开指定技能的 SKILL.md，脱去 YAML frontmatter 并包装为标准 XML 格式。

        Args:
            skill_name: 技能名称
            args: 传入技能的附带参数
            skills_dir: 可选显式指定的 skills 根目录
            skill_manager: 可选注入的 SkillManager 实例

        Returns:
            展开后的 XML + 参数字符串，若技能不存在则返回 None
        """
        name = skill_name.strip()
        if not name:
            return None

        file_path: Path | None = None

        if skill_manager is not None:
            skill = skill_manager.get(name)
            if skill is not None:
                file_path = skill.file_path

        if file_path is None and skills_dir is not None:
            root = Path(skills_dir).resolve()
            candidates = [
                root / name / "SKILL.md",
                root / name / "skill.md",
                root / f"{name}.md",
            ]
            if root.name == name and (root / "SKILL.md").is_file():
                candidates.insert(0, root / "SKILL.md")
            for c in candidates:
                if c.is_file():
                    file_path = c
                    break

        if file_path is None:
            search_dirs = [
                self.workspace / ".agents" / "skills",
                self.workspace / ".my-pi-agent" / "skills",
                self.workspace / "skills",
                self.paths.skills_dir,
                self.paths.agents_home / "skills",
            ]
            for sdir in search_dirs:
                if not sdir.is_dir():
                    continue
                candidates = [
                    sdir / name / "SKILL.md",
                    sdir / name / "skill.md",
                    sdir / f"{name}.md",
                ]
                for c in candidates:
                    if c.is_file():
                        file_path = c
                        break
                if file_path is not None:
                    break

        if file_path is None:
            return None

        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            return None

        # 剥离 YAML Frontmatter
        normalized = content.replace("\r\n", "\n")
        match = re.match(r"^---\n(.*?)\n---\n?", normalized, re.DOTALL)
        if match:
            body = normalized[match.end() :].strip()
        else:
            body = normalized.strip()

        location = str(file_path.resolve())
        xml_block = f'<skill name="{name}" location="{location}">\n{body}\n</skill>'

        clean_args = args.strip()
        if clean_args:
            return f"{xml_block}\n\n{clean_args}"
        return xml_block

    def expand_template(
        self,
        template_name: str,
        args_string: str = "",
        prompts_dir: Path | str | None = None,
    ) -> str | None:
        """展开指定 Prompt 模板，剥离 YAML frontmatter 并执行 Bash 风格参数变量替换。

        Args:
            template_name: 模板标识名（对应 prompts/<template_name>.md）
            args_string: 命令行输入的参数字符串
            prompts_dir: 可选显式指定的 prompts 目录

        Returns:
            替换后的 Prompt 文本，若模板不存在则返回 None
        """
        name = template_name.strip()
        if not name:
            return None

        file_path: Path | None = None

        if prompts_dir is not None:
            root = Path(prompts_dir).resolve()
            candidates = [
                root / f"{name}.md",
                root / name,
            ]
            for c in candidates:
                if c.is_file():
                    file_path = c
                    break

        if file_path is None:
            search_dirs = [
                self.workspace / "prompts",
                self.workspace / ".my-pi-agent" / "prompts",
                self.workspace / ".agents" / "prompts",
                self.paths.prompts_dir,
                self.paths.agents_home / "prompts",
            ]
            for pdir in search_dirs:
                if not pdir.is_dir():
                    continue
                candidates = [
                    pdir / f"{name}.md",
                    pdir / name,
                ]
                for c in candidates:
                    if c.is_file():
                        file_path = c
                        break
                if file_path is not None:
                    break

        if file_path is None:
            return None

        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            return None

        # 剥离 YAML Frontmatter
        normalized = content.replace("\r\n", "\n")
        match = re.match(r"^---\n(.*?)\n---\n?", normalized, re.DOTALL)
        if match:
            body = normalized[match.end() :].strip()
        else:
            body = normalized.strip()

        return self.substitute_template_args(body, args_string)

    def substitute_template_args(self, template_body: str, args_string: str) -> str:
        """以 Bash shlex 分词与变量语义替换模板正文中的参数占位符。

        支持语法全集：
        - $1, $2, $N: 1-indexed 位置参数
        - $@, $ARGUMENTS: 全部参数空格连接
        - ${N:-default}: 带默认值的位置参数
        - ${@:-default}, ${ARGUMENTS:-default}: 无参时的全局默认值
        - ${@:N}: 从第 N 个参数开始截取到末尾
        - ${@:N:L}: 从第 N 个参数开始截取 L 个
        """
        clean_args_str = args_string.strip()
        if clean_args_str:
            try:
                args = shlex.split(clean_args_str, posix=True)
            except ValueError:
                args = clean_args_str.split()
        else:
            args = []

        all_args = " ".join(args)

        # 1. ${@:N:L}
        def replace_slice_len(m: re.Match[str]) -> str:
            start = int(m.group(1))
            length = int(m.group(2))
            start_idx = max(0, start - 1)
            if start_idx < len(args):
                return " ".join(args[start_idx : start_idx + length])
            return ""

        result = re.sub(r"\$\{@:(\d+):(\d+)\}", replace_slice_len, template_body)

        # 2. ${@:N}
        def replace_slice(m: re.Match[str]) -> str:
            start = int(m.group(1))
            start_idx = max(0, start - 1)
            if start_idx < len(args):
                return " ".join(args[start_idx:])
            return ""

        result = re.sub(r"\$\{@:(\d+)\}", replace_slice, result)

        # 3. ${@:-default} 或 ${ARGUMENTS:-default}
        def replace_all_default(m: re.Match[str]) -> str:
            default_val = m.group(1)
            return all_args if all_args else default_val

        result = re.sub(r"\$\{(?:@|ARGUMENTS):-(.*?)\}", replace_all_default, result)

        # 4. ${@} 或 ${ARGUMENTS}
        result = re.sub(r"\$\{(?:@|ARGUMENTS)\}", all_args, result)

        # 5. $@ 或 $ARGUMENTS
        result = re.sub(r"\$(?:ARGUMENTS\b|@)", all_args, result)

        # 6. ${N:-default}
        def replace_pos_default(m: re.Match[str]) -> str:
            n = int(m.group(1))
            default_val = m.group(2)
            if 1 <= n <= len(args) and args[n - 1]:
                return args[n - 1]
            return default_val

        result = re.sub(r"\$\{(\d+):-(.*?)\}", replace_pos_default, result)

        # 7. ${N}
        def replace_pos_braced(m: re.Match[str]) -> str:
            n = int(m.group(1))
            if 1 <= n <= len(args):
                return args[n - 1]
            return ""

        result = re.sub(r"\$\{(\d+)\}", replace_pos_braced, result)

        # 8. $N
        def replace_pos(m: re.Match[str]) -> str:
            n = int(m.group(1))
            if 1 <= n <= len(args):
                return args[n - 1]
            return ""

        result = re.sub(r"\$(\d+)", replace_pos, result)

        return result

    def expand_macro(
        self,
        text: str,
        skills_dir: Path | str | None = None,
        prompts_dir: Path | str | None = None,
    ) -> tuple[str, bool]:
        """统一识别并展开文本中的输入宏（/skill:<name> 或 /<template>）。

        Returns:
            (expanded_text, is_expanded)
        """
        raw = text.strip()
        if not raw.startswith("/"):
            return text, False

        # 1. /skill:<name> [args] 或 /skill <name> [args]
        if raw.startswith("/skill:") or raw.startswith("/skill "):
            prefix_len = len("/skill:") if raw.startswith("/skill:") else len("/skill ")
            rest = raw[prefix_len:].strip()
            if not rest:
                return text, False
            if " " in rest:
                skill_name, args = rest.split(" ", 1)
            else:
                skill_name, args = rest, ""
            expanded_skill = self.expand_skill(skill_name.strip(), args.strip(), skills_dir=skills_dir)
            if expanded_skill is not None:
                return expanded_skill, True
            return text, False

        # 2. /<template> [args]
        without_slash = raw[1:].strip()
        if not without_slash:
            return text, False

        if " " in without_slash:
            template_name, args = without_slash.split(" ", 1)
        else:
            template_name, args = without_slash, ""

        expanded_template = self.expand_template(template_name.strip(), args.strip(), prompts_dir=prompts_dir)
        if expanded_template is not None:
            return expanded_template, True

        return text, False
