"""Security exceptions to uv's release-age cooldown, written and pruned by machine.

pyproject.toml sets `[tool.uv] exclude-newer = "7 days"`, so no resolution may
pick a file uploaded in the last seven days. A security fix should not wait that
long, so a fixed version younger than the cooldown gets an entry in
`[tool.uv.exclude-newer-package]`:

    ruff = "2026-10-09T19:47:30Z"

The value is the upload time of the fixed version's last file, rounded up to the
next whole second. It lets that version through and nothing published after it.
uv has no exact-version exception, and `false` would open the package to every
future release for as long as the entry stays.

Workaround: Renovate writes the pnpm equivalent (`minimumReleaseAgeExclude`)
into its own security pull requests, but not this one for uv. Delete this tool,
its workflows and the table once Renovate's uv manager writes these entries
itself. Tracked in https://github.com/martinfrancois/guideprint/issues/40;
`tests/test_uv_cooldown.py::test_renovate_still_lacks_uv_security_exceptions`
fails when that happens.

An entry must not outlive the cooldown. A package-specific cutoff beats the
global one, so an old entry freezes its package at the fixed version: a pinned
dependency then fails its next Renovate update, and a transitive one silently
stops moving. `prune` removes every entry whose cutoff is at least one cooldown
old. Removal is then a no-op for resolution: the locked version was uploaded
before the cutoff, so the global cooldown admits it too. Nothing in this
repository runs `prune` on a schedule, because a check that fails with the
passage of time would block the next security pull request. The scheduled
prune in https://github.com/martinfrancois/dependency-watchdog applies the same
rule, re-locks, and opens a pull request.

    python tools/uv_cooldown.py changed-pins BASE_PYPROJECT   pins this branch moved
    python tools/uv_cooldown.py exempt NAME==VERSION [...]    add entries, then run uv lock
    python tools/uv_cooldown.py prune [--now ISO8601]         remove matured entries
    python tools/uv_cooldown.py same-versions OLD_LOCK NEW_LOCK

Standard library only, so it runs before `uv sync` and without the project.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

TABLE = "[tool.uv.exclude-newer-package]"
_ENTRY = re.compile(r'^\s*"?(?P<name>[A-Za-z0-9._-]+)"?\s*=\s*"(?P<cutoff>[^"]+)"\s*$')
_PIN = re.compile(r"^\s*(?P<name>[A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*==\s*(?P<version>[^\s;,]+)")
_DURATION = re.compile(r"^\s*(?P<n>\d+)\s*(?P<unit>hours?|days?|weeks?)\s*$")
_ISO_DURATION = re.compile(r"^P(?:(?P<d>\d+)D)?(?:T(?P<h>\d+)H)?$")


def normalize(name: str) -> str:
    """PEP 503 name normalisation, which is how uv compares package names."""
    return re.sub(r"[-_.]+", "-", name).lower()


def cooldown(pyproject: Mapping[str, object]) -> timedelta:
    """The relative `exclude-newer` from `[tool.uv]`; an absolute date has no cooldown."""
    tool = pyproject.get("tool")
    uv = tool.get("uv") if isinstance(tool, dict) else None
    value = uv.get("exclude-newer") if isinstance(uv, dict) else None
    if not isinstance(value, str):
        raise ValueError("[tool.uv] exclude-newer is not set to a duration")
    friendly = _DURATION.match(value)
    if friendly:
        n, unit = int(friendly["n"]), friendly["unit"].rstrip("s")
        return {"hour": timedelta(hours=n), "day": timedelta(days=n), "week": timedelta(weeks=n)}[
            unit
        ]
    iso = _ISO_DURATION.match(value)
    if iso and (iso["d"] or iso["h"]):
        return timedelta(days=int(iso["d"] or 0), hours=int(iso["h"] or 0))
    raise ValueError(f"exclude-newer = {value!r} is not a duration this tool understands")


def entries(pyproject: Mapping[str, object]) -> dict[str, str]:
    """`[tool.uv.exclude-newer-package]` as parsed by tomllib, keys normalised."""
    tool = pyproject.get("tool")
    uv = tool.get("uv") if isinstance(tool, dict) else None
    table = uv.get("exclude-newer-package") if isinstance(uv, dict) else None
    if not isinstance(table, dict):
        raise ValueError(f"{TABLE} is missing; it must exist, even when empty")
    return {normalize(k): str(v) for k, v in table.items()}


def _table_bounds(lines: list[str]) -> tuple[int, int]:
    """Index of the table header and of the first line after the table."""
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == TABLE)
    except StopIteration:
        raise ValueError(f"{TABLE} is missing; it must exist, even when empty") from None
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")),
        len(lines),
    )
    return start, end


def add_entries(text: str, new: dict[str, tuple[str, str]]) -> str:
    """Add or replace entries. `new` maps a normalised name to (cutoff, comment)."""
    lines = text.splitlines(keepends=True)
    doomed = set(new)
    text = remove_entries(text, doomed & set(_entry_lines(lines)))
    lines = text.splitlines(keepends=True)
    _, end = _table_bounds(lines)
    # Insert after the last non-blank line of the table so a blank line still separates tables.
    at = end
    while at > 0 and not lines[at - 1].strip():
        at -= 1
    block = [
        f'\n# {comment}\n{name} = "{cutoff}"\n' for name, (cutoff, comment) in sorted(new.items())
    ]
    return "".join(lines[:at] + block + lines[at:])


def _entry_lines(lines: list[str]) -> dict[str, int]:
    start, end = _table_bounds(lines)
    found: dict[str, int] = {}
    for i in range(start + 1, end):
        match = _ENTRY.match(lines[i])
        if match:
            found[normalize(match["name"])] = i
    return found


def remove_entries(text: str, doomed: Iterable[str]) -> str:
    """Remove entries with the comment lines directly above each and the blank line above those.

    add_entries writes every entry as its own paragraph (blank line, comment, entry), so this is
    its exact inverse, and the table's header comment, a separate paragraph, is never touched.
    """
    lines = text.splitlines(keepends=True)
    at = _entry_lines(lines)
    drop: set[int] = set()
    start, _ = _table_bounds(lines)
    for name in doomed:
        i = at[name]
        drop.add(i)
        j = i - 1
        while j > start and lines[j].lstrip().startswith("#"):
            drop.add(j)
            j -= 1
        if j > start and not lines[j].strip():
            drop.add(j)
    return "".join(line for i, line in enumerate(lines) if i not in drop)


def assert_entries(text: str, expected: dict[str, str]) -> None:
    """Re-parse the edited file and require exactly the intended entries."""
    actual = entries(tomllib.loads(text))
    if actual != expected:
        raise SystemExit(
            f"refusing to write: expected entries {expected}, the edit parses as {actual}"
        )


def matured(current: dict[str, str], period: timedelta, now: datetime) -> list[str]:
    """Entries whose cutoff is at least one cooldown old; `false` and other forms are left alone."""
    out = []
    for name, cutoff in current.items():
        try:
            when = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is not None and now - when >= period:
            out.append(name)
    return sorted(out)


def cutoff_for(upload_times: list[datetime]) -> datetime:
    """One second past the last upload, floored to whole seconds.

    Measured with uv 0.13.0 on ruff 0.17.0, last file at 19:47:29.248971Z: a
    cutoff of exactly that time, or one microsecond later, still dropped that
    file from uv.lock (17 of 18 files); 19:47:30Z kept all 18.
    """
    last = max(upload_times)
    return last.replace(microsecond=0) + timedelta(seconds=1)


def pypi_upload_times(name: str, version: str) -> list[datetime]:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urllib.request.urlopen(url, timeout=30) as response:
        files = json.load(response)["urls"]
    if not files:
        raise SystemExit(f"{name} {version} has no files on PyPI")
    return [datetime.fromisoformat(f["upload_time_iso_8601"].replace("Z", "+00:00")) for f in files]


def pins(pyproject: Mapping[str, object]) -> dict[str, str]:
    """Every `name==version` requirement in dependencies, optional ones and dependency groups."""
    project = pyproject.get("project")
    found: list[object] = []
    if isinstance(project, dict):
        found += project.get("dependencies", [])
        for group in project.get("optional-dependencies", {}).values():
            found += group
    groups = pyproject.get("dependency-groups")
    if isinstance(groups, dict):
        for group in groups.values():
            found += group
    out = {}
    for requirement in found:
        match = _PIN.match(requirement) if isinstance(requirement, str) else None
        if match:
            out[normalize(match["name"])] = match["version"]
    return out


def changed_pins(base: Mapping[str, object], head: Mapping[str, object]) -> dict[str, str]:
    old = pins(base)
    return {n: v for n, v in pins(head).items() if old.get(n) != v}


def locked_versions(lock: Mapping[str, object]) -> set[tuple[str, str]]:
    packages = lock.get("package", [])
    assert isinstance(packages, list)
    return {(p["name"], p.get("version", "")) for p in packages}


def exempt(
    path: Path,
    requested: list[str],
    now: datetime,
    upload_times: Callable[[str, str], list[datetime]],
    reason: str,
) -> list[str]:
    text = path.read_text()
    data = tomllib.loads(text)
    period = cooldown(data)
    before = entries(data)
    new: dict[str, tuple[str, str]] = {}
    for item in requested:
        name, _, version = item.partition("==")
        times = upload_times(name, version)
        cutoff = cutoff_for(times)
        if now - cutoff >= period:
            continue  # old enough already; an entry would only hold the package back later
        stamp = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        prune_after = (cutoff + period).strftime("%Y-%m-%dT%H:%M:%SZ")
        new[normalize(name)] = (stamp, f"{name} {version}: {reason}. Prune after {prune_after}.")
    if not new:
        return []
    edited = add_entries(text, new)
    assert_entries(edited, {**before, **{n: c for n, (c, _) in new.items()}})
    path.write_text(edited)
    return sorted(new)


def prune(path: Path, now: datetime) -> list[str]:
    text = path.read_text()
    data = tomllib.loads(text)
    before = entries(data)
    doomed = matured(before, cooldown(data), now)
    if not doomed:
        return []
    edited = remove_entries(text, doomed)
    assert_entries(edited, {n: c for n, c in before.items() if n not in doomed})
    path.write_text(edited)
    return doomed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--now", type=datetime.fromisoformat, default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    changed = sub.add_parser("changed-pins")
    changed.add_argument("base", type=Path)
    add = sub.add_parser("exempt")
    add.add_argument("requirements", nargs="+")
    add.add_argument("--reason", default="security fix")
    sub.add_parser("prune")
    same = sub.add_parser("same-versions")
    same.add_argument("old", type=Path)
    same.add_argument("new", type=Path)
    args = parser.parse_args(argv)
    now = args.now or datetime.now(UTC)

    if args.command == "changed-pins":
        base = tomllib.loads(args.base.read_text())
        head = tomllib.loads(args.pyproject.read_text())
        for name, version in sorted(changed_pins(base, head).items()):
            print(f"{name}=={version}")
    elif args.command == "exempt":
        for name in exempt(args.pyproject, args.requirements, now, pypi_upload_times, args.reason):
            print(name)
    elif args.command == "prune":
        for name in prune(args.pyproject, now):
            print(name)
    elif args.command == "same-versions":
        old = locked_versions(tomllib.loads(args.old.read_text()))
        new = locked_versions(tomllib.loads(args.new.read_text()))
        if old != new:
            print(
                f"versions changed: removed {sorted(old - new)}, added {sorted(new - old)}",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
