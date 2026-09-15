# my-pi-agent 产品级用户主目录与配置鉴权体系设计规范

- **文档名称**：产品级用户主目录、配置与鉴权体系架构设计规范
- **归档路径**：`docs/coding/09-user-home-and-configuration-architecture-design.md`
- **日期**：2026-09-14
- **状态**：完成评审，准备实施
- **目标包**：
  - `src/my_coding_agent/`（路径调度中心 `AgentPaths`、配置层叠加载器、集中式会话隔离）
  - `src/my_agent_llm/`（独立凭证中心 `AuthManager`、多 Provider 凭据模型、OAuth 自动刷新）
  - `tui/`（`/login`、`/settings`、`/session` 交互命令驱动与工作区显示）

---

## 一、架构愿景与产品级定位 (Vision & Principles)

作为一个正式面向终端用户分发的 AI Coding Agent 产品（通过 `npm install -g my-pi-agent` 或 `uv tool install my-pi-agent` 安装），必须彻底摆脱“开发期原型在当前目录随意生成 session 文件夹”的粗糙做法，严格对齐 **Pi** 与 **Tau** 的工业级最佳实践：

1. **工作区绝对零污染（Zero-Pollution Workspace）**：
   - 无论用户在机器的哪个目录（如 `C:\Users\...\Desktop`、`D:\code\react-app`）启动 Agent，绝不主动在该项目目录下生成 session、run-history 或全局凭据文件；
   - 杜绝 `git status` 出现与项目无关的未暂存中间状态；
   - 所有运行时会话数据、执行日志、诊断信息一律集中持久化至用户主目录 `~/.my-pi-agent/`。
2. **凭据与鉴权集中管理（Centralized Auth & Credentials）**：
   - 彻底斩断对宿主 `~/.pi` 等外部工具私有目录的越界偷读，完全拥有独立的认证命名空间；
   - 全局凭证集中存储在用户目录下的 `~/.my-pi-agent/auth.json`（支持多账号 Profile、API Key 与 OAuth 自动续期）；
   - 一次配置 / 登录，在全系统所有工作区内通用；同时严格支持项目级 `.env` 作为特定项目的高优先级临时覆盖。
3. **分层级联配置系统（Cascading JSON Settings）**：
   - 配置采用工业标准的 JSON 格式：全局 `~/.my-pi-agent/settings.json` 定义默认行为；
   - 团队工作区 `.my-pi-agent/settings.json` 实现受控覆盖；
   - 启动参数 CLI Flags（`-m`, `--mode`）拥有最高裁决权。
4. **统一路径调度中心（Single Source of Truth: AgentPaths）**：
   - 消除散落在各模块中的硬编码路径，由专职路径类管理所有全局与局部资源映射。

---

## 二、业界标杆深度对标分析（Pi vs Tau）

经多路 Subagent 对本地官方安装的 **Pi**（`C:/Users/ASUS/.pi/agent/`）与 **Tau**（`D:/code/python/agent-program/tau/`）源码级的深入调查，提炼出两者的核心架构精髓：

### 2.1 Pi (`@earendil-works/pi-coding-agent`) 架构调研

1. **用户主目录全景 (`~/.pi/agent/`)**：
   - `settings.json`：全局偏好设置；
   - `auth.json`：全局凭据库（`mode: 0o600`），采用 `{ provider: { type: "api_key" | "oauth", ... } }` 格式；
   - `models-store.json`：动态缓存的远程模型目录与定价表；
   - `trust.json`：项目安全信任数据库（映射 cwd 到 boolean 信任决策）；
   - `sessions/`：按工作区路径编码存储会话；
   - `skills/`、`extensions/`、`prompts/`、`themes/`、`npm/`、`git/`、`bin/`（内置 `fd.exe` / `rg.exe`）。
2. **会话目录编码机制**：
   - 使用符号转义算法：`--${resolvedCwd.replace(/^[/\\\\]/, "").replace(/[/\\\\:]/g, "-")}--`；
   - 例如：`D:\code\python\my-pi-agent` 编码为 `--D--code-python-my-pi-agent--`；
   - 会话文件遵循 `${fileTimestamp}_${uuidv7}.jsonl`。
3. **配置与合并模型**：
   - 采用 `deepMergeObjects` 递归合并字典对象；
   - 数组完全覆盖（不合并）；
   - 特权键（`httpProxy`, `defaultProjectTrust`）仅限全局生效，防止恶意仓库越权。
4. **资源分级与 Precedence Rank**：
   - 严格的 0~4 优先级排序：项目显式 (0) > 项目自动 (1) > 用户显式 (2) > 用户自动 (3) > 安装包 (4)。

### 2.2 Tau (`tau-ai`) 架构调研

