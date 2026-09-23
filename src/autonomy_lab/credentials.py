"""Read only the explicitly selected model credential, without evaluating shell code."""

import os
import shlex
from pathlib import Path

KEY_NAMES = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_KEY")


def gemini_key(env_file: Path | None = None) -> str:
    for name in KEY_NAMES:
        if value := os.environ.get(name):
            return value
    path = (env_file or Path("~/Dev/.env")).expanduser()
    if path.is_file():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].lstrip()
            name, separator, raw_value = line.partition("=")
            if separator and name.strip() in KEY_NAMES:
                try:
                    parts = shlex.split(raw_value, comments=True, posix=True)
                except ValueError:
                    raise ValueError("Gemini credential has invalid quoting") from None
                if len(parts) == 1 and parts[0]:
                    return parts[0]
    raise RuntimeError("No Gemini credential found in the environment or selected .env file")
