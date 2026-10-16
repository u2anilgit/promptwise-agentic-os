"""Guards on the committed lockfiles (requirements.lock / requirements-dev.lock)."""
import re
import tomllib
from pathlib import Path

import pytest
from packaging.utils import canonicalize_name

from core.security.supply_chain import find_known_bad, load_known_bad, parse_lockfile

ROOT = Path(__file__).resolve().parents[3]
LOCKS = ["requirements.lock", "requirements-dev.lock"]


def _config():
    return {"security": {"known_bad_packages_path": str(ROOT / "security" / "known_bad_packages.yaml")}}


@pytest.mark.parametrize("lock", LOCKS)
def test_every_locked_package_is_hash_pinned(lock):
    entries = parse_lockfile(ROOT / lock)
    assert len(entries) > 20
    assert [e.name for e in entries if not e.hashes] == []


@pytest.mark.parametrize("lock", LOCKS)
def test_no_locked_package_is_on_the_known_bad_list(lock):
    entries = parse_lockfile(ROOT / lock)
    installed = {e.name: e.version for e in entries}
    assert find_known_bad(installed, load_known_bad(_config())) == []


def test_every_direct_runtime_dependency_is_in_the_runtime_lock():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    locked = {e.name for e in parse_lockfile(ROOT / "requirements.lock")}
    wanted = {str(canonicalize_name(re.split(r"[\[<>=!~ ;]", d, maxsplit=1)[0])) for d in project["dependencies"]}
    assert wanted - locked == set()


def test_dev_lock_is_a_superset_of_the_runtime_lock_with_identical_pins():
    # An environment built from the dev lock must also satisfy the runtime lock (doctor's deps.integrity
    # compares against requirements.lock). Compile the dev lock with `-c requirements.lock`.
    runtime = {e.name: e.version for e in parse_lockfile(ROOT / "requirements.lock")}
    dev = {e.name: e.version for e in parse_lockfile(ROOT / "requirements-dev.lock")}
    assert set(runtime) - set(dev) == set()
    assert {n: (runtime[n], dev[n]) for n in runtime if runtime[n] != dev[n]} == {}


def test_litellm_is_not_a_dependency_until_a_deliberate_decision_adds_it():
    # docs/ARCHITECTURE.md "LiteLLM posture": it was compromised on PyPI (1.82.7/1.82.8, 2026-03-24).
    # Adding it requires an exact pin + hash, a sandboxed sidecar, and removing this guard on purpose.
    for lock in LOCKS:
        assert "litellm" not in {e.name for e in parse_lockfile(ROOT / lock)}
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert not any("litellm" in d.lower() for d in project["dependencies"])
