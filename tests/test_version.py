"""Ensure __version__ in __init__.py matches pyproject.toml."""

from pathlib import Path

import mait_code


def test_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    for line in pyproject.read_text().splitlines():
        if line.startswith("version"):
            pyproject_version = line.split('"')[1]
            break
    else:
        raise AssertionError("version not found in pyproject.toml")

    assert mait_code.__version__ == pyproject_version, (
        f"__init__.py has {mait_code.__version__!r} "
        f"but pyproject.toml has {pyproject_version!r}"
    )
