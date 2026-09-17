"""resource_scanner: 统一扫描并提取 Context、Skills、Prompts、Extensions 资源看板。

严格基于 my-pi-agent 规范管理全局用户目录 (~/.my-pi-agent/) 与项目本地资源，实现严格的项目级环境隔离。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from my_coding_agent.paths import AgentPaths

logger = logging.getLogger(__name__)


def _format_display_path(p: Path | str) -> str:
    """将绝对路径规范化为 ~ 开头的展示友好路径。"""
    resolved = Path(p).resolve()
    try:
        home = Path.home().resolve()
        if resolved == home:
            return "~"
        if resolved.is_relative_to(home):
            rel = resolved.relative_to(home)
            return f"~\\{rel}" if "\\" in str(resolved) else f"~/{rel}"
    except Exception:
        pass
    return str(resolved)


def get_all_skill_dirs(workspace_path: Path, paths: AgentPaths | None = None) -> list[Path]:
    """收集所有可供 SkillManager 扫描的技能根目录（去重且存在才收录）。

    覆盖：
    1. 用户全局技能目录 (~/.my-pi-agent/skills, ~/.agents/skills)
    2. 工作区局部技能目录 (<ws>/.skills, <ws>/skills, <ws>/.agents/skills, <ws>/.my-pi-agent/skills)
    3. 本 Agent 包管理器声明的已安装包目录 (~/.my-pi-agent/settings.json)
    """
    effective_paths = paths or AgentPaths()
    dirs: list[Path] = []
    seen: set[str] = set()

    def add_dir(d: Path | str | None) -> None:
        if d is None:
            return
        p = Path(d).resolve()
        if p.is_dir() and str(p) not in seen:
            seen.add(str(p))
            dirs.append(p)

    # 1. 全局技能目录
    add_dir(effective_paths.skills_dir)
    add_dir(effective_paths.agents_home / "skills")

    # 2. 项目局部技能目录
    add_dir(workspace_path / ".skills")
    add_dir(workspace_path / "skills")
    add_dir(workspace_path / ".agents" / "skills")
    add_dir(workspace_path / ".my-pi-agent" / "skills")

    # 3. 扫描 my-pi-agent 包管理器声明的已安装包目录
    settings_candidates = [
        effective_paths.settings_path,
        effective_paths.project_settings_path(workspace_path),
    ]
    for sc in settings_candidates:
        if not sc.is_file():
            continue
        try:
            data = json.loads(sc.read_text(encoding="utf-8"))
            for pkg in data.get("packages", []):
                pkg_dir: Path | None = None
                if pkg.startswith("git:"):
                    pkg_dir = effective_paths.home / "git" / pkg[len("git:") :]
                elif pkg.startswith("npm:"):
                    pkg_dir = effective_paths.home / "npm" / "node_modules" / pkg[len("npm:") :]

                if not pkg_dir or not pkg_dir.is_dir():
                    continue

                pkg_json_file = pkg_dir / "package.json"
                if not pkg_json_file.is_file():
                    continue

                try:
                    pkg_data = json.loads(pkg_json_file.read_text(encoding="utf-8"))
                    pi_conf = pkg_data.get("pi", {})
                    sks = pi_conf.get("skills", [])
                    if isinstance(sks, str):
                        sks = [sks]
                    for sk in sks:
                        s_path = (pkg_dir / sk).resolve()
                        if (s_path / "SKILL.md").is_file():
                            add_dir(s_path.parent)
                        elif s_path.is_dir():
                            add_dir(s_path)
                except Exception:
                    continue
        except Exception:
            continue

    return dirs


def scan_loaded_resources(
    workspace_path: Path,
    paths: AgentPaths | None = None,
) -> dict[str, list[str]]:
    """扫描并提取当前项目环境加载的 Context、Skills、Prompts、Extensions 看板列表。"""
    ws = Path(workspace_path).resolve()
    effective_paths = paths or AgentPaths()

    context_files: list[str] = []
    skills_set: set[str] = set()
    prompts_set: set[str] = set()
    extensions_set: set[str] = set()

    # ── 1. Context 文件扫描 ──
    # 全局指令优先 (~/.my-pi-agent/AGENTS.md 或 ~/.agents/AGENTS.md)
    global_agents: Path | None = None
    if (effective_paths.home / "AGENTS.md").is_file():
        global_agents = (effective_paths.home / "AGENTS.md").resolve()
    elif (effective_paths.agents_home / "AGENTS.md").is_file():
        global_agents = (effective_paths.agents_home / "AGENTS.md").resolve()

    if global_agents:
        context_files.append(_format_display_path(global_agents))

    # 工作区指令
    for fname in ["AGENTS.override.md", "AGENTS.md", "CLAUDE.md"]:
        candidate = ws / fname
        if candidate.is_file():
            if global_agents is None or candidate.resolve() != global_agents:
                context_files.append(fname)

    # ── 2. Skills 发现 ──
    skill_dirs = get_all_skill_dirs(ws, effective_paths)
    for s_dir in skill_dirs:
        try:
            for child in s_dir.iterdir():
                if (child / "SKILL.md").is_file():
                    skills_set.add(child.name)
        except Exception:
            continue

    # ── 3. Prompts / Prompt-Templates 发现 ──
    prompt_scan_dirs: list[Path] = [
        effective_paths.prompts_dir,
        effective_paths.agents_home / "prompts",
        ws / "prompts",
        ws / ".my-pi-agent" / "prompts",
        ws / ".agents" / "prompts",
    ]
    for pd in prompt_scan_dirs:
        if pd.is_dir():
            for md in pd.glob("*.md"):
                prompts_set.add(f"/{md.stem}")

    # ── 4. Packages (Extensions, Skills, Prompts) 深度补充 ──
    settings_candidates = [
        effective_paths.settings_path,
        effective_paths.project_settings_path(ws),
    ]
    for sc in settings_candidates:
        if not sc.is_file():
            continue
        try:
            data = json.loads(sc.read_text(encoding="utf-8"))
            for pkg in data.get("packages", []):
                pkg_dir: Path | None = None
                label = ""
                if pkg.startswith("git:"):
                    repo_path = pkg[len("git:") :]
                    pkg_dir = effective_paths.home / "git" / repo_path
                    label = repo_path.replace("github.com/", "")
                elif pkg.startswith("npm:"):
                    npm_name = pkg[len("npm:") :]
                    pkg_dir = effective_paths.home / "npm" / "node_modules" / npm_name
                    label = npm_name

                if not pkg_dir or not pkg_dir.is_dir():
                    continue

                pkg_json_file = pkg_dir / "package.json"
                if not pkg_json_file.is_file():
                    continue

                try:
                    pkg_data = json.loads(pkg_json_file.read_text(encoding="utf-8"))
                    pi_conf = pkg_data.get("pi", {})

                    # Extensions
                    exts = pi_conf.get("extensions", [])
                    if isinstance(exts, str):
                        exts = [exts]
                    if not exts and pkg_data.get("name"):
                        extensions_set.add(label)
                    for ext in exts:
                        sub = ext.lstrip("./")
                        if sub in ("index.js", "index.ts", "src/index.ts", "src/index.js", "dist/index.js"):
                            extensions_set.add(label)
                        else:
                            sub_clean = (
                                sub.replace("/index.ts", "").replace("/index.js", "").replace("dist/extensions/", "")
                            )
                            extensions_set.add(f"{label}:{sub_clean}")

                    # Prompts
                    prs = pi_conf.get("prompts", [])
                    if isinstance(prs, str):
                        prs = [prs]
                    for pr in prs:
                        pr_path = (pkg_dir / pr).resolve()
                        if pr_path.is_dir():
                            for md in pr_path.glob("*.md"):
                                prompts_set.add(f"/{md.stem}")
                except Exception:
                    continue
        except Exception:
            continue

    # 补充本地与全局 extensions 目录
    local_ext_dir = effective_paths.project_agent_dir(ws) / "extensions"
    if local_ext_dir.is_dir():
        for f in local_ext_dir.glob("*.py"):
            extensions_set.add(f.stem)

    if effective_paths.extensions_dir.is_dir():
        for f in effective_paths.extensions_dir.glob("*.py"):
            extensions_set.add(f.stem)

    # 补充 MCP 服务器声明 (若存在)
    mcp_file = ws / ".mcp.json"
    if mcp_file.is_file():
        try:
            mcp_data = json.loads(mcp_file.read_text(encoding="utf-8"))
            for srv_name in mcp_data.get("mcpServers", {}):
                extensions_set.add(f"mcp:{srv_name}")
        except Exception as exc:
            logger.debug("读取 .mcp.json 失败: %s", exc)

    return {
        "context": context_files,
        "skills": sorted(list(skills_set)),
        "prompts": sorted(list(prompts_set)),
        "extensions": sorted(list(extensions_set)),
    }
