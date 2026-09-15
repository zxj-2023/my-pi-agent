# my-pi-agent 对标 Pi 核心命令与输入宏系统实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依据 `docs/coding/11-pi-command-system-architecture-design.md`，为 `my-pi-agent` 全面落地对标 Pi 的全套会话生命周期与分支漫游命令（`/new`, `/resume`, `/name`, `/compact`, `/tree`, `/fork`, `/clone`）、输入行宏扩展（`!cmd`, `!!cmd`, `/skill:<name>`, `/<template>`）、模型与思考深度切换（`/model`, `/thinking`, `/logout`, `/reload`, `/trust`）以及 CLI 启动参数对齐。

**Architecture:**

- **后端服务层 (`src/my_coding_agent/rpc_server.py`)**：扩展 15 个 stdio JSON-RPC 2.0 异步方法，打通会话管理、DAG 树分支、上下文压缩、Shell 宏与资源热重载。
- **宏解析引擎 (`src/my_coding_agent/macro.py`)**：实现 Shell 宏执行管道（区分入上下文与静默）、Skill XML 模板解包与 Prompt 模板参数替换。
- **前端表现层 (`tui/src/app.ts`)**：实现 TUI 输入框 `!` Bash Mode 动态变色、命令路由分发、ASCII 分支树渲染与会话列表挑选。
- **CLI 参数映射 (`tui/bin/my-agent.js`)**：打通 `-c`, `-r`, `-n`, `--thinking`, `--no-session` 启动参数。

**Tech Stack:** Python 3.12, Node.js / TypeScript, `@earendil-works/pi-tui`, JSON-RPC 2.0, `pytest`, `filelock`.

**Spec:** `docs/coding/11-pi-command-system-architecture-design.md`

## Global Constraints

- **工作区绝对零污染**：所有会话持久化与分支均在 `~/.my-pi-agent/sessions/<slug>-<hash>/` 内进行，严禁向项目代码仓库写入任何 `.jsonl` 临时会话。
- **延期落盘铁律**：`/new` 与启动时的新会话，在未产生首条 `assistant` 消息前绝不向磁盘创建空文件。
- **Never-Throw 边界**：所有 RPC 请求和宏处理必须在内部捕获异常并包装为规范的 JSON-RPC 响应，绝不让未处理异常崩溃子进程。
- **全量回归保障**：既有 615 项 Python 测试与 10 项 TUI 前端测试必须保持 100% 绿灯。

---

## 实施任务总览表 (Overview)

| Task # | 核心任务 | 交付文件 / 模块 | 预估测试 |
| :--- | :--- | :--- | :--- |
| **Task 1** | 会话生命周期控制与上下文压缩 RPC | `src/my_coding_agent/rpc_server.py`<br>`tests/coding/test_session_rpc.py` | 10 项单测 (新建) |
| **Task 2** | 会话树 DAG 漫游、分支切换、Fork 与 Clone | `src/my_coding_agent/rpc_server.py`<br>`tests/coding/test_session_tree_rpc.py` | 8 项单测 (新建) |
| **Task 3** | 输入行即时宏扩展系统 (`!cmd`, `!!cmd`, `/skill`, `/template`) | `src/my_coding_agent/macro.py`<br>`tests/coding/test_macros.py` | 12 项单测 (新建) |
| **Task 4** | 模型切换、思考深度、凭证注销与资源热重载 | `src/my_coding_agent/rpc_server.py`<br>`tests/coding/test_model_resource_rpc.py` | 10 项单测 (新建) |
| **Task 5** | TUI 命令闭环、输入行变色与全量端到端回归 | `tui/src/app.ts`<br>`tui/bin/my-agent.js`<br>`tui/test/app.test.js` | 全库 650+ 项测试 |

---

## 任务执行细节 (Detailed Tasks)

### Task 1: 会话生命周期控制与上下文压缩 RPC

**Files:**

- Modify: `src/my_coding_agent/rpc_server.py`
- Create: `tests/coding/test_session_rpc.py`

**Interfaces:**

- Consumes: `SessionStore`, `AgentPaths`, `ContextManager`
- Produces:
  - `session_new`: 重置会话、生成新会话路径并初始化
  - `session_list`: 枚举当前工作区的历史 `.jsonl` 列表（支持分页/搜索）
  - `session_resume`: 重新载入指定历史会话并重建上下文
  - `session_name`: 写入 `session_info` 标题条目
  - `session_compact`: 触发手工 L4 上下文压缩并回传 Token 差量

- [ ] **Step 1: 编写 `tests/coding/test_session_rpc.py` 失败测试**

