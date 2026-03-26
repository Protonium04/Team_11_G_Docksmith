# tests/test_models.py
# Run: python3 -m pytest tests/test_models.py -v

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from docksmith.models import ImageManifest, LayerEntry, ImageConfig


def test_image_config_defaults():
    c = ImageConfig()
    assert c.Env == []
    assert c.Cmd == []
    assert c.WorkingDir == ""


def test_layer_entry_fields():
    l = LayerEntry(digest="sha256:abc", size=1024, createdBy="COPY . /app")
    assert l.digest == "sha256:abc"
    assert l.size == 1024
    assert l.createdBy == "COPY . /app"


def test_image_manifest_fields():
    config = ImageConfig(Env=["X=1"], Cmd=["python", "main.py"], WorkingDir="/app")
    layers = [LayerEntry(digest="sha256:abc", size=100, createdBy="COPY")]
    m = ImageManifest(
        name="myapp", tag="latest", digest="sha256:xyz",
        created="2024-01-01T00:00:00", config=config, layers=layers
    )
    assert m.name == "myapp"
    assert m.tag == "latest"
    assert len(m.layers) == 1
    assert m.config.WorkingDir == "/app"


def test_manifest_layers_default_empty():
    config = ImageConfig()
    m = ImageManifest(name="x", tag="y", digest="", created="now", config=config)
    assert m.layers == []