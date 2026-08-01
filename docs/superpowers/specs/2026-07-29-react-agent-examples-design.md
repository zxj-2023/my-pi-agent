# Two Minimal ReAct Agent Examples

## Goal

Provide two independently runnable Python examples that demonstrate a minimal tool-using ReAct agent:

- a LangGraph example using a native `StateGraph` and `ToolNode` ReAct loop;
- a LangChain example using the current `create_agent` helper.

Both examples must load model credentials from `.env` and make the model call the same local multiplication tool before answering.

## Scope

The project will contain these user-facing files:

```text
langgraph_react.py
langchain_react.py
.env.example
.gitignore
README.md
pyproject.toml
```

`uv` will manage the Python environment and lock compatible versions of LangChain, LangGraph, the OpenAI integration, and `python-dotenv`. A small test module may verify the local tool behavior without requiring a model API key.

## Runtime Contract

Each script will:

1. Call `load_dotenv()`.
2. Require `OPENAI_API_KEY`, with a clear error if it is absent.
3. Read optional `OPENAI_MODEL` and `OPENAI_BASE_URL` values for model selection and OpenAI-compatible endpoints.
4. Create a `ChatOpenAI` model and a `multiply(a, b)` tool.
5. Ask the agent to use that tool for a fixed multiplication question.
6. Print the final assistant response.

The supplied `.env.example` will contain placeholders only. `.gitignore` will exclude `.env`, virtual environments, caches, and generated coverage data.

## Error Handling And Verification

Missing configuration will fail before any API request. The README will show the `uv sync` and `uv run` commands. Verification will cover syntax/import behavior and the deterministic local tool; a live agent run remains dependent on a valid model key and provider.

## Non-Goals

This is a teaching example, not an application framework. It will not add memory, persistence, streaming, web search, a UI, custom routing, or provider-specific configuration files.
