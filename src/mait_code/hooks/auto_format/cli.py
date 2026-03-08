"""Auto-format hook — formats code after edits."""

from mait_code.logging import log_invocation, setup_logging


@log_invocation(name="mc-hook-format")
def main():
    """Run auto-formatting on changed files."""
    setup_logging()
    # Placeholder: will run project-specific formatters
