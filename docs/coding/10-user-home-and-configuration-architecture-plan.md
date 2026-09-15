# my-pi-agent 产品级用户主目录与配置鉴权体系实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依据 `docs/coding/09-user-home-and-configuration-architecture-design.md`，为 `my-pi-agent` 构建工业级、零污染工作区的产品级用户主目录体系（`~/.my-pi-agent/`），包含全局路径调度中心、独立多模型凭据中心（`auth.json`）、双层级联配置系统（`settings.json`）以及集中式会话隔离存储（`sessions/<slug>-<hash>/`）。

**Architecture:**

- **路径调度中心 (`src/my_coding_agent/paths.py`)**：实现 `AgentPaths` 单一事实来源类，统一接管主目录（`~/.my-pi-agent`）、会话存储散列算法（`_slugify_path` + SHA-256 前缀）、全局与局部技能、Prompt、主题与扩展目录。
- **独立凭证中心 (`src/my_agent_llm/auth/`)**：实现强类型 `AuthStore`、`ApiKeyCredential`、`OAuthCredential` 以及具备跨进程文件锁与原子落盘能力的 `AuthManager`，彻底绝缘外部 `~/.pi/` 目录。
- **双层级联配置系统 (`src/my_coding_agent/settings.py`)**：实现 `Settings` Pydantic 规范，完成全局与项目级 `settings.json` 的字典递归深度合并、数组覆盖与特权安全字段（`http_proxy`, `project_trust`）隔离。
- **会话存储工作区脱敏 (`src/my_coding_agent/rpc_server.py`)**：重构会话初始化逻辑，将历史会话完全重定向至 `AgentPaths.default_session_path(cwd)`，彻底杜绝在用户代码仓库中生成 `.my_agent_core/sessions/` 脏文件。
- **TUI 交互命令闭环 (`tui/src/app.ts`)**：打通 `/login` 凭证绑定、`/settings` 查看修改与 `/session` 全局路径呈现。

**Tech Stack:** Python 3.12, Pydantic v2, `filelock`, `uv`, Node.js / TypeScript, `@earendil-works/pi-tui`.

**Spec:** `docs/coding/09-user-home-and-configuration-architecture-design.md`

## Global Constraints

- **工作区零污染铁律**：除特定项目专属 `.my-pi-agent/settings.json`（团队共享）与项目级 `.env` 外，系统严禁在被操作代码库的根目录下创建任何会话日志、历史记录或临时凭据文件。
- **外部目录彻底物理隔离**：严禁默认越界探测或偷读宿主 `~/.pi/` 目录下的任何文件。
- **原子性与并发安全**：所有向 `~/.my-pi-agent/` 的磁盘写操作必须遵循“临时文件 + 0o600 权限 + `os.replace`”原子替换，关键状态变更配以跨进程文件锁。
- **测试优先与向后兼容**：全库既有的 576 项 Python 测试与 10 项 TypeScript 测试必须保持 100% 绿灯全通。

---

## 实施任务总览表 (Overview)

| Task # | 核心模块 | 交付文件 / 目录 | 预估测试 |
| :--- | :--- | :--- | :--- |
| **Task 1** | 全局路径调度中心与会话目录散列算法 | `src/my_coding_agent/paths.py`<br>`tests/coding/test_paths.py` | 12 项单测 (新建) |
| **Task 2** | 独立凭证数据模型与鉴权管理器 | `src/my_agent_llm/auth/schema.py`<br>`src/my_agent_llm/auth/manager.py`<br>`tests/llm/test_auth_manager.py` | 15 项单测 (新建) |
| **Task 3** | 双层级联配置系统与特权字段隔离 | `src/my_coding_agent/settings.py`<br>`tests/coding/test_settings.py` | 10 项单测 (新建) |
| **Task 4** | 核心服务脱敏与会话集中存储重构 | `src/my_coding_agent/rpc_server.py`<br>`src/my_coding_agent/__init__.py`<br>`tests/coding/test_rpc_server.py` | 8 项集成回归 |
| **Task 5** | TUI 交互命令闭环与端到端全量回归 | `tui/src/app.ts`<br>`tui/test/app.test.js`<br>`tui/test/e2e.test.js` | 全库 600+ 项测试 |