```python
from pathlib import Path
import json
import pytest
from my_coding_agent.paths import AgentPaths
from my_coding_agent.rpc_server import RpcServer
from my_agent_llm.models import Response, StreamChunk

class FakeLLM:
    def __init__(self, model="fake-model"):
        self.model = model
    async def achat(self, *a, **kw):
        return Response(content="Summary: All tasks done.", model=self.model)
    async def achat_stream(self, *a, **kw):
        yield StreamChunk(content="ok")

@pytest.mark.anyio
async def test_session_lifecycle_rpc(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}
    })

    # 1. 初始执行一个 Prompt 生成消息
    await server.handle_request({
        "jsonrpc": "2.0", "id": 2, "method": "prompt", "params": {"text": "hello"}
    })

    # 2. session_name
    name_resp = await server.handle_request({
        "jsonrpc": "2.0", "id": 3, "method": "session_name", "params": {"name": "测试会话一"}
    })
    assert name_resp["result"]["status"] == "ok"
    assert name_resp["result"]["name"] == "测试会话一"

    # 3. session_list
    list_resp = await server.handle_request({
        "jsonrpc": "2.0", "id": 4, "method": "session_list", "params": {}
    })
    assert list_resp["result"]["status"] == "ok"
    assert len(list_resp["result"]["sessions"]) >= 1
    assert list_resp["result"]["sessions"][0]["name"] == "测试会话一"

    # 4. session_compact
    compact_resp = await server.handle_request({
        "jsonrpc": "2.0", "id": 5, "method": "session_compact", "params": {"instructions": "重点关注总结"}
    })
    assert compact_resp["result"]["status"] == "ok"

    # 5. session_new
    new_resp = await server.handle_request({
        "jsonrpc": "2.0", "id": 6, "method": "session_new", "params": {}
    })
    assert new_resp["result"]["status"] == "ok"
    assert new_resp["result"]["session_id"] != ""
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run python -m pytest tests/coding/test_session_rpc.py -v`
Expected: FAIL (`Method 'session_name' not found`)

- [ ] **Step 3: 在 `src/my_coding_agent/rpc_server.py` 中实现会话控制方法**

在 `handle_request` 中接入：

- `session_name`：调用 `self.agent.session.store.append_entry(...)` 或 `SessionInfoEntry`；
- `session_list`：使用 `paths.project_session_dir(workspace)` 扫描 `.jsonl` 文件，流式提取首行 Header 与最新 `session_info`；
- `session_resume`：校验目标文件是否存在，重新为 `CodingAgent` 绑定目标 session 并重建上下文；
- `session_compact`：调用 `self.agent.agent.context_manager.compact(...)` 并将生成的条目追加至 session；
- `session_new`：调用 `paths.project_session_dir(workspace)` 生成全新 UUIDv7 文件名，重置 Agent 实例。

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run python -m pytest tests/coding/test_session_rpc.py -v`
Expected: 100% passed (绿灯).

---

### Task 2: 会话树 DAG 漫游、分支切换、Fork 与 Clone

**Files:**

- Modify: `src/my_coding_agent/rpc_server.py`
- Create: `tests/coding/test_session_tree_rpc.py`

**Interfaces:**

- Consumes: `SessionTree`, `SessionManager`, `rpc_server.py`
- Produces:
  - `session_tree`: 提取并返回当前会话树节点拓扑（id, parent_id, role, preview, is_leaf）
  - `session_branch`: 回退/切换活动分支指针，若目标为 User 提问则回传待修改文本
  - `session_fork`: 将目标节点之前的所有历史派生为全新独立 `.jsonl` 文件
  - `session_clone`: 复制当前活跃路径完整生成全新会话

- [ ] **Step 1: 编写 `tests/coding/test_session_tree_rpc.py` 失败测试**

```python
from pathlib import Path
import pytest
from my_coding_agent.rpc_server import RpcServer
from my_agent_llm.models import Response, StreamChunk

class FakeLLM:
    def __init__(self):
        self.model = "fake"
    async def achat(self, *a, **kw):
        return Response(content="answer", model=self.model)
    async def achat_stream(self, *a, **kw):
        yield StreamChunk(content="answer chunk")