1. **路径中心 (`TauPaths`)**：
   - 在 `src/tau_coding/paths.py` 中通过 `@dataclass(frozen=True, slots=True)` 集中管理所有路径；
   - 统一定义 `home = Path.home() / ".tau"` 与 `agents_home = Path.home() / ".agents"`。
2. **精巧的会话路径散列算法 (`_slugify_path`)**：
   - Tau 结合了可读性与防冲突：`f"{slug or 'project'}-{sha256(cwd)[:6]}"`；
   - 针对超长路径自动逆向截取关键层级，总长度严格限制在 72 字符以内，彻底免疫 Windows 260 字符路径溢出。
3. **凭据安全模型 (`credentials.json`)**：
   - 数据模型严格区分 `ApiKeyCredential` 与 `OAuthCredential`（支持 `access`, `refresh`, `expires`, `account_id`, `metadata`）；
   - 采用 `NamedTemporaryFile` + `chmod(0o600)` + `replace()` 保证写入原子性与跨平台权限安全；
   - 在内存中使用每凭据独立的 `asyncio.Lock()` 串行化 Token 刷新，消灭网络并发抖动与竞态刷新。
4. **安全沙箱机制**：
   - 严禁从项目目录加载 `credentials.json` 或 `providers.json`，防止克隆未知代码库时端点被劫持或 Token 被窃取。

---

## 三、my-pi-agent 用户主目录拓扑规范 (`~/.my-pi-agent/`)

我们将融合 Pi 的极简直观与 Tau 的严谨哈希安全，确立 `my-pi-agent` 官方产品级用户主目录规范：

```text
~/.my-pi-agent/
├── auth.json                   # ⭐ 全局统一凭证中心 (API Keys & OAuth Tokens, 权限 0600)
├── auth.json.lock              # 凭证读写与刷新跨进程文件锁
├── settings.json               # ⭐ 全局用户偏好配置 (默认模型、思考深度、UI 主题、代理等)
│
├── sessions/                   # ⭐ 集中式历史会话存储中心 (按工作区散列隔离)
│   └── <project-slug>-<hash>/  # 单个工作区的专属会话归档目录
│       ├── default.jsonl       # 当前工作区默认/最近会话 DAG 树
│       └── <timestamp>_<id>.jsonl # 归档历史会话
│
├── skills/                     # ⭐ 用户全局技能包目录 (遵从 Agent Skills 规范)
│   └── <skill-name>/
│       └── SKILL.md
│
├── prompts/                    # 用户全局自定义 Prompt 模板
├── themes/                     # 用户自定义 TUI 调色盘 JSON
├── extensions/                 # 用户全局自定义 Python 扩展
│
└── logs/                       # 诊断与审计日志
    └── agent.log
```

---

## 四、路径调度中心规范 (`AgentPaths`)

在 `src/my_coding_agent/paths.py` 中实现单一事实来源类 `AgentPaths`：

```python
"""AgentPaths: 统一管理全局用户目录与项目本地资源的路径调度中心。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AgentPaths:
    """集中解析与管理 my-pi-agent 的全局与项目级路径。"""

    home: Path = field(
        default_factory=lambda: Path(
            os.environ.get("MY_AGENT_HOME")
            or Path.home() / ".my-pi-agent"
        ).resolve()
    )
    agents_home: Path = field(
        default_factory=lambda: (Path.home() / ".agents").resolve()
    )

    # ── 全局资源路径 ──
    @property
    def auth_path(self) -> Path:
        return self.home / "auth.json"

    @property
    def auth_lock_path(self) -> Path:
        return self.home / "auth.json.lock"

    @property
    def settings_path(self) -> Path:
        return self.home / "settings.json"

    @property
    def sessions_dir(self) -> Path:
        return self.home / "sessions"

    @property
    def skills_dir(self) -> Path:
        return self.home / "skills"

    @property
    def prompts_dir(self) -> Path:
        return self.home / "prompts"

    @property
    def themes_dir(self) -> Path:
        return self.home / "themes"

    @property
    def extensions_dir(self) -> Path:
        return self.home / "extensions"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    # ── 项目局部路径 ──
    def project_agent_dir(self, cwd: Path) -> Path:
        return cwd / ".my-pi-agent"

    def project_settings_path(self, cwd: Path) -> Path:
        return self.project_agent_dir(cwd) / "settings.json"

    def project_skills_dir(self, cwd: Path) -> Path:
        return self.project_agent_dir(cwd) / "skills"

    def project_agents_skills_dir(self, cwd: Path) -> Path:
        return cwd / ".agents" / "skills"

    # ── 会话分区映射算法 (Tau Slug + Hash 优化版) ──
    def project_session_dir(self, cwd: Path) -> Path:
        """根据项目 cwd 计算全局唯一的 sessions/<slug>-<hash> 目录。"""
        resolved = cwd.resolve()
        digest = sha256(str(resolved).encode("utf-8")).hexdigest()[:6]
        slug = self._slugify_path(resolved)
        target = self.sessions_dir / f"{slug}-{digest}"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def default_session_path(self, cwd: Path) -> Path:
        return self.project_session_dir(cwd) / "default.jsonl"

    def ensure_directories(self) -> None:
        """初次启动自动建巢，静默初始化目录骨架。"""
        for d in (self.home, self.sessions_dir, self.skills_dir, self.prompts_dir, self.themes_dir, self.extensions_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _slugify_path(path: Path, max_length: int = 48) -> str:
        parts = [p for p in path.parts if p not in (path.anchor, "")]
        try:
            rel = path.relative_to(Path.home())
            parts = ["home", *rel.parts]
        except ValueError:
            pass
        normalized = [
            clean for p in parts
            if (clean := re.sub(r"[^a-zA-Z0-9._-]+", "-", p).strip(".-_").lower())
        ]
        slug = "-".join(normalized)
        if len(slug) <= max_length:
            return slug or "project"
        # 超过限制逆向保留最具体目录
        suffix_parts: list[str] = []
        cur_len = 0
        for p in reversed(normalized):
            if cur_len + len(p) + 1 > max_length:
                break
            suffix_parts.append(p)
            cur_len += len(p) + 1
        return "-".join(reversed(suffix_parts)) or slug[-max_length:].strip("-")
```