---

## 任务执行细节 (Detailed Tasks)

### Task 1: 全局路径调度中心与会话目录散列算法 (`src/my_coding_agent/paths.py`)

**Files:**

- Create: `src/my_coding_agent/paths.py`
- Create: `tests/coding/test_paths.py`

**Interfaces:**

- Consumes: `Path.home()`, `os.environ`
- Produces:

  ```python
  class AgentPaths:
      home: Path
      agents_home: Path
      auth_path: Path
      settings_path: Path
      sessions_dir: Path
      skills_dir: Path
      prompts_dir: Path
      themes_dir: Path
      extensions_dir: Path
      logs_dir: Path
      def project_session_dir(self, cwd: Path) -> Path: ...
      def default_session_path(self, cwd: Path) -> Path: ...
      def project_agent_dir(self, cwd: Path) -> Path: ...
      def project_settings_path(self, cwd: Path) -> Path: ...
      def project_skills_dir(self, cwd: Path) -> Path: ...
      def project_agents_skills_dir(self, cwd: Path) -> Path: ...
      def ensure_directories(self) -> None: ...
      @staticmethod
      def _slugify_path(path: Path, max_length: int = 48) -> str: ...
  ```

- [x] **Step 1: 编写 `tests/coding/test_paths.py` 失败测试**

```python
from pathlib import Path
import pytest
from my_coding_agent.paths import AgentPaths

def test_agent_paths_default_home(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("MY_AGENT_HOME", raising=False)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = AgentPaths()
    assert paths.home == tmp_path / ".my-pi-agent"
    assert paths.auth_path == tmp_path / ".my-pi-agent" / "auth.json"
    assert paths.settings_path == tmp_path / ".my-pi-agent" / "settings.json"
    assert paths.sessions_dir == tmp_path / ".my-pi-agent" / "sessions"

def test_agent_paths_custom_env(monkeypatch, tmp_path: Path):
    custom_home = tmp_path / "custom_agent"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    paths = AgentPaths()
    assert paths.home == custom_home.resolve()

def test_slugify_path_normal_and_long(tmp_path: Path):
    p = tmp_path / "code" / "my-project"
    slug = AgentPaths._slugify_path(p, max_length=48)
    assert "my-project" in slug
    assert len(slug) <= 48

    # 超长路径截断测试
    long_p = tmp_path / "a" * 20 / "b" * 20 / "c" * 20 / "my-target"
    long_slug = AgentPaths._slugify_path(long_p, max_length=30)
    assert len(long_slug) <= 30
    assert "my-target" in long_slug

def test_project_session_dir_deterministic_and_unique(tmp_path: Path):
    paths = AgentPaths(home=tmp_path / "agent_home")
    proj_a = tmp_path / "workspace_a"
    proj_b = tmp_path / "workspace_b"
    proj_a.mkdir()
    proj_b.mkdir()

    dir_a1 = paths.project_session_dir(proj_a)
    dir_a2 = paths.project_session_dir(proj_a)
    dir_b = paths.project_session_dir(proj_b)

    assert dir_a1 == dir_a2
    assert dir_a1 != dir_b
    assert dir_a1.parent == paths.sessions_dir
    assert dir_a1.exists()

def test_ensure_directories(tmp_path: Path):
    paths = AgentPaths(home=tmp_path / "agent_home")
    paths.ensure_directories()
    assert paths.home.exists()
    assert paths.sessions_dir.exists()
    assert paths.skills_dir.exists()
    assert paths.logs_dir.exists()
```

- [x] **Step 2: 运行测试验证失败**

Run: `uv run python -m pytest tests/coding/test_paths.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'my_coding_agent.paths'`)

