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
class AgentPaths:
    """集中式跨平台路径调度器。"""

    @classmethod
    def global_home(cls) -> Path:
        """全局配置主目录 ~/.my-pi-agent/"""
        return Path.home() / ".my-pi-agent"

    @classmethod
    def auth_file(cls) -> Path:
        """全局凭证库路径 ~/.my-pi-agent/auth.json"""
        return cls.global_home() / "auth.json"

    @classmethod
    def global_settings_file(cls) -> Path:
        """全局设置路径 ~/.my-pi-agent/settings.json"""
        return cls.global_home() / "settings.json"

    @classmethod
    def session_dir_for_workspace(cls, workspace: Path | str) -> Path:
        """针对特定工作区生成集中式隔离会话路径。"""
        slug = cls._slugify_workspace(workspace)
        return cls.global_home() / "sessions" / slug
```

### 1. 工作区路径散列算法 (`_slugify_workspace`)

为兼顾**人类可读性**并彻底解决 Windows 平台下的 **260 字符路径深度溢出 (MAX_PATH)**：

- 取当前工作区目录基名作为语义前缀（如 `my-react-app`）；
- 结合规范化绝对路径的 SHA-256 前 6 位哈希值作为防碰撞后缀；
- 生成类似 `my-react-app-32a29b` 的紧凑目录名，既便于运维排查，又具备绝对唯一性。

---

## 三、独立凭据中心 (`auth.json`) 与多源自愈绑定

`~/.my-pi-agent/auth.json` 采用独立的安全命名空间，并严格设置 `0o600` 文件权限（仅当前操作系统用户可读写）：

```json
{
  "openai": {
    "type": "api_key",
    "api_key": "sk-proj-...",
    "base_url": "https://api.openai.com/v1"
  },
  "deepseek": {
    "type": "api_key",
    "api_key": "sk-...",
    "base_url": "https://api.deepseek.com"
  },
  "anthropic": {
    "type": "api_key",
    "api_key": "sk-ant-..."
  },
  "antigravity": {
    "type": "oauth",
    "access_token": "ya29.a0...",
    "refresh_token": "1//04...",
    "expires_at": 1758000000
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
