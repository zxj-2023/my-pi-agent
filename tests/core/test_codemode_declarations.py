"""Tests for Codemode TypeScript compact declarations generator."""

from typing import Optional
from pydantic import BaseModel


from my_agent_core.codemode.declarations import (
    generate_codemode_description,
    render_tool_signature,
    schema_to_ts,
)
from my_agent_core.tools.core import Tool


class TestSchemaToTs:
    """Test schema_to_ts JSON Schema to TypeScript type converter."""

    def test_primitives(self):
        assert schema_to_ts({"type": "string"}) == "string"
        assert schema_to_ts({"type": "integer"}) == "number"
        assert schema_to_ts({"type": "number"}) == "number"
        assert schema_to_ts({"type": "boolean"}) == "boolean"

    def test_empty_and_null(self):
        assert schema_to_ts({}) in ("any", "void")
        assert schema_to_ts(None) in ("any", "void")
        assert schema_to_ts({"type": "null"}) in ("null", "void", "any")

    def test_array(self):
        assert schema_to_ts({"type": "array", "items": {"type": "string"}}) == "Array<string>"
        assert schema_to_ts({"type": "array", "items": {"type": "integer"}}) == "Array<number>"
        assert schema_to_ts({"type": "array"}) == "Array<any>"

    def test_object_with_properties(self):
        schema = {
            "type": "object",
            "properties": {
                "prop1": {"type": "string"},
                "prop2": {"type": "integer"},
            },
            "required": ["prop1"],
        }
        assert schema_to_ts(schema) == "{ prop1: string; prop2?: number; }"

    def test_object_empty_properties(self):
        schema = {"type": "object", "properties": {}}
        assert schema_to_ts(schema) == "{}"

    def test_unions(self):
        any_of = {"anyOf": [{"type": "string"}, {"type": "number"}]}
        assert schema_to_ts(any_of) == "string | number"

        one_of = {"oneOf": [{"type": "string"}, {"type": "boolean"}]}
        assert schema_to_ts(one_of) == "string | boolean"

    def test_enums(self):
        enum_schema = {"type": "string", "enum": ["read", "write"]}
        assert schema_to_ts(enum_schema) == "'read' | 'write'"

        int_enum = {"enum": [1, 2, 3]}
        assert schema_to_ts(int_enum) == "1 | 2 | 3"

    def test_pydantic_model_json_schema(self):
        class FileReadArgs(BaseModel):
            path: str
            offset: Optional[int] = None
            limit: int = 100

        schema = FileReadArgs.model_json_schema()
        ts_type = schema_to_ts(schema)
        # path is required -> path: string;
        assert "path: string;" in ts_type
        # offset and limit are optional -> offset?: ...; limit?: number;
        assert "offset?:" in ts_type
        assert "limit?: number;" in ts_type

    def test_all_of(self):
        schema = {
            "allOf": [
                {"type": "object", "properties": {"a": {"type": "string"}}},
                {"type": "object", "properties": {"b": {"type": "number"}}},
            ]
        }
        ts_type = schema_to_ts(schema)
        assert ts_type == "{ a?: string; } & { b?: number; }"

    def test_const_values(self):
        assert schema_to_ts({"const": "fixed_value"}) == "'fixed_value'"
        assert schema_to_ts({"const": True}) == "true"
        assert schema_to_ts({"const": False}) == "false"
        assert schema_to_ts({"const": None}) == "null"
        assert schema_to_ts({"const": 42}) == "42"

    def test_additional_properties(self):
        schema_dict = {"type": "object", "additionalProperties": {"type": "string"}}
        assert schema_to_ts(schema_dict) == "Record<string, string>"

        schema_any = {"type": "object", "additionalProperties": True}
        assert schema_to_ts(schema_any) == "Record<string, any>"

        schema_none = {"type": "object", "additionalProperties": False}
        assert schema_to_ts(schema_none) == "{}"

    def test_type_list(self):
        schema = {"type": ["string", "null"]}
        assert schema_to_ts(schema) == "string | null"

    def test_ref_resolution_and_circular(self):
        root = {
            "$defs": {
                "User": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                "Node": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "integer"},
                        "next": {"$ref": "#/$defs/Node"},
                    },
                },
            }
        }
        ref_schema = {"$ref": "#/$defs/User"}
        assert schema_to_ts(ref_schema, root_schema=root) == "{ name: string; }"

        # Circular ref returns ref name without crashing
        circular_schema = {"$ref": "#/$defs/Node"}
        ts_node = schema_to_ts(circular_schema, root_schema=root)
        assert "value?: number;" in ts_node
        assert "next?: Node;" in ts_node


