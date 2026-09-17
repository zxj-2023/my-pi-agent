# 用户主目录、配置与凭据隔离体系规范 (`my_coding_agent.settings`)

- **定位**：跨项目集中式管理中心与零污染配置体系 (`src/my_coding_agent/paths.py`, `settings.py`)
- **设计标杆**：`@earendil-works/pi-coding-agent`、`tau` (`tau_coding.paths`)
- **核心原则**：工作区零污染（Zero-Pollution Workspace）、多模型凭据独立中心（`auth.json`）、双层级联配置（`settings.json`）、集中式散列会话持久化

---

## 一、架构愿景与产品级定位

作为一个面向全球开发者分发的生产级 Coding Agent 产品，必须杜绝在用户项目工作区随意生成临时日志或私有会话文件夹的粗糙行为，严格对齐工业级最佳实践：

```text
               用户任意项目工作区 (如 D:\code\my-react-app)
                                    │
                                    ▼ 运行 my-pi-agent
                                    │
                  工作区绝对零污染 (Zero Pollution!)
           git status 永远保持纯净，绝无未跟踪的 session 脏文件
                                    │
                                    ▼ 所有数据集中收敛
                用户全局主目录 (~/.my-pi-agent/)
```

### 1. 全局用户主目录全景布局 (`~/.my-pi-agent/`)

```text
~/.my-pi-agent/
├── auth.json                   # 多 Provider 认证凭据中心 (权限 0o600)
├── settings.json               # 用户全局默认行为配置 (主题、默认模型、思考等级)
├── trust.json                  # 项目安全信任数据库 (记录各工作区信任决策)
├── models-cache.json           # 动态拉取的模型目录与上下文窗口磁盘缓存 (4 小时 TTL)
└── sessions/                   # 集中式项目会话隔离存储
    ├── react-app-a89c4d/       # slugify 友好的工作区隔离目录 (逆向散列防溢出)
    │   ├── default.jsonl       # 默认会话 (原子追加式 DAG 树存储)
    │   ├── 2026-09-17_xxx.jsonl
    │   └── subagents/          # 子智能体衍生会话存储
    └── backend-api-f27b11/
        └── default.jsonl
```

---

## 二、统一路径调度中心 (`AgentPaths`)

在 `src/my_coding_agent/paths.py` 中，通过不可变数据模型集中管理所有全局与工作区相关路径：

```python
@dataclass(frozen=True, slots=True)
class AgentPaths:
    """集中解析与管理 my-pi-agent 的全局与项目级路径调度中心。"""

    home: Path = field(
        default_factory=lambda: Path(
            os.environ.get("MY_AGENT_HOME") or (Path.home() / ".my-pi-agent")
        ).resolve()
    )
    agents_home: Path = field(default_factory=lambda: (Path.home() / ".agents").resolve())

    # ── 全局资源路径 ──
    @property
    def auth_path(self) -> Path:
        """全局凭证库路径 ~/.my-pi-agent/auth.json"""
        return self.home / "auth.json"

    @property
    def auth_lock_path(self) -> Path:
        """全局凭证跨进程文件锁 ~/.my-pi-agent/auth.json.lock"""
        return self.home / "auth.json.lock"

    @property
    def settings_path(self) -> Path:
        """全局设置路径 ~/.my-pi-agent/settings.json"""
        return self.home / "settings.json"

    @property
    def sessions_dir(self) -> Path:
        """全局会话集中存储目录 ~/.my-pi-agent/sessions/"""
        return self.home / "sessions"

    @property
    def skills_dir(self) -> Path:
        return self.home / "skills"

    @property
    def prompts_dir(self) -> Path:
        return self.home / "prompts"

    # ── 会话分区映射算法 (Tau Slug + Hash 优化版) ──
    def project_session_dir(self, cwd: Path) -> Path:
        """根据项目 cwd 计算全局唯一的 sessions/<slug>-<hash> 目录。"""
        resolved = cwd.resolve()
        digest = sha256(str(resolved).encode("utf-8")).hexdigest()[:6]
        slug = self._slugify_path(resolved)
        target = self.sessions_dir / f"{slug}-{digest}"
        target.mkdir(parents=True, exist_ok=True)
        return target
```

