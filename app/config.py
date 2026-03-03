from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int | None = None) -> int | None:
    if value is None or not value.strip():
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def _parse_admin_ids(raw: str | None) -> set[int]:
    if not raw:
        return set()
    parsed: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            parsed.add(int(part))
        except ValueError:
            continue
    return parsed


def _env_get(key: str, default: str | None = None) -> str | None:
    value = os.getenv(key)
    if value is not None:
        return value
    # Graceful fallback when .env was saved with UTF-8 BOM and key becomes '\ufeffKEY'.
    bom_key = f"\ufeff{key}"
    value = os.getenv(bom_key)
    if value is not None:
        return value
    return default


@dataclass(frozen=True)
class Config:
    bot_token: str
    webapp_url: str
    orders_group_id: int | None
    admin_user_ids: set[int]
    dev_mode: bool
    dev_user_id: int
    db_path: Path
    mini_app_title: str
    mini_app_logo_url: str

    @property
    def has_order_destination(self) -> bool:
        return self.orders_group_id is not None


@lru_cache(maxsize=1)
def get_config() -> Config:
    load_dotenv()

    bot_token = (_env_get("BOT_TOKEN", "") or "").strip()
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is required in environment.")

    webapp_url = (_env_get("WEBAPP_URL", "http://127.0.0.1:8000") or "").strip() or "http://127.0.0.1:8000"

    db_raw = (_env_get("DATABASE_PATH", "data/app.db") or "data/app.db").strip()
    db_path = Path(db_raw)
    if not db_path.parent.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)

    return Config(
        bot_token=bot_token,
        webapp_url=webapp_url,
        orders_group_id=_as_int(_env_get("ORDERS_GROUP_ID"), None),
        admin_user_ids=_parse_admin_ids(_env_get("ADMIN_USER_IDS")),
        dev_mode=_as_bool(_env_get("DEV_MODE"), default=False),
        dev_user_id=_as_int(_env_get("DEV_USER_ID"), 777000) or 777000,
        db_path=db_path,
        mini_app_title=(_env_get("MINI_APP_TITLE", "OZON Oskemen") or "").strip() or "OZON Oskemen",
        mini_app_logo_url=(
            _env_get(
                "MINI_APP_LOGO_URL",
                "https://upload.wikimedia.org/wikipedia/commons/thumb/9/91/Ozon_logo.svg/512px-Ozon_logo.svg.png",
            ).strip()
            or "https://upload.wikimedia.org/wikipedia/commons/thumb/9/91/Ozon_logo.svg/512px-Ozon_logo.svg.png"
        ),
    )
