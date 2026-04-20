from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
SKILLS_DIR = ROOT / ".claude" / "skills"

for path in [str(SRC_DIR), str(SKILLS_DIR)]:
    if path not in sys.path:
        sys.path.insert(0, path)
