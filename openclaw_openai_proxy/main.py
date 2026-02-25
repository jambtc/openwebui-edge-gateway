from __future__ import annotations

import uvicorn

from .server import app


def run() -> None:
    uvicorn.run(app, host="0.0.0.0", port=4010)


if __name__ == "__main__":
    run()
