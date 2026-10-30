#!/usr/bin/env python
"""Container healthcheck: worker heartbeat freshness."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def main() -> int:
    path = Path(os.environ.get("WORKER_HEALTH_FILE", "/tmp/nasmap-worker-heartbeat"))
    if not path.exists():
        return 1
    age = time.time() - path.stat().st_mtime
    return 0 if age < 120 else 1


if __name__ == "__main__":
    sys.exit(main())
