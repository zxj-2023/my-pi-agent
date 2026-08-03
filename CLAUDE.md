# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Learning project: build a minimal agent framework from scratch, then a coding agent on top of it. Modeled on **pi** (pi-mono) and its Python port **pig-mono** (`pig-agent-core` / `pig-coding-agent` two-layer structure). Transparency and understandability are prioritized over generality — this is deliberately not production code.

Planned two layers:
- `packages/my-agent-core` — framework layer (≈ `pig-agent-core`, src 布局：`src/my_agent_core/`). Currently a minimal ReAct loop; being evolved per a 7-stage v1 roadmap (below).
- `my_coding_agent/` — coding agent layer (≈ `pig-coding-agent`). Not started.

The framework depends only on the `openai` SDK + `pydantic` + stdlib — **no agent-framework dependency, by design**（pydantic 是通用库；禁的是 langchain/langgraph 这类 agent 框架）。

## Commands

Uses `uv` with a project-local `.venv` (never global pip). Run from `packages/my-agent-core`（该目录是独立 uv 项目）。

```powershell
cd packages/my-agent-core
uv sync                                       # install deps
Copy-Item .env.example .env                  # then fill real values into .env
uv run python -m my_agent_core.main          # run the demo (needs OPENAI_API_KEY in .env)
uv run python -m pytest -q                   # offline tests (no API key needed)
uv run python -m pytest tests/test_x.py::test_name -q   # run a single test
```

Notes:
- `tests/` 在 `packages/my-agent-core/tests/`，当前有 `test_tools.py` + `test_registry.py`（29 个离线测试）。测试清单对应框架设计文档的 §7/§8（见 Roadmap），test-first。
- `uv run pytest -q` can emit a spurious `Failed to canonicalize script path` warning in some environments; `uv run python -m pytest -q` is the clean equivalent.

## Environment

Config is read from `.env` (via `python-dotenv`) by `main.py` only.

| Var | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | yes | API key |
| `OPENAI_MODEL` | no | model name; code default `gpt-4.1-mini` |
| `OPENAI_BASE_URL` | no | OpenAI-compatible endpoint |

The client is plain `openai.OpenAI(...)`, so any OpenAI-compatible endpoint works. The shipped `.env.example` targets an Aliyun compatible-mode endpoint (model `qwen3.6-flash`) via `OPENAI_BASE_URL` — the effective model comes from `.env`, not the code default.

## Current architecture (what is actually implemented)

`packages/my-agent-core`（src 布局：`packages/my-agent-core/src/my_agent_core/`）里的三个文件形成一个完整的 ReAct (Reason + Act) loop — `tool_calls` parsing, scheduling, error tolerance are written by hand; schema generation and parameter validation are delegated to pydantic:

- **`tools.py`** — up-translation layer. `@tool` (支持 `name`/`description`/`params_model` 覆盖) builds a `Tool` class (function + JSON schema + pydantic 参数模型 + `to_openai_schema`/`execute`/`__call__`) from the function name, docstring, and type hints (pydantic 全集类型，允许默认值；无标注参数与 `*args`/`**kwargs` 在装饰时拒绝). `ToolResult` 承载执行结果（ok/data/error，永不抛）。
- **`registry.py`** — `ToolRegistry`：工具注册表（register/unregister/get/get_schemas/execute），`execute` 收完整 `tool_call`（内部 JSON 解析 + 查表），全部错误转 `ToolResult`。
- **`agent.py`** — `run_agent(question, *, tools, client, model, system_prompt=None)`, the scheduler. **Messages are plain OpenAI wire-format dicts in a list — there is no Message class; the protocol format IS the state.** Loop: send full history + schemas → if the response has no `tool_calls`, return the text (classic exit condition); else execute each tool call, append `role:"tool"` observations paired by `tool_call_id`, and repeat.
- **`main.py`** — demo entry point: 3 example tools + 3 fixed questions; supplies its own `DEMO_SYSTEM_PROMPT`.

Design decisions baked in (keep them unless explicitly asked otherwise):
- **The client is dependency-injected** — production passes `openai.OpenAI(...)`, tests pass a fake client. This is *the* seam that makes the whole loop offline-testable.
- **No default system prompt** at the library layer (`system_prompt=None` sends no system message); persona is the application layer's choice.
- **No infinite-loop guard** — exit is decided entirely by the model; a stuck tool loop burns tokens until Ctrl+C.
- **Sync, sequential** tool execution (multiple `tool_calls` in one turn run one by one).

## Roadmap / target architecture (designed, NOT yet implemented)

`packages/my-agent-core/README.md` holds the authoritative **7-stage v1 plan**; `docs/superpowers/specs/2026-08-01-*.md` holds five design specs (framework / session / context / skills / extensibility). Current code is the pre-refactor `run_agent` version; the plan evolves it toward pi's three-piece shape:

- `llm.py` (`openai_chat`) — the **single LLM seam** (SDK response → wire dict). Future async-ification / provider swaps touch only here.
- `loop.py` (`run_loop`) — stateless loop pure function with `before_tool`/`after_tool` middleware, pre-execution argument validation, `max_iterations`, lifecycle events.
- `agent.py` (`Agent` class) — stateful shell over `run_loop`; then session persistence, context compaction, skills, and dynamic tools layer on in later stages.

Each roadmap stage references test numbers (§7 / §8 checklists) in those design docs — when implementing a stage, write the listed tests first. The older `2026-07-29` / `2026-07-31` docs are archived learning notes (LangChain/LangGraph study phase; example code removed).

## Reference codebases

- `D:/code/python/pig-mono` — pig-mono, the **direct** Python reference being ported.
- `D:/code/python/pi` (`packages/agent`) — the original pi (TypeScript) being studied.

## Conventions

- Docs, READMEs, and code comments/docstrings are written in **Chinese**; identifiers are English. Match the existing style when editing — don't translate comments to English.
- `.claude/`, `.codex/`, `.superpowers/`, `.mcp.json` are gitignored local tooling config, not part of the project.
