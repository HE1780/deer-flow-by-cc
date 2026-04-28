"""Tests for LoopDetectionMiddleware."""

import copy
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage

from deerflow.agents.middlewares.loop_detection_middleware import (
    _HARD_STOP_MSG,
    LoopDetectionMiddleware,
    _hash_tool_calls,
)


def _make_runtime(thread_id="test-thread"):
    """Build a minimal Runtime mock with context."""
    runtime = MagicMock()
    runtime.context = {"thread_id": thread_id}
    return runtime


def _make_state(tool_calls=None, content=""):
    """Build a minimal AgentState dict with an AIMessage.

    Deep-copies *content* when it is mutable (e.g. list) so that
    successive calls never share the same object reference.
    """
    safe_content = copy.deepcopy(content) if isinstance(content, list) else content
    msg = AIMessage(content=safe_content, tool_calls=tool_calls or [])
    return {"messages": [msg]}


def _bash_call(cmd="ls"):
    return {"name": "bash", "id": f"call_{cmd}", "args": {"command": cmd}}


class TestHashToolCalls:
    def test_same_calls_same_hash(self):
        a = _hash_tool_calls([_bash_call("ls")])
        b = _hash_tool_calls([_bash_call("ls")])
        assert a == b

    def test_different_calls_different_hash(self):
        a = _hash_tool_calls([_bash_call("ls")])
        b = _hash_tool_calls([_bash_call("pwd")])
        assert a != b

    def test_order_independent(self):
        a = _hash_tool_calls([_bash_call("ls"), {"name": "read_file", "args": {"path": "/tmp"}}])
        b = _hash_tool_calls([{"name": "read_file", "args": {"path": "/tmp"}}, _bash_call("ls")])
        assert a == b

    def test_empty_calls(self):
        h = _hash_tool_calls([])
        assert isinstance(h, str)
        assert len(h) > 0

    def test_stringified_dict_args_match_dict_args(self):
        dict_call = {
            "name": "read_file",
            "args": {"path": "/tmp/demo.py", "start_line": "1", "end_line": "150"},
        }
        string_call = {
            "name": "read_file",
            "args": '{"path":"/tmp/demo.py","start_line":"1","end_line":"150"}',
        }

        assert _hash_tool_calls([dict_call]) == _hash_tool_calls([string_call])

    def test_reversed_read_file_range_matches_forward_range(self):
        forward_call = {
            "name": "read_file",
            "args": {"path": "/tmp/demo.py", "start_line": 10, "end_line": 300},
        }
        reversed_call = {
            "name": "read_file",
            "args": {"path": "/tmp/demo.py", "start_line": 300, "end_line": 10},
        }

        assert _hash_tool_calls([forward_call]) == _hash_tool_calls([reversed_call])

    def test_stringified_non_dict_args_do_not_crash(self):
        non_dict_json_call = {"name": "bash", "args": '"echo hello"'}
        plain_string_call = {"name": "bash", "args": "echo hello"}

        json_hash = _hash_tool_calls([non_dict_json_call])
        plain_hash = _hash_tool_calls([plain_string_call])

        assert isinstance(json_hash, str)
        assert isinstance(plain_hash, str)
        assert json_hash
        assert plain_hash

    def test_grep_pattern_affects_hash(self):
        grep_foo = {"name": "grep", "args": {"path": "/tmp", "pattern": "foo"}}
        grep_bar = {"name": "grep", "args": {"path": "/tmp", "pattern": "bar"}}

        assert _hash_tool_calls([grep_foo]) != _hash_tool_calls([grep_bar])

    def test_glob_pattern_affects_hash(self):
        glob_py = {"name": "glob", "args": {"path": "/tmp", "pattern": "*.py"}}
        glob_ts = {"name": "glob", "args": {"path": "/tmp", "pattern": "*.ts"}}

        assert _hash_tool_calls([glob_py]) != _hash_tool_calls([glob_ts])

    def test_write_file_content_affects_hash(self):
        v1 = {"name": "write_file", "args": {"path": "/tmp/a.py", "content": "v1"}}
        v2 = {"name": "write_file", "args": {"path": "/tmp/a.py", "content": "v2"}}
        assert _hash_tool_calls([v1]) != _hash_tool_calls([v2])

    def test_str_replace_content_affects_hash(self):
        a = {
            "name": "str_replace",
            "args": {"path": "/tmp/a.py", "old_str": "foo", "new_str": "bar"},
        }
        b = {
            "name": "str_replace",
            "args": {"path": "/tmp/a.py", "old_str": "foo", "new_str": "baz"},
        }
        assert _hash_tool_calls([a]) != _hash_tool_calls([b])


