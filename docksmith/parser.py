# docksmith/parser.py
# ============================================================
#  PROTHAM — File 1: Docksmithfile Parser
#  Test: python3 -m pytest tests/test_parser.py -v
# ============================================================

import json
from dataclasses import dataclass

VALID_INSTRUCTIONS = {"FROM", "COPY", "RUN", "WORKDIR", "ENV", "CMD"}


@dataclass
class Instruction:
    type: str         # FROM, COPY, RUN, WORKDIR, ENV, CMD
    args: str         # Everything after the keyword
    line_number: int  # Original line number (for error messages)

    def __repr__(self):
        return f"Instruction(type={self.type!r}, args={self.args!r}, line={self.line_number})"


# ── Main parser ───────────────────────────────────────────────────────────────

def parse_docksmithfile(filepath: str) -> list:
    """
    Reads a Docksmithfile and returns a list of Instruction objects.
    Fails immediately with clear error + line number on unknown instructions.
    """
    instructions = []

    try:
        with open(filepath, "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        raise FileNotFoundError(
            f"[BUILD ERROR] Docksmithfile not found at: {filepath}"
        )

    for i, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()

        # Skip blank lines and comments
        if not line or line.startswith("#"):
            continue

        # Split keyword from rest of line
        parts = line.split(None, 1)
        keyword = parts[0].upper()
        args = parts[1].strip() if len(parts) > 1 else ""

        # Fail immediately on unknown instruction
        if keyword not in VALID_INSTRUCTIONS:
            raise ValueError(
                f"[PARSE ERROR] Line {i}: Unknown instruction '{parts[0]}'.\n"
                f"  Valid instructions: {', '.join(sorted(VALID_INSTRUCTIONS))}\n"
                f"  Got: {line!r}"
            )

        # Validate args for each instruction
        _validate_args(keyword, args, i)

        instructions.append(Instruction(type=keyword, args=args, line_number=i))

    if not instructions:
        raise ValueError(
            f"[PARSE ERROR] Docksmithfile is empty or has no valid instructions."
        )

    # Must start with FROM
    if instructions[0].type != "FROM":
        raise ValueError(
            f"[PARSE ERROR] Line {instructions[0].line_number}: "
            f"Docksmithfile must start with FROM, got '{instructions[0].type}'"
        )

    return instructions


def _validate_args(keyword: str, args: str, line_number: int):
    """Validates each instruction has correct argument format."""

    if keyword == "FROM":
        if not args:
            raise ValueError(
                f"[PARSE ERROR] Line {line_number}: FROM needs an image name.\n"
                f"  Example: FROM alpine:latest"
            )

    elif keyword == "COPY":
        if len(args.split(None, 1)) < 2:
            raise ValueError(
                f"[PARSE ERROR] Line {line_number}: COPY needs <src> and <dest>.\n"
                f"  Example: COPY . /app"
            )

    elif keyword == "RUN":
        if not args:
            raise ValueError(
                f"[PARSE ERROR] Line {line_number}: RUN needs a command.\n"
                f"  Example: RUN echo hello"
            )

    elif keyword == "WORKDIR":
        if not args:
            raise ValueError(
                f"[PARSE ERROR] Line {line_number}: WORKDIR needs a path.\n"
                f"  Example: WORKDIR /app"
            )

    elif keyword == "ENV":
        if "=" not in args:
            raise ValueError(
                f"[PARSE ERROR] Line {line_number}: ENV must be KEY=value.\n"
                f"  Example: ENV APP_NAME=myapp\n"
                f"  Got: {args!r}"
            )

    elif keyword == "CMD":
        try:
            result = json.loads(args)
            if not isinstance(result, list):
                raise ValueError()
            if not all(isinstance(x, str) for x in result):
                raise ValueError()
        except (json.JSONDecodeError, ValueError):
            raise ValueError(
                f"[PARSE ERROR] Line {line_number}: CMD must be a JSON string array.\n"
                f"  Example: CMD [\"python\", \"main.py\"]\n"
                f"  Got: {args!r}"
            )


# ── Argument parsers (called by builder.py) ───────────────────────────────────

def parse_from_args(args: str) -> tuple:
    """
    Parses 'alpine:latest' → ('alpine', 'latest')
    Defaults tag to 'latest' if not specified.
    """
    if ":" in args:
        name, tag = args.split(":", 1)
    else:
        name, tag = args, "latest"
    return name.strip(), tag.strip()


def parse_env_args(args: str) -> tuple:
    """
    Parses 'KEY=value' → ('KEY', 'value')
    Handles values that contain = signs (e.g. URL=http://x.com/a=b)
    """
    if "=" not in args:
        raise ValueError(f"[PARSE ERROR] ENV must be KEY=value format. Got: {args!r}")
    key, _, value = args.partition("=")
    return key.strip(), value.strip()


def parse_copy_args(args: str) -> tuple:
    """
    Parses '. /app' → ('.', '/app')
    """
    parts = args.split(None, 1)
    if len(parts) < 2:
        raise ValueError(
            f"[PARSE ERROR] COPY needs <src> and <dest>. Got: {args!r}"
        )
    return parts[0], parts[1]


def parse_cmd_args(args: str) -> list:
    """
    Parses '["python", "main.py"]' → ['python', 'main.py']
    """
    try:
        result = json.loads(args)
        if not isinstance(result, list):
            raise ValueError()
        return result
    except (json.JSONDecodeError, ValueError):
        raise ValueError(
            f"[PARSE ERROR] CMD must be a JSON array.\n"
            f"  Example: CMD [\"python\", \"main.py\"]\n"
            f"  Got: {args!r}"
        )