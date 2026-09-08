"""对话转录本自愈与断头保护引擎：保证每一条 Assistant 工具调用均有且仅有一条紧邻的工具结果。

对齐 Tau (tau_agent.tool_history) 与 Pi 架构，采用三阶段状态机：
1. Phase 1: 预留就近配对（防止同名 ID 误抢夺）；
2. Phase 2: 贪心匹配或合成中断结果（"Tool call interrupted by user"）；
3. Phase 2.5: 真实结果反超合成中断；
4. Phase 3: 重构转录本、孤儿结果丢弃与保序重排。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from my_agent_llm.models import Message

_INTERRUPTED_TOOL_RESULT = "Tool call interrupted by user"


@dataclass(frozen=True, slots=True)
class ToolHistoryRepair:
    """修复后的合法转录本以及结构化诊断计数。"""

    messages: tuple[Message, ...]
    changed: bool = False
    synthesized_results: int = 0
    dropped_orphan_results: int = 0
    dropped_duplicate_results: int = 0
    reordered_results: int = 0

    def diagnostic_data(self) -> dict[str, int]:
        """返回 JSON 友好的诊断计数字典。"""
        return {
            "synthesizedResults": self.synthesized_results,
            "droppedOrphanResults": self.dropped_orphan_results,
            "droppedDuplicateResults": self.dropped_duplicate_results,
            "reorderedResults": self.reordered_results,
        }


def _get_tool_calls(msg: Message) -> list[dict[str, Any]]:
    """提取 assistant 消息中包含的 tool_calls 列表。"""
    if msg.role == "assistant" and msg.metadata:
        calls = msg.metadata.get("tool_calls")
        if isinstance(calls, list):
            return [c for c in calls if isinstance(c, dict)]
    return []


def _get_tool_call_id(msg: Message) -> str | None:
    """提取 tool 消息绑定的 tool_call_id。"""
    if msg.role == "tool" and msg.metadata:
        tid = msg.metadata.get("tool_call_id")
        if tid is not None:
            return str(tid)
    return None


def repair_tool_history(messages: Sequence[Message]) -> ToolHistoryRepair:
    """对会话历史进行确定性拓扑自愈，确保所有工具调用均合法闭合。"""
    call_occurrences: list[tuple[tuple[int, int], dict[str, Any], int]] = []
    for msg_idx, message in enumerate(messages):
        calls = _get_tool_calls(message)
        for offset, call in enumerate(calls, start=1):
            call_occurrences.append(((msg_idx, offset), call, msg_idx + offset))

    results_by_id: dict[str, list[tuple[int, Message]]] = defaultdict(list)
    for msg_idx, message in enumerate(messages):
        tid = _get_tool_call_id(message)
        if tid is not None:
            results_by_id[tid].append((msg_idx, message))

    selected_results: dict[tuple[int, int], tuple[int | None, Message]] = {}
    used_result_positions: set[int] = set()
    synthesized_results = 0

    # ── Phase 1: 预留已就近配对的调用 (Reserve already-adjacent pairs) ──
    for occurrence, call, expected_pos in call_occurrences:
        if expected_pos >= len(messages):
            continue
        candidate = messages[expected_pos]
        if _get_tool_call_id(candidate) == call.get("id"):
            selected_results[occurrence] = (expected_pos, candidate)
            used_result_positions.add(expected_pos)

    # ── Phase 2: 剩余调用贪心匹配或补齐中断结果 (Match remaining or synthesize) ──
    for occurrence, call, _ in call_occurrences:
        if occurrence in selected_results:
            continue
        call_id = str(call.get("id", ""))
        candidates = results_by_id.get(call_id, [])

        matched_pos: int | None = None
        matched_msg: Message | None = None

        # 优先在调用之后寻找未被使用的真实结果
        for cand_pos, cand_msg in candidates:
            if cand_pos in used_result_positions:
                continue
            if cand_pos > occurrence[0] and cand_msg.content != _INTERRUPTED_TOOL_RESULT:
                matched_pos, matched_msg = cand_pos, cand_msg
                break

        # 次优：任意未使用的结果
        if matched_msg is None:
            for cand_pos, cand_msg in candidates:
                if cand_pos not in used_result_positions:
                    matched_pos, matched_msg = cand_pos, cand_msg
                    break

        if matched_msg is not None and matched_pos is not None:
            selected_results[occurrence] = (matched_pos, matched_msg)
            used_result_positions.add(matched_pos)
        else:
            # 补齐中断结果
            synthetic = Message(
                role="tool",
                content=_INTERRUPTED_TOOL_RESULT,
                metadata={"tool_call_id": call_id, "is_error": True},
            )
            selected_results[occurrence] = (None, synthetic)
            synthesized_results += 1

    # ── Phase 2.5: 真实结果反超合成中断 ──
    for occurrence, call, _ in call_occurrences:
        pos, _ = selected_results[occurrence]
        if pos is not None:
            continue
        call_id = str(call.get("id", ""))
        for cand_pos, cand_msg in results_by_id.get(call_id, []):
            if cand_pos not in used_result_positions:
                selected_results[occurrence] = (cand_pos, cand_msg)
                used_result_positions.add(cand_pos)
                synthesized_results -= 1
                break

    # ── Phase 3: 重建转录本、孤儿丢弃与保序重排 ──
    repaired: list[Message] = []
    all_called_ids = {str(call.get("id", "")) for _, call, _ in call_occurrences}
    dropped_orphan_results = 0
    dropped_duplicate_results = 0
    reordered_results = 0

    for msg_idx, message in enumerate(messages):
        if message.role == "tool":
            tid = _get_tool_call_id(message)
            if msg_idx not in used_result_positions:
                if tid not in all_called_ids:
                    dropped_orphan_results += 1
                else:
                    dropped_duplicate_results += 1
                continue
            # 已使用的工具结果将在对应的 assistant 消息之后紧跟插入，此处跳过
            continue

        repaired.append(message)
        if message.role == "assistant":
            calls = _get_tool_calls(message)
            for offset, _ in enumerate(calls, start=1):
                occ = (msg_idx, offset)
                orig_pos, tool_res = selected_results[occ]
                expected_pos = msg_idx + offset
                if orig_pos != expected_pos:
                    reordered_results += 1
                repaired.append(tool_res)

    changed = len(repaired) != len(messages) or any(
        r != o for r, o in zip(repaired, messages, strict=False)
    )

    return ToolHistoryRepair(
        messages=tuple(repaired),
        changed=changed,
        synthesized_results=synthesized_results,
        dropped_orphan_results=dropped_orphan_results,
        dropped_duplicate_results=dropped_duplicate_results,
        reordered_results=reordered_results,
    )