class TestLoopDetection:
    def test_no_tool_calls_returns_none(self):
        mw = LoopDetectionMiddleware()
        runtime = _make_runtime()
        state = {"messages": [AIMessage(content="hello")]}
        result = mw._apply(state, runtime)
        assert result is None

    def test_below_threshold_returns_none(self):
        mw = LoopDetectionMiddleware(warn_threshold=3)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        # First two identical calls — no warning
        for _ in range(2):
            result = mw._apply(_make_state(tool_calls=call), runtime)
            assert result is None

    def test_warn_at_threshold(self):
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=5)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        for _ in range(2):
            mw._apply(_make_state(tool_calls=call), runtime)

        # Third identical call triggers warning
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is not None
        msgs = result["messages"]
        assert len(msgs) == 1
        assert isinstance(msgs[0], HumanMessage)
        assert "LOOP DETECTED" in msgs[0].content

    def test_warn_only_injected_once(self):
        """Warning for the same hash should only be injected once per thread."""
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=10)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        # First two — no warning
        for _ in range(2):
            mw._apply(_make_state(tool_calls=call), runtime)

        # Third — warning injected
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is not None
        assert "LOOP DETECTED" in result["messages"][0].content

        # Fourth — warning already injected, should return None
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is None

    def test_hard_stop_at_limit(self):
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=call), runtime)

        # Fourth call triggers hard stop
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is not None
        msgs = result["messages"]
        assert len(msgs) == 1
        # Hard stop strips tool_calls
        assert isinstance(msgs[0], AIMessage)
        assert msgs[0].tool_calls == []
        assert _HARD_STOP_MSG in msgs[0].content

    def test_different_calls_dont_trigger(self):
        mw = LoopDetectionMiddleware(warn_threshold=2)
        runtime = _make_runtime()

        # Each call is different
        for i in range(10):
            result = mw._apply(_make_state(tool_calls=[_bash_call(f"cmd_{i}")]), runtime)
            assert result is None

    def test_window_sliding(self):
        mw = LoopDetectionMiddleware(warn_threshold=3, window_size=5)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        # Fill with 2 identical calls
        mw._apply(_make_state(tool_calls=call), runtime)
        mw._apply(_make_state(tool_calls=call), runtime)

        # Push them out of the window with different calls
        for i in range(5):
            mw._apply(_make_state(tool_calls=[_bash_call(f"other_{i}")]), runtime)

        # Now the original call should be fresh again — no warning
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is None

    def test_reset_clears_state(self):
        mw = LoopDetectionMiddleware(warn_threshold=2)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        mw._apply(_make_state(tool_calls=call), runtime)
        mw._apply(_make_state(tool_calls=call), runtime)

        # Would trigger warning, but reset first
        mw.reset()
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is None

    def test_non_ai_message_ignored(self):
        mw = LoopDetectionMiddleware()
        runtime = _make_runtime()
        state = {"messages": [SystemMessage(content="hello")]}
        result = mw._apply(state, runtime)
        assert result is None

    def test_empty_messages_ignored(self):
        mw = LoopDetectionMiddleware()
        runtime = _make_runtime()
        result = mw._apply({"messages": []}, runtime)
        assert result is None

    def test_thread_id_from_runtime_context(self):
        """Thread ID should come from runtime.context, not state."""
        mw = LoopDetectionMiddleware(warn_threshold=2)
        runtime_a = _make_runtime("thread-A")
        runtime_b = _make_runtime("thread-B")
        call = [_bash_call("ls")]

        # One call on thread A
        mw._apply(_make_state(tool_calls=call), runtime_a)
        # One call on thread B
        mw._apply(_make_state(tool_calls=call), runtime_b)

        # Second call on thread A — triggers warning (2 >= warn_threshold)
        result = mw._apply(_make_state(tool_calls=call), runtime_a)
        assert result is not None
        assert "LOOP DETECTED" in result["messages"][0].content

        # Second call on thread B — also triggers (independent tracking)
        result = mw._apply(_make_state(tool_calls=call), runtime_b)
        assert result is not None
        assert "LOOP DETECTED" in result["messages"][0].content

    def test_lru_eviction(self):
        """Old threads should be evicted when max_tracked_threads is exceeded."""
        mw = LoopDetectionMiddleware(warn_threshold=2, max_tracked_threads=3)
        call = [_bash_call("ls")]

        # Fill up 3 threads
        for i in range(3):
            runtime = _make_runtime(f"thread-{i}")
            mw._apply(_make_state(tool_calls=call), runtime)

        # Add a 4th thread — should evict thread-0
        runtime_new = _make_runtime("thread-new")
        mw._apply(_make_state(tool_calls=call), runtime_new)

        assert "thread-0" not in mw._history
        assert "thread-0" not in mw._tool_freq
        assert "thread-0" not in mw._tool_freq_warned
        assert "thread-new" in mw._history
        assert len(mw._history) == 3

    def test_thread_safe_mutations(self):
        """Verify lock is used for mutations (basic structural test)."""
        mw = LoopDetectionMiddleware()
        # The middleware should have a lock attribute
        assert hasattr(mw, "_lock")
        assert isinstance(mw._lock, type(mw._lock))

    def test_fallback_thread_id_when_missing(self):
        """When runtime context has no thread_id, should use 'default'."""
        mw = LoopDetectionMiddleware(warn_threshold=2)
        runtime = MagicMock()
        runtime.context = {}
        call = [_bash_call("ls")]

        mw._apply(_make_state(tool_calls=call), runtime)
        assert "default" in mw._history


