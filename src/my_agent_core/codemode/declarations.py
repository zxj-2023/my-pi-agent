"""TypeScript compact declarations generator for Codemode.

Converts Python Pydantic parameter schemas into compact TypeScript type definitions,
aligning with Pi's `@earendil-works/pi-codemode` format and inline token budgets.
"""

from __future__ import annotations

from typing import Any, Sequence, get_type_hints

CORE_TOOL_NAMES: tuple[str, ...] = (
    "read",
    "write",
    "edit",
    "bash",
    "grep",
    "find",
    "ls",
)

CODEMODE_INTRO = """\
Execute JavaScript code in a secure Node.js sandbox to orchestrate tools and process data.

## Execution Rules
- Code runs in an isolated asynchronous context (top-level await is supported).
- Call tools concurrently with `Promise.all` or `Promise.allSettled` to reduce latency.
- Filter, slice, and transform tool results in-memory before returning them.
- Use `return value` or `text(value)` to output final results.
- Call `exit()` to terminate early.
- Optional line 1 configuration: `// @options: {"timeout_ms": 30000, "max_output_tokens": 5000}`.
"""

CODEMODE_GLOBALS = """\
## Global Environment & API
- `tools.<name>(args)`: Call workspace tools asynchronously. Returns a Promise. Failed calls reject with Error (use try/catch).
- `text(value)`: Append text to output. Non-strings are JSON-serialized.
- `image({ type: "image", data: string, mimeType: string })`: Append an image to output.
- `console.log(...)`: Debug logs collected into `<console_output>`.
- `store(key, value)`: Persist session key-value data (committed only on successful execution).
- `load(key)`: Retrieve persisted session key-value data.
- `ALL_TOOLS`: Array of all registered tools `[{ name, description }]`.
"""


def schema_to_ts(
    schema: dict[str, Any] | None,
    root_schema: dict[str, Any] | None = None,
    _visited: set[str] | None = None,
) -> str:
    """Convert a JSON Schema dictionary into a TypeScript type declaration string.

    Supports:
    - Primitives: string, integer -> number, number, boolean, null
    - Arrays: Array<T>
    - Objects: { prop1: string; prop2?: number; }
    - Unions: anyOf, oneOf -> type1 | type2
    - Enums: 'a' | 'b' or 1 | 2
    - References: $ref resolution in $defs / definitions
    - Empty schema or null -> any
    """
    if not schema or not isinstance(schema, dict):
        return "any"

    if root_schema is None and ("$defs" in schema or "definitions" in schema):
        root_schema = schema

    # 1. Resolve $ref
    if "$ref" in schema:
        ref = schema["$ref"]
        if _visited is None:
            _visited = set()
        if ref in _visited:
            return ref.rstrip("/").split("/")[-1]
        _visited.add(ref)

        if root_schema:
            parts = [p for p in ref.lstrip("#/").split("/") if p]
            curr: Any = root_schema
            for p in parts:
                if isinstance(curr, dict) and p in curr:
                    curr = curr[p]
                else:
                    curr = None
                    break
            if curr is not None and isinstance(curr, dict):
                return schema_to_ts(curr, root_schema=root_schema, _visited=_visited)
        return ref.rstrip("/").split("/")[-1]

    # 2. Const
    if "const" in schema:
        val = schema["const"]
        if isinstance(val, str):
            return f"'{val}'"
        if isinstance(val, bool):
            return "true" if val else "false"
        if val is None:
            return "null"
        return str(val)

    # 3. Enum
    if "enum" in schema:
        members: list[str] = []
        for val in schema["enum"]:
            if isinstance(val, str):
                members.append(f"'{val}'")
            elif isinstance(val, bool):
                members.append("true" if val else "false")
            elif val is None:
                members.append("null")
            else:
                members.append(str(val))
        return " | ".join(members) if members else "any"

    # 4. anyOf / oneOf
    if "anyOf" in schema:
        sub_types = [schema_to_ts(sub, root_schema=root_schema, _visited=_visited) for sub in schema["anyOf"]]
        deduped = list(dict.fromkeys(sub_types))
        return " | ".join(deduped) if deduped else "any"

    if "oneOf" in schema:
        sub_types = [schema_to_ts(sub, root_schema=root_schema, _visited=_visited) for sub in schema["oneOf"]]
        deduped = list(dict.fromkeys(sub_types))
        return " | ".join(deduped) if deduped else "any"

    # 5. allOf
    if "allOf" in schema:
        sub_types = [schema_to_ts(sub, root_schema=root_schema, _visited=_visited) for sub in schema["allOf"]]
        deduped = list(dict.fromkeys(sub_types))
        return " & ".join(deduped) if deduped else "any"

    # 6. Type based resolution
    stype = schema.get("type")

    # List of types (e.g. ["string", "null"])
    if isinstance(stype, list):
        types_mapped: list[str] = []
        for t in stype:
            if t == "string":
                types_mapped.append("string")
            elif t in ("integer", "number"):
                types_mapped.append("number")
            elif t == "boolean":
                types_mapped.append("boolean")
            elif t == "null":
                types_mapped.append("null")
            else:
                types_mapped.append("any")
        return " | ".join(list(dict.fromkeys(types_mapped)))

    if stype == "string":
        return "string"
    if stype in ("integer", "number"):
        return "number"
    if stype == "boolean":
        return "boolean"
    if stype == "null":
        return "null"
    if stype == "void":
        return "void"

    # Array
    if stype == "array" or "items" in schema:
        items_schema = schema.get("items")
        if items_schema and isinstance(items_schema, dict):
            item_ts = schema_to_ts(items_schema, root_schema=root_schema, _visited=_visited)
            return f"Array<{item_ts}>"
        return "Array<any>"

    # Object
    if stype == "object" or "properties" in schema:
        if "properties" in schema:
            props = schema["properties"]
            if not props:
                return "{}"
            required = set(schema.get("required", []))
            fields: list[str] = []
            for prop_name, prop_schema in props.items():
                opt = "" if prop_name in required else "?"
                name_repr = (
                    prop_name if prop_name.isidentifier() and not prop_name.startswith("$") else f"'{prop_name}'"
                )
                prop_ts = schema_to_ts(prop_schema, root_schema=root_schema, _visited=_visited)
                fields.append(f"{name_repr}{opt}: {prop_ts};")
            return "{ " + " ".join(fields) + " }"
        if "additionalProperties" in schema:
            add_prop = schema["additionalProperties"]
            if isinstance(add_prop, dict) and add_prop:
                val_ts = schema_to_ts(add_prop, root_schema=root_schema, _visited=_visited)
                return f"Record<string, {val_ts}>"
            if add_prop is False:
                return "{}"
            return "Record<string, any>"
        if stype == "object":
            return "Record<string, any>"

    return "any"