@pytest.mark.anyio
async def test_session_tree_fork_clone_rpc(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}
    })
    await server.handle_request({
        "jsonrpc": "2.0", "id": 2, "method": "prompt", "params": {"text": "first prompt"}
    })

    # 1. session_tree
    tree_resp = await server.handle_request({
        "jsonrpc": "2.0", "id": 3, "method": "session_tree", "params": {}
    })
    assert tree_resp["result"]["status"] == "ok"
    assert len(tree_resp["result"]["nodes"]) > 0

    # 2. session_clone
    clone_resp = await server.handle_request({
        "jsonrpc": "2.0", "id": 4, "method": "session_clone", "params": {}
    })
    assert clone_resp["result"]["status"] == "ok"
    assert clone_resp["result"]["new_session_id"] != ""

    # 3. session_fork
    user_node = [n for n in tree_resp["result"]["nodes"] if n.get("role") == "user"][0]
    fork_resp = await server.handle_request({
        "jsonrpc": "2.0", "id": 5, "method": "session_fork", "params": {"entry_id": user_node["id"]}
    })
    assert fork_resp["result"]["status"] == "ok"
    assert fork_resp["result"]["prompt_text"] == "first prompt"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run python -m pytest tests/coding/test_session_tree_rpc.py -v`
Expected: FAIL (`Method 'session_tree' not found`)

- [ ] **Step 3: 在 `src/my_coding_agent/rpc_server.py` 中实现分支与树状算法**

- 实现 `session_tree`：读取当前 `self.agent.session.entries`，生成轻量级 DAG 节点列表，标识 `active_leaf_id`；
- 实现 `session_branch`：依据 `target_id` 重设当前 Session 的 `current_id` 指针，重新投影上下文并返回可选回填文本；
- 实现 `session_fork` 与 `session_clone`：截取指定祖先路径 entries，通过 `AgentPaths` 生成新 `.jsonl` 文件，写入并切换激活。

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run python -m pytest tests/coding/test_session_tree_rpc.py -v`
Expected: 100% passed (绿灯).

---

### Task 3: 输入行即时宏扩展系统 (`!cmd`, `!!cmd`, `/skill`, `/template`)

**Files:**

- Create: `src/my_coding_agent/macro.py`
- Modify: `src/my_coding_agent/rpc_server.py`
- Create: `tests/coding/test_macros.py`

**Interfaces:**

- Consumes: `subprocess`, `SkillManager`, `AgentPaths`
- Produces:

  ```python
  class MacroEngine:
      def execute_shell(self, command: str, cwd: Path, exclude_from_context: bool) -> dict[str, Any]: ...
      def expand_skill(self, skill_name: str, args: str, skills_dir: Path) -> str | None: ...
      def expand_template(self, template_name: str, args_string: str, prompts_dir: Path) -> str | None: ...
  ```

- [x] **Step 1: 编写 `tests/coding/test_macros.py` 失败测试**

```python
from pathlib import Path
import pytest
from my_coding_agent.macro import MacroEngine

def test_shell_macro_execution(tmp_path: Path):
    engine = MacroEngine()
    # 1. 正常执行
    res = engine.execute_shell("echo hello_macro", cwd=tmp_path, exclude_from_context=False)
    assert res["status"] == "ok"
    assert "hello_macro" in res["output"]
    assert res["exit_code"] == 0
    assert res["exclude_from_context"] is False

    # 2. 静默执行标记
    res_silent = engine.execute_shell("echo silent", cwd=tmp_path, exclude_from_context=True)
    assert res_silent["exclude_from_context"] is True

def test_skill_macro_expansion(tmp_path: Path):
    engine = MacroEngine()
    skill_dir = tmp_path / "skills" / "deploy"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: deploy\ndescription: test\n---\n# Deploy Steps\nRun script.", encoding="utf-8")

    expanded = engine.expand_skill("deploy", "staging --dry-run", skills_dir=tmp_path / "skills")
    assert expanded is not None
    assert '<skill name="deploy"' in expanded
    assert "staging --dry-run" in expanded
    assert "---" not in expanded  # YAML Frontmatter 必须剥离

def test_template_macro_expansion(tmp_path: Path):
    engine = MacroEngine()
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "review.md").write_text("Review target: $1 with options: $@", encoding="utf-8")

    expanded = engine.expand_template("review", "src/main.py --strict", prompts_dir=prompts_dir)
    assert expanded == "Review target: src/main.py with options: src/main.py --strict"
```

- [x] **Step 2: 运行测试验证失败**

Run: `uv run python -m pytest tests/coding/test_macros.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'my_coding_agent.macro'`)

- [x] **Step 3: 实现 `src/my_coding_agent/macro.py` 并接入 `rpc_server.py`**

- 实现 `MacroEngine`：包含 Shell 进程执行、`SKILL.md` 正则脱壳、Bash 风格引号分词与 `$1`/`$@`/`${N:-default}` 替换算法；
- 在 `rpc_server.py` 增加 `shell_exec` RPC 方法：执行命令后，若 `exclude_from_context=False`，自动构造 `role: "bashExecution"` 追加至当前 Session。

- [x] **Step 4: 运行测试验证通过**

Run: `uv run python -m pytest tests/coding/test_macros.py -v`
Expected: 100% passed (绿灯).

---

### Task 4: 模型切换、思考深度、凭证注销与资源热重载

**Files:**

- Modify: `src/my_coding_agent/rpc_server.py`
- Create: `tests/coding/test_model_resource_rpc.py`

**Interfaces:**

