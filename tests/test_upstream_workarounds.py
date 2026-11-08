"""Expiry checks for workarounds that wait on an upstream release. Each test
fails once its workaround can go; its docstring says what to remove."""

import json
import urllib.request
from datetime import UTC, datetime, timedelta

# uv's exclude-newer in pyproject.toml and Renovate's minimumReleaseAge both
# keep a release out for this long, so a wheel younger than that cannot be
# locked yet and the hold still has to stay.
COOLDOWN = timedelta(days=7)


def minor_of_cpython_3(tag: str) -> int:
    """12 for cp312, 9 for cp39; a large number for any other tag."""
    minor = tag.removeprefix("cp3")
    return int(minor) if tag.startswith("cp3") and minor.isdigit() else 999


def installs_on_cpython_315_linux(filename: str) -> bool:
    """Whether a wheel installs on the regular CPython 3.15 build on x86_64
    Linux, the platform CI runs uv on."""
    if not filename.endswith(".whl"):
        return False
    python, abi, platform = filename.removesuffix(".whl").split("-")[-3:]
    pythons, abis, platforms = python.split("."), abi.split("."), platform.split(".")
    linux = any(p == "any" or ("linux" in p and p.endswith("_x86_64")) for p in platforms)
    stable_abi = "abi3" in abis and any(minor_of_cpython_3(p) <= 15 for p in pythons)
    cpython = ("cp315" in pythons and "cp315" in abis) or stable_abi
    pure = "none" in abis and any(p in ("py3", "py315") for p in pythons)
    return linux and (cpython or pure)


def lockable_cp315_wheels(files: list[dict[str, str]], now: datetime) -> list[str]:
    return [
        file["filename"]
        for file in files
        if installs_on_cpython_315_linux(file["filename"])
        and now - datetime.fromisoformat(file["upload_time_iso_8601"]) > COOLDOWN
    ]


def test_expiry_signal_fires_on_a_matured_cp315_wheel() -> None:
    now = datetime(2026, 11, 8, tzinfo=UTC)
    old, new = "2026-10-01T00:00:00Z", "2026-11-05T00:00:00Z"

    def wheel(tags: str, uploaded: str) -> dict[str, str]:
        return {"filename": f"onnxruntime-9.9.9-{tags}.whl", "upload_time_iso_8601": uploaded}

    assert lockable_cp315_wheels([wheel("cp315-cp315-manylinux_2_27_x86_64", old)], now)
    assert lockable_cp315_wheels([wheel("cp312-abi3-manylinux_2_28_x86_64", old)], now)
    assert not lockable_cp315_wheels([wheel("cp315-cp315-manylinux_2_27_x86_64", new)], now)
    assert not lockable_cp315_wheels([wheel("cp315-cp315t-manylinux_2_27_x86_64", old)], now)
    assert not lockable_cp315_wheels([wheel("cp315-cp315-macosx_14_0_arm64", old)], now)
    assert not lockable_cp315_wheels([wheel("cp314-cp314-manylinux_2_27_x86_64", old)], now)
    assert not lockable_cp315_wheels([wheel("cp316-abi3-manylinux_2_28_x86_64", old)], now)


def test_onnxruntime_still_lacks_cp315_wheels() -> None:
    """Workaround expiry for the Python 3.15 hold in renovate.json.

    Tracked in https://github.com/martinfrancois/guideprint/issues/124.

    When this fails, the newest onnxruntime release has had a CPython 3.15
    wheel for Linux x86_64 for longer than the cooldown, so uv can lock it.
    Follow the removal steps in the issue.
    """
    with urllib.request.urlopen("https://pypi.org/pypi/onnxruntime/json", timeout=60) as response:
        release = json.load(response)
    version = release["info"]["version"]
    assert release["urls"], f"PyPI lists no files for onnxruntime {version}"
    matured = lockable_cp315_wheels(release["urls"], datetime.now(UTC))
    assert not matured, (
        f"onnxruntime {version} ships a CPython 3.15 wheel older than the cooldown: {matured}. "
        "Remove the Python 3.15 hold, see this test's docstring."
    )
