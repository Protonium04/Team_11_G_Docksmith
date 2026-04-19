# tests/test_reporter.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from docksmith.reporter import print_step, print_build_success

def test_print_step_hit(capsys):
    print_step(1, 3, "COPY", ". /app", status="hit")
    out = capsys.readouterr().out
    assert "[CACHE HIT]" in out
    assert "Step 1/3" in out

def test_print_step_miss(capsys):
    print_step(2, 3, "RUN", "echo hi", status="miss", elapsed=1.23)
    out = capsys.readouterr().out
    assert "[CACHE MISS]" in out
    assert "1.23s" in out

def test_print_step_no_status(capsys):
    print_step(1, 3, "FROM", "alpine:latest")
    out = capsys.readouterr().out
    assert "FROM" in out
    assert "[CACHE" not in out

def test_print_build_success(capsys):
    print_build_success("sha256:abcdef1234567890", "myapp", "latest", 4.56)
    out = capsys.readouterr().out
    assert "myapp:latest" in out
    assert "4.56s" in out
