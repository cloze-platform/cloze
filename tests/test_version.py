"""The version string and the changelog agree."""

import re
from pathlib import Path

import llm_chat


def test_version_matches_the_latest_changelog_release():
    changelog = (Path(__file__).parent.parent / "CHANGELOG.md").read_text()
    releases = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.M)
    assert releases and releases[0] == llm_chat.__version__


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", llm_chat.__version__)
