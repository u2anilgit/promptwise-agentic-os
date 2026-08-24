import pytest
from pydantic import ValidationError
from core.packs.models import PackManifest


def _valid_kwargs(**overrides):
    base = dict(
        name="repo-intelligence",
        version="1.0.0",
        kind="intelligence",
        summary="Reverse-engineers an existing repo into docs",
        requires_core=">=0.4.0,<0.5.0",
        capabilities=["fs:read", "fs:write:docs/reverse-engineered/**"],
        permissions_rationale="Needs fs:write only to write generated docs under docs/reverse-engineered/.",
        dependencies=[],
    )
    base.update(overrides)
    return base


def test_valid_manifest_parses():
    manifest = PackManifest(**_valid_kwargs())
    assert manifest.kind == "intelligence"
    assert manifest.capabilities == ["fs:read", "fs:write:docs/reverse-engineered/**"]


def test_all_kind_values_accepted():
    for kind in ("stack", "database", "cloud-devops", "architecture", "migration", "lifecycle", "intelligence"):
        manifest = PackManifest(**_valid_kwargs(kind=kind))
        assert manifest.kind == kind


def test_unknown_kind_rejected():
    with pytest.raises(ValidationError):
        PackManifest(**_valid_kwargs(kind="not-a-real-kind"))


def test_name_must_be_safe_slug():
    with pytest.raises(ValidationError):
        PackManifest(**_valid_kwargs(name="../../etc/passwd"))


def test_name_rejects_uppercase_and_spaces():
    with pytest.raises(ValidationError):
        PackManifest(**_valid_kwargs(name="Repo Intelligence"))


def test_name_allows_hyphens_and_digits():
    manifest = PackManifest(**_valid_kwargs(name="stack-python3-fastapi"))
    assert manifest.name == "stack-python3-fastapi"


def test_permissions_rationale_must_not_be_blank():
    with pytest.raises(ValidationError):
        PackManifest(**_valid_kwargs(permissions_rationale="   "))


def test_capabilities_and_dependencies_default_empty():
    kwargs = _valid_kwargs()
    del kwargs["capabilities"]
    del kwargs["dependencies"]
    manifest = PackManifest(**kwargs)
    assert manifest.capabilities == []
    assert manifest.dependencies == []
