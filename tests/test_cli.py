# tests/test_cli.py
# Run: python3 -m pytest tests/test_cli.py -v

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from click.testing import CliRunner
from docksmith.main import cli
import docksmith.state as state_module
from docksmith.state import save_manifest
from docksmith.models import ImageManifest, LayerEntry, ImageConfig


def make_manifest(name="myapp", tag="latest"):
    return ImageManifest(
        name="myapp", tag="latest", digest="",
        created="2024-01-01T00:00:00",
        config=ImageConfig(Env=["X=1"], Cmd=["echo","hi"], WorkingDir="/app"),
        layers=[LayerEntry(digest="sha256:abc123", size=256, createdBy="COPY")],
    )


import pytest

@pytest.fixture(autouse=True)
def patch_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(state_module, "IMAGES_DIR", str(tmp_path / "images"))
    monkeypatch.setattr(state_module, "LAYERS_DIR", str(tmp_path / "layers"))
    monkeypatch.setattr(state_module, "CACHE_DIR",  str(tmp_path / "cache"))


def test_images_empty():
    runner = CliRunner()
    result = runner.invoke(cli, ["images"])
    assert result.exit_code == 0
    assert "No images found" in result.output


def test_images_shows_stored_image():
    save_manifest(make_manifest())
    runner = CliRunner()
    result = runner.invoke(cli, ["images"])
    assert result.exit_code == 0
    assert "myapp" in result.output
    assert "latest" in result.output


def test_rmi_removes_image():
    save_manifest(make_manifest())
    runner = CliRunner()
    result = runner.invoke(cli, ["rmi", "myapp:latest"])
    assert result.exit_code == 0
    assert "Deleted" in result.output


def test_rmi_nonexistent_fails():
    runner = CliRunner()
    result = runner.invoke(cli, ["rmi", "ghost:latest"])
    assert result.exit_code != 0


def test_build_missing_context_fails():
    runner = CliRunner()
    result = runner.invoke(cli, ["build", "-t", "test:latest", "/nonexistent/path"])
    assert result.exit_code != 0