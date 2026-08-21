import zipfile

from core.diagnostics.support_bundle import generate_support_bundle


def test_generate_support_bundle_creates_a_zip_with_expected_entries(tmp_path):
    config = {
        "audit": {"log_path": str(tmp_path / "audit.jsonl")},
        "paths": {"packs_installed": str(tmp_path / "packs" / "installed")},
    }
    out_path = tmp_path / "bundle.zip"
    result = generate_support_bundle(config, out_path)
    assert result == out_path
    assert out_path.exists()
    with zipfile.ZipFile(out_path) as z:
        names = z.namelist()
    assert "doctor_output.txt" in names
    assert "resolved_config.yaml" in names


def test_generate_support_bundle_redacts_secrets_from_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMPTWISE_TESTSECRET__VALUE", "sk-ant-api03-shouldnotappear1234567890")
    config = {"audit": {"log_path": str(tmp_path / "audit.jsonl")}}
    out_path = tmp_path / "bundle.zip"
    generate_support_bundle(config, out_path)
    with zipfile.ZipFile(out_path) as z:
        content = z.read("resolved_config.yaml").decode("utf-8")
    assert "sk-ant-api03-shouldnotappear1234567890" not in content
