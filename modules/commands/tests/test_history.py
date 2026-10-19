"""History tests — recording + recent(n) (TP-CAT-01)."""

from bccmd import History


def test_append_and_recent():
    history = History()
    history.append(command="LINE", raw_inputs=["0,0", "10,0"], summary="LINE: 1 segment(s)")
    history.append(command="CIRCLE", raw_inputs=["5,5", "3"], summary="CIRCLE done")
    history.append(command="MOVE", raw_inputs=["0,0", "1,1"], summary="MOVE done")
    recent = history.recent(2)
    assert [e.command for e in recent] == ["CIRCLE", "MOVE"]
    assert recent[0].inputs == ["5,5", "3"]


def test_entry_fields_and_timestamp():
    history = History()
    entry = history.append(
        command="ERASE", raw_inputs=["<selection>"],
        summary="ERASE: removed 1 object(s)", status="ok",
    )
    assert entry.command == "ERASE"
    assert entry.status == "ok"
    assert entry.timestamp  # ISO-8601 UTC
    assert "T" in entry.timestamp
    assert entry.inputs == ["<selection>"]


def test_recent_over_capacity():
    history = History(limit=3)
    for i in range(5):
        history.append(command=f"C{i}", summary="")
    assert len(history) == 3
    assert [e.command for e in history.recent(10)] == ["C2", "C3", "C4"]


def test_recent_zero_or_negative():
    history = History()
    history.append(command="LINE", summary="")
    assert history.recent(0) == []
    assert history.recent(-1) == []


def test_last_command():
    history = History()
    assert history.last_command() is None
    history.append(command="LINE", summary="", status="cancelled")
    history.append(command="CIRCLE", summary="")
    assert history.last_command() == "CIRCLE"


def test_as_lines_echo_format():
    history = History()
    history.append(command="LINE", raw_inputs=["0,0"], summary="LINE: 1 segment(s)")
    lines = history.as_lines()
    assert "Command: LINE" in lines
    assert "  0,0" in lines
    assert any("-> LINE: 1 segment(s) [ok]" in line for line in lines)


def test_clear():
    history = History()
    history.append(command="LINE", summary="")
    history.clear()
    assert len(history) == 0
