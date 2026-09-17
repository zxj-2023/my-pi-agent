import sys
from pathlib import Path
import pytest
from my_agent_core.session.entries import MessageEntry
from my_coding_agent.macro import MacroEngine
from my_coding_agent.rpc_server import RpcServer
from my_agent_llm.models import Response, StreamChunk


class FakeLLM:
    def __init__(self, model="fake-model"):
        self.model = model

    async def achat(self, *a, **kw):
        return Response(content="fake reply", model=self.model)

    async def achat_stream(self, *a, **kw):
        yield StreamChunk(content="fake chunk")


def test_shell_macro_execution(tmp_path: Path):
    engine = MacroEngine()

    # 1. 正常执行与输出捕获
    res = engine.execute_shell("echo hello_macro", cwd=tmp_path, exclude_from_context=False)
    assert res["status"] == "ok"
    assert "hello_macro" in res["output"]
    assert res["exit_code"] == 0
    assert res["exclude_from_context"] is False

    # 2. 静默执行标记
    res_silent = engine.execute_shell("echo silent", cwd=tmp_path, exclude_from_context=True)
    assert res_silent["exclude_from_context"] is True
    assert "silent" in res_silent["output"]

    # 3. 错误退出码
    cmd_fail = f'"{sys.executable}" -c "import sys; sys.exit(42)"'
    res_fail = engine.execute_shell(cmd_fail, cwd=tmp_path)
    assert res_fail["exit_code"] == 42
    assert res_fail["status"] == "error"

    # 4. stdout 和 stderr 捕获
    cmd_stderr = (
        f"\"{sys.executable}\" -c \"import sys; sys.stdout.write('out_part\\n'); sys.stderr.write('err_part\\n')\""
    )
    res_streams = engine.execute_shell(cmd_stderr, cwd=tmp_path)
    assert "out_part" in res_streams["stdout"]
    assert "err_part" in res_streams["stderr"]
    assert "out_part" in res_streams["output"]
    assert "err_part" in res_streams["output"]

    # 5. 超时控制
    cmd_timeout = f'"{sys.executable}" -c "import time; time.sleep(5)"'
    res_timeout = engine.execute_shell(cmd_timeout, cwd=tmp_path, timeout=0.2)
    assert res_timeout["status"] == "error"
    assert res_timeout["exit_code"] != 0
    assert "timed out" in res_timeout["output"].lower()

    # 6. 空命令防御
    res_empty = engine.execute_shell("", cwd=tmp_path)
    assert res_empty["status"] == "error"
    assert res_empty["exit_code"] == -1


def test_skill_macro_expansion(tmp_path: Path):
    engine = MacroEngine()
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "deploy"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: deploy\ndescription: deployment procedure\n---\n# Deploy Steps\nRun deploy script.",
        encoding="utf-8",
    )

    # 1. 正常展开：剥离 frontmatter、标准 XML 封装、追加参数
    expanded = engine.expand_skill("deploy", "staging --dry-run", skills_dir=skills_dir)
    assert expanded is not None
    assert '<skill name="deploy"' in expanded
    assert f'location="{str((skill_dir / "SKILL.md").resolve())}"' in expanded
    assert "# Deploy Steps" in expanded
    assert "Run deploy script." in expanded
    assert "staging --dry-run" in expanded
    assert "---" not in expanded
    assert "description: deployment procedure" not in expanded

    # 2. 无参数展开：末尾不附带多余空行参数
    expanded_no_args = engine.expand_skill("deploy", "", skills_dir=skills_dir)
    assert expanded_no_args is not None
    assert expanded_no_args.endswith("</skill>")

    # 3. 不存在的技能返回 None
    missing = engine.expand_skill("nonexistent_skill", "args", skills_dir=skills_dir)
    assert missing is None

    # 4. 空技能名称返回 None
    assert engine.expand_skill("", "args") is None

    # 5. 通过 SkillManager 展开技能
    from my_agent_core.skills import SkillManager

    manager = SkillManager(dirs=[skills_dir])
    expanded_sm = engine.expand_skill("deploy", "prod", skill_manager=manager)
    assert expanded_sm is not None
    assert '<skill name="deploy"' in expanded_sm
    assert "prod" in expanded_sm


def test_template_macro_expansion(tmp_path: Path):
    engine = MacroEngine()
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True)

    # 1. 位置参数 $1, $2 与全部参数 $@, $ARGUMENTS，Bash shlex 引号分词
    (prompts_dir / "review.md").write_text(
        "Target: $1 | Second: $2 | AllAt: $@ | AllArgs: $ARGUMENTS",
        encoding="utf-8",
    )
    expanded = engine.expand_template(
        "review",
        "\"src/main.py\" 'second arg with space' 3rd_arg",
        prompts_dir=prompts_dir,
    )
    assert expanded == (
        "Target: src/main.py | "
        "Second: second arg with space | "
        "AllAt: src/main.py second arg with space 3rd_arg | "
        "AllArgs: src/main.py second arg with space 3rd_arg"
    )

    # 2. 带默认值位置参数 ${N:-default}
    (prompts_dir / "defaults.md").write_text(
        "A: ${1:-alpha} | B: ${2:-beta}",
        encoding="utf-8",
    )
    exp_def1 = engine.expand_template("defaults", "custom_a", prompts_dir=prompts_dir)
    assert exp_def1 == "A: custom_a | B: beta"

    exp_def2 = engine.expand_template("defaults", "", prompts_dir=prompts_dir)
    assert exp_def2 == "A: alpha | B: beta"

    # 3. 全部参数默认值 ${@:-default}
    (prompts_dir / "all_defaults.md").write_text(
        "Result: ${@:-none specified}",
        encoding="utf-8",
    )
    exp_all_def = engine.expand_template("all_defaults", "", prompts_dir=prompts_dir)
    assert exp_all_def == "Result: none specified"
    exp_all_given = engine.expand_template("all_defaults", "foo bar", prompts_dir=prompts_dir)
    assert exp_all_given == "Result: foo bar"

    # 4. 切片参数 ${@:N} 与 ${@:N:L}
    (prompts_dir / "slice.md").write_text(
        "From2: ${@:2} | From2Len2: ${@:2:2}",
        encoding="utf-8",
    )
    exp_slice = engine.expand_template("slice", "a b c d e", prompts_dir=prompts_dir)
    assert exp_slice == "From2: b c d e | From2Len2: b c"

    # 5. 带 YAML Frontmatter 的模板自动脱壳
    (prompts_dir / "with_frontmatter.md").write_text(
        "---\ndescription: test prompt\n---\nPrompt body: $1",
        encoding="utf-8",
    )
    exp_fm = engine.expand_template("with_frontmatter", "hello", prompts_dir=prompts_dir)
    assert exp_fm == "Prompt body: hello"

    # 6. 不存在的模板返回 None
    assert engine.expand_template("nonexistent", "args", prompts_dir=prompts_dir) is None
    assert engine.expand_template("", "args") is None


