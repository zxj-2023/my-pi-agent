# Two Minimal ReAct Agent Examples Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build two minimal, independently runnable ReAct agent examples using LangGraph and LangChain with credentials loaded from `.env`.

**Architecture:** Each script owns its model configuration, one deterministic `multiply` tool, agent construction, and console output so the two APIs can be compared without hidden shared abstractions. Both scripts use `ChatOpenAI`; environment loading and configuration validation occur before an agent sends a request.

**Tech Stack:** Python 3.11+, uv, LangGraph, LangChain, langchain-openai, python-dotenv, pytest.

---

## File Structure

- `pyproject.toml`: Declares runtime and test dependencies for uv.
- `.gitignore`: Prevents local credentials, virtual environments, caches, and coverage artifacts from being tracked.
- `.env.example`: Documents the environment variables without including a real credential.
- `langgraph_react.py`: Standalone LangGraph StateGraph ReAct example.
- `langchain_react.py`: Standalone LangChain ReAct-style tool-calling example.
- `tests/test_langgraph_react.py`: Tests the LangGraph script's deterministic tool and missing-key validation.
- `tests/test_langchain_react.py`: Tests the LangChain script's deterministic tool and missing-key validation.
- `README.md`: Explains setup, configuration, execution, and the distinction between the examples.

## Task 1: Bootstrap The uv Project

**Files:**
- Create: `D:\code\python\ReAct\pyproject.toml`
- Create: `D:\code\python\ReAct\.gitignore`
- Create: `D:\code\python\ReAct\.env.example`

- [ ] **Step 1: Create the project manifest**

```toml
[project]
name = "react-agent-examples"
version = "0.1.0"
description = "Minimal LangChain and LangGraph ReAct agent examples"
requires-python = ">=3.11"
dependencies = [
    "langchain>=1.0,<2.0",
    "langchain-openai>=1.0,<2.0",
    "langgraph>=1.0,<2.0",
    "python-dotenv>=1.0,<2.0",
]

[dependency-groups]
dev = [
    "pytest>=8.0,<10.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Add ignored local files and example configuration**

```gitignore
.env
.venv/
__pycache__/
.pytest_cache/
.coverage
htmlcov/
```

```dotenv
OPENAI_API_KEY=replace_with_your_api_key
OPENAI_MODEL=gpt-4.1-mini
# OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
```

- [ ] **Step 3: Resolve the environment**

Run: `uv sync --dev`

Expected: uv creates `uv.lock` and `.venv` and resolves all declared dependencies.

- [ ] **Step 4: Record the repository state without initializing Git**

Run: `Test-Path .git`

Expected: `False`. Do not run `git init` or create commits because repository initialization is outside the requested example scope.

## Task 2: Implement The LangGraph Example With Tests

**Files:**
- Create: `D:\code\python\ReAct\tests\test_langgraph_react.py`
- Create: `D:\code\python\ReAct\langgraph_react.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from langgraph_react import build_agent, build_model, multiply


def test_multiply_tool_returns_product() -> None:
    assert multiply.invoke({"a": 6, "b": 7}) == 42


def test_build_model_requires_openai_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        build_model()


def test_build_agent_compiles_without_api_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    assert build_agent() is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_langgraph_react.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'langgraph_react'`.

- [ ] **Step 3: Write the minimal LangGraph implementation**

```python
from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


def build_model() -> ChatOpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing. Add it to .env.")

    options = {
        "api_key": api_key,
        "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
    }
    if base_url := os.getenv("OPENAI_BASE_URL"):
        options["base_url"] = base_url

    return ChatOpenAI(**options)


def build_agent():
    model = build_model().bind_tools([multiply])

    def call_model(state: MessagesState):
        return {"messages": [model.invoke(state["messages"])]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode([multiply]))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    return graph.compile()


def main() -> None:
    load_dotenv()
    agent = build_agent()
    response = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Use the multiply tool to calculate 37 times 19.",
                }
            ]
        }
    )
    print(response["messages"][-1].content)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_langgraph_react.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Run the non-network smoke check**

Run: `uv run python -m compileall langgraph_react.py`

Expected: compilation completes without syntax errors.

## Task 3: Implement The LangChain Example With Tests

**Files:**
- Create: `D:\code\python\ReAct\tests\test_langchain_react.py`
- Create: `D:\code\python\ReAct\langchain_react.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from langchain_react import build_model, multiply


def test_multiply_tool_returns_product() -> None:
    assert multiply.invoke({"a": 37, "b": 19}) == 703


def test_build_model_requires_openai_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        build_model()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_langchain_react.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'langchain_react'`.

- [ ] **Step 3: Write the minimal LangChain implementation**

```python
from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


def build_model() -> ChatOpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing. Add it to .env.")

    options = {
        "api_key": api_key,
        "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
    }
    if base_url := os.getenv("OPENAI_BASE_URL"):
        options["base_url"] = base_url

    return ChatOpenAI(**options)


def main() -> None:
    load_dotenv()
    agent = create_agent(
        model=build_model(),
        tools=[multiply],
        system_prompt="Use the multiply tool before answering arithmetic questions.",
    )
    response = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Use the multiply tool to calculate 37 times 19.",
                }
            ]
        }
    )
    print(response["messages"][-1].content)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_langchain_react.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Run the non-network smoke check**

Run: `uv run python -m compileall langchain_react.py`

Expected: compilation completes without syntax errors.

## Task 4: Document Setup And Verify The Complete Example

**Files:**
- Create: `D:\code\python\ReAct\README.md`

- [ ] **Step 1: Write the README**

````markdown
# Minimal ReAct Agent Examples

Two small Python examples show the same multiplication-tool workflow through LangGraph and LangChain.

## Setup

```powershell
uv sync --dev
Copy-Item .env.example .env
```

Set `OPENAI_API_KEY` in `.env`. Set `OPENAI_MODEL` when the default model is unavailable. `OPENAI_BASE_URL` is optional for an OpenAI-compatible endpoint.

## Run

```powershell
uv run python langgraph_react.py
uv run python langchain_react.py
```

Both programs ask the agent to call `multiply(37, 19)` and print the final answer.

## Test

```powershell
uv run pytest -q
```
````

- [ ] **Step 2: Run the complete offline test suite**

Run: `uv run pytest -q`

Expected: `5 passed`.

- [ ] **Step 3: Run both syntax checks**

Run: `uv run python -m compileall langgraph_react.py langchain_react.py`

Expected: both scripts compile without syntax errors.

- [ ] **Step 4: Perform a live run only when `.env` contains a valid tool-calling model key**

Run: `uv run python langgraph_react.py`

Expected: the model calls `multiply` and the final output contains `703`.

Run: `uv run python langchain_react.py`

Expected: the model calls `multiply` and the final output contains `703`.

- [ ] **Step 5: Leave repository initialization and commits unchanged**

Run: `Test-Path .git`

Expected: `False`. Do not create a repository or commit files unless the user explicitly requests it.