class TestAppendText:
    """Unit tests for LoopDetectionMiddleware._append_text."""

    def test_none_content_returns_text(self):
        result = LoopDetectionMiddleware._append_text(None, "hello")
        assert result == "hello"

    def test_str_content_concatenates(self):
        result = LoopDetectionMiddleware._append_text("existing", "appended")
        assert result == "existing\n\nappended"

    def test_empty_str_content_concatenates(self):
        result = LoopDetectionMiddleware._append_text("", "appended")
        assert result == "\n\nappended"

    def test_list_content_appends_text_block(self):
        """List content (e.g. Anthropic thinking mode) should get a new text block."""
        content = [
            {"type": "thinking", "text": "Let me think..."},
            {"type": "text", "text": "Here is my answer"},
        ]
        result = LoopDetectionMiddleware._append_text(content, "stop msg")
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0] == content[0]
        assert result[1] == content[1]
        assert result[2] == {"type": "text", "text": "\n\nstop msg"}

    def test_empty_list_content_appends_text_block(self):
        result = LoopDetectionMiddleware._append_text([], "stop msg")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0] == {"type": "text", "text": "\n\nstop msg"}

    def test_unexpected_type_coerced_to_str(self):
        """Unexpected content types should be coerced to str as a fallback."""
        result = LoopDetectionMiddleware._append_text(42, "stop msg")
        assert isinstance(result, str)
        assert result == "42\n\nstop msg"

    def test_list_content_not_mutated_in_place(self):
        """_append_text must not modify the original list."""
        original = [{"type": "text", "text": "hello"}]
        result = LoopDetectionMiddleware._append_text(original, "appended")
        assert len(original) == 1  # original unchanged
        assert len(result) == 2  # new list has the appended block


class TestHardStopWithListContent:
    """Regression tests: hard stop must not crash when AIMessage.content is a list."""

    def test_hard_stop_with_list_content(self):
        """Hard stop on list content should not raise TypeError (regression)."""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        # Build state with list content (e.g. Anthropic thinking mode)
        list_content = [
            {"type": "thinking", "text": "Let me think..."},
            {"type": "text", "text": "I'll run ls"},
        ]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=call, content=list_content), runtime)

        # Fourth call triggers hard stop — must not raise TypeError
        result = mw._apply(_make_state(tool_calls=call, content=list_content), runtime)
        assert result is not None
        msg = result["messages"][0]
        assert isinstance(msg, AIMessage)
        assert msg.tool_calls == []
        # Content should remain a list with the stop message appended
        assert isinstance(msg.content, list)
        assert len(msg.content) == 3
        assert msg.content[2]["type"] == "text"
        assert _HARD_STOP_MSG in msg.content[2]["text"]

    def test_hard_stop_with_none_content(self):
        """Hard stop on None content should produce a plain string."""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=call), runtime)

        # Fourth call with default empty-string content
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is not None
        msg = result["messages"][0]
        assert isinstance(msg.content, str)
        assert _HARD_STOP_MSG in msg.content

    def test_hard_stop_with_str_content(self):
        """Hard stop on str content should concatenate the stop message."""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=call, content="thinking..."), runtime)

        result = mw._apply(_make_state(tool_calls=call, content="thinking..."), runtime)
        assert result is not None
        msg = result["messages"][0]
        assert isinstance(msg.content, str)
        assert msg.content.startswith("thinking...")
        assert _HARD_STOP_MSG in msg.content

    def test_hard_stop_clears_raw_tool_call_metadata(self):
        """Forced-stop messages must not retain provider-level raw tool-call payloads."""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        def _make_provider_state():
            return {
                "messages": [
                    AIMessage(
                        content="thinking...",
                        tool_calls=call,
                        additional_kwargs={
                            "tool_calls": [
                                {
                                    "id": "call_ls",
                                    "type": "function",
                                    "function": {"name": "bash", "arguments": '{"command":"ls"}'},
                                    "thought_signature": "sig-1",
                                }
                            ],
                            "function_call": {"name": "bash", "arguments": '{"command":"ls"}'},
                        },
                        response_metadata={"finish_reason": "tool_calls"},
                    )
                ]
            }

        for _ in range(3):
            mw._apply(_make_provider_state(), runtime)

        result = mw._apply(_make_provider_state(), runtime)
        assert result is not None
        msg = result["messages"][0]
        assert msg.tool_calls == []
        assert "tool_calls" not in msg.additional_kwargs
        assert "function_call" not in msg.additional_kwargs
        assert msg.response_metadata["finish_reason"] == "stop"


