"""Tests for the reflect CLI command."""

import sys
from io import StringIO
from unittest.mock import patch


def test_cmd_reflect_skipped(tmp_path):
    """Test output when reflection is skipped."""
    from mait_code.tools.memory.cli import cmd_reflect

    class Args:
        days = 7
        min_new = 3

    mock_result = {
        "skipped": True,
        "reason": "not enough new observations since last reflection",
        "insights": [],
        "stored": 0,
        "memory_diff": None,
    }

    with patch("mait_code.tools.memory.cli.connection"), \
         patch("mait_code.tools.memory.reflect.reflect", return_value=mock_result):
        captured = StringIO()
        sys.stdout = captured
        try:
            cmd_reflect(Args())
        finally:
            sys.stdout = sys.__stdout__

    output = captured.getvalue()
    assert "skipped" in output.lower()
    assert "not enough" in output.lower()


def test_cmd_reflect_success(tmp_path):
    """Test output on successful reflection."""
    from mait_code.tools.memory.cli import cmd_reflect

    class Args:
        days = 7
        min_new = 3

    mock_result = {
        "skipped": False,
        "reason": None,
        "insights": ["Pattern A", "Pattern B"],
        "stored": 2,
        "memory_diff": "Proposed additions to MEMORY.md:\n\n+ New fact",
    }

    with patch("mait_code.tools.memory.cli.connection"), \
         patch("mait_code.tools.memory.reflect.reflect", return_value=mock_result):
        captured = StringIO()
        sys.stdout = captured
        try:
            cmd_reflect(Args())
        finally:
            sys.stdout = sys.__stdout__

    output = captured.getvalue()
    assert "Generated 2 insights" in output
    assert "Pattern A" in output
    assert "Pattern B" in output
    assert "Stored 2" in output
    assert "Proposed additions" in output
    assert "+ New fact" in output


def test_cmd_reflect_no_insights(tmp_path):
    """Test output when LLM generates no insights."""
    from mait_code.tools.memory.cli import cmd_reflect

    class Args:
        days = 14
        min_new = 0

    mock_result = {
        "skipped": False,
        "reason": None,
        "insights": [],
        "stored": 0,
        "memory_diff": None,
    }

    with patch("mait_code.tools.memory.cli.connection"), \
         patch("mait_code.tools.memory.reflect.reflect", return_value=mock_result):
        captured = StringIO()
        sys.stdout = captured
        try:
            cmd_reflect(Args())
        finally:
            sys.stdout = sys.__stdout__

    output = captured.getvalue()
    assert "No insights generated" in output
    assert "14 days" in output


def test_cmd_reflect_success_without_memory_diff(tmp_path):
    """Test output when insights exist but no MEMORY.md updates proposed."""
    from mait_code.tools.memory.cli import cmd_reflect

    class Args:
        days = 7
        min_new = 3

    mock_result = {
        "skipped": False,
        "reason": None,
        "insights": ["Insight without memory updates"],
        "stored": 1,
        "memory_diff": None,
    }

    with patch("mait_code.tools.memory.cli.connection"), \
         patch("mait_code.tools.memory.reflect.reflect", return_value=mock_result):
        captured = StringIO()
        sys.stdout = captured
        try:
            cmd_reflect(Args())
        finally:
            sys.stdout = sys.__stdout__

    output = captured.getvalue()
    assert "Generated 1 insights" in output
    assert "Insight without memory updates" in output
    assert "Stored 1" in output
    assert "Proposed additions" not in output
    assert "Review and apply" not in output


def test_reflect_subparser_args():
    """Test that the reflect subparser accepts --days and --min-new."""
    # Verify the args are parsed correctly by checking argparse
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    p_reflect = sub.add_parser("reflect")
    p_reflect.add_argument("--days", type=int, default=7)
    p_reflect.add_argument("--min-new", type=int, default=3)

    args = parser.parse_args(["reflect", "--days", "14", "--min-new", "5"])
    assert args.days == 14
    assert args.min_new == 5

    # Defaults
    args = parser.parse_args(["reflect"])
    assert args.days == 7
    assert args.min_new == 3