def _get_tool_params_schema(tool: Any) -> dict[str, Any]:
    """Extract JSON Schema dictionary for a Tool's parameters."""
    if getattr(tool, "raw_schema", None) is not None:
        return tool.raw_schema  # type: ignore[no-any-return]

    params_model = getattr(tool, "params_model", None)
    if params_model is not None and hasattr(params_model, "model_json_schema"):
        return params_model.model_json_schema()  # type: ignore[no-any-return]

    if hasattr(tool, "to_openai_schema"):
        try:
            openai_schema = tool.to_openai_schema()
            return openai_schema.get("function", {}).get("parameters", {}) or {}  # type: ignore[no-any-return]
        except Exception:
            pass

    if hasattr(tool, "parameters") and isinstance(tool.parameters, dict):
        return tool.parameters

    return {}


def _get_tool_return_type_ts(tool: Any, default_return_type: str | None = None) -> str:
    """Infer the TypeScript return type for a Tool."""
    if default_return_type is not None:
        return default_return_type

    if hasattr(tool, "return_type_ts") and tool.return_type_ts:
        return str(tool.return_type_ts)

    func = getattr(tool, "func", None)
    if func and callable(func):
        try:
            hints = get_type_hints(func)
            if "return" in hints:
                ret = hints["return"]
                if ret is str:
                    return "string"
                if ret in (int, float):
                    return "number"
                if ret is bool:
                    return "boolean"
                if ret is None or ret is type(None):
                    return "void"
                if ret is dict:
                    return "Record<string, any>"
                if hasattr(ret, "model_json_schema"):
                    return schema_to_ts(ret.model_json_schema())
        except Exception:
            pass

    return "string"