class TestRenderToolSignature:
    """Test render_tool_signature for Tool instances."""

    def test_read_tool_signature(self):
        def read(path: str, offset: int = 0, limit: int = 100) -> str:
            """Read file contents. Supports text and images."""
            return ""

        tool = Tool(read)
        sig = render_tool_signature(tool)

        assert "/** Read file contents. Supports text and images. */" in sig
        assert "read(args: { path: string; offset?: number; limit?: number; }): Promise<string>;" in sig

    def test_tool_with_prompt_guidelines(self):
        def edit(path: str, old_text: str, new_text: str) -> str:
            """Edit file content."""
            return ""

        tool = Tool(
            edit,
            prompt_guidelines=[
                "Always provide exact old_text.",
                "Ensure unique non-overlapping regions.",
            ],
        )
        sig = render_tool_signature(tool)

        assert "/**" in sig
        assert " * Edit file content." in sig
        assert " * Guidelines:" in sig
        assert " * - Always provide exact old_text." in sig
        assert " * - Ensure unique non-overlapping regions." in sig
        assert " */" in sig
        assert "edit(args: { path: string; old_text: string; new_text: string; }): Promise<string>;" in sig

    def test_tool_no_args(self):
        def get_status() -> str:
            """Get current agent status."""
            return "ok"

        tool = Tool(get_status)
        sig = render_tool_signature(tool)

        assert "get_status(args?: {}): Promise<string>;" in sig

    def test_tool_indentation(self):
        def ping() -> str:
            """Ping workspace."""
            return "pong"

        tool = Tool(ping)
        sig = render_tool_signature(tool, indent="  ")
        lines = sig.splitlines()
        for line in lines:
            assert line.startswith("  ")

    def test_tool_return_types(self):
        def count_lines(path: str) -> int:
            """Count lines."""
            return 0

        def is_valid() -> bool:
            """Check validity."""
            return True

        def reset_state() -> None:
            """Reset state."""
            pass

        class CustomResult(BaseModel):
            output: str
            exit_code: int

        def run_proc() -> CustomResult:
            """Run process."""
            return CustomResult(output="", exit_code=0)

        assert "Promise<number>;" in render_tool_signature(Tool(count_lines))
        assert "Promise<boolean>;" in render_tool_signature(Tool(is_valid))
        assert "Promise<void>;" in render_tool_signature(Tool(reset_state))
        assert "Promise<{ output: string; exit_code: number; }>;" in render_tool_signature(Tool(run_proc))

    def test_tool_raw_schema(self):
        def raw_fn(**kwargs):
            """Raw schema tool."""
            return ""

        tool = Tool(
            raw_fn,
            raw_schema={
                "type": "object",
                "properties": {"action": {"type": "string"}},
                "required": ["action"],
            },
        )
        sig = render_tool_signature(tool)
        assert "raw_fn(args: { action: string; }): Promise<string>;" in sig


class TestGenerateCodemodeDescription:
    """Test generate_codemode_description description and budget capping."""

    def test_full_description_elements(self):
        def read(path: str) -> str:
            """Read file contents."""
            return ""

        def bash(command: str, timeout: int = 30) -> str:
            """Execute bash command."""
            return ""

        tools = [Tool(read), Tool(bash)]
        desc = generate_codemode_description(tools)

        # Intro and execution environment
        assert "JavaScript" in desc or "Node.js" in desc
        # Globals
        assert "tools." in desc
        assert "text(" in desc
        assert "image(" in desc
        assert "console.log" in desc
        assert "store(" in desc
        assert "load(" in desc
        assert "ALL_TOOLS" in desc
        assert "exit()" in desc
        assert "// @options:" in desc
        # TypeScript declarations block
        assert "declare const tools: {" in desc
        assert "read(args: { path: string; }): Promise<string>;" in desc
        assert "bash(args: { command: string; timeout?: number; }): Promise<string>;" in desc
        assert desc.strip().endswith("};") or desc.strip().endswith("```")

    def test_inline_budget_capping(self):
        def tool_one(arg1: str) -> str:
            """Tool one description that takes some character space."""
            return ""

        def tool_two(arg2: str, extra: int = 10) -> str:
            """Tool two description with some more characters."""
            return ""

        def tool_three(arg3: str) -> str:
            """Tool three description."""
            return ""

        tools = [Tool(tool_one), Tool(tool_two), Tool(tool_three)]

        # Inline budget = 30 tokens ~ 120 chars
        # tool_one's signature is ~100 chars, so tool_two/tool_three will exceed budget
        desc = generate_codemode_description(tools, inline_budget=30)

        assert "declare const tools: {" in desc
        assert "tool_one(args: {" in desc
        # Subsequent tools are summarized by name only without breaking syntax
        assert "tool_two(args: {" not in desc
        assert "tool_three(args: {" not in desc
        assert "tool_two" in desc
        assert "tool_three" in desc
        # Guidance to ALL_TOOLS is included
        assert "ALL_TOOLS" in desc

    def test_core_tools_prioritization(self):
        def mcp_custom_long_tool(arg: str) -> str:
            """MCP custom tool."""
            return ""

        def read(path: str) -> str:
            """Read file."""
            return ""

        def write(path: str, content: str) -> str:
            """Write file."""
            return ""

        # Given MCP custom tool first, core tools (read, write) should be prioritized
        tools = [Tool(mcp_custom_long_tool), Tool(read), Tool(write)]
        # Tight budget: only enough for 2 tools (~180 chars)
        desc = generate_codemode_description(tools, inline_budget=50)

        # Core tools should appear in declarations
        assert "read(args: {" in desc
        assert "write(args: {" in desc
        # MCP tool should be summarized
        assert "mcp_custom_long_tool(args: {" not in desc
        assert "mcp_custom_long_tool" in desc

    def test_empty_tools(self):
        desc = generate_codemode_description([])
        assert "declare const tools: {};" in desc