@pytest.mark.anyio
async def test_rpc_shell_exec(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )

    assert server.agent is not None
    initial_entries_count = len(server.agent.session.tree.entries)

    # 1. exclude_from_context=False：执行命令并将格式化消息追加至 session
    resp1 = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "shell_exec",
            "params": {"command": "echo hello_context", "exclude_from_context": False},
        }
    )
    assert resp1["result"]["status"] == "ok"
    assert "hello_context" in resp1["result"]["output"]
    assert resp1["result"]["exit_code"] == 0

    assert server.agent is not None
    entries_after_exec = list(server.agent.session.tree.entries.values())
    assert len(entries_after_exec) == initial_entries_count + 1

    last_entry = entries_after_exec[-1]
    assert isinstance(last_entry, MessageEntry)
    assert "Ran `echo hello_context`" in last_entry.message.content
    assert "hello_context" in last_entry.message.content

    # 2. exclude_from_context=True：静默执行，不追加到 session
    resp2 = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "shell_exec",
            "params": {"command": "echo silent_probe", "exclude_from_context": True},
        }
    )
    assert resp2["result"]["status"] == "ok"
    assert "silent_probe" in resp2["result"]["output"]
    assert server.agent is not None
    assert len(server.agent.session.tree.entries) == initial_entries_count + 1

    # 3. 缺少 command 参数返回错误
    resp_missing_cmd = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "shell_exec",
            "params": {},
        }
    )
    assert "error" in resp_missing_cmd
    assert resp_missing_cmd["error"]["code"] == -32602

    # 4. 未初始化 agent 调用 shell_exec 返回错误
    uninit_server = RpcServer(llm=FakeLLM())
    resp_uninit = await uninit_server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "shell_exec",
            "params": {"command": "echo test"},
        }
    )
    assert "error" in resp_uninit
    assert resp_uninit["error"]["code"] == -32001


@pytest.mark.anyio
async def test_rpc_macro_expand(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    # 构造 workspace 下的 skill 与 template
    skills_dir = workspace / ".agents" / "skills"
    skill_dir = skills_dir / "deploy"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: deploy\ndescription: test\n---\n# Deploy\nPerform deployment.",
        encoding="utf-8",
    )

    prompts_dir = workspace / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "review.md").write_text(
        "Review target: $1 with options: $@",
        encoding="utf-8",
    )

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )

    # 1. 展开 /skill:<name> [args] 与 /skill <name> [args]
    resp_skill = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "macro_expand",
            "params": {"text": "/skill:deploy staging --check"},
        }
    )
    assert resp_skill["result"]["status"] == "ok"
    assert resp_skill["result"]["expanded"] is True
    assert '<skill name="deploy"' in resp_skill["result"]["text"]
    assert "staging --check" in resp_skill["result"]["text"]

    resp_skill_space = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 21,
            "method": "macro_expand",
            "params": {"text": "/skill deploy prod --fast"},
        }
    )
    assert resp_skill_space["result"]["status"] == "ok"
    assert resp_skill_space["result"]["expanded"] is True
    assert '<skill name="deploy"' in resp_skill_space["result"]["text"]
    assert "prod --fast" in resp_skill_space["result"]["text"]

    # 2. 展开 /<template> [args]
    resp_tpl = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "macro_expand",
            "params": {"text": "/review src/main.py --strict"},
        }
    )
    assert resp_tpl["result"]["status"] == "ok"
    assert resp_tpl["result"]["expanded"] is True
    assert resp_tpl["result"]["text"] == "Review target: src/main.py with options: src/main.py --strict"

    # 3. 未知宏或非宏文本保持原样且 expanded=False
    resp_unknown_skill = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "macro_expand",
            "params": {"text": "/skill:unknown_test"},
        }
    )
    assert resp_unknown_skill["result"]["status"] == "ok"
    assert resp_unknown_skill["result"]["expanded"] is False
    assert resp_unknown_skill["result"]["text"] == "/skill:unknown_test"

    resp_normal = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "macro_expand",
            "params": {"text": "hello this is normal input"},
        }
    )
    assert resp_normal["result"]["status"] == "ok"
    assert resp_normal["result"]["expanded"] is False
    assert resp_normal["result"]["text"] == "hello this is normal input"
