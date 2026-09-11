# 树状会话与持久化存储子系统 (`my_agent_core.session`)

- **定位**：崩溃安全的树状对话历史、状态折叠投影与只追加存储引擎 (`packages/my-agent-core/src/my_agent_core/session/`)
- **核心模块**：
  - `entries.py`：9 种强类型判别多态实体（`SessionEntry` Discriminated Union）
  - `tree.py`：纯内存 DAG 算法（死锁环路检测、路径回溯、LCA 最近公共祖先）
  - `memory.py`：`SessionState` 不可变事件溯源状态折叠投影（`from_entries`）
  - `storage.py`：纯异步只追加 `SessionStorage` 协议与 `InMemorySessionStorage` 驱动
  - `jsonl.py`：`JsonlSessionStorage` 追加驱动、跨进程文件锁与 `.tmp` 碎片自愈
  - `session.py`：高级 `Session` 与 `SessionTree` 树状分支会话门面
  - `store.py`：工作区天然物理隔离的会话仓库管理器 `SessionStore`
- **主要实现**：`session/` 子包

---

## 一、架构设计：从单文件覆写到领域分治只追加微内核

在早期版本中，会话持久化采用“每次写入都覆写整个 JSONL 文件”的方式，随着对话加长，存在严重的 I/O 写放大风险，且无法支持非消息类的系统状态变化（如模型切换、思考深度变化、分支打标等）。

在对标 **Tau (`tau_agent`)** 深度模块化演进后，会话子系统拆解为 7 个内聚模块，并全面升级为**事件溯源（Event Sourcing）与只追加（Append-Only）架构**：

```text
                           SessionStore (会话仓库)
                     管理 <workspace>/.my_agent_core/sessions/
                                     │
                                     ▼
                                  Session
               (持有会话文件路径、元数据与当前指针 current_id)
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
            SessionTree                             SessionStorage
   (纯内存 DAG 拓扑，死锁环检测)                  (只追加存储驱动，文件锁守护)
                 │                                       │
                 ▼                                       ▼
         9 种多态 SessionEntry                     JsonlSessionStorage /
 (Message, Compaction, ModelChange...)           InMemorySessionStorage
                 │                                       │
                 └───────────────────┬───────────────────┘
                                     │
                                     ▼
                               SessionState
                (事件溯源纯函数折叠投影: from_entries)
```

---

## 二、9 种多态条目实体 (`session/entries.py`)

所有条目继承自 `BaseSessionEntry`，基于 Pydantic v2 构建，禁止未知字段（`extra="forbid"`），原生支持 `camelCase` 别名与 `snake_case` 互转：

```python
class BaseSessionEntry(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    parent_id: str | None = None
    timestamp: float = Field(default_factory=time.time)
```

通过 `type: Literal[...]` 判别字段组成统一的 `SessionEntry` 联合体：

| 条目类型 (`type`) | 类名 | 核心属性 | 语义与作用 |
| :--- | :--- | :--- | :--- |
| `session_info` | `SessionInfoEntry` | `cwd`, `title`, `metadata` | 记录会话创建环境与初始元数据（流首项） |
| `message` | `MessageEntry` | `message: Message` | 对话消息包装（支持 `role`, `content`, `metadata`） |
| `model_change` | `ModelChangeEntry` | `model`, `provider` | 运行时动态切换模型记录 |
| `thinking_level_change` | `ThinkingLevelChangeEntry` | `thinking_level` | 思考深度级别变更记录 |
| `compaction` | `CompactionEntry` | `summary`, `first_kept_entry_id`, `tokens_saved` | 上下文压缩摘要实体，记录历史条目折叠边界 |
| `branch_summary` | `BranchSummaryEntry` | `from_id`, `summary` | 分支回溯或合并时的摘要归纳 |
| `label` | `LabelEntry` | `target_id`, `label` | 给特定节点打业务标签（如 `checkpoint`） |
| `leaf` | `LeafEntry` | `target_id` | 显式标记活动叶子节点指针 |
| `custom` | `CustomEntry` | `data: dict[str, Any]` | 供第三方插件扩展保存自定义元数据 |

