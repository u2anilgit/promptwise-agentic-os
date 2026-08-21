from pathlib import Path

from core.diagnostics.hardware import HardwareProfile, detect_hardware, write_hardware_profile


def test_detect_hardware_returns_positive_values():
    profile = detect_hardware()
    assert profile.total_ram_gb > 0
    assert profile.available_ram_gb > 0
    assert profile.cpu_count >= 1
    assert isinstance(profile.has_gpu, bool)


def test_write_hardware_profile_creates_yaml(tmp_path):
    profile = HardwareProfile(total_ram_gb=16.0, available_ram_gb=9.5, cpu_count=8, has_gpu=False)
    out_path = tmp_path / "hardware_profile.yaml"
    write_hardware_profile(profile, out_path)
    assert out_path.exists()
    content = out_path.read_text()
    assert "total_ram_gb: 16.0" in content
    assert "cpu_count: 8" in content