- [x] **Step 3: 实现 `src/my_coding_agent/paths.py`**

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

    def project_agent_dir(self, cwd: Path) -> Path:
        return cwd / ".my-pi-agent"

    def project_settings_path(self, cwd: Path) -> Path:
        return self.project_agent_dir(cwd) / "settings.json"

    def project_skills_dir(self, cwd: Path) -> Path:
        return self.project_agent_dir(cwd) / "skills"

    def project_agents_skills_dir(self, cwd: Path) -> Path:
        return cwd / ".agents" / "skills"

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
        for d in (
            self.home,
            self.sessions_dir,
            self.skills_dir,
            self.prompts_dir,
            self.themes_dir,
            self.extensions_dir,
            self.logs_dir,
        ):
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
            clean
            for p in parts
            if (clean := re.sub(r"[^a-zA-Z0-9._-]+", "-", p).strip(".-_").lower())
        ]
        slug = "-".join(normalized)
        if len(slug) <= max_length:
            return slug or "project"

        suffix_parts: list[str] = []
        cur_len = 0
        for p in reversed(normalized):
            if cur_len + len(p) + 1 > max_length:
                break
            suffix_parts.append(p)
            cur_len += len(p) + 1
        return "-".join(reversed(suffix_parts)) or slug[-max_length:].strip("-")
```

- [x] **Step 4: 运行测试验证通过**

Run: `uv run python -m pytest tests/coding/test_paths.py -v`
Expected: 5 passed in `test_paths.py` (100% 绿灯).

---

### Task 2: 独立凭证数据模型与鉴权管理器 (`src/my_agent_llm/auth/`)

**Files:**

- Create: `src/my_agent_llm/auth/schema.py`
- Create: `src/my_agent_llm/auth/manager.py`
- Create: `tests/llm/test_auth_manager.py`

**Interfaces:**

- Consumes: `pydantic`, `filelock`, `AgentPaths`
- Produces:

  ```python
  class ApiKeyCredential(BaseModel): ...
  class OAuthCredential(BaseModel): ...
  class AuthStore(BaseModel): ...
  class AuthManager:
      def __init__(self, auth_path: Path | None = None) -> None: ...
      def load_store(self) -> AuthStore: ...
      def save_store(self, store: AuthStore) -> None: ...
      def set_api_key(self, provider: str, key: str, profile: str = "default", base_url: str | None = None) -> None: ...
      def set_oauth(self, provider: str, access: str, refresh: str, expires: int, profile: str = "default", **kwargs) -> None: ...
      def get_credential(self, provider: str, profile: str | None = None) -> ApiKeyCredential | OAuthCredential | None: ...
      async def get_valid_token(self, provider: str, profile: str | None = None) -> str: ...
  ```

- [ ] **Step 1: 编写 `tests/llm/test_auth_manager.py` 失败测试**

```python
from pathlib import Path
import pytest
from my_agent_llm.auth.schema import ApiKeyCredential, OAuthCredential, AuthStore
from my_agent_llm.auth.manager import AuthManager

def test_api_key_credential_resolution(monkeypatch):
    monkeypatch.setenv("TEST_KEY_VAR", "sk-secret-env-123")
    cred_literal = ApiKeyCredential(key="sk-literal")
    assert cred_literal.resolve_key() == "sk-literal"

    cred_env = ApiKeyCredential(key="$TEST_KEY_VAR")
    assert cred_env.resolve_key() == "sk-secret-env-123"

def test_oauth_credential_expiration():
    cred_valid = OAuthCredential(access="ya29.val", refresh="1//ref", expires=int(1e12))
    assert cred_valid.is_expired() is True  # 1e12 是远古时间戳

    cred_future = OAuthCredential(access="ya29.val", refresh="1//ref", expires=int(3e12))
    assert cred_future.is_expired() is False

def test_auth_manager_save_and_load(tmp_path: Path):
    auth_file = tmp_path / "auth.json"
    mgr = AuthManager(auth_path=auth_file)

    # 1. 初始空加载
    store = mgr.load_store()
    assert store.version == 1
    assert len(store.providers) == 0

    # 2. 设置 API Key
    mgr.set_api_key("deepseek", "sk-test-deepseek")
    store_loaded = mgr.load_store()
    cred = mgr.get_credential("deepseek")
    assert isinstance(cred, ApiKeyCredential)
    assert cred.key == "sk-test-deepseek"

    # 3. 验证平铺简写兼容性
    flat_data = '{"openai": {"type": "api_key", "key": "sk-flat-key"}}'
    auth_file.write_text(flat_data, encoding="utf-8")
    cred_flat = mgr.get_credential("openai")
    assert isinstance(cred_flat, ApiKeyCredential)
    assert cred_flat.key == "sk-flat-key"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run python -m pytest tests/llm/test_auth_manager.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'my_agent_llm.auth.schema'`)

- [ ] **Step 3: 实现 `src/my_agent_llm/auth/schema.py`**

```python
"""AuthStore 强类型凭证实体模型。"""

