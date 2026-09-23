"""Real AX command: persist one startup per reconstructed process."""

import json
import os
import time
import uuid
from pathlib import Path

assert not any(os.environ.get(k) for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"))
path = Path("/workspace/ax-lifecycle.json")
run_id = os.environ["AX_PROBE_RUN_ID"]
state = json.loads(path.read_text()) if path.exists() else {"run_id": run_id, "startups": []}
assert state["run_id"] == run_id
state["startups"].append(
    {
        "boot_id": str(uuid.uuid4()),
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "started_at": time.time(),
        "process_stat": Path("/proc/self/stat").read_text(),
    }
)
temporary = path.with_suffix(".tmp")
with temporary.open("w") as stream:
    json.dump(state, stream)
    stream.flush()
    os.fsync(stream.fileno())
os.replace(temporary, path)
directory = os.open(path.parent, os.O_RDONLY)
os.fsync(directory)
os.close(directory)
while True:
    time.sleep(60)
