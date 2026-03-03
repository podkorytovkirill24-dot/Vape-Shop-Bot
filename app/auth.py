from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException, status

from app.config import Config


@dataclass
class TelegramIdentity:
    user_id: int
    first_name: str
    username: str | None
    language_code: str


def _verify_telegram_init_data(init_data: str, bot_token: str, max_age_seconds: int = 2_592_000) -> dict[str, str]:
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Telegram hash.")

    auth_date_str = pairs.get("auth_date", "")
    try:
        auth_date = int(auth_date_str)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid auth_date.") from exc
    if max_age_seconds > 0 and (time.time() - auth_date) > max_age_seconds:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="initData is expired.")

    data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Telegram signature.")
    return pairs


def _identity_from_verified_pairs(pairs: dict[str, str]) -> TelegramIdentity:
    user_json = pairs.get("user")
    if not user_json:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Telegram user is missing.")
    try:
        user_data = json.loads(user_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Telegram user payload.") from exc

    try:
        user_id = int(user_data["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Telegram user id.") from exc

    return TelegramIdentity(
        user_id=user_id,
        first_name=str(user_data.get("first_name", "")).strip() or "Guest",
        username=user_data.get("username"),
        language_code=str(user_data.get("language_code", "ru")),
    )


def resolve_identity(
    *,
    config: Config,
    telegram_init_data: str | None,
    dev_user_id_header: str | None,
) -> TelegramIdentity:
    if telegram_init_data:
        verified = _verify_telegram_init_data(telegram_init_data.strip(), config.bot_token)
        return _identity_from_verified_pairs(verified)

    if config.dev_mode:
        chosen = dev_user_id_header.strip() if dev_user_id_header else str(config.dev_user_id)
        try:
            user_id = int(chosen)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid dev user id.") from exc
        return TelegramIdentity(
            user_id=user_id,
            first_name="Dev User",
            username="dev_user",
            language_code="ru",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось авторизоваться в Telegram Mini App. Откройте приложение через кнопку /start.",
    )


async def extract_identity_headers(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    x_dev_user_id: str | None = Header(default=None, alias="X-Dev-User-Id"),
) -> tuple[str | None, str | None]:
    return x_telegram_init_data, x_dev_user_id