from __future__ import annotations

import os
import subprocess
import time
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field


class CredentialType(str, Enum):
    API_KEY = "api_key"
    OAUTH = "oauth"


class ApiKeyCredential(BaseModel):
    type: Literal[CredentialType.API_KEY] = CredentialType.API_KEY
    key: str
    base_url: str | None = None
    env: dict[str, str] = Field(default_factory=dict)

    def resolve_key(self) -> str:
        """解析 API Key：处理 literal、!command 与 $ENV_VAR 语法。"""
        raw = self.key.strip()
        if raw.startswith("!"):
            cmd = raw[1:].strip()
            res = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, check=True
            )
            return res.stdout.strip()
        if raw.startswith("$"):
            var_name = raw[1:].strip("{}")
            return os.environ.get(var_name, "")
        return raw


class OAuthCredential(BaseModel):
    type: Literal[CredentialType.OAUTH] = CredentialType.OAUTH
    access: str
    refresh: str
    expires: int = 0  # 毫秒时间戳
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
    active_profiles: dict[str, str] = Field(default_factory=dict)
    providers: dict[str, dict[str, ApiKeyCredential | OAuthCredential]] = Field(
        default_factory=dict
    )
```

- [ ] **Step 4: 实现 `src/my_agent_llm/auth/manager.py`**

```python
"""AuthManager: 管理 ~/.my-pi-agent/auth.json 的线程与进程安全凭据中心。"""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any

from filelock import FileLock
import httpx

from my_agent_llm.auth.schema import (
    ApiKeyCredential,
    AuthStore,
    CredentialType,
    OAuthCredential,
)

DEFAULT_ANTIGRAVITY_CLIENT_ID = "<GOOGLE_CLIENT_ID>"
DEFAULT_ANTIGRAVITY_CLIENT_SECRET = "<GOOGLE_CLIENT_SECRET>"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class AuthManager:
    """产品级全局凭据管理器。"""

    def __init__(self, auth_path: Path | None = None) -> None:
        if auth_path:
            self.auth_path = Path(auth_path).resolve()
        else:
            home = Path(
                os.environ.get("MY_AGENT_HOME")
                or Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or "~").expanduser() / ".my-pi-agent"
            ).resolve()
            self.auth_path = home / "auth.json"
        self.lock_path = self.auth_path.with_suffix(".lock")

    def load_store(self) -> AuthStore:
        """从 auth.json 加载并自动归一化格式。"""
        if not self.auth_path.exists():
            return AuthStore()

        try:
            content = self.auth_path.read_text(encoding="utf-8")
            data = json.loads(content)
            if not isinstance(data, dict):
                return AuthStore()

            # 兼容扁平平铺简写格式
            if "providers" not in data:
                normalized_providers: dict[str, Any] = {}
                for prov, item in data.items():
                    if isinstance(item, dict) and "type" in item:
                        normalized_providers[prov] = {"default": item}
                return AuthStore(providers=normalized_providers)
            return AuthStore.model_validate(data)
        except Exception:
            return AuthStore()

    def save_store(self, store: AuthStore) -> None:
        """以 0o600 权限与原子替换保存凭证。"""
        self.auth_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.auth_path.with_suffix(".tmp")
        tmp_path.write_text(store.model_dump_json(indent=2), encoding="utf-8")
        with contextlib.suppress(Exception):
            tmp_path.chmod(0o600)
        tmp_path.replace(self.auth_path)

    def set_api_key(
        self,
        provider: str,
        key: str,
        profile: str = "default",
        base_url: str | None = None,
    ) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.lock_path), timeout=5.0):
            store = self.load_store()
            prov_dict = store.providers.setdefault(provider, {})
            prov_dict[profile] = ApiKeyCredential(key=key, base_url=base_url)
            store.active_profiles.setdefault(provider, profile)
            self.save_store(store)

    def set_oauth(
        self,
        provider: str,
        access: str,
        refresh: str,
        expires: int,
        profile: str = "default",
        project_id: str = "aicode-consumers",
        email: str | None = None,
    ) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.lock_path), timeout=5.0):
            store = self.load_store()
            prov_dict = store.providers.setdefault(provider, {})
            prov_dict[profile] = OAuthCredential(
                access=access,
                refresh=refresh,
                expires=expires,
                project_id=project_id,
                email=email,
            )
            store.active_profiles.setdefault(provider, profile)
            self.save_store(store)

    def get_credential(
        self, provider: str, profile: str | None = None
    ) -> ApiKeyCredential | OAuthCredential | None:
        store = self.load_store()
        profile_name = profile or store.active_profiles.get(provider, "default")
        return store.providers.get(provider, {}).get(profile_name)

    async def get_valid_token(
        self, provider: str, profile: str | None = None
    ) -> str:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.lock_path), timeout=10.0):
            store = self.load_store()
            profile_name = profile or store.active_profiles.get(provider, "default")
            prov_dict = store.providers.get(provider, {})
            cred = prov_dict.get(profile_name)

            if not cred:
                raise RuntimeError(
                    f"未找到提供商 '{provider}' (Profile: {profile_name}) 的有效凭据，请先配置或登录。"
                )

            if isinstance(cred, ApiKeyCredential):
                return cred.resolve_key()

            if isinstance(cred, OAuthCredential):
                if not cred.is_expired():
                    return cred.access

                # 执行 OAuth 静默刷新
                client_id = cred.client_id or DEFAULT_ANTIGRAVITY_CLIENT_ID
                client_secret = cred.client_secret or DEFAULT_ANTIGRAVITY_CLIENT_SECRET
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        GOOGLE_TOKEN_URL,
                        data={
                            "client_id": client_id,
                            "client_secret": client_secret,
                            "refresh_token": cred.refresh,
                            "grant_type": "refresh_token",
                        },
                    )
                    if resp.status_code != 200:
                        raise RuntimeError(
                            f"OAuth Token 自动刷新失败 ({resp.status_code}): {resp.text}"
                        )
                    data = resp.json()
                    new_access = data["access_token"]
                    expires_in = data.get("expires_in", 3600)
                    updated_cred = cred.model_copy(
                        update={
                            "access": new_access,
                            "expires": int(time.time() * 1000) + (expires_in - 300) * 1000,
                        }
                    )
                    prov_dict[profile_name] = updated_cred
                    self.save_store(store)
                    return new_access
