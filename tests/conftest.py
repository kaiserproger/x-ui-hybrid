"""Shared pytest setup: make the project root importable so tests can do
`from bot.db import Store` and `import landing` without installing anything."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
