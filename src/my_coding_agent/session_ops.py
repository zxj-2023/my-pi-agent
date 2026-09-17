"""会话树文件、拓扑与统计操作模块。

负责会话磁盘扫描与定位、树状 DAG 节点渲染、使用量与全局统计指标计算。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from my_agent_core.session import Session, SessionInfoEntry
from my_agent_core.session.entries import (
    BranchSummaryEntry,
    CompactionEntry,
    LabelEntry,
    LeafEntry,
    MessageEntry,
    ModelChangeEntry,
    ThinkingLevelChangeEntry,
)
from my_agent_core.session.tree import lowest_common_ancestor
from my_agent_core.tool_history import repair_tool_history
from my_agent_llm import Message
from my_coding_agent.paths import AgentPaths
from my_coding_agent.serialization import uuid7_str

logger = logging.getLogger(__name__)


def compute_session_usage(session: Session, model_name: str) -> dict[str, Any]:
    """对标 Pi 规范，从会话历史中提取所有 Assistant 消息的 usage 累加统计。"""
    totals: dict[str, Any] = {
        "input": 0,
        "output": 0,
        "cacheRead": 0,
        "cacheWrite": 0,
        "total": 0,
        "cost": 0.0,
        "latestCacheHitRate": 0.0,
    }
    for msg in session.get_full_history_messages():
        if msg.role == "assistant" and msg.metadata:
            usage = msg.metadata.get("usage")
            if usage and isinstance(usage, dict):
                prompt_tok = usage.get("prompt_tokens") or usage.get("input") or 0
                comp_tok = usage.get("completion_tokens") or usage.get("output") or 0
                cache_read = usage.get("cache_read_tokens") or usage.get("cache_read") or usage.get("cacheRead") or 0
                cache_write = (
                    usage.get("cache_write_tokens") or usage.get("cache_write") or usage.get("cacheWrite") or 0
                )
                total_tok = usage.get("total_tokens") or usage.get("total") or (prompt_tok + comp_tok)

                totals["input"] += prompt_tok
                totals["output"] += comp_tok
                totals["cacheRead"] += cache_read
                totals["cacheWrite"] += cache_write
                totals["total"] += total_tok

                total_prompt = prompt_tok + cache_read + cache_write
                if total_prompt > 0 and cache_read > 0:
                    totals["latestCacheHitRate"] = (cache_read / total_prompt) * 100.0

                model_lower = (model_name or "").lower()
                if "gemini" in model_lower:
                    totals["cost"] += (prompt_tok * 0.1 + comp_tok * 0.4 + cache_read * 0.025) / 1000000.0
                elif "claude" in model_lower:
                    if "opus" in model_lower:
                        totals["cost"] += (prompt_tok * 15.0 + comp_tok * 75.0 + cache_read * 1.5) / 1000000.0
                    else:
                        totals["cost"] += (prompt_tok * 3.0 + comp_tok * 15.0 + cache_read * 0.3) / 1000000.0
                elif "deepseek" in model_lower:
                    totals["cost"] += (prompt_tok * 0.14 + comp_tok * 0.28 + cache_read * 0.014) / 1000000.0
                elif "gpt-4o" in model_lower:
                    totals["cost"] += (prompt_tok * 2.5 + comp_tok * 10.0 + cache_read * 1.25) / 1000000.0

    # 对标 Pi 原厂 calculateContextTokens：提取最后一次推理生效的 Context 大小
    last_context_tokens = 0
    history_msgs = session.get_full_history_messages()
    for msg in reversed(history_msgs):
        if msg.role == "assistant" and msg.metadata:
            usage = msg.metadata.get("usage")
            if usage and isinstance(usage, dict):
                prompt_tok = usage.get("prompt_tokens") or usage.get("input") or 0
                comp_tok = usage.get("completion_tokens") or usage.get("output") or 0
                cache_read = usage.get("cache_read_tokens") or usage.get("cache_read") or usage.get("cacheRead") or 0
                cache_write = (
                    usage.get("cache_write_tokens") or usage.get("cache_write") or usage.get("cacheWrite") or 0
                )
                tot = prompt_tok + comp_tok + cache_read + cache_write
                if tot > 0:
                    last_context_tokens = tot
                    break

    if not last_context_tokens and history_msgs:
        total_chars = sum(len(m.content or "") for m in history_msgs)
        last_context_tokens = max(1, total_chars // 4)

    totals["contextTokens"] = last_context_tokens
    totals["cacheHitRate"] = totals["latestCacheHitRate"]

    return totals


def compute_session_stats(
    session: Session, default_model: str = "default", default_provider: str = "model"
) -> dict[str, Any]:
    """对标 Pi 官方 getSessionStats()，汇总会话全局 Message/Token/Cost 统计。"""
    entries = list(session.tree.entries.values())
    session_file = str(session.path) if session.path else "In-memory"
    session_id = session.id
    session_name = session.metadata.get("name") or session.metadata.get("title")

    user_messages = 0
    assistant_messages = 0
    tool_calls = 0
    tool_results = 0
    total_messages = 0

    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    cache_write_tokens = 0
    total_cost = 0.0

    usage_by_key: dict[str, dict[str, Any]] = {}
    prev_prompt_tokens = 0
    prev_reported_cache = False
    missed_tokens_total = 0
    missed_cost_total = 0.0
    miss_count_total = 0

    for msg in session.get_full_history_messages():
        role = msg.role
        total_messages += 1
        if role == "user":
            user_messages += 1
        elif role == "tool":
            tool_results += 1
        elif role == "assistant":
            assistant_messages += 1
            if msg.metadata and msg.metadata.get("tool_calls"):
                tool_calls += len(msg.metadata["tool_calls"])

            usage = msg.metadata.get("usage") if msg.metadata else None
            if usage and isinstance(usage, dict):
                try:
                    in_t = int(usage.get("prompt_tokens") or usage.get("input") or 0)
                    out_t = int(usage.get("completion_tokens") or usage.get("output") or 0)
                    cr_t = int(usage.get("cache_read_tokens") or usage.get("cache_read") or usage.get("cacheRead") or 0)
                    cw_t = int(
                        usage.get("cache_write_tokens") or usage.get("cache_write") or usage.get("cacheWrite") or 0
                    )
                except (ValueError, TypeError):
                    in_t, out_t, cr_t, cw_t = 0, 0, 0, 0

                input_tokens += in_t
                output_tokens += out_t
                cache_read_tokens += cr_t
                cache_write_tokens += cw_t

                model_str = getattr(msg, "model", None) or default_model
                provider_str = getattr(msg, "provider", None) or default_provider
                breakdown_key = model_str if "/" in model_str else f"{provider_str}/{model_str}"

                step_cost = 0.0
                m_lower = breakdown_key.lower()
                if "gemini" in m_lower:
                    step_cost = (in_t * 0.1 + out_t * 0.4 + cr_t * 0.025) / 1000000.0
                elif "claude" in m_lower:
                    if "opus" in m_lower:
                        step_cost = (in_t * 15.0 + out_t * 75.0 + cr_t * 1.5) / 1000000.0
                    else:
                        step_cost = (in_t * 3.0 + out_t * 15.0 + cr_t * 0.3) / 1000000.0
                elif "deepseek" in m_lower:
                    step_cost = (in_t * 0.14 + out_t * 0.28 + cr_t * 0.014) / 1000000.0
                elif "gpt-4o" in m_lower:
                    step_cost = (in_t * 2.5 + out_t * 10.0 + cr_t * 1.25) / 1000000.0
                else:
                    step_cost = (in_t * 1.0 + out_t * 3.0 + cr_t * 0.5) / 1000000.0

                total_cost += step_cost

                if breakdown_key not in usage_by_key:
                    usage_by_key[breakdown_key] = {"key": breakdown_key, "cost": 0.0, "tokens": 0}
                usage_by_key[breakdown_key]["cost"] += step_cost
                usage_by_key[breakdown_key]["tokens"] += in_t + out_t + cr_t + cw_t

                prompt_t = in_t + cr_t + cw_t
                if prev_prompt_tokens > 0 and (cr_t > 0 or prev_reported_cache):
                    missed = min(prev_prompt_tokens, prompt_t) - cr_t
                    if missed > 1000:
                        missed_tokens_total += missed
                        miss_count_total += 1
                        missed_cost_total += (missed * 0.1) / 1000000.0

                prev_prompt_tokens = prompt_t
                prev_reported_cache = cr_t > 0 or cw_t > 0

    for entry in entries:
        if getattr(entry, "type", "") in ("compaction", "branch_summary"):
            summary_usage = getattr(entry, "usage", None) or getattr(entry, "metadata", {}).get("usage")
            if summary_usage and isinstance(summary_usage, dict):
                try:
                    in_t = int(summary_usage.get("prompt_tokens") or summary_usage.get("input") or 0)
                    out_t = int(summary_usage.get("completion_tokens") or summary_usage.get("output") or 0)
                except (ValueError, TypeError):
                    in_t, out_t = 0, 0
                c_cost = (in_t * 0.5 + out_t * 1.5) / 1000000.0
                key = "Tools/summaries"
                if key not in usage_by_key:
                    usage_by_key[key] = {"key": key, "cost": 0.0, "tokens": 0}
                usage_by_key[key]["cost"] += c_cost
                usage_by_key[key]["tokens"] += in_t + out_t
                total_cost += c_cost

    breakdown_list = sorted(usage_by_key.values(), key=lambda x: x["cost"], reverse=True)

    return {
        "sessionFile": session_file,
        "sessionId": session_id,
        "sessionName": session_name,
        "totalMessages": total_messages,
        "userMessages": user_messages,
        "assistantMessages": assistant_messages,
        "toolCalls": tool_calls,
        "toolResults": tool_results,
        "tokens": {
            "input": input_tokens,
            "output": output_tokens,
            "cacheRead": cache_read_tokens,
            "cacheWrite": cache_write_tokens,
            "total": input_tokens + output_tokens + cache_read_tokens + cache_write_tokens,
        },
        "cost": total_cost,
        "usageBreakdown": breakdown_list,
        "cacheWaste": {
            "missedTokens": missed_tokens_total,
            "missedCost": missed_cost_total,
            "missCount": miss_count_total,
        },
    }


def list_project_sessions(
    paths: AgentPaths,
    workspace_path: Path,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """扫描指定工作区（或全局）的所有 JSONL 会话文件并提取元数据摘要。"""
    target_dirs: list[Path] = []
    if all_projects:
        if paths.sessions_dir.exists():
            target_dirs = [d for d in paths.sessions_dir.iterdir() if d.is_dir()]
    else:
        proj_dir = paths.project_session_dir(workspace_path)
        if proj_dir.exists():
            target_dirs = [proj_dir]

    sessions_meta: list[dict[str, Any]] = []
    for s_dir in target_dirs:
        for f in s_dir.glob("*.jsonl"):
            try:
                with open(f, encoding="utf-8") as fh:
                    line1 = fh.readline()
                    if not line1:
                        continue
                    header = json.loads(line1)
                    sid = header.get("id") or f.stem
                    cwd_val = header.get("cwd", "")
                    created_val = header.get("createdAt") or header.get("created_at") or os.path.getctime(f)
                    meta_obj = header.get("metadata") or {}
                    s_name = header.get("name") or header.get("title") or meta_obj.get("name") or meta_obj.get("title")
                    parent_session = (
                        header.get("parentSession")
                        or header.get("parent_session")
                        or header.get("parentSessionId")
                        or header.get("parent_session_id")
                        or meta_obj.get("parent_session_path")
                        or meta_obj.get("parent_session_id")
                        or meta_obj.get("parentSession")
                    )
                    first_msg_text = None
                    msg_count = 0
                    for line in fh:
                        line_str = line.strip()
                        if not line_str:
                            continue
                        try:
                            entry_data = json.loads(line_str)
                            etype = entry_data.get("type")
                            if etype == "message":
                                msg_count += 1
                                if first_msg_text is None and entry_data.get("message", {}).get("role") == "user":
                                    content = entry_data.get("message", {}).get("content", "")
                                    if isinstance(content, str) and content.strip():
                                        first_msg_text = content.strip().splitlines()[0][:60]
                            elif etype in ("session_info", "sessionInfo"):
                                latest_name = entry_data.get("name") or entry_data.get("title")
                                if latest_name:
                                    s_name = latest_name
                        except Exception:
                            continue

                    modified_val = os.path.getmtime(f)
                    sessions_meta.append(
                        {
                            "id": sid,
                            "name": s_name or first_msg_text or sid,
                            "first_message": first_msg_text,
                            "path": str(f.resolve()),
                            "cwd": cwd_val,
                            "modified": modified_val,
                            "created_at": created_val,
                            "message_count": msg_count,
                            "parent_session": parent_session,
                            "parent_session_path": parent_session,
                        }
                    )
            except Exception:
                continue

    sessions_meta.sort(key=lambda s: s.get("modified", 0), reverse=True)
    return sessions_meta


def resolve_session_file(
    session_id: str,
    paths: AgentPaths,
    workspace_path: Path,
) -> tuple[Path | None, list[str]]:
    """根据 session_id (全称/前缀/路径) 查找匹配的目标会话文件。

    返回 (target_file, matches_names)：
    - 若唯一匹配成功：(Path, [])
    - 若匹配到多个歧义文件：(None, [matches])
    - 若未找到：(None, [])
    """
    session_dir = paths.project_session_dir(workspace_path)

    cand = Path(session_id)
    if cand.is_file():
        cand_resolved = cand.resolve()
        if cand_resolved.is_relative_to(paths.sessions_dir) or cand_resolved.is_relative_to(workspace_path):
            return cand_resolved, []

    if "/" not in session_id and "\\" not in session_id:
        if (session_dir / f"{session_id}.jsonl").is_file():
            return session_dir / f"{session_id}.jsonl", []
        if (session_dir / session_id).is_file():
            return session_dir / session_id, []

    matches: list[Path] = []
    if session_dir.exists():
        for f in session_dir.glob("*.jsonl"):
            try:
                with open(f, encoding="utf-8") as fh:
                    first_line = fh.readline()
                    if first_line:
                        header = json.loads(first_line)
                        fid = header.get("id", "")
                        if (
                            fid == session_id
                            or fid.startswith(session_id)
                            or f.stem == session_id
                            or f.stem.startswith(session_id)
                        ):
                            matches.append(f)
            except Exception:
                continue

    if not matches and paths.sessions_dir.exists():
        for s_dir in paths.sessions_dir.iterdir():
            if not s_dir.is_dir() or s_dir == session_dir:
                continue
            for f in s_dir.glob("*.jsonl"):
                try:
                    with open(f, encoding="utf-8") as fh:
                        first_line = fh.readline()
                        if first_line:
                            header = json.loads(first_line)
                            fid = header.get("id", "")
                            if (
                                fid == session_id
                                or fid.startswith(session_id)
                                or f.stem == session_id
                                or f.stem.startswith(session_id)
                            ):
                                matches.append(f)
                except Exception:
                    continue

    if len(matches) == 1:
        return matches[0], []
    elif len(matches) > 1:
        return None, [m.name for m in matches]

    return None, []


def build_tree_nodes(session: Session) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """遍历 SessionTree 构建包含 DAG 分支关系、节点角色及预览文本的结构化节点列表。"""
    entries = list(session.tree.entries.values())
    active_leaf_id = session.tree.current_id
    root_id = session.tree.root_id

    active_path_ids: set[str] = set()
    if active_leaf_id and active_leaf_id in session.tree.entries:
        active_path_ids = {e.id for e in session.tree.get_current_path()}

    parent_ids = {e.parent_id for e in entries if e.parent_id is not None}

    nodes: list[dict[str, Any]] = []
    for entry in entries:
        eid = entry.id
        pid = entry.parent_id
        etype = getattr(entry, "type", "message")
        role = getattr(entry, "role", etype)

        preview = ""
        if isinstance(entry, MessageEntry):
            msg = entry.message
            content = msg.content or ""
            if msg.metadata and msg.metadata.get("tool_calls"):
                tc_names = [
                    tc.get("function", {}).get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                    for tc in msg.metadata.get("tool_calls", [])
                ]
                prefix = f"[Tool Call: {', '.join(filter(None, tc_names))}]"
                preview = f"{prefix} {content}".strip() if content else prefix
            else:
                preview = content
        elif isinstance(entry, CompactionEntry):
            preview = entry.summary
        elif isinstance(entry, BranchSummaryEntry):
            preview = entry.summary
        elif isinstance(entry, SessionInfoEntry):
            preview = entry.name or entry.title or ""
        elif isinstance(entry, ModelChangeEntry):
            preview = f"Model: {entry.model}"
        elif isinstance(entry, ThinkingLevelChangeEntry):
            preview = f"Thinking: {entry.thinking_level}"
        elif isinstance(entry, LabelEntry):
            preview = f"Label: {entry.label}"
        elif isinstance(entry, LeafEntry):
            preview = f"Leaf: {entry.leaf_id}"
        else:
            preview = str(getattr(entry, "content", "") or getattr(entry, "summary", "") or "")

        if len(preview) > 200:
            preview = preview[:200] + "..."

        nodes.append(
            {
                "id": eid,
                "parent_id": pid,
                "role": role,
                "type": etype,
                "preview": preview,
                "is_leaf": eid not in parent_ids,
                "is_active": eid in active_path_ids,
                "timestamp": getattr(entry, "timestamp", 0.0),
            }
        )

    return nodes, active_leaf_id, root_id


def _copy_entries_to_session(entries: list[Any], target_session: Session) -> None:
    """深度复制历史条目到目标会话树中。"""
    for entry in entries:
        if isinstance(entry, MessageEntry):
            target_session.add_message(entry.role, entry.content, **(entry.metadata or {}))
        elif isinstance(entry, CompactionEntry):
            new_compaction = CompactionEntry(
                parent_id=target_session.tree.current_id,
                summary=entry.summary,
                replaces_entry_ids=list(entry.replaces_entry_ids),
                metadata=dict(entry.metadata),
            )
            target_session.append_entry(new_compaction)
        elif isinstance(entry, BranchSummaryEntry):
            new_bs = BranchSummaryEntry(
                parent_id=target_session.tree.current_id,
                summary=entry.summary,
                details=dict(entry.details),
            )
            target_session.append_entry(new_bs)
        else:
            copied = entry.model_copy(update={"parent_id": target_session.tree.current_id})
            target_session.append_entry(copied)


def fork_session_tree(
    session: Session,
    entry_id: str,
    paths: AgentPaths,
    workspace_path: Path,
) -> tuple[Session, str, Path]:
    """从指定 entry_id 分叉开辟新会话，复制截止至该 entry_id 父节点的历史路径。

    返回 (new_session, prompt_text, new_session_file)。
    """
    if entry_id not in session.tree.entries:
        raise KeyError(f"Entry '{entry_id}' not found in session")

    target_entry = session.tree.entries[entry_id]
    prompt_text = (
        getattr(target_entry, "content", "")
        or (target_entry.message.content if isinstance(target_entry, MessageEntry) else "")
        or ""
    )

    cutoff_id = target_entry.parent_id
    path_entries = session.tree.get_path_to_entry(cutoff_id) if cutoff_id and cutoff_id in session.tree.entries else []

    session_dir = paths.project_session_dir(workspace_path)
    session_dir.mkdir(parents=True, exist_ok=True)
    new_session_id = uuid7_str()
    new_session_file = session_dir / f"{new_session_id}.jsonl"

    new_session = Session(path=new_session_file, cwd=str(workspace_path))
    new_session.id = new_session_id
    new_session.metadata["parent_session_id"] = session.id
    new_session.metadata["parent_session_path"] = str(session.path) if session.path else ""
    new_session.metadata["parentSession"] = str(session.path) if session.path else session.id
    new_session.metadata["forked_from_entry_id"] = entry_id
    if prompt_text:
        fork_title = prompt_text.strip().splitlines()[0][:60]
        new_session.metadata["name"] = fork_title
        new_session.metadata["title"] = fork_title

    _copy_entries_to_session(path_entries, new_session)
    new_session.save()

    return new_session, prompt_text, new_session_file


def clone_session_tree(
    session: Session,
    paths: AgentPaths,
    workspace_path: Path,
) -> tuple[Session, str, Path]:
    """完整克隆当前活跃路径的所有条目并生成全新独立会话副本。

    返回 (new_session, clone_title, new_session_file)。
    """
    active_leaf_id = session.tree.current_id
    path_entries = session.tree.get_current_path() if active_leaf_id else []

    session_dir = paths.project_session_dir(workspace_path)
    session_dir.mkdir(parents=True, exist_ok=True)
    new_session_id = uuid7_str()
    new_session_file = session_dir / f"{new_session_id}.jsonl"

    new_session = Session(path=new_session_file, cwd=str(workspace_path))
    new_session.id = new_session_id
    new_session.metadata["parent_session_id"] = session.id
    new_session.metadata["parent_session_path"] = str(session.path) if session.path else ""
    new_session.metadata["parentSession"] = str(session.path) if session.path else session.id
    cur_name = session.metadata.get("name") or session.metadata.get("title")
    clone_title = f"{cur_name} (clone)" if cur_name else f"Clone of {session.id[:8]}"
    new_session.metadata["name"] = clone_title
    new_session.metadata["title"] = clone_title
    if active_leaf_id:
        new_session.metadata["cloned_from_leaf_id"] = active_leaf_id

    _copy_entries_to_session(path_entries, new_session)
    new_session.save()

    return new_session, clone_title, new_session_file


async def branch_session_tree(
    session: Session,
    target_id: str,
    summarize: bool = False,
    llm: Any = None,
    system_messages: list[Any] | None = None,
) -> tuple[str | None, str, str | None, list[Any]]:
    """在现有 SessionTree 中切换分支点，可选生成废弃分支摘要，并修复重放消息。

    返回 (new_leaf_id, editor_text, branch_summary_text, repaired_messages)。
    """
    if target_id not in session.tree.entries:
        raise KeyError(f"Entry '{target_id}' not found in session")

    target_entry = session.tree.entries[target_id]
    is_user = getattr(target_entry, "role", None) == "user" or (
        isinstance(target_entry, MessageEntry) and target_entry.message.role == "user"
    )

    old_leaf_id = session.tree.current_id
    branch_summary_text: str | None = None

    if is_user:
        new_leaf_id = target_entry.parent_id
        editor_text = (
            getattr(target_entry, "content", "")
            or (target_entry.message.content if isinstance(target_entry, MessageEntry) else "")
            or ""
        )
    else:
        new_leaf_id = target_id
        editor_text = ""

    if new_leaf_id is not None and session.compaction_floor is not None:
        if not session._after_floor(new_leaf_id):
            raise ValueError(
                f"Cannot branch past compaction floor {session.compaction_floor}: entry {new_leaf_id} is prior to compacted history"
            )
    elif new_leaf_id is None and session.compaction_floor is not None:
        raise ValueError(
            f"Cannot branch past compaction floor {session.compaction_floor}: root is prior to compacted history"
        )

    if summarize and old_leaf_id and old_leaf_id != new_leaf_id:
        old_path = session.tree.get_path_to_entry(old_leaf_id)
        new_path_ids = (
            {e.id for e in session.tree.get_path_to_entry(new_leaf_id)}
            if new_leaf_id and new_leaf_id in session.tree.entries
            else set()
        )
        abandoned_entries = [e for e in old_path if e.id not in new_path_ids]

        if abandoned_entries:
            lca = lowest_common_ancestor(session.tree.entries, old_leaf_id, new_leaf_id) if new_leaf_id else None
            summary_prompt = (
                "Please concisely summarize the key decisions, code changes, and exploration from this abandoned conversation branch in 1-2 sentences:\n"
                + "\n".join(
                    f"{getattr(e, 'role', 'entry')}: {getattr(e, 'content', '')}"
                    for e in abandoned_entries
                    if hasattr(e, "content") or hasattr(e, "message")
                )
            )
            try:
                if llm is not None and hasattr(llm, "achat"):
                    resp = await llm.achat([Message(role="user", content=summary_prompt)])
                    branch_summary_text = getattr(resp, "content", "") or "Branch summary"
                else:
                    branch_summary_text = "Branch exploration summary"
            except Exception:
                branch_summary_text = "Branch exploration summary"

            summary_entry = BranchSummaryEntry(
                parent_id=new_leaf_id,
                summary=branch_summary_text,
                details={
                    "abandoned_from": old_leaf_id,
                    "abandoned_count": len(abandoned_entries),
                    "lca": lca,
                },
            )
            session.tree.entries[summary_entry.id] = summary_entry
            session.tree.current_id = summary_entry.id
            session.save()
            new_leaf_id = summary_entry.id

    if not (summarize and branch_summary_text):
        session.tree.current_id = new_leaf_id
        session.save()

    system = system_messages or []
    restored = system + session.get_full_history_messages()
    repaired_messages = list(repair_tool_history(restored).messages)

    return new_leaf_id, editor_text, branch_summary_text, repaired_messages