class TestToolFrequencyDetection:
    """Tests for per-tool-type frequency detection (Layer 2).

    This catches the case where an agent calls the same tool type many times
    with *different* arguments (e.g. read_file on 40 different files), which
    bypasses hash-based detection.
    """

    def _read_call(self, path):
        return {"name": "read_file", "id": f"call_read_{path}", "args": {"path": path}}

    def test_below_freq_warn_returns_none(self):
        mw = LoopDetectionMiddleware(tool_freq_warn=5, tool_freq_hard_limit=10)
        runtime = _make_runtime()

        for i in range(4):
            result = mw._apply(_make_state(tool_calls=[self._read_call(f"/file_{i}.py")]), runtime)
            assert result is None

    def test_freq_warn_at_threshold(self):
        mw = LoopDetectionMiddleware(tool_freq_warn=5, tool_freq_hard_limit=10)
        runtime = _make_runtime()

        for i in range(4):
            mw._apply(_make_state(tool_calls=[self._read_call(f"/file_{i}.py")]), runtime)

        # 5th call to read_file (different file each time) triggers freq warning
        result = mw._apply(_make_state(tool_calls=[self._read_call("/file_4.py")]), runtime)
        assert result is not None
        msg = result["messages"][0]
        assert isinstance(msg, HumanMessage)
        assert "read_file" in msg.content
        assert "LOOP DETECTED" in msg.content

    def test_freq_warn_only_injected_once(self):
        mw = LoopDetectionMiddleware(tool_freq_warn=3, tool_freq_hard_limit=10)
        runtime = _make_runtime()

        for i in range(2):
            mw._apply(_make_state(tool_calls=[self._read_call(f"/file_{i}.py")]), runtime)

        # 3rd triggers warning
        result = mw._apply(_make_state(tool_calls=[self._read_call("/file_2.py")]), runtime)
        assert result is not None
        assert "LOOP DETECTED" in result["messages"][0].content

        # 4th should not re-warn (already warned for read_file)
        result = mw._apply(_make_state(tool_calls=[self._read_call("/file_3.py")]), runtime)
        assert result is None

    def test_freq_hard_stop_at_limit(self):
        mw = LoopDetectionMiddleware(tool_freq_warn=3, tool_freq_hard_limit=6)
        runtime = _make_runtime()

        for i in range(5):
            mw._apply(_make_state(tool_calls=[self._read_call(f"/file_{i}.py")]), runtime)

        # 6th call triggers hard stop
        result = mw._apply(_make_state(tool_calls=[self._read_call("/file_5.py")]), runtime)
        assert result is not None
        msg = result["messages"][0]
        assert isinstance(msg, AIMessage)
        assert msg.tool_calls == []
        assert "FORCED STOP" in msg.content
        assert "read_file" in msg.content

    def test_different_tools_tracked_independently(self):
        """read_file and bash should have independent frequency counters."""
        mw = LoopDetectionMiddleware(tool_freq_warn=3, tool_freq_hard_limit=10)
        runtime = _make_runtime()

        # 2 read_file calls
        for i in range(2):
            mw._apply(_make_state(tool_calls=[self._read_call(f"/file_{i}.py")]), runtime)

        # 2 bash calls — should not trigger (bash count = 2, read_file count = 2)
        for i in range(2):
            result = mw._apply(_make_state(tool_calls=[_bash_call(f"cmd_{i}")]), runtime)
            assert result is None

        # 3rd read_file triggers (read_file count = 3)
        result = mw._apply(_make_state(tool_calls=[self._read_call("/file_2.py")]), runtime)
        assert result is not None
        assert "read_file" in result["messages"][0].content

    def test_freq_reset_clears_state(self):
        mw = LoopDetectionMiddleware(tool_freq_warn=3, tool_freq_hard_limit=10)
        runtime = _make_runtime()

        for i in range(2):
            mw._apply(_make_state(tool_calls=[self._read_call(f"/file_{i}.py")]), runtime)

        mw.reset()

        # After reset, count restarts — should not trigger
        result = mw._apply(_make_state(tool_calls=[self._read_call("/file_new.py")]), runtime)
        assert result is None

    def test_freq_reset_per_thread_clears_only_target(self):
        """reset(thread_id=...) should clear frequency state for that thread only."""
        mw = LoopDetectionMiddleware(tool_freq_warn=3, tool_freq_hard_limit=10)
        runtime_a = _make_runtime("thread-A")
        runtime_b = _make_runtime("thread-B")

        # 2 calls on each thread
        for i in range(2):
            mw._apply(_make_state(tool_calls=[self._read_call(f"/a_{i}.py")]), runtime_a)
            mw._apply(_make_state(tool_calls=[self._read_call(f"/b_{i}.py")]), runtime_b)

        # Reset only thread-A
        mw.reset(thread_id="thread-A")

        assert "thread-A" not in mw._tool_freq
        assert "thread-A" not in mw._tool_freq_warned

        # thread-B state should still be intact — 3rd call triggers warn
        result = mw._apply(_make_state(tool_calls=[self._read_call("/b_2.py")]), runtime_b)
        assert result is not None
        assert "LOOP DETECTED" in result["messages"][0].content

        # thread-A restarted from 0 — should not trigger
        result = mw._apply(_make_state(tool_calls=[self._read_call("/a_new.py")]), runtime_a)
        assert result is None

    def test_freq_per_thread_isolation(self):
        """Frequency counts should be independent per thread."""
        mw = LoopDetectionMiddleware(tool_freq_warn=3, tool_freq_hard_limit=10)
        runtime_a = _make_runtime("thread-A")
        runtime_b = _make_runtime("thread-B")

        # 2 calls on thread A
        for i in range(2):
            mw._apply(_make_state(tool_calls=[self._read_call(f"/file_{i}.py")]), runtime_a)

        # 2 calls on thread B — should NOT push thread A over threshold
        for i in range(2):
            mw._apply(_make_state(tool_calls=[self._read_call(f"/other_{i}.py")]), runtime_b)

        # 3rd call on thread A — triggers (count=3 for thread A only)
        result = mw._apply(_make_state(tool_calls=[self._read_call("/file_2.py")]), runtime_a)
        assert result is not None
        assert "LOOP DETECTED" in result["messages"][0].content

    def test_multi_tool_single_response_counted(self):
        """When a single response has multiple tool calls, each is counted."""
        mw = LoopDetectionMiddleware(tool_freq_warn=5, tool_freq_hard_limit=10)
        runtime = _make_runtime()

        # Response 1: 2 read_file calls → count = 2
        call = [self._read_call("/a.py"), self._read_call("/b.py")]
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is None

        # Response 2: 2 more → count = 4
        call = [self._read_call("/c.py"), self._read_call("/d.py")]
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is None

        # Response 3: 1 more → count = 5 → triggers warn
        result = mw._apply(_make_state(tool_calls=[self._read_call("/e.py")]), runtime)
        assert result is not None
        assert "read_file" in result["messages"][0].content

    def test_hash_detection_takes_priority(self):
        """Hash-based hard stop fires before frequency check for identical calls."""
        mw = LoopDetectionMiddleware(
            warn_threshold=2,
            hard_limit=3,
            tool_freq_warn=100,
            tool_freq_hard_limit=200,
        )
        runtime = _make_runtime()
        call = [self._read_call("/same_file.py")]

        for _ in range(2):
            mw._apply(_make_state(tool_calls=call), runtime)

        # 3rd identical call → hash hard_limit=3 fires (not freq)
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is not None
        msg = result["messages"][0]
        assert isinstance(msg, AIMessage)
        assert _HARD_STOP_MSG in msg.content


