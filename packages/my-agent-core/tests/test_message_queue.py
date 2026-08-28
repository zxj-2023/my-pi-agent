from my_agent_core.message_queue import MessageQueue


def test_message_queue_basic():
    q = MessageQueue()
    assert len(q) == 0
    assert not q
    assert not q.has_steering()
    assert not q.has_followup()
    assert q.get_status() == "Queue empty"

    q.add_steering("Steer 1")
    assert len(q) == 1
    assert bool(q)
    assert q.has_steering()
    assert not q.has_followup()
    assert "1 steering" in q.get_status()

    q.add_followup("Follow 1")
    assert len(q) == 2
    assert q.has_steering()
    assert q.has_followup()
    assert "1 steering" in q.get_status() and "1 follow-up" in q.get_status()


def test_steering_one_at_a_time():
    q = MessageQueue(steering_mode="one-at-a-time")
    q.add_steering("S1")
    q.add_steering("S2")
    q.add_followup("F1")

    s_msgs = q.get_steering_messages()
    assert len(s_msgs) == 1
    assert s_msgs[0].content == "S1"
    assert q.has_steering()
    assert len(q) == 2

    s_msgs2 = q.get_steering_messages()
    assert len(s_msgs2) == 1
    assert s_msgs2[0].content == "S2"
    assert not q.has_steering()
    assert q.has_followup()


def test_steering_all():
    q = MessageQueue(steering_mode="all")
    q.add_steering("S1")
    q.add_steering("S2")
    q.add_followup("F1")

    s_msgs = q.get_steering_messages()
    assert len(s_msgs) == 2
    assert [m.content for m in s_msgs] == ["S1", "S2"]
    assert not q.has_steering()
    assert q.has_followup()


def test_followup_one_at_a_time_and_all():
    q = MessageQueue(followup_mode="one-at-a-time")
    q.add_followup("F1")
    q.add_followup("F2")

    f1 = q.get_followup_messages()
    assert len(f1) == 1
    assert f1[0].content == "F1"
    assert q.has_followup()

    q.followup_mode = "all"
    q.add_followup("F3")
    f_all = q.get_followup_messages()
    assert len(f_all) == 2
    assert [m.content for m in f_all] == ["F2", "F3"]
    assert not q.has_followup()


def test_clear_and_peek():
    q = MessageQueue()
    q.add_steering("S1")
    assert q.peek().content == "S1"
    cleared = q.clear()
    assert len(cleared) == 1
    assert len(q) == 0
    assert q.peek() is None