- Consumes: `LLM`, `Settings`, `AuthManager`, `AgentPaths`
- Produces:
  - `model_switch`: 3 级匹配切换模型，并记录 `model_change`
  - `thinking_set`: 切换思考深度并记录 `thinking_level_change`
  - `auth_logout`: 在 `auth.json` 中抹除凭据
  - `resource_reload`: 重新扫描并热合并资源，回传变更报告
  - `trust_set`: 读写 `trust.json`

- [x] **Step 1: 编写 `tests/coding/test_model_resource_rpc.py` 失败测试**

```python
from pathlib import Path
import json
import pytest
from my_coding_agent.rpc_server import RpcServer
from my_coding_agent.paths import AgentPaths

@pytest.mark.anyio
async def test_model_thinking_and_reload_rpc(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer()
    await server.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}
    })

    # 1. thinking_set
    t_resp = await server.handle_request({
        "jsonrpc": "2.0", "id": 2, "method": "thinking_set", "params": {"level": "high"}
    })
    assert t_resp["result"]["status"] == "ok"
    assert t_resp["result"]["level"] == "high"

    # 2. resource_reload
    r_resp = await server.handle_request({
        "jsonrpc": "2.0", "id": 3, "method": "resource_reload", "params": {}
    })
    assert r_resp["result"]["status"] == "ok"
    assert "summary" in r_resp["result"]

    # 3. trust_set
    trust_resp = await server.handle_request({
        "jsonrpc": "2.0", "id": 4, "method": "trust_set", "params": {"trusted": True}
    })
    assert trust_resp["result"]["status"] == "ok"
    assert (AgentPaths(home=custom_home).home / "trust.json").exists()
```

- [x] **Step 2: 运行测试验证失败**

Run: `uv run python -m pytest tests/coding/test_model_resource_rpc.py -v`
Expected: FAIL (`Method 'thinking_set' not found`)

- [x] **Step 3: 在 `src/my_coding_agent/rpc_server.py` 中实现对应 RPC 方法**

- 实现 `model_switch` 与 `thinking_set`，联动 `AgentSession` 状态与 entries 记录；
- 实现 `auth_logout`，调用 `AuthManager` 安全删除指定 Provider 的 Key；
- 实现 `resource_reload`，重新调用 `load_settings` 与上下文发现并输出 Diff；
- 实现 `trust_set`，写入 `~/.my-pi-agent/trust.json`。

- [x] **Step 4: 运行测试验证通过**

Run: `uv run python -m pytest tests/coding/test_model_resource_rpc.py -v`
Expected: 100% passed (绿灯).

---

### Task 5: TUI 命令闭环、输入行变色与全量端到端回归

**Files:**

- Modify: `tui/src/app.ts`
- Modify: `tui/bin/my-agent.js`
- Modify: `tui/test/app.test.js`

**Interfaces:**

- Consumes: 新增的 15 个 RPC 方法
- Produces:
  - TUI 注册完整 Slash 命令（`/new`, `/resume`, `/name`, `/compact`, `/tree`, `/fork`, `/clone`, `/reload`, `/trust` 等）
  - 输入框输入 `!` 动态切换 Bash Mode 变色；
  - 启动参数 `-c`, `-r`, `-n`, `--thinking`, `--no-session` 完整生效。

- [x] **Step 1: 在 `tui/src/app.ts` 中实现命令分发、宏展开与 Bash 变色**

- 监听 `editor.onChange`：当输入以 `!` 开头时切换输入框边框颜色为黄色；
- 在 `handleSlashCommand` 中接入全部对标命令；
- 在输入提交前优先检测 `!`、`!!`、`/skill:` 与 `/<template>` 展开。

- [x] **Step 2: 扩展 `tui/test/app.test.js` 覆盖全量命令**

编写单测依次触发 `/new`, `/resume`, `/name`, `/compact`, `/tree`, `/fork`, `/clone`, `!command`。

- [x] **Step 3: 运行 TUI 编译与前端单测**

Run:

```bash
npm run build --prefix tui
npm test
```

Expected: 100% passed (全绿).

- [x] **Step 4: 执行全库终极端到端回归矩阵**

Run:

```bash
uv run python -m pytest
npm test
npx pyright
```

Expected:

- Python 测试全绿 (650+ passed)
- Node.js 测试全绿
- Pyright 静态类型检查 0 errors, 0 warnings

---

## 计划自审对照表 (Self-Review Checklist)

1. **需求覆盖全量核对**：除用户明确排除的 5 个命令外，Pi 的所有会话控制、宏扩展、思考切换、热重载全部建档。
2. **零占位符**：所有步骤给出完整代码与预期断言，零 TODO。
3. **架构正交性**：维持 Python 纯无头微内核原则，通过标准 JSON-RPC 驱动 TUI 前端。
