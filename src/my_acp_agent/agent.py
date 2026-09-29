"""ACP ``Agent`` 协议实现 —— 把 ``CodingAgent`` 暴露给支持 ACP 的编辑器。

设计要点：
- **复用而非重写**：会话、工具、权限门禁、上下文压缩全部沿用 ``my_coding_agent``，
  本层只负责协议翻译与生命周期编排；
- **一个 ACP 会话 = 一个 ``CodingAgent`` 实例**：ACP 的 ``session_id`` 直接复用
  my-pi-agent 的会话 UUID，因此会话文件、``/tree`` 分支、``--continue`` 续接全部互通；
- **审批走 ACP 反向请求**：``PermissionGate`` 的 ``confirm_callback`` 接到
  ``session/request_permission``，编辑器弹窗即审批入口。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from acp import PROTOCOL_VERSION
from acp.exceptions import RequestError
from acp.schema import (
    AgentCapabilities,
    CloseSessionResponse,
    Implementation,
    InitializeResponse,
    ListSessionsResponse,
    LoadSessionResponse,
    McpCapabilities,
    NewSessionResponse,
    PromptCapabilities,
    PromptResponse,
    SessionCapabilities,
    SessionInfo,
    SessionListCapabilities,
    SessionMode,
    SessionModeState,
    SetSessionModeResponse,
)
from my_agent_core.events import (
    AgentEnd,
    MessageEnd,
    MessageUpdate,
    ToolExecutionEnd,
    ToolExecutionStart,
)
from my_agent_core.session import Session, SessionInfoEntry
from my_agent_llm.auth.manager import AuthManager
from my_coding_agent.agent import CodingAgent
from my_coding_agent.model_catalog import resolve_initial_llm
from my_coding_agent.paths import AgentPaths
from my_coding_agent.permissions import PermissionGate
from my_coding_agent.resource_scanner import get_all_skill_dirs
from my_coding_agent.serialization import uuid7_str
from my_coding_agent.session_ops import list_project_sessions, resolve_session_file
from my_coding_agent.settings import load_settings

from my_acp_agent.events import (
    translate_message_update,
    translate_tool_end,
    translate_tool_start,
)
from my_acp_agent.mcp import to_mcp_server_configs
from my_acp_agent.permissions import AcpPermissionBridge

if TYPE_CHECKING:
    from acp import AgentSideConnection

logger = logging.getLogger(__name__)

__all__ = ["AcpAgent", "AGENT_NAME", "AGENT_VERSION", "SESSION_MODES"]

AGENT_NAME = "my-pi-agent"
AGENT_VERSION = "0.1.0"

#: 对外暴露的会话模式，与 ``PermissionGate`` 的四种安全模式一一对应。
SESSION_MODES = [
    SessionMode(id="review", name="Review", description="写操作前逐次请求审批"),
    SessionMode(id="autonomous", name="Autonomous", description="自动放行写操作"),
    SessionMode(id="strict", name="Strict", description="只读，拒绝一切写操作"),
    SessionMode(id="yolo", name="YOLO", description="完全放行，不做任何拦截"),
]

_VALID_MODES = {m.id for m in SESSION_MODES}

_CREDENTIAL_HINT = (
    "未检测到可用的模型凭据。请先运行 `my-pi-agent` 并执行 /login <provider> <key> 绑定，"
    "或设置对应的环境变量（如 DEEPSEEK_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY）。"
)

#: 内核 ``AgentEnd.stop_reason`` → ACP ``StopReason``。
_STOP_REASONS = {
    "end_turn": "end_turn",
    "max_iterations": "max_turn_requests",
    "max_turns": "max_turn_requests",
    "cancelled": "cancelled",
    "blocked": "refusal",
    "error": "refusal",
}


@dataclass
class _Session:
    """一个 ACP 会话的运行时状态。"""

    session_id: str
    cwd: Path
    agent: CodingAgent
    mode: str
    bridge: AcpPermissionBridge
    mcp_servers: list[Any] = field(default_factory=list)
    cancelled: bool = False
    usage: dict[str, int] = field(
        default_factory=lambda: {
            "input": 0,
            "output": 0,
            "cacheRead": 0,
            "cacheWrite": 0,
            "total": 0,
        }
    )


class AcpAgent:
    """ACP Agent 协议实现。

    由 ``my_acp_agent.server.run()`` 通过 ``acp.run_agent`` 挂到 stdio 上运行。
    """

    def __init__(
        self,
        *,
        workspace: Path | str | None = None,
        model: str | None = None,
        mode: str | None = None,
        paths: AgentPaths | None = None,
        llm: Any | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve() if workspace else Path.cwd().resolve()
        self.model = model
        self.default_mode = mode
        self.paths = paths or AgentPaths()
        self.paths.ensure_directories()

        self.conn: AgentSideConnection | None = None
        self._sessions: dict[str, _Session] = {}
        self._llm: Any | None = llm
        self._auth_mgr: AuthManager | None = None

    # ── 连接生命周期 ────────────────────────────────────────────────

    def on_connect(self, conn: AgentSideConnection) -> None:
        """由 ``AgentSideConnection`` 在构造后回调，注入反向请求通道。"""
        self.conn = conn

    # ── ACP 协议方法 ────────────────────────────────────────────────

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: Any = None,
        client_info: Implementation | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        return InitializeResponse(
            protocol_version=PROTOCOL_VERSION,
            agent_capabilities=AgentCapabilities(
                load_session=True,
                prompt_capabilities=PromptCapabilities(image=False, audio=False, embedded_context=False),
                session_capabilities=SessionCapabilities(list=SessionListCapabilities()),
                mcp_capabilities=McpCapabilities(http=True, sse=True),
            ),
            agent_info=Implementation(name=AGENT_NAME, title="my-pi-agent", version=AGENT_VERSION),
        )

    async def new_session(
        self,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[Any] | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        workspace = Path(cwd).resolve()
        session_id = uuid7_str()
        session_file = self.paths.project_session_dir(workspace) / f"{session_id}.jsonl"

        session = Session(path=session_file, cwd=str(workspace))
        session.id = session_id
        # Session 默认懒落盘（首次追加消息才写文件）。ACP 客户端在 session/new 之后
        # 可能立刻调用 session/list，这里主动落盘一次，保证会话立即可见。
        session.save()

        mode = self._resolve_mode(None)
        self._build_session(session_id, workspace, session, mode, mcp_servers)
        return NewSessionResponse(
            session_id=session_id,
            modes=self._mode_state(mode),
        )

    async def load_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[Any] | None = None,
        additional_directories: list[str] | None = None,
        **kwargs: Any,
    ) -> LoadSessionResponse | None:
        workspace = Path(cwd).resolve()
        target_file, matches = resolve_session_file(session_id, self.paths, workspace)
        if matches:
            raise RequestError.invalid_params({"sessionId": session_id, "matches": matches})
        if target_file is None or not target_file.is_file():
            raise RequestError.resource_not_found(f"session:{session_id}")

        session = Session.load(target_file)
        mode = self._resolve_mode(None)
        self._build_session(session_id, workspace, session, mode, mcp_servers)

        # 回放历史消息，让编辑器重建对话视口。
        await self._replay_history(session_id, session)
        return LoadSessionResponse(modes=self._mode_state(mode))

    async def list_sessions(
        self,
        cwd: str | None = None,
        cursor: str | None = None,
        **kwargs: Any,
    ) -> ListSessionsResponse:
        workspace = Path(cwd).resolve() if cwd else self.workspace
        records = list_project_sessions(self.paths, workspace)
        return ListSessionsResponse(
            sessions=[
                SessionInfo(
                    session_id=str(rec.get("id") or ""),
                    cwd=str(rec.get("cwd") or workspace),
                    title=rec.get("name") or None,
                )
                for rec in records
                if rec.get("id")
            ]
        )

    async def set_session_mode(
        self,
        session_id: str,
        mode_id: str,
        **kwargs: Any,
    ) -> SetSessionModeResponse | None:
        runtime = self._require_session(session_id)
        if mode_id not in _VALID_MODES:
            raise RequestError.invalid_params({"modeId": mode_id, "valid": sorted(_VALID_MODES)})

        runtime.mode = mode_id
        gate = runtime.agent.permission_gate
        if gate is not None:
            gate.mode = "autonomous" if mode_id == "yolo" else mode_id  # type: ignore[assignment]
        return SetSessionModeResponse()

    async def close_session(self, session_id: str, **kwargs: Any) -> CloseSessionResponse | None:
        runtime = self._sessions.pop(session_id, None)
        if runtime is not None:
            await runtime.agent.close_mcp()
        return CloseSessionResponse()

    async def prompt(
        self,
        session_id: str,
        prompt: list[Any],
        **kwargs: Any,
    ) -> PromptResponse:
        runtime = self._require_session(session_id)
        runtime.cancelled = False

        text = self._extract_prompt_text(prompt)
        if not text:
            return PromptResponse(stop_reason="end_turn")

        stop_reason = "end_turn"
        async for event in runtime.agent.run_stream(text):
            if runtime.cancelled:
                stop_reason = "cancelled"
                break
            await self._dispatch(runtime, event)

        return PromptResponse(stop_reason=stop_reason)  # type: ignore[arg-type]

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        runtime = self._sessions.get(session_id)
        if runtime is None:
            return
        runtime.cancelled = True
        runtime.agent.abort()

    # ── 内部实现 ────────────────────────────────────────────────────

    def _build_session(
        self,
        session_id: str,
        workspace: Path,
        session: Session,
        mode: str,
        mcp_servers: list[Any] | None = None,
    ) -> _Session:
        """装配一个会话的 ``CodingAgent`` 与权限桥。"""
        bridge = AcpPermissionBridge(session_id=session_id, workspace=workspace)
        if self.conn is not None:
            bridge.bind(self.conn)

        gate = PermissionGate(
            mode=mode,  # type: ignore[arg-type]
            confirm_callback=bridge.confirm,
        )
        mcp_configs = to_mcp_server_configs(mcp_servers)
        agent = CodingAgent(
            workspace=workspace,
            llm=self._resolve_llm(),
            session=session,
            permission_gate=gate,
            skill_dirs=get_all_skill_dirs(workspace, self.paths),
            extra_mcp_servers=mcp_configs,
        )

        runtime = _Session(
            session_id=session_id,
            cwd=workspace,
            agent=agent,
            mode=mode,
            bridge=bridge,
            mcp_servers=mcp_configs,
        )
        self._sessions[session_id] = runtime
        return runtime

    def _resolve_llm(self) -> Any:
        """惰性解析模型客户端；无有效凭据时抛出 ACP 认证错误。

        构造时注入的 ``llm``（测试替身或宿主预置客户端）优先，不做凭据探测。
        """
        if self._llm is not None:
            return self._llm

        if self._auth_mgr is None:
            self._auth_mgr = AuthManager(auth_path=self.paths.auth_path)
        settings = load_settings(self.paths, cwd=self.workspace)
        try:
            llm = resolve_initial_llm(self.workspace, self.model, settings, self._auth_mgr)
        except Exception as exc:
            # 凭据缺失/无效时 resolve_initial_llm 会抛 ValueError；转成 ACP 认证错误，
            # 让编辑器给出可操作的提示而不是笼统的 internal error。
            raise RequestError.auth_required({"hint": _CREDENTIAL_HINT, "detail": str(exc)}) from exc
        if llm is None:
            raise RequestError.auth_required({"hint": _CREDENTIAL_HINT})
        self._llm = llm
        return llm

    def _resolve_mode(self, requested: str | None) -> str:
        if requested in _VALID_MODES:
            return requested
        if self.default_mode in _VALID_MODES:
            return self.default_mode
        settings = load_settings(self.paths, cwd=self.workspace)
        configured = getattr(settings, "default_permission_mode", None)
        return configured if configured in _VALID_MODES else "review"

    def _mode_state(self, current: str) -> SessionModeState:
        return SessionModeState(current_mode_id=current, available_modes=list(SESSION_MODES))

    def _require_session(self, session_id: str) -> _Session:
        runtime = self._sessions.get(session_id)
        if runtime is None:
            raise RequestError.invalid_params({"sessionId": session_id, "reason": "unknown session"})
        return runtime

    @staticmethod
    def _extract_prompt_text(prompt: list[Any]) -> str:
        """从 ACP 内容块列表中抽取纯文本（非文本块暂不支持）。"""
        parts: list[str] = []
        for block in prompt or []:
            text = getattr(block, "text", None)
            if text:
                parts.append(str(text))
        return "\n".join(parts).strip()

    async def _dispatch(self, runtime: _Session, event: Any) -> None:
        """把单个内核事件翻译并广播为 ACP ``session/update``。"""
        conn = self.conn
        if conn is None:
            return

        if isinstance(event, MessageUpdate):
            for update in translate_message_update(event):
                await conn.session_update(session_id=runtime.session_id, update=update)
        elif isinstance(event, ToolExecutionStart):
            await conn.session_update(
                session_id=runtime.session_id,
                update=translate_tool_start(event, runtime.cwd),
            )
        elif isinstance(event, ToolExecutionEnd):
            await conn.session_update(
                session_id=runtime.session_id,
                update=translate_tool_end(event, runtime.cwd),
            )
        elif isinstance(event, MessageEnd):
            self._accumulate_usage(runtime, event)
        elif isinstance(event, AgentEnd):
            pass

    @staticmethod
    def _accumulate_usage(runtime: _Session, event: MessageEnd) -> None:
        """累加助手消息上的 usage，供后续统计与成本核算使用。"""
        if event.message is None or event.message.role != "assistant":
            return
        usage = (event.message.metadata or {}).get("usage")
        if not isinstance(usage, dict):
            return
        bucket = runtime.usage
        bucket["input"] += usage.get("prompt_tokens") or usage.get("input") or 0
        bucket["output"] += usage.get("completion_tokens") or usage.get("output") or 0
        bucket["cacheRead"] += usage.get("cache_read_tokens") or usage.get("cache_read") or 0
        bucket["cacheWrite"] += usage.get("cache_write_tokens") or usage.get("cache_write") or 0
        bucket["total"] += usage.get("total_tokens") or usage.get("total") or 0

    async def _replay_history(self, session_id: str, session: Session) -> None:
        """把已持久化的会话历史回放给编辑器（``session/load`` 语义）。"""
        conn = self.conn
        if conn is None:
            return

        from acp import update_agent_message_text, update_user_message_text

        for message in session.get_history():
            if message.role == "user":
                await conn.session_update(session_id=session_id, update=update_user_message_text(message.content or ""))
            elif message.role == "assistant" and message.content:
                await conn.session_update(session_id=session_id, update=update_agent_message_text(message.content))


def _session_info_entry(name: str, workspace: Path, parent_id: str | None) -> SessionInfoEntry:
    """构造会话命名条目（供后续扩展会话重命名使用）。"""
    return SessionInfoEntry(name=name, title=name, cwd=str(workspace), parent_id=parent_id)
