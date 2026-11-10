from __future__ import annotations

from pathlib import Path

import pytest

from my_agent_core.registry import ToolRegistry
from my_agent_core.session import Session, CodemodeStoreEntry
from my_agent_core.tools.codemode import make_codemode_tool

pytestmark = pytest.mark.anyio


@pytest.fixture
def temp_session(tmp_path: Path) -> Session:
    session_file = tmp_path / "test_session.jsonl"
    return Session(path=session_file)


async def test_multi_turn_store_persistence(temp_session: Session):
    registry = ToolRegistry()
    tool = make_codemode_tool(registry, session=temp_session)

    # Turn 1: Store initial counter
    res1 = await tool.execute({"code": "store('counter', 10); text('turn1_done');"})
    assert res1.ok is True
    assert "turn1_done" in res1.content

    # Verify session tree recorded the write
    path_entries = temp_session.tree.get_current_path()
    store_entries = [e for e in path_entries if isinstance(e, CodemodeStoreEntry)]
    assert len(store_entries) == 1
    assert store_entries[0].data == {"counter": 10}

    # Turn 2: Read counter and compute
    res2 = await tool.execute({"code": "text(load('counter') + 5);"})
    assert res2.ok is True
    assert "15" in res2.content

    # Turn 3: Add new key and update counter
    res3 = await tool.execute({"code": "store('msg', 'hello'); store('counter', 20); text('turn3_done');"})
    assert res3.ok is True

    # Turn 4: Verify both keys
    res4 = await tool.execute({"code": "text(load('msg') + ' ' + load('counter'));"})
    assert res4.ok is True
    assert "hello 20" in res4.content


async def test_error_script_does_not_persist_store(temp_session: Session):
    registry = ToolRegistry()
    tool = make_codemode_tool(registry, session=temp_session)

    # Turn 1: Establish safe value
    res1 = await tool.execute({"code": "store('status', 'safe'); text('saved');"})
    assert res1.ok is True

    initial_entry_count = len(temp_session.tree.entries)

    # Turn 2: Attempt dirty write followed by throw
    res2 = await tool.execute({"code": "store('status', 'corrupted'); throw new Error('boom');"})
    assert res2.ok is False
    assert "Script failed" in res2.content

    # Verify no new entry was added to session
    assert len(temp_session.tree.entries) == initial_entry_count

    # Turn 3: Read back status, ensuring it remains 'safe'
    res3 = await tool.execute({"code": "text(load('status'));"})
    assert res3.ok is True
    assert "safe" in res3.content
    assert "corrupted" not in res3.content


async def test_session_rewind_isolation(temp_session: Session):
    registry = ToolRegistry()
    tool = make_codemode_tool(registry, session=temp_session)

    # Turn 1: Val = 100
    res1 = await tool.execute({"code": "store('num', 100); text('t1');"})
    assert res1.ok is True
    checkpoint_id = temp_session.tree.current_id
    assert checkpoint_id is not None

    # Turn 2 (Branch A): Val = 200
    res2 = await tool.execute({"code": "store('num', 200); text('t2');"})
    assert res2.ok is True
    branch_a_id = temp_session.tree.current_id

    # Verify Branch A reads 200
    res2_check = await tool.execute({"code": "text(load('num'));"})
    assert "200" in res2_check.content

    # Rewind to checkpoint (Turn 1)
    temp_session.rewind(checkpoint_id)

    # Turn 3 (Branch B): Should read 100, not 200!
    res3 = await tool.execute({"code": "text(load('num'));"})
    assert res3.ok is True
    assert "100" in res3.content

    # Turn 4 (Branch B): Overwrite with 300
    res4 = await tool.execute({"code": "store('num', 300); text('t4');"})
    assert res4.ok is True

    # Branch B now reads 300
    res4_check = await tool.execute({"code": "text(load('num'));"})
    assert "300" in res4_check.content

    # Rewind back to Branch A
    assert branch_a_id is not None
    temp_session.rewind(branch_a_id)
    res_a_check = await tool.execute({"code": "text(load('num'));"})
    assert "200" in res_a_check.content


async def test_session_fork_isolation(temp_session: Session, tmp_path: Path):
    registry = ToolRegistry()
    tool = make_codemode_tool(registry, session=temp_session)

    # Base turn
    await tool.execute({"code": "store('env', 'production'); text('ok');"})
    base_id = temp_session.tree.current_id
    assert base_id is not None

    # Fork session
    fork_file = tmp_path / "forked_session.jsonl"
    forked_session = temp_session.fork(base_id, new_path=fork_file)
    forked_tool = make_codemode_tool(registry, session=forked_session)

    # Verify forked session inherited production
    res_fork_read = await forked_tool.execute({"code": "text(load('env'));"})
    assert "production" in res_fork_read.content

    # Modify in forked session
    await forked_tool.execute({"code": "store('env', 'staging'); text('modified');"})
    res_fork_mod = await forked_tool.execute({"code": "text(load('env'));"})
    assert "staging" in res_fork_mod.content

    # Original session remains 'production'
    res_orig = await tool.execute({"code": "text(load('env'));"})
    assert "production" in res_orig.content


async def test_session_disk_persistence_and_reload(tmp_path: Path):
    registry = ToolRegistry()
    session_file = tmp_path / "persisted.jsonl"
    session1 = Session(path=session_file)
    tool1 = make_codemode_tool(registry, session=session1)

    await tool1.execute({"code": "store('api_version', 'v2'); store('retries', 3); text('done');"})

    # Ensure file exists and contains entries
    assert session_file.exists()

    # Reload from disk
    session2 = Session.load(session_file)
    tool2 = make_codemode_tool(registry, session=session2)

    res = await tool2.execute({"code": "text(load('api_version') + ' r=' + load('retries'));"})
    assert res.ok is True
    assert "v2 r=3" in res.content


async def test_custom_entry_backward_compatibility(temp_session: Session):
    # Test folding of CustomEntry(custom_type="codemode-store")
    temp_session.add_custom_entry("codemode-store", {"legacy_key": "legacy_val"})

    registry = ToolRegistry()
    tool = make_codemode_tool(registry, session=temp_session)

    res = await tool.execute({"code": "text(load('legacy_key'));"})
    assert res.ok is True
    assert "legacy_val" in res.content
