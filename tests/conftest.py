from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
SKILLS_DIR = SRC_DIR / "skills"

for path in [str(SRC_DIR), str(SKILLS_DIR)]:
    if path not in sys.path:
        sys.path.insert(0, path)

os.environ.setdefault("SKILLS_DIR", str(SKILLS_DIR))
