"""LOCAL verification only: inject a computation failure by a marker file.

Not imported by production. Bind loopback only; uses the real routes/store/model.
"""

import os
from pathlib import Path

import uvicorn

from harbinger.api.main import app
from harbinger.api.routers import workbench

original = workbench.analyze
marker = Path(os.environ["HARBINGER_AUDIT_FAULT_FILE"])


def controlled_analysis(*args, **kwargs):
    if marker.exists():
        raise RuntimeError("LOCAL audit injected analysis failure")
    return original(*args, **kwargs)


workbench.analyze = controlled_analysis

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=18000, access_log=False)
