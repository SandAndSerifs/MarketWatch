from __future__ import annotations

import os

import pytest

os.environ.setdefault("MARKETPILOT_ENV", "test")
os.environ["MARKET_DATA_PROVIDER"] = "none"
os.environ["RUN_ENGINE"] = "false"
os.environ["AI_PROVIDER"] = "none"
for k in ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY", "MASSIVE_API_KEY", "FINNHUB_API_KEY", "ANTHROPIC_API_KEY",
          "SMTP_HOST", "ALERT_WEBHOOK_URL"):
    os.environ.pop(k, None)


@pytest.fixture()
def db(tmp_path):
    from marketpilot import db as dbmod
    from marketpilot.app import seed
    from marketpilot.config import reset_settings_cache

    url = f"sqlite:///{tmp_path / 'test.db'}"
    os.environ["DATABASE_URL"] = url
    reset_settings_cache()
    dbmod.init_engine(url)
    with dbmod.session_scope() as s:
        seed(s)
    yield dbmod
    dbmod.get_engine().dispose()
