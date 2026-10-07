"""MyPiAgent adapter conforming to Harbor's BaseAgent interface."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from my_agent_core.agent import Agent
from my_agent_core.session import Session
from my_agent_llm.client import LLM
from my_agent_llm.config import Config

from my_pi_eval.tools import HarborToolRegistry

try:
    from harbor.agents.base import BaseAgent  # pyright: ignore[reportMissingImports]
except ImportError:
    # Graceful fallback when harbor package is not installed in local environment
    class BaseAgent:
        @staticmethod
        def name() -> str:
            return "base-agent"

        @property
        def version(self) -> str | None:
            return None

        async def setup(self, environment: Any) -> None:
            pass

        async def run(self, instruction: str, environment: Any, context: Any) -> None:
            pass


def resolve_eval_llm(model_str: str) -> LLM:
    """Resolve provider, model, API key, and base URL from env or AuthManager."""
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

    from my_agent_llm.auth.manager import AuthManager
    from my_agent_llm.auth.schema import ApiKeyCredential

    auth_mgr = AuthManager()
    api_key = None
    base_url = None

    if provider == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            cred = auth_mgr.get_credential("deepseek")
            if isinstance(cred, ApiKeyCredential):
                api_key = cred.resolve_key()
        base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    elif provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            cred = auth_mgr.get_credential("openai")
            if isinstance(cred, ApiKeyCredential):
                api_key = cred.resolve_key()
        base_url = os.environ.get("OPENAI_BASE_URL")
    elif provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            cred = auth_mgr.get_credential("anthropic")
            if isinstance(cred, ApiKeyCredential):
                api_key = cred.resolve_key()
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
    elif provider == "antigravity":
        from my_agent_llm.auth.antigravity import AntigravityAuthResolver

        resolver = AntigravityAuthResolver()
        credentials = resolver.resolve_credentials()
        if credentials:
            api_key = credentials.access_token

    config = Config(
        provider=provider,
        model=model_name,
        api_key=api_key or os.environ.get(f"{provider.upper()}_API_KEY"),
        base_url=base_url,
    )
    return LLM(config=config)


class MyPiAgent(BaseAgent):
    """Adapter bridging my-pi-agent to the Harbor benchmark evaluation harness."""

    @staticmethod
    def name() -> str:
        return "my-pi-agent"

    @property
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

        logs_dir = getattr(context, "logs_dir", None)
        if logs_dir:
            session_path = Path(logs_dir) / "session.jsonl"
        else:
            session_path = Path(tempfile.gettempdir()) / f"my_pi_eval_{uuid4().hex[:8]}.jsonl"

        session = Session(path=session_path)

        system_prompt = (
            "You are a skilled terminal problem-solving agent running in a Linux sandbox.\n"
            "You have access to 7 tools: bash, read, write, edit, ls, grep, find.\n"
            "Use bash to execute shell commands, read/write/edit to manipulate files.\n"
            "Solve the user task directly and efficiently. When you are done, conclude your answer."
        )

        inner_agent = Agent(
            llm=llm,
            tools=registry.list(),
            session=session,
            system_prompt=system_prompt,
        )

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
        duration_sec = time.perf_counter() - start_time

        # Extract token usage if available
        prompt_tokens = 0
        completion_tokens = 0
        cache_read_tokens = 0

        inner_agent = getattr(coding_agent, "agent", None)
        if inner_agent and getattr(inner_agent, "context_manager", None):
            tracker = getattr(inner_agent.context_manager, "token_tracker", None)
            if tracker:
                prompt_tokens = getattr(tracker, "prompt_tokens", 0)
                completion_tokens = getattr(tracker, "completion_tokens", 0)
                cache_read_tokens = getattr(tracker, "cache_read_tokens", 0)

        logs_dir = getattr(context, "logs_dir", None)
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