def render_tool_signature(
    tool: Any,
    indent: str = "",
    return_type: str | None = None,
) -> str:
    """Render a Tool as a TypeScript function declaration with JSDoc comments.

    Example:
    /** Read file contents. Supports text and images. */
    read(args: { path: string; offset?: number; limit?: number; }): Promise<string>;
    """
    desc = (getattr(tool, "description", None) or "").strip()
    guidelines = list(getattr(tool, "prompt_guidelines", []) or [])

    # Format JSDoc
    if not desc and not guidelines:
        jsdoc = ""
    elif not guidelines and "\n" not in desc and len(desc) <= 120:
        jsdoc = f"{indent}/** {desc} */\n"
    else:
        doc_lines = [f"{indent}/**"]
        if desc:
            for line in desc.splitlines():
                line = line.strip()
                if line:
                    doc_lines.append(f"{indent} * {line}")
                else:
                    doc_lines.append(f"{indent} *")
        if guidelines:
            if desc:
                doc_lines.append(f"{indent} *")
            doc_lines.append(f"{indent} * Guidelines:")
            for g in guidelines:
                doc_lines.append(f"{indent} * - {g.strip()}")
        doc_lines.append(f"{indent} */\n")
        jsdoc = "\n".join(doc_lines)

    # Format parameters schema
    schema = _get_tool_params_schema(tool)
    root = schema if ("$defs" in schema or "definitions" in schema) else None
    props = schema.get("properties") if isinstance(schema, dict) else None

    ret_ts = _get_tool_return_type_ts(tool, return_type)

    tool_name = getattr(tool, "name", "tool")
    if props is not None and len(props) > 0:
        args_ts = schema_to_ts(schema, root_schema=root)
        call_sig = f"{indent}{tool_name}(args: {args_ts}): Promise<{ret_ts}>;"
    elif props is not None and len(props) == 0:
        call_sig = f"{indent}{tool_name}(args?: {{}}): Promise<{ret_ts}>;"
    elif not schema or schema == {}:
        call_sig = f"{indent}{tool_name}(args?: {{}}): Promise<{ret_ts}>;"
    else:
        args_ts = schema_to_ts(schema, root_schema=root)
        call_sig = f"{indent}{tool_name}(args: {args_ts}): Promise<{ret_ts}>;"

    return f"{jsdoc}{call_sig}"


def _prioritize_tools(tools: Sequence[Any]) -> list[Any]:
    """Sort tools prioritizing core workspace tools first while preserving stable order."""
    core_map = {name: i for i, name in enumerate(CORE_TOOL_NAMES)}
    core: list[Any] = []
    others: list[Any] = []
    for t in tools:
        tname = getattr(t, "name", "")
        if tname in core_map:
            core.append(t)
        else:
            others.append(t)
    core.sort(key=lambda t: core_map.get(getattr(t, "name", ""), 999))
    return core + others


def generate_codemode_description(
    tools: Sequence[Any],
    inline_budget: int = 3000,
    sort_core_first: bool = True,
) -> str:
    """Generate the full Codemode tool description with TypeScript declarations.

    Includes:
    - Environment & execution instructions
    - Global functions and API contracts
    - `declare const tools: { ... };` with inline token budget capping (~4 chars/token).
      When the declaration character limit is reached, subsequent tools are summarized
      by name only without breaking TypeScript syntax.
    """
    budget_chars = inline_budget * 4
    tools_list = _prioritize_tools(tools) if sort_core_first else list(tools)

    signatures: list[str] = []
    summarized_names: list[str] = []
    current_chars = 0
    budget_exceeded = False

    for tool in tools_list:
        tname = getattr(tool, "name", "tool")
        if budget_exceeded:
            summarized_names.append(tname)
            continue

        sig = render_tool_signature(tool, indent="  ")
        cost = len(sig) + (2 if signatures else 0)
        if current_chars + cost <= budget_chars:
            signatures.append(sig)
            current_chars += cost
        else:
            budget_exceeded = True
            summarized_names.append(tname)

    body_parts: list[str] = []
    if signatures:
        body_parts.append("\n\n".join(signatures))

    if summarized_names:
        summary_lines = ["  // Other tools (exceeded inline budget; inspect via ALL_TOOLS):"]
        for name in summarized_names:
            summary_lines.append(f"  // - {name}")
        body_parts.append("\n".join(summary_lines))

    if body_parts:
        inner = "\n\n".join(body_parts)
        decl_block = f"declare const tools: {{\n{inner}\n}};"
    else:
        decl_block = "declare const tools: {};"

    desc_parts = [
        CODEMODE_INTRO.strip(),
        "",
        CODEMODE_GLOBALS.strip(),
        "",
        "## TypeScript Tool Declarations",
        "```typescript",
        decl_block,
        "```",
    ]

    if summarized_names:
        desc_parts.extend(
            [
                "",
                "*Note: Some tools exceeded the inline token budget and are summarized by name above. Use the global `ALL_TOOLS` array to inspect their metadata dynamically.*",
            ]
        )

    return "\n".join(desc_parts)
