import core

def test_core_package_has_version():
    assert hasattr(core, "__version__")
    assert core.__version__ == "0.1.0"