class TestPathFailureDetection:
    """Layer 3: detect repeated *failures* of write_file / str_replace on the same path.

    Motivation: when the agent writes a deliverable to one path but its
    reasoning later assumes a different path, str_replace on the wrong
    path keeps returning ``Error: ...`` for varying ``old_str`` / ``new_str``
    arguments. Layer 1 (hash) and Layer 2 (per-tool frequency) both miss
    this:

    - Layer 1 intentionally hashes full args for write_file/str_replace
      (so legitimate iterative editing is not flagged), so each retry
      with different args produces a different hash.
    - Layer 2's threshold (50 calls) is far higher than the typical
      death-spiral length and lets the agent burn many turns first.

    Layer 3 fires only when the same (tool_name, path) pair has produced
    N consecutive ``Error: ...`` ToolMessages — which is exactly the
    failure mode and very unlikely to happen on a healthy run.
    """

    def _ai_call(self, tool_name, path, call_id, **extra_args):
        return AIMessage(
            content="",
            tool_calls=[{
                "name": tool_name,
                "id": call_id,
                "args": {"path": path, **extra_args},
            }],
        )

    def _tool_result(self, call_id, content):
        return ToolMessage(content=content, tool_call_id=call_id)

    def _build_history_with_failed_attempts(self, tool_name, path, failure_count, latest_call_id):
        """Build a message history simulating ``failure_count`` past failed
        attempts on (tool_name, path), followed by a fresh AIMessage that is
        about to make the (failure_count + 1)-th attempt on the same path.
        """
        messages = []
        for i in range(failure_count):
            cid = f"call_fail_{i}"
            messages.append(self._ai_call(tool_name, path, cid, old_str=f"v{i}", new_str=f"u{i}"))
            messages.append(self._tool_result(cid, f"Error: file not found: {path}"))
        # Latest AIMessage — this is the one loop detection runs on.
        messages.append(self._ai_call(tool_name, path, latest_call_id, old_str="vN", new_str="uN"))
        return {"messages": messages}

    def test_no_warn_below_threshold(self):
        """2 prior failures + 1 fresh call = 3 attempts, below default warn=3."""
        mw = LoopDetectionMiddleware(path_failure_warn=3, path_failure_hard_limit=4)
        runtime = _make_runtime()

        state = self._build_history_with_failed_attempts(
            "str_replace", "/mnt/user-data/outputs/x.html",
            failure_count=1, latest_call_id="call_latest",
        )
        result = mw._apply(state, runtime)
        assert result is None

    def test_warn_at_path_failure_threshold(self):
        """3rd attempt on same (tool, path) after 2 prior failures -> warn."""
        mw = LoopDetectionMiddleware(path_failure_warn=3, path_failure_hard_limit=10)
        runtime = _make_runtime()

        state = self._build_history_with_failed_attempts(
            "str_replace", "/mnt/user-data/outputs/x.html",
            failure_count=2, latest_call_id="call_latest",
        )
        result = mw._apply(state, runtime)
        assert result is not None
        msg = result["messages"][0]
        assert isinstance(msg, HumanMessage)
        assert "LOOP DETECTED" in msg.content
        # Mention the offending path so the model can self-correct.
        assert "/mnt/user-data/outputs/x.html" in msg.content
        assert "str_replace" in msg.content

    def test_hard_stop_at_path_failure_limit(self):
        """4th attempt with 3 prior failures triggers hard stop."""
        mw = LoopDetectionMiddleware(path_failure_warn=2, path_failure_hard_limit=4)
        runtime = _make_runtime()

        state = self._build_history_with_failed_attempts(
            "str_replace", "/mnt/user-data/outputs/x.html",
            failure_count=3, latest_call_id="call_latest",
        )
        result = mw._apply(state, runtime)
        assert result is not None
        ai_msgs = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert len(ai_msgs) == 1
        assert ai_msgs[0].tool_calls == []
        assert "FORCED STOP" in ai_msgs[0].content
        assert "/mnt/user-data/outputs/x.html" in ai_msgs[0].content

    def test_successful_tool_calls_reset_streak(self):
        """A successful (non-Error) ToolMessage breaks the failure streak."""
        mw = LoopDetectionMiddleware(path_failure_warn=3, path_failure_hard_limit=4)
        runtime = _make_runtime()

        path = "/mnt/user-data/outputs/x.html"
        messages = [
            self._ai_call("str_replace", path, "c1", old_str="a", new_str="b"),
            self._tool_result("c1", f"Error: file not found: {path}"),
            self._ai_call("str_replace", path, "c2", old_str="a", new_str="b"),
            self._tool_result("c2", f"Error: file not found: {path}"),
            # Successful call mid-stream — should clear the streak
            self._ai_call("str_replace", path, "c3", old_str="x", new_str="y"),
            self._tool_result("c3", "OK"),
            # Latest call: only 1 prior failure since the OK reset
            self._ai_call("str_replace", path, "c_latest", old_str="z", new_str="w"),
        ]
        result = mw._apply({"messages": messages}, runtime)
        assert result is None

    def test_different_paths_tracked_independently(self):
        """Failures on /a.html should not contaminate /b.html's counter."""
        mw = LoopDetectionMiddleware(path_failure_warn=3, path_failure_hard_limit=4)
        runtime = _make_runtime()

        messages = [
            # 2 failures on /a.html
            self._ai_call("str_replace", "/a.html", "ca1", old_str="x", new_str="y"),
            self._tool_result("ca1", "Error: not found"),
            self._ai_call("str_replace", "/a.html", "ca2", old_str="x", new_str="y"),
            self._tool_result("ca2", "Error: not found"),
            # Latest call is on /b.html — first attempt, no prior failures on /b.html
            self._ai_call("str_replace", "/b.html", "cb1", old_str="x", new_str="y"),
        ]
        result = mw._apply({"messages": messages}, runtime)
        assert result is None

    def test_only_applies_to_write_file_and_str_replace(self):
        """read_file failures are not part of this signature (cross-file
        exploration after a missing target is legitimate)."""
        mw = LoopDetectionMiddleware(path_failure_warn=3, path_failure_hard_limit=4)
        runtime = _make_runtime()

        path = "/mnt/user-data/outputs/x.html"
        messages = []
        for i in range(3):
            cid = f"cr{i}"
            messages.append(AIMessage(
                content="",
                tool_calls=[{"name": "read_file", "id": cid, "args": {"path": path}}],
            ))
            messages.append(self._tool_result(cid, "Error: file not found"))
        messages.append(AIMessage(
            content="",
            tool_calls=[{"name": "read_file", "id": "cr_latest", "args": {"path": path}}],
        ))
        result = mw._apply({"messages": messages}, runtime)
        # Layer 3 should not fire on read_file. Layer 1/2 may also not fire
        # under default thresholds — confirm: result is None.
        assert result is None

    def test_write_file_path_failure_also_detected(self):
        """write_file path failures should be flagged the same as str_replace."""
        mw = LoopDetectionMiddleware(path_failure_warn=3, path_failure_hard_limit=10)
        runtime = _make_runtime()

        path = "/mnt/user-data/outputs/x.html"
        messages = [
            self._ai_call("write_file", path, "cw1", content="v1"),
            self._tool_result("cw1", f"Error: Permission denied writing to file: {path}"),
            self._ai_call("write_file", path, "cw2", content="v2"),
            self._tool_result("cw2", f"Error: Permission denied writing to file: {path}"),
            self._ai_call("write_file", path, "cw_latest", content="v3"),
        ]
        result = mw._apply({"messages": messages}, runtime)
        assert result is not None
        assert "LOOP DETECTED" in result["messages"][0].content
        assert "write_file" in result["messages"][0].content


