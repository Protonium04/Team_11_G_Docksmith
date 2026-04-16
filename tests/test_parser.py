# tests/test_parser.py
import os, sys, tempfile, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from docksmith.parser import (
    parse_docksmithfile, parse_from_args,
    parse_env_args, parse_copy_args, parse_cmd_args,
)

def write_df(content):
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix="_Docksmithfile", delete=False)
    tmp.write(content); tmp.close(); return tmp.name

def test_parses_all_six():
    p = write_df("FROM alpine:latest\nWORKDIR /app\nENV X=1\nCOPY . /app\nRUN echo hi\nCMD [\"sh\"]\n")
    ins = parse_docksmithfile(p)
    assert [i.type for i in ins] == ["FROM","WORKDIR","ENV","COPY","RUN","CMD"]

def test_skips_comments_and_blanks():
    p = write_df("# comment\n\nFROM alpine:latest\n\nRUN echo hi\n")
    ins = parse_docksmithfile(p)
    assert len(ins) == 2

def test_unknown_instruction_fails_with_line_number():
    p = write_df("FROM alpine:latest\nEXPOSE 8080\n")
    with pytest.raises(ValueError) as e:
        parse_docksmithfile(p)
    assert "Line 2" in str(e.value)
    assert "EXPOSE" in str(e.value)

def test_must_start_with_from():
    p = write_df("RUN echo hi\n")
    with pytest.raises(ValueError): parse_docksmithfile(p)

def test_cmd_invalid_json_fails():
    p = write_df("FROM alpine:latest\nCMD python main.py\n")
    with pytest.raises(ValueError) as e:
        parse_docksmithfile(p)
    assert "JSON" in str(e.value)

def test_env_no_equals_fails():
    p = write_df("FROM alpine:latest\nENV APPNAME\n")
    with pytest.raises(ValueError): parse_docksmithfile(p)

def test_line_numbers_correct():
    p = write_df("# comment\n\nFROM alpine:latest\nRUN echo hi\n")
    ins = parse_docksmithfile(p)
    assert ins[0].line_number == 3
    assert ins[1].line_number == 4

def test_parse_from_with_tag():
    assert parse_from_args("alpine:3.18") == ("alpine", "3.18")

def test_parse_from_no_tag():
    assert parse_from_args("alpine") == ("alpine", "latest")

def test_parse_env_value_with_equals():
    k, v = parse_env_args("URL=http://x.com/a=b")
    assert k == "URL" and v == "http://x.com/a=b"

def test_parse_copy_args():
    assert parse_copy_args(". /app") == (".", "/app")

def test_parse_cmd_args():
    assert parse_cmd_args('["python","main.py"]') == ["python","main.py"]
