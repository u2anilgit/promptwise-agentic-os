# core/tests/policy/test_jit.py
from core.policy.jit import check_jit_grant, grant_jit_permission


def _config(tmp_path):
    return {"policy": {"jit_grants_path": str(tmp_path / "jit_grants.json")}}


def test_grant_jit_permission_returns_a_grant_with_expiry(tmp_path):
    config = _config(tmp_path)
    grant = grant_jit_permission(config, scope="shell.exec.git", ttl_seconds=60)
    assert grant.scope == "shell.exec.git"
    assert grant.expires_at > grant.granted_at


def test_check_jit_grant_true_for_an_unexpired_grant(tmp_path):
    config = _config(tmp_path)
    grant_jit_permission(config, scope="shell.exec.git", ttl_seconds=60)
    assert check_jit_grant(config, "shell.exec.git") is True


def test_check_jit_grant_false_for_an_unknown_scope(tmp_path):
    config = _config(tmp_path)
    assert check_jit_grant(config, "shell.exec.rm") is False


def test_check_jit_grant_false_after_ttl_expires(tmp_path, monkeypatch):
    import core.policy.jit as jit_module

    config = _config(tmp_path)
    grant_jit_permission(config, scope="shell.exec.git", ttl_seconds=1)

    real_now = jit_module._now

    def _future_now():
        from datetime import timedelta

        return real_now() + timedelta(seconds=10)

    monkeypatch.setattr(jit_module, "_now", _future_now)
    assert check_jit_grant(config, "shell.exec.git") is False


def test_multiple_grants_for_different_scopes_are_independent(tmp_path):
    config = _config(tmp_path)
    grant_jit_permission(config, scope="shell.exec.git", ttl_seconds=60)
    grant_jit_permission(config, scope="fs.write.tmp", ttl_seconds=60)
    assert check_jit_grant(config, "shell.exec.git") is True
    assert check_jit_grant(config, "fs.write.tmp") is True
    assert check_jit_grant(config, "shell.exec.rm") is False
