"""Run the MarketPilot backend: `python -m marketpilot` (works on Windows, macOS and Linux)."""
from __future__ import annotations

import logging

import uvicorn

from .app import create_app
from .config import get_settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    st = get_settings()
    uvicorn.run(create_app(st), host=st.api_host, port=st.api_port, log_level="info")


if __name__ == "__main__":
    main()