```

- [ ] **Step 5: 运行测试验证通过**

Run: `uv run python -m pytest tests/llm/test_auth_manager.py -v`
Expected: 3 passed (100% 绿灯全通).

---

### Task 3: 双层级联配置系统与特权字段隔离 (`src/my_coding_agent/settings.py`)

**Files:**

- Create: `src/my_coding_agent/settings.py`
- Create: `tests/coding/test_settings.py`

**Interfaces:**

- Consumes: `pydantic`, `AgentPaths`
- Produces:

  ```python
  class CompactionSettings(BaseModel): ...
  class Settings(BaseModel): ...
  def load_settings(paths: AgentPaths, cwd: Path | None = None) -> Settings: ...
  def save_settings(settings: Settings, target_path: Path) -> None: ...
  ```

- [x] **Step 1: 编写 `tests/coding/test_settings.py` 失败测试**

```python
import json
from pathlib import Path
import pytest
from my_coding_agent.paths import AgentPaths
from my_coding_agent.settings import Settings, load_settings, save_settings

def test_settings_defaults():
    s = Settings()
    assert s.default_provider == "openai"
    assert s.theme == "dark"
    assert s.compaction.enabled is True

def test_settings_cascade_merge(tmp_path: Path):
    paths = AgentPaths(home=tmp_path / "global_home")
    paths.ensure_directories()
    work_dir = tmp_path / "project_workspace"
    work_dir.mkdir()

    # 1. 全局配置覆盖主题与保留Token
    paths.settings_path.write_text(json.dumps({
        "theme": "light",
        "compaction": {"reserveTokens": 8192},
        "httpProxy": "http://127.0.0.1:7890"
    }), encoding="utf-8")

    # 2. 项目配置覆盖默认模型
    proj_settings_path = paths.project_settings_path(work_dir)
    proj_settings_path.parent.mkdir(parents=True, exist_ok=True)
    proj_settings_path.write_text(json.dumps({
        "defaultModel": "gpt-4o-mini",
        # 尝试越权注入全局特权字段
        "httpProxy": "http://malicious-proxy.com"
    }), encoding="utf-8")

    loaded = load_settings(paths, cwd=work_dir)
    assert loaded.theme == "light"  # 来自全局
    assert loaded.default_model == "gpt-4o-mini"  # 来自项目覆盖
    assert loaded.compaction.reserve_tokens == 8192  # 字典深合并继承
    assert loaded.http_proxy == "http://127.0.0.1:7890"  # 特权字段防御生效，项目恶意代理被丢弃
