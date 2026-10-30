"""Guard the stream parsing in ``scripts/probe_permissions.py``.

The probe only runs against a live Claude Code, so nothing else exercises its
parser. These tests feed it recorded stream-json shapes instead, so a change in
the event format fails here rather than as a crash halfway through a probe.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "probe_permissions.py"


@pytest.fixture(scope="module")
def probe() -> Iterator[ModuleType]:
    spec = importlib.util.spec_from_file_location("probe_permissions", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # @dataclass resolves its own module through sys.modules while executing.
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    yield module
    monkeypatch.undo()


#: A denied probe as Claude Code streams it, trimmed to the events that matter.
#: ``permission_denied`` carries its message as a string, not an object.
DENIED_STREAM = [
    {"type": "system", "subtype": "init"},
    {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "Bash",
                    "input": {"command": "git push --dry-run"},
                }
            ]
        },
    },
    {
        "type": "system",
        "subtype": "permission_denied",
        "message": "This command requires approval",
    },
    {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": "This command requires approval",
                }
            ]
        },
    },
    {"type": "result", "subtype": "success"},
]


def test_blocks_skip_events_without_a_message_object(probe: ModuleType) -> None:
    stdout = "\n".join(json.dumps(event) for event in DENIED_STREAM)

    blocks = list(probe._blocks(probe._events(stdout)))

    assert [block["type"] for block in blocks] == ["tool_use", "tool_result"]


def test_events_ignore_non_json_lines(probe: ModuleType) -> None:
    stdout = 'Shell cwd was reset\n{"type": "result"}\n{not json'

    assert probe._events(stdout) == [{"type": "result"}]