class TestHardStopOrphanToolMessageRemoval:
    """Hard stop must clean orphan ToolMessages whose tool_call_id matches
    the AIMessage being stripped. Otherwise strict providers (MiniMax/Anthropic)
    reject the next call with 400 "tool result's tool id ... not found".

    Spec: docs/superpowers/specs/2026-04-27-loop-detection-orphan-tool-msg.md
    """

    def _state_with_tool_msg(self, tool_calls, tool_call_ids_for_results):
        """Build state where AIMessage has tool_calls AND matching ToolMessages
        already exist in history (simulates: tools already executed, history
        has the responses, then loop detection fires hard_stop)."""
        ai_msg = AIMessage(content="thinking...", tool_calls=tool_calls)
        tool_msgs = [
            ToolMessage(content=f"result for {tcid}", tool_call_id=tcid)
            for tcid in tool_call_ids_for_results
        ]
        # Order in real history: AI msg → its ToolMessages.
        # But the LATEST AIMessage (the one with the loop) is at the end.
        # For loop detection to trigger on it, it must be messages[-1].
        # So we layer: prior AIMessage with tool_calls → prior ToolMessages → latest looping AIMessage.
        prior_ai = AIMessage(
            content="prior turn",
            tool_calls=[{"name": tc["name"], "id": tcid, "args": tc["args"]}
                        for tc, tcid in zip(tool_calls, tool_call_ids_for_results)],
        )
        return {"messages": [prior_ai, *tool_msgs, ai_msg]}

    def test_hard_stop_emits_remove_message_for_orphan_tool_msg(self):
        """When hard_stop strips tool_calls from last AIMessage, any ToolMessage
        in history whose tool_call_id matches must be removed via RemoveMessage."""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()

        looping_call_id = "call_loop_1"
        tool_calls = [{"name": "bash", "id": looping_call_id, "args": {"command": "ls"}}]

        # Trip the loop detector with 3 prior identical calls
        for _ in range(3):
            mw._apply(_make_state(tool_calls=tool_calls), runtime)

        # 4th call: hard_stop fires. Build state where the looping AIMessage's
        # tool_call already produced a ToolMessage in history.
        state = self._state_with_tool_msg(tool_calls, [looping_call_id])
        result = mw._apply(state, runtime)

        assert result is not None
        msgs = result["messages"]
        # Expect: at least one RemoveMessage + the stripped AIMessage
        remove_msgs = [m for m in msgs if isinstance(m, RemoveMessage)]
        ai_msgs = [m for m in msgs if isinstance(m, AIMessage)]

        assert len(remove_msgs) == 1, f"expected 1 RemoveMessage, got {remove_msgs}"
        assert len(ai_msgs) == 1, f"expected 1 stripped AIMessage, got {ai_msgs}"

        # The RemoveMessage targets the orphan ToolMessage by its message id.
        # ToolMessage in fixture had no explicit id, so langchain auto-assigns one.
        # Look up the orphan in fixture state and verify the RemoveMessage points to it.
        orphan_tool_msg = next(
            m for m in state["messages"]
            if isinstance(m, ToolMessage) and m.tool_call_id == looping_call_id
        )
        assert remove_msgs[0].id == orphan_tool_msg.id

        # The stripped AIMessage must have tool_calls cleared (existing contract)
        assert ai_msgs[0].tool_calls == []
        assert _HARD_STOP_MSG in ai_msgs[0].content

    def test_hard_stop_no_remove_when_no_orphan_exists(self):
        """If the looping AIMessage's tool_calls have not been executed yet
        (no matching ToolMessage in history), no RemoveMessage is emitted.
        This covers the case where loop detection fires in after_model
        before the tool node runs."""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()

        tool_calls = [{"name": "bash", "id": "call_no_result", "args": {"command": "ls"}}]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=tool_calls), runtime)

        # 4th call: hard_stop fires, but ToolMessage hasn't been added to history
        result = mw._apply(_make_state(tool_calls=tool_calls), runtime)

        assert result is not None
        msgs = result["messages"]
        remove_msgs = [m for m in msgs if isinstance(m, RemoveMessage)]
        ai_msgs = [m for m in msgs if isinstance(m, AIMessage)]

        assert len(remove_msgs) == 0, f"no orphan exists → no RemoveMessage; got {remove_msgs}"
        assert len(ai_msgs) == 1
        assert ai_msgs[0].tool_calls == []

    def test_hard_stop_removes_only_matching_orphans_not_unrelated_tool_msgs(self):
        """Narrow scope: RemoveMessage targets ONLY ToolMessages whose tool_call_id
        is in the looping AIMessage's tool_calls. Unrelated ToolMessages from
        prior valid turns must remain untouched."""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()

        looping_id = "call_loop"
        unrelated_id = "call_unrelated_earlier_turn"

        tool_calls = [{"name": "bash", "id": looping_id, "args": {"command": "ls"}}]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=tool_calls), runtime)

        # Build history with:
        #   - unrelated valid AI+Tool pair from earlier (must NOT be removed)
        #   - looping AI msg with its already-produced ToolMessage (orphan to clean)
        unrelated_ai = AIMessage(
            content="earlier valid turn",
            tool_calls=[{"name": "bash", "id": unrelated_id, "args": {"command": "pwd"}}],
        )
        unrelated_tool = ToolMessage(content="/home", tool_call_id=unrelated_id, id="msg_unrelated_tool")
        looping_orphan_tool = ToolMessage(content="result", tool_call_id=looping_id, id="msg_looping_orphan")
        looping_ai = AIMessage(content="loop", tool_calls=tool_calls)

        state = {
            "messages": [unrelated_ai, unrelated_tool, looping_orphan_tool, looping_ai]
        }
        result = mw._apply(state, runtime)

        assert result is not None
        remove_msgs = [m for m in result["messages"] if isinstance(m, RemoveMessage)]
        # Only the looping orphan ToolMessage gets removed
        assert len(remove_msgs) == 1
        assert remove_msgs[0].id == looping_orphan_tool.id
        # The unrelated ToolMessage's id must NOT be in any RemoveMessage
        removed_ids = {m.id for m in remove_msgs}
        assert unrelated_tool.id not in removed_ids

    def test_hard_stop_handles_multiple_tool_calls_in_one_message(self):
        """Hard-stop AIMessage may carry several tool_calls; each with a matching
        ToolMessage in history must produce its own RemoveMessage."""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()

        ids = ["call_a", "call_b"]
        tool_calls = [
            {"name": "bash", "id": "call_a", "args": {"command": "ls"}},
            {"name": "bash", "id": "call_b", "args": {"command": "pwd"}},
        ]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=tool_calls), runtime)

        looping_ai = AIMessage(content="loop", tool_calls=tool_calls)
        orphans = [ToolMessage(content=f"r_{tcid}", tool_call_id=tcid) for tcid in ids]
        state = {"messages": [*orphans, looping_ai]}

        result = mw._apply(state, runtime)
        assert result is not None
        remove_msgs = [m for m in result["messages"] if isinstance(m, RemoveMessage)]
        assert len(remove_msgs) == 2
        removed_ids = {m.id for m in remove_msgs}
        assert removed_ids == {orphans[0].id, orphans[1].id}
