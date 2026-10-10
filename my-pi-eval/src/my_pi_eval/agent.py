"""MyPiAgent adapter conforming to Harbor's BaseAgent interface."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

try:
    from dotenv import load_dotenv

    # 优先加载 my-pi-eval 目录专属的 .env 文件
    _eval_root = Path(__file__).resolve().parent.parent.parent
    _eval_env = _eval_root / ".env"
    if _eval_env.exists():
        load_dotenv(_eval_env, override=True)
    else:
        load_dotenv(override=True)
except ImportError:
    pass

from my_agent_core.agent import Agent
from my_agent_core.session import Session
from my_agent_llm.client import LLM
from my_agent_llm.config import Config

from my_pi_eval.tools import HarborToolRegistry

try:
    from my_coding_agent.tracer import DebugEventTracer
except ImportError:
    DebugEventTracer = None

if TYPE_CHECKING:

    class BaseAgent:
        """Harbor BaseAgent stub for static type checking."""

        @staticmethod
        def name() -> str:
            return "base-agent"

        def version(self) -> str | None:
            return None

        async def setup(self, environment: Any) -> None:
            pass

        async def run(self, instruction: str, environment: Any, context: Any) -> None:
            pass
else:
    try:
        from harbor.agents.base import BaseAgent
    except ImportError:

        class BaseAgent:
            def __init__(
                self,
                logs_dir: Any = None,
                model_name: str | None = None,
                *args: Any,
                **kwargs: Any,
            ) -> None:
                self.logs_dir = logs_dir
                self.model_name = model_name

            @staticmethod
            def name() -> str:
                return "base-agent"

            def version(self) -> str | None:
                return None

            async def setup(self, environment: Any) -> None:
                pass

            async def run(self, instruction: str, environment: Any, context: Any) -> None:
                pass


def resolve_eval_llm(model_str: str) -> LLM:
    """从 my-pi-eval/.env 或系统环境变量解析评测 API Key，严禁读取本地 ~/.my-pi-agent/auth.json。"""
    provider = "openai"
    model_name = model_str
    if "/" in model_str:
        provider, model_name = model_str.split("/", 1)
    elif "deepseek" in model_str:
        provider = "deepseek"
    elif "claude" in model_str:
        provider = "anthropic"
    elif "gemini" in model_str:
        provider = "antigravity"

    api_key = None
    base_url = None

    if provider == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    elif provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        base_url = os.environ.get("OPENAI_BASE_URL")
    elif provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
    elif provider == "antigravity":
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTIGRAVITY_API_KEY")

    if not api_key:
        env_var = f"{provider.upper()}_API_KEY"
        raise ValueError(
            f"评测环境未检测到 {env_var}！\n"
            f"评测模块严禁读取本地 ~/.my-pi-agent/auth.json，必须在 'my-pi-eval/.env' 中配置 API Key。\n"
            f"请在 my-pi-eval/.env 中添加: {env_var}=sk-xxxx。"
        )

    config = Config(
        provider=provider,
        model=model_name,
        api_key=api_key,
        base_url=base_url,
    )
    return LLM(config=config)


class MyPiAgent(BaseAgent):
    """Adapter bridging my-pi-agent to the Harbor benchmark evaluation harness."""

    def __init__(
        self,
        logs_dir: Path | None = None,
        model_name: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        if logs_dir is None:
            logs_dir = Path(tempfile.gettempdir()) / f"my_pi_agent_{uuid4().hex[:8]}"
            logs_dir.mkdir(parents=True, exist_ok=True)
        super().__init__(logs_dir=logs_dir, model_name=model_name, *args, **kwargs)

    @staticmethod
    def name() -> str:
        return "my-pi-agent"

    def version(self) -> str | None:
        return "0.1.1"

    async def setup(self, environment: Any) -> None:
        """Environment setup hook prior to task execution."""
        pass

    def _build_coding_agent(self, environment: Any, context: Any) -> Any:
        """Construct the core Agent wired with HarborToolRegistry and model credentials."""
        registry = HarborToolRegistry(environment)
        model_name = getattr(context, "model", None) or os.getenv("DEFAULT_MODEL", "deepseek/deepseek-chat")

        llm = resolve_eval_llm(model_name)

        logs_dir = getattr(context, "logs_dir", None) or getattr(self, "logs_dir", None)
        if logs_dir:
            session_path = Path(logs_dir) / "session.jsonl"
        else:
            session_path = Path(tempfile.gettempdir()) / f"my_pi_eval_{uuid4().hex[:8]}.jsonl"

        session = Session(path=session_path)

        system_prompt = (
            "You are an expert coding assistant operating inside pi, a coding agent harness. "
            "You help users by reading files, executing commands, editing code, and writing new files.\n\n"
            "<tools>\n"
            "- read: Read file contents\n"
            "- bash: Execute bash commands (ls, grep, find, etc.)\n"
            "- edit: Make precise file edits with exact text replacement, including multiple disjoint edits in one call\n"
            "- write: Create or overwrite files\n"
            "- grep: Grep file contents\n"
            "- find: Fuzzy path search and glob search\n"
            "- ls: List directory contents\n\n"
            "In addition to the tools above, you may have access to other custom tools depending on the project.\n"
            "</tools>\n\n"
            "<rules>\n"
            "- Use read to examine files instead of cat or sed.\n"
            "- You can inspect PI_* environment variables for current model and session details.\n"
            "- Use edit for precise changes (edits[].oldText must match exactly)\n"
            "- When changing multiple separate locations in one file, use one edit call with multiple entries in edits[] instead of multiple edit calls\n"
            "- Each edits[].oldText is matched against the original file, not after earlier edits are applied. Do not emit overlapping or nested edits. Merge nearby changes into one edit.\n"
            "- Keep edits[].oldText as small as possible while still being unique in the file. Do not pad with large unchanged regions.\n"
            "- Use write only for new files or complete rewrites.\n"
            "- Be concise in your responses\n"
            "- Show file paths clearly when working with files\n"
            "</rules>\n\n"
            f"<cwd>\n{registry.cwd}\n</cwd>\n"
        )

        inner_agent = Agent(
            llm=llm,
            tools=registry.list(),
            session=session,
            system_prompt=system_prompt,
            context_budget=100_000,
            keep_recent_tokens=20_000,
        )

        if logs_dir and DebugEventTracer is not None:
            try:
                debug_log_path = Path(logs_dir) / "debug.log"
                events_log_path = Path(logs_dir) / "events.jsonl"
                tracer = DebugEventTracer(
                    log_path=debug_log_path,
                    events_path=events_log_path,
                    console_output=False,
                )
                inner_agent.subscribe(tracer)
            except (OSError, RuntimeError) as exc:
                _ = exc

        class AgentFacade:
            def __init__(self, agent_instance: Agent):
                self.agent = agent_instance

            async def run(self, prompt_text: str) -> str:
                res = await self.agent.run(prompt_text)
                return str(res or "")

        return AgentFacade(inner_agent)

    async def run(self, instruction: str, environment: Any, context: Any) -> None:
        """Execute task instruction inside the container sandbox."""
        coding_agent = self._build_coding_agent(environment, context)

        start_time = time.perf_counter()
        error_msg: str | None = None
        try:
            await coding_agent.run(instruction)
        except Exception as exc:
            error_msg = str(exc)
        except asyncio.CancelledError as exc:
            error_msg = f"Task cancelled / timeout: {exc}"
            raise
        finally:
            duration_sec = time.perf_counter() - start_time

            # Extract token usage directly from session file (most reliable and complete)
            prompt_tokens = 0
            completion_tokens = 0
            cache_read_tokens = 0

            session = getattr(coding_agent, "session", None) or getattr(
                getattr(coding_agent, "agent", None), "session", None
            )
            session_file = Path(session.path) if session and getattr(session, "path", None) else None
            if session_file and session_file.exists():
                try:
                    for line in session_file.read_text(encoding="utf-8", errors="replace").splitlines():
                        if not line.strip():
                            continue
                        d_entry = json.loads(line)
                        msg = d_entry.get("message") or {}
                        meta = msg.get("metadata") or {}
                        usage = meta.get("usage") or msg.get("usage") or {}
                        if isinstance(usage, dict):
                            prompt_tokens += usage.get("prompt_tokens") or usage.get("input") or 0
                            completion_tokens += usage.get("completion_tokens") or usage.get("output") or 0
                            cache_read_tokens += (
                                usage.get("cache_read_tokens") or usage.get("cache_read") or usage.get("cacheRead") or 0
                            )
                except (json.JSONDecodeError, OSError) as exc:
                    _ = exc

            logs_dir = getattr(context, "logs_dir", None) or getattr(self, "logs_dir", None)
            if logs_dir:
                metrics_path = Path(logs_dir) / "metrics.json"
                raw_task_id = getattr(context, "task_id", None)
                task_id_str = raw_task_id if isinstance(raw_task_id, str) else "unknown"
                task_metric = {
                    "task_id": task_id_str,
                    "duration_sec": round(duration_sec, 3),
                    "prompt_tokens": prompt_tokens if isinstance(prompt_tokens, int) else 0,
                    "completion_tokens": completion_tokens if isinstance(completion_tokens, int) else 0,
                    "cache_read_tokens": cache_read_tokens if isinstance(cache_read_tokens, int) else 0,
                    "error": error_msg,
                }
                metrics_path.write_text(json.dumps(task_metric, indent=2), encoding="utf-8")

            self._last_metrics = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cache_read_tokens": cache_read_tokens,
                "duration_sec": duration_sec,
            }

    def populate_context_post_run(self, context: Any) -> None:
        """Backfill token metrics into Harbor's AgentContext post execution."""
        if hasattr(self, "_last_metrics") and self._last_metrics:
            if hasattr(context, "n_input_tokens"):
                context.n_input_tokens = self._last_metrics.get("prompt_tokens")
            if hasattr(context, "n_output_tokens"):
                context.n_output_tokens = self._last_metrics.get("completion_tokens")
            if hasattr(context, "n_cache_tokens"):
                context.n_cache_tokens = self._last_metrics.get("cache_read_tokens")