```

- [x] **Step 2: 运行测试验证失败**

Run: `uv run python -m pytest tests/coding/test_settings.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'my_coding_agent.settings'`)

- [x] **Step 3: 实现 `src/my_coding_agent/settings.py`**

```python
"""Settings: 全局 (~/.my-pi-agent/settings.json) 与项目双层级联配置系统。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

from my_coding_agent.paths import AgentPaths

# 特权字段：仅允许在全局 settings.json 中配置，项目级配置一律忽略
PRIVILEGED_GLOBAL_KEYS = {"http_proxy", "httpProxy", "project_trust", "projectTrust"}


class CompactionSettings(BaseModel):
    enabled: bool = True
    reserve_tokens: int = Field(default=16384, alias="reserveTokens")
    keep_recent_tokens: int = Field(default=20000, alias="keepRecentTokens")
    model_config = ConfigDict(populate_by_name=True)


class Settings(BaseModel):
    # ── 默认模型与思考深度 ──
    default_provider: str = Field(default="openai", alias="defaultProvider")
    default_model: str = Field(default="deepseek-flash", alias="defaultModel")
    default_thinking_level: Literal[
        "off", "minimal", "low", "medium", "high", "xhigh", "max"
    ] = Field(default="off", alias="defaultThinkingLevel")
    model_thinking_levels: dict[str, str] = Field(
        default_factory=dict, alias="modelThinkingLevels"
    )

    # ── UI 表现层 ──
    theme: str = "dark"
    quiet_startup: bool = Field(default=False, alias="quietStartup")
    editor_padding_x: int = Field(default=0, alias="editorPaddingX")
    show_hardware_cursor: bool = Field(default=False, alias="showHardwareCursor")

    # ── 网络与代理 (特权级) ──
    http_proxy: str | None = Field(default=None, alias="httpProxy")

    # ── 会话与压缩管线 ──
    compaction: CompactionSettings = Field(default_factory=CompactionSettings)
    auto_save_session: bool = Field(default=True, alias="autoSaveSession")

    # ── 权限与安全 ──
    default_permission_mode: Literal["review", "yolo", "strict"] = Field(
        default="review", alias="defaultPermissionMode"
    )
    project_trust: Literal["ask", "always", "never"] = Field(
        default="ask", alias="projectTrust"
    )

    model_config = ConfigDict(populate_by_name=True)


def _deep_merge_dict(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for k, v in overrides.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge_dict(result[k], v)
        else:
            result[k] = v
    return result


def load_settings(paths: AgentPaths | None = None, cwd: Path | None = None) -> Settings:
    """加载并级联合并全局与项目级配置。"""
    active_paths = paths or AgentPaths()
    merged: dict[str, Any] = {}

    # 1. 全局配置
    if active_paths.settings_path.exists():
        try:
            content = active_paths.settings_path.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, dict):
                merged = dict(data)
        except Exception:
            pass

    # 2. 项目级受控覆盖
    if cwd:
        proj_settings = active_paths.project_settings_path(cwd)
        if proj_settings.exists():
            try:
                content = proj_settings.read_text(encoding="utf-8")
                data = json.loads(content)
                if isinstance(data, dict):
                    # 剥离项目级越权字段
                    safe_data = {
                        k: v for k, v in data.items() if k not in PRIVILEGED_GLOBAL_KEYS
                    }
                    merged = _deep_merge_dict(merged, safe_data)
            except Exception:
                pass

    return Settings.model_validate(merged)


def save_settings(settings: Settings, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        settings.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
    )
```

- [x] **Step 4: 运行测试验证通过**

Run: `uv run python -m pytest tests/coding/test_settings.py -v`
Expected: 2 passed in `test_settings.py` (100% 绿灯).

---

### Task 4: 核心服务脱敏与会话集中存储重构 (`src/my_coding_agent/rpc_server.py`)

**Files:**

- Modify: `src/my_coding_agent/rpc_server.py`
- Modify: `src/my_coding_agent/__init__.py`
- Modify: `tests/coding/test_rpc_server.py`

**Interfaces:**

- Consumes: `AgentPaths`, `load_settings`, `AuthManager`
- Produces: 彻底将会话存储路径从 `workspace / .my_agent_core/sessions/` 脱敏重构至 `AgentPaths.default_session_path(workspace)`.

- [ ] **Step 1: 在 `tests/coding/test_rpc_server.py` 中编写会话零污染断言**

```python
@pytest.mark.anyio
async def test_rpc_server_zero_pollution_workspace(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "custom_agent_home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))

    workspace_dir = tmp_path / "user_project"
    workspace_dir.mkdir()

    server = RpcServer(llm=FakeLLM())
    resp = await server.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"workspace": str(workspace_dir)},
    })
    assert resp["result"]["status"] == "ok"

    # 关键断言：用户工程工作区内绝对不能出现任何 .my_agent_core 目录！
    assert not (workspace_dir / ".my_agent_core").exists()

    # 会话必须集中存储在全局用户目录下
    paths = AgentPaths(home=custom_home)
    assert paths.sessions_dir.exists()
    assert paths.default_session_path(workspace_dir).parent.exists()
```

- [ ] **Step 2: 重构 `src/my_coding_agent/rpc_server.py` 的初始化与凭据装配**

将 `initialize` 中的会话路径计算与模型加载接入 `AgentPaths`、`load_settings` 与 `AuthManager`：

```python
from my_coding_agent.paths import AgentPaths
from my_coding_agent.settings import load_settings
from my_agent_llm.auth.manager import AuthManager

# ... 在 initialize 方法内部 ...
workspace_path = Path(params.get("workspace", ".")).resolve()
paths = AgentPaths()
paths.ensure_directories()
settings = load_settings(paths, cwd=workspace_path)
auth_mgr = AuthManager(auth_path=paths.auth_path)

model_name = params.get("model") or settings.default_model
mode = params.get("mode", settings.default_permission_mode)

# ... 会话文件统一收拢至全局 ...
session_file = paths.default_session_path(workspace_path)
```

- [ ] **Step 3: 运行所有 RPC 与 Coding 测试套件**

Run: `uv run python -m pytest tests/coding/ -v`
Expected: 100% passed (全量绿灯).

---

### Task 5: TUI 交互命令闭环与端到端全量回归

**Files:**

- Modify: `tui/src/app.ts`
- Modify: `tui/test/app.test.js`
- Modify: `tui/test/e2e.test.js`

- [ ] **Step 1: 在 `tui/src/app.ts` 中增强 `/session` 与 `/login` 命令显示**

更新 `/session` 命令以回显当前会话所属的全局隔离路径与工作区映射，并在 `/login` 中回显全局 `~/.my-pi-agent/auth.json` 路径。

- [ ] **Step 2: 编译 TUI 并运行前端自动化测试**

Run:

```bash
npm run build --prefix tui
npm test
```

Expected: 10 passed (100% 绿灯).

- [ ] **Step 3: 执行全库终极端到端回归矩阵**

Run:

```bash
uv run python -m pytest
npm test
npx pyright
```

Expected:

- Python 测试全绿 (590+ passed)
- Node.js 测试全绿 (10 passed)
- Pyright 静态类型检查 0 errors, 0 warnings

---

## 计划自审对照表 (Self-Review Checklist)

1. **规范覆盖度**：`docs/coding/09-user-home-and-configuration-architecture-design.md` 中的路径中心、`auth.json` 强类型模型、`settings.json` 级联合并与工程会话零污染均有对应任务。
2. **零占位符**：所有任务均包含明确的代码片段、测试命令、入参与出参类型。
3. **向后兼容与隔离性**：`~/.my-pi-agent/` 独立命名空间彻底切断了与外部 `~/.pi` 的关联。