---

## 五、鉴权与凭证中心规范 (`auth.json`)

### 5.1 存储数据模型

在 `src/my_agent_llm/auth/schema.py` 中建立 Pydantic 模型：

```python
class CredentialType(str, Enum):
    API_KEY = "api_key"
    OAUTH = "oauth"

class ApiKeyCredential(BaseModel):
    type: Literal[CredentialType.API_KEY] = CredentialType.API_KEY
    key: str                                    # 支持明文、"$ENV_VAR"、"!command"
    base_url: str | None = None
    env: dict[str, str] = Field(default_factory=dict)

    def resolve_key(self) -> str:
        raw = self.key.strip()
        if raw.startswith("!"):
            res = subprocess.run(raw[1:].strip(), shell=True, capture_output=True, text=True, check=True)
            return res.stdout.strip()
        if raw.startswith("$"):
            var_name = raw[1:].strip("{}")
            return os.environ.get(var_name, "")
        return raw

class OAuthCredential(BaseModel):
    type: Literal[CredentialType.OAUTH] = CredentialType.OAUTH
    access: str                                 # Bearer Access Token
    refresh: str                                # Refresh Token
    expires: int = 0                            # 到期时间戳 (ms)
    project_id: str = "aicode-consumers"
    email: str | None = None
    client_id: str | None = None
    client_secret: str | None = None

    def is_expired(self, buffer_ms: int = 300_000) -> bool:
        if self.expires <= 0:
            return False
        return self.expires <= int(time.time() * 1000) + buffer_ms

class AuthStore(BaseModel):
    version: int = 1
    active_profiles: dict[str, str] = Field(default_factory=dict) # {"antigravity": "work", "openai": "default"}
    providers: dict[str, dict[str, ApiKeyCredential | OAuthCredential]] = Field(default_factory=dict)
```

### 5.2 兼容平铺简写格式

若用户直接手动编写简版 `auth.json`：

```json
{
  "deepseek": {
    "type": "api_key",
    "key": "sk-xxxxxx"
  },
  "antigravity": {
    "type": "oauth",
    "access": "ya29.xxxx",
    "refresh": "1//xxxx",
    "expires": 1789401004417
  }
}
```

`AuthManager` 自动将其规范化为 `providers[provider]["default"]`，保持极简用户手写体验。

### 5.3 凭据解析与优先级阶梯

当 Agent 需要连接某个 Provider 时，严格遵循以下解析流水线：

1. **CLI 参数覆盖**：启动显式 `--api-key <key>`；
2. **工作区项目级 `.env`**：当前工作区的 `.env`（`OPENAI_API_KEY`、`DEEPSEEK_API_KEY` 等）；
3. **全局凭据中心**：`~/.my-pi-agent/auth.json` 对应 Provider 的当前 Active Profile；
4. **系统环境变量**：操作系统全局环境变量；
5. **报错指引**：若均未提供，触发友好拦截并在终端提示使用 `/login`。

### 5.4 Antigravity OAuth 内置公共客户端与刷新时序

内置 Google Cloud Code Assist 官方标准公开客户端参数，消除对本地环境变量的强制依赖：

