"""tools/uv_cooldown.py edits pyproject.toml unattended, so every edit is checked
against a re-parse, and the guard itself is shown to fire on a damaged edit."""

import io
import re
import sys
import tarfile
import tomllib
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import uv_cooldown as uc

ROOT = Path(__file__).resolve().parent.parent

BASE = """\
[project]
name = "x"
dependencies = ["pillow==12.3.0"]

[dependency-groups]
dev = ["ruff==0.16.10", "pytest==9.1.1"]

[tool.uv]
exclude-newer = "7 days"

[tool.uv.exclude-newer-package]
# Header comment that must survive every edit.

[tool.ruff]
line-length = 100
"""

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def _parsed(text: str) -> dict[str, str]:
    return uc.entries(tomllib.loads(text))


def test_add_then_remove_round_trips() -> None:
    added = uc.add_entries(BASE, {"ruff": ("2026-10-09T19:47:30Z", "ruff 0.17.0: fix")})
    assert _parsed(added) == {"ruff": "2026-10-09T19:47:30Z"}
    assert tomllib.loads(added)["tool"]["ruff"]["line-length"] == 100
    assert uc.remove_entries(added, ["ruff"]) == BASE


def test_replacing_an_entry_keeps_one_line_and_one_comment() -> None:
    once = uc.add_entries(BASE, {"ruff": ("2026-10-09T19:47:30Z", "first")})
    twice = uc.add_entries(once, {"ruff": ("2026-10-10T00:00:00Z", "second")})
    assert _parsed(twice) == {"ruff": "2026-10-10T00:00:00Z"}
    assert "first" not in twice
    assert "Header comment" in twice


def test_matured_uses_the_cooldown_and_skips_other_forms() -> None:
    current = {
        "old": (NOW - timedelta(days=7)).isoformat(),
        "young": (NOW - timedelta(days=6, hours=23)).isoformat(),
        "off": "false",
        "relative": "30 days",
    }
    assert uc.matured(current, timedelta(days=7), NOW) == ["old"]


def test_cutoff_is_one_second_past_the_last_upload() -> None:
    last = datetime(2026, 10, 9, 19, 47, 29, 248971, tzinfo=UTC)
    first = datetime(2026, 10, 9, 19, 46, 38, tzinfo=UTC)
    assert uc.cutoff_for([last, first]) == datetime(2026, 10, 9, 19, 47, 30, tzinfo=UTC)


def test_cooldown_formats() -> None:
    for value, expected in [("7 days", 7), ("1 week", 7), ("P7D", 7), ("168 hours", 7)]:
        data = {"tool": {"uv": {"exclude-newer": value}}}
        assert uc.cooldown(data) == timedelta(days=expected)
    with pytest.raises(ValueError):
        uc.cooldown({"tool": {"uv": {"exclude-newer": "2026-10-01T00:00:00Z"}}})


def test_changed_pins_reports_only_moved_pins() -> None:
    head = BASE.replace("ruff==0.16.10", "ruff==0.17.0")
    assert uc.changed_pins(tomllib.loads(BASE), tomllib.loads(head)) == {"ruff": "0.17.0"}


def test_exempt_and_prune_end_to_end(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_text(BASE)
    young = [datetime(2026, 10, 9, 19, 47, 29, tzinfo=UTC)]
    old = [datetime(2026, 9, 1, tzinfo=UTC)]
    times = {"ruff": young, "pytest": old}

    def lookup(name: str, version: str) -> list[datetime]:
        return times[name]

    assert uc.exempt(path, ["ruff==0.17.0", "pytest==9.1.1"], NOW, lookup, "fix") == ["ruff"]
    assert uc.prune(path, NOW) == []
    assert uc.prune(path, NOW + timedelta(days=5)) == ["ruff"]
    assert path.read_text() == BASE


def test_outcome_guard_refuses_a_damaged_edit(tmp_path: Path) -> None:
    """The negative control: a remover that drops the header orphans the entries."""
    added = uc.add_entries(
        BASE, {"a": ("2026-10-01T00:00:00Z", "a"), "b": ("2026-10-02T00:00:00Z", "b")}
    )
    damaged = added.replace(uc.TABLE + "\n", "")
    with pytest.raises((SystemExit, tomllib.TOMLDecodeError, ValueError)):
        uc.assert_entries(damaged, {"b": "2026-10-02T00:00:00Z"})
    wrong = uc.remove_entries(added, ["a", "b"])
    with pytest.raises(SystemExit):
        uc.assert_entries(wrong, {"b": "2026-10-02T00:00:00Z"})


def renovate_writes_uv_exceptions(tarball: bytes) -> bool:
    """True once Renovate's compiled pep621 manager handles vulnerability alerts.

    That is how Renovate wrote the pnpm equivalent (PR #40020): npm/artifacts.js
    reads `isVulnerabilityAlert` to add minimumReleaseAgeExclude entries.
    """
    with tarfile.open(fileobj=io.BytesIO(tarball)) as tar:
        for member in tar.getmembers():
            if re.fullmatch(r"package/dist/modules/manager/pep621/.*\.js", member.name):
                handle = tar.extractfile(member)
                if handle and b"isVulnerabilityAlert" in handle.read():
                    return True
    return False


def _tarball(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return out.getvalue()


def test_expiry_signal_fires_on_a_renovate_that_has_the_feature() -> None:
    uv_js = "package/dist/modules/manager/pep621/processors/uv.js"
    assert renovate_writes_uv_exceptions(_tarball({uv_js: b"if (u.isVulnerabilityAlert) {}"}))
    assert not renovate_writes_uv_exceptions(_tarball({uv_js: b"const cmd = 'uv lock';"}))


def test_renovate_still_lacks_uv_security_exceptions() -> None:
    """Workaround expiry for tools/uv_cooldown.py.

    Tracked in https://github.com/martinfrancois/guideprint/issues/40.

    When this fails, the Renovate version pinned in ci.yml writes uv cooldown
    exceptions into its own security pull requests. Confirm on a security PR,
    then delete tools/uv_cooldown.py, its workflows and this test.
    """
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    match = re.search(r"--package renovate@(\d+\.\d+\.\d+)", ci)
    assert match, "ci.yml no longer pins renovate; point this test at the new pin"
    version = match.group(1)
    url = f"https://registry.npmjs.org/renovate/-/renovate-{version}.tgz"
    with urllib.request.urlopen(url, timeout=60) as response:
        tarball = response.read()
    assert not renovate_writes_uv_exceptions(tarball), (
        f"Renovate {version} handles vulnerability alerts in its uv manager. "
        "Remove the uv cooldown workaround, see this test's docstring."
    )
