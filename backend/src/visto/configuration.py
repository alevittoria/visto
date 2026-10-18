"""Explicit local provider-key resolution without mutating the process environment.

The supported UTF-8 (optional BOM) subset is a plain ``OPENAI_API_KEY=value``
assignment with optional ``export``, surrounding whitespace, single/double quotes,
blank lines and comments. Unquoted comments start with ``#`` after whitespace;
quoted values may have a trailing comment. Quotes do not support escapes. All
values are literal: no interpolation, command substitution or evaluation occurs.
Other variables are ignored, including their syntax. No file is read at import.
"""

import os
import re
from pathlib import Path

_TARGET = re.compile(r"(?:export[ \t]+)?OPENAI_API_KEY(?=$|[^A-Za-z0-9_])")
_ASSIGNMENT = re.compile(r"(?:export[ \t]+)?OPENAI_API_KEY[ \t]*=[ \t]*(.*)")
_INVALID_ENTRY = "Env file has invalid or duplicate OPENAI_API_KEY entries"


def _literal_value(value: str) -> str:
    if not value or value.startswith("#"):
        return ""
    if value[0] in ("'", '"'):
        end = value.find(value[0], 1)
        if end == -1:
            raise ValueError(_INVALID_ENTRY)
        remainder = value[end + 1 :].strip()
        if remainder and not remainder.startswith("#"):
            raise ValueError(_INVALID_ENTRY)
        return value[1:end]
    return re.split(r"[ \t]+#", value, maxsplit=1)[0].rstrip()


def resolve_api_key(env_file: Path) -> str:
    """Prefer a nonblank process key, otherwise read only the selected env file.

    A missing file/key returns an empty string. Unreadable/invalid UTF-8 files,
    duplicate key assignments and malformed target-key lines raise sanitized
    ``ValueError`` messages without file paths, source lines or credential data.
    """
    process_key = os.environ.get("OPENAI_API_KEY", "")
    if process_key.strip():
        return process_key
    try:
        contents = env_file.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return ""
    except UnicodeError:
        raise ValueError("Env file must contain valid UTF-8 text") from None
    except OSError:
        raise ValueError("Env file could not be read") from None

    key = ""
    found = False
    for raw_line in contents.splitlines():
        line = raw_line.strip()
        if not _TARGET.match(line):
            continue
        assignment = _ASSIGNMENT.fullmatch(line)
        if found or assignment is None:
            raise ValueError(_INVALID_ENTRY)
        key = _literal_value(assignment.group(1))
        found = True
    return key