---

## 三、纯内存 DAG 树算法 (`session/tree.py`)

所有树拓扑计算均为**纯函数内存算法，零物理磁盘 I/O**：

1. **`entries_by_id`**：将条目序列转换为字典映射，严格检测并拦截重复 ID（防脏数据注入）；
2. **`path_to_entry`**：从任意指定节点沿 `parent_id` 向上回溯至根节点，生成主线路径列表。内置 `seen: set[str]` 环路检测，若出现循环依赖立即抛出 `SessionTreeError("Cycle detected")`；
3. **`lowest_common_ancestor`**：计算两个分支节点的最近公共祖先（LCA），为分支比较与差量合并提供基准点；
4. **`find_branches`**：提取当前树中所有合法的叶子节点集合。

---

## 四、事件溯源状态折叠投影 (`session/memory.py`)

`SessionState` 是不可变的数据快照类，通过纯函数 `from_entries` 线性折叠主线路径上的所有条目，产出当前节点的真实运行时状态：

```python
@dataclass(frozen=True)
class SessionState:
    messages: list[Message]
    model: str | None = None
    provider: str | None = None
    thinking_level: str | None = None
    label: str | None = None
    active_leaf_id: str | None = None

    @classmethod
    def from_entries(
        cls,
        entries: Sequence[SessionEntry],
        leaf_id: str | None = None,
    ) -> SessionState:
        ...
```

- **压缩折叠机制**：当路径上存在 `CompactionEntry` 时，`from_entries` 自动将 `first_kept_entry_id` 之前的旧消息折叠为一条规范化的摘要消息：`UserMessage("Previous conversation summary:\n{summary}")`，并无缝拼接后续保留的消息；
- **状态纯净性**：不修改底层存储条目，多次查询同一路径保证 100% 幂等。

---

## 五、纯异步只追加存储驱动 (`session/storage.py` & `jsonl.py`)

### 1. `SessionStorage` 抽象契约

```python
class SessionStorage(Protocol):
    async def append(self, entry: SessionEntry) -> None: ...
    async def append_batch(self, entries: Sequence[SessionEntry]) -> None: ...
    async def read_all(self) -> list[SessionEntry]: ...
```

- **`InMemorySessionStorage`**：纯内存读写，供离线单元测试极速运行，消除文件系统锁竞争；
- **`JsonlSessionStorage`**：生产级磁盘持久化驱动。

### 2. 崩溃安全原子性与跨进程锁守护

- **只追加写入（Append-Only）**：新节点直接使用 `a+` 追加写入文件末尾，写操作复杂度恒定为 $O(1)$，消除重写全量历史的写放大；
- **跨进程文件锁（`.{name}.lock`）**：在执行追加前，通过跨进程文件锁排队写入（Windows 平台使用 `msvcrt.locking`，POSIX 平台使用 `fcntl.flock`），彻底杜绝多进程并发写入冲突；
- **临时碎片自愈（Self-Healing）**：初始化时自动扫描并清理可能因系统掉电残留的未完成 `.tmp` 临时文件；
- **遗留格式向后平滑迁移**：自动检测旧版第 0 行文件头字典，将其平滑迁移为合法的 `SessionInfoEntry`。

---

## 六、`SessionStore` 工作区隔离管理 (`session/store.py`)

`SessionStore` 负责在 `<workspace>/.my_agent_core/sessions/` 目录下管理会话文件生命周期：

- **`create() / create_session()`**：生成以时间戳和 UUID 命名的持久化会话；
- **`open(id_or_prefix) / open_session(id_or_prefix)`**：根据全 ID 或短前缀模糊匹配加载已有会话；
- **`list() -> list[SessionMeta]`**：扫描目录并按 `created_at` 倒序返回会话元信息列表；
- **`delete(id_or_prefix)`**：安全物理删除会话文件及锁文件；
- **`fork(id_or_prefix, entry_id)`**：从指定会话的历史分叉点派生新分支会话；
- **子代理会话天然隔离**：子代理运行实例会话统一存放在 `<session_dir>/subagents/`，与主会话天然隔离，不污染工程主目录。