### 1. 工作区路径散列算法 (`_slugify_path`)

为兼顾**人类可读性**并彻底解决 Windows 平台下的 **260 字符路径深度溢出 (MAX_PATH)**：

- 取当前工作区目录规范化分段作为语义前缀（如 `my-react-app`）；
- 结合规范化绝对路径的 SHA-256 前 6 位哈希值作为防碰撞后缀；
- 生成类似 `my-react-app-32a29b` 的紧凑目录名，既便于运维排查，又具备绝对唯一性。

---

## 三、独立凭据中心 (`auth.json`) 与多源自愈绑定

`~/.my-pi-agent/auth.json` 采用独立的安全命名空间，由 `AuthManager` 施加跨进程文件锁（`auth.json.lock`）保护，并严格设置 `0o600` 文件权限（仅当前操作系统用户可读写）。

数据结构严格映射 `src/my_agent_llm/auth/schema.py` 中的强类型 Pydantic 模型（`ApiKeyCredential` 使用 `key` 字段；`OAuthCredential` 使用 `access`、`refresh`、`expires` 字段）：

```json
{
  "version": 1,
  "active_profiles": {
    "openai": "default",
    "deepseek": "default",
    "anthropic": "default",
    "antigravity": "default"
  },
  "providers": {
    "openai": {
      "default": {
        "type": "api_key",
        "key": "sk-proj-...",
        "base_url": "https://api.openai.com/v1"
      }
    },
    "deepseek": {
      "default": {
        "type": "api_key",
        "key": "sk-...",
        "base_url": "https://api.deepseek.com"
      }
    },
    "anthropic": {
      "default": {
        "type": "api_key",
        "key": "sk-ant-..."
      }
    },
    "antigravity": {
      "default": {
        "type": "oauth",
        "access": "ya29.a0...",
        "refresh": "1//04...",
        "expires": 1758000000
      }
    }
  }
}
```

同时，`AuthManager.load_store()` 具备自动归一化能力，亦向下无缝兼容扁平平铺简写格式：

```json
{
  "deepseek": {
    "type": "api_key",
    "key": "sk-...",
    "base_url": "https://api.deepseek.com"
  },
  "antigravity": {
    "type": "oauth",
    "access": "ya29.a0...",
    "refresh": "1//04...",
    "expires": 1758000000
  }
}
```

### 1. 凭据优先级与多源探测顺序

系统在解析大模型认证凭据时，按以下由高到低的优先级链式自愈探测：

1. **当前工作区 `.env`**：优先用于临时项目覆盖或自动化测试；
2. **进程环境变量**：如 `OPENAI_API_KEY`、`DEEPSEEK_API_KEY`、`ANTHROPIC_API_KEY`；
3. **主目录 `~/.my-pi-agent/auth.json`**：标准产品凭据库；
4. **宿主兼容探测 `~/.pi/agent/auth.json`**：若用户已在官方 Pi 登录过 Antigravity 等服务，支持无感一键绑定与复用。

---

## 四、双层级联配置系统 (`settings.json`)

系统采用深层字典合并（Deep Merge）算法实现配置级联：

1. **全局默认层**：`~/.my-pi-agent/settings.json` 定义个人偏好（默认模型、思考等级、配色主题等）；
2. **团队项目层**：`<workspace>/.my-pi-agent/settings.json`（可纳入版本控制，共享项目级技能、MCP 规则）；
3. **命令行启动层**：CLI 启动参数（如 `-m gpt-4o --thinking high`）拥有最高优先生效权；
4. **安全约束**：特权键（如 `httpProxy`、`projectTrust`）强制锁定仅能在全局层配置，杜绝恶意第三方代码仓库越权。