- **Client ID**: `<GOOGLE_CLIENT_ID>`
- **Client Secret**: `<GOOGLE_CLIENT_SECRET>`
- **Token Endpoint**: `https://oauth2.googleapis.com/token`
- **刷新时机**：当 `expires <= now + 5分钟` 时，自动发起异步刷新请求，并由 `NamedTemporaryFile` + `0o600` 权限原子替换写入 `auth.json`。

---

## 六、配置系统规范 (`settings.json`)

### 6.1 配置数据模型 (`Settings`)

在 `src/my_coding_agent/settings.py` 中定义强类型模型：

```python
class Settings(BaseModel):
    # ── 默认模型与思考深度 ──
    default_provider: str = "openai"
    default_model: str = "deepseek-flash"
    default_thinking_level: Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"] = "off"
    model_thinking_levels: dict[str, str] = Field(default_factory=dict) # {"openai/o3-mini": "medium"}

    # ── UI 表现层 ──
    theme: str = "dark"
    quiet_startup: bool = False
    editor_padding_x: int = 0
    show_hardware_cursor: bool = False

    # ── 网络与代理 (特权级：仅全局生效) ──
    http_proxy: str | None = None

    # ── 会话与压缩管线 ──
    compaction: CompactionSettings = Field(default_factory=CompactionSettings)
    auto_save_session: bool = True

    # ── 权限与安全 ──
    default_permission_mode: Literal["review", "yolo", "strict"] = "review"
    project_trust: Literal["ask", "always", "never"] = "ask"
```

### 6.2 级联覆盖规则

1. **基础值**：代码内置的默认常量；
2. **全局覆盖**：读取 `~/.my-pi-agent/settings.json`；
3. **项目覆盖**：若项目安全可信，读取 `<workspace>/.my-pi-agent/settings.json`；
4. **合并算法**：
   - 字典/子对象进行递归深拷贝合并；
   - 列表/数组整体替换；
   - `http_proxy`、`project_trust` 等安全敏感字段**忽略项目级配置**，防止跨站/恶意仓库劫持流量。

---

## 七、交互命令体系设计 (`/login`, `/settings`, `/session`)

在前端 TUI (`tui/src/app.ts`) 与 RPC 门面中打通产品级交互：

### 1. `/login` 命令

- **`/login`**（无参）：列出当前所有 Provider 的凭证状态与生效账号；
- **`/login deepseek <key>`** 或 **`/login openai <key>`**：
  直接将 API Key 保存至 `~/.my-pi-agent/auth.json`；
- **`/login antigravity`**：
  - 终端启动本地异步 Loopback 回调服务器（端口 `51121`）；
  - 自动唤起浏览器打开 Google OAuth 授权页；
  - 收到授权回调后自动换取 Token 并存入 `~/.my-pi-agent/auth.json`，完成零门槛登录。

### 2. `/settings` 命令

- 查看或就地修改配置（如 `/settings model deepseek-chat` 或 `/settings theme dark`），自动持久化到 `~/.my-pi-agent/settings.json`。

### 3. `/session` 与 `my-agent -c`

- **`/session`**：显示当前会话所属的全局存储路径、会话 ID、Token 统计与消息总数；
- **`my-agent -c`**：一键续接当前工作区的最新历史会话；
- **`my-agent -r`**：列出当前工作区的所有历史会话，提供快速切换选择器。

---

## 八、实施路线图 (Implementation Roadmap)

| 阶段 | 核心任务 | 交付物与验证 |
| :--- | :--- | :--- |
| **Phase 1: 路径中心与目录建巢** | 实现 `src/my_coding_agent/paths.py`（`AgentPaths`），支持 Slug + SHA256 会话分区与自动初始化 | 单元测试验证路径映射与跨平台路径安全 |
| **Phase 2: 独立凭据中心 (`AuthManager`)** | 实现 `src/my_agent_llm/auth/`，支持 `auth.json` 强类型模型、Profile 管理与 Antigravity 异步刷新 | 单元测试验证 Token 序列化、过期刷新与文件原子落盘 |
| **Phase 3: 级联配置系统 (`Settings`)** | 实现 `src/my_coding_agent/settings.py`，完成全局与项目级 `settings.json` 深度合并与特权键保护 | 单元测试验证配置层叠与无效键防御 |
| **Phase 4: 会话存储脱敏迁移** | 将 `rpc_server.py` 的会话存储重构为 `AgentPaths.default_session_path(cwd)`，彻底消灭工程目录 `.my_agent_core/` | 启动测试验证工作区内零脏文件生成 |
| **Phase 5: TUI `/login` 与终端体验整合** | 在 TUI 中接入 `/login`（API Key 快速绑定与 Antigravity 授权引导）及状态回显 | 端到端测试验证登录与热重载 |
