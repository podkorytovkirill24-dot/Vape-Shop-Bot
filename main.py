from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import uvicorn
from aiogram import Bot
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import create_api_router
from app.bot import build_dispatcher, configure_bot_menu, start_polling_task
from app.config import get_config
from app.db import Database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

config = get_config()
APP_MODE = (os.getenv("APP_MODE", "bot") or "bot").strip().lower()
if APP_MODE not in {"all", "web", "bot"}:
    raise RuntimeError("APP_MODE must be one of: all, web, bot.")

RUN_WEB = APP_MODE in {"all", "web"}
RUN_BOT = APP_MODE in {"all", "bot"}
logger.info("Starting app with APP_MODE=%s (RUN_WEB=%s, RUN_BOT=%s)", APP_MODE, RUN_WEB, RUN_BOT)

db = Database(
    config.db_path,
    defaults={
        "store_name": config.mini_app_title,
        "store_logo_url": config.mini_app_logo_url,
        "currency_symbol": "\u20b8",
        "city_name": "\u0423\u0441\u0442\u044c-\u041a\u0430\u043c\u0435\u043d\u043e\u0433\u043e\u0440\u0441\u043a",
        "delivery_fee": "1000",
        "delivery_note": (
            "\u0417\u0430\u0432\u0438\u0441\u0438\u0442 \u043e\u0442 \u043a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u0430 "
            "\u0437\u0430\u043a\u0430\u0437\u043e\u0432 \u0438 \u043c\u043e\u0436\u0435\u0442 \u0434\u043b\u0438\u0442\u044c\u0441\u044f "
            "\u043d\u0435 \u0431\u043e\u043b\u0435\u0435 5 \u0447\u0430\u0441\u043e\u0432"
        ),
        "support_contact": "@support",
        "store_rules": (
            "\u0420\u0430\u0431\u043e\u0442\u0430 \u0441 14:00 \u0434\u043e 22:00\\n"
            "\u0412\u043a\u0443\u0441\u044b,\u043f\u043e\u0437\u0432\u043e\u043d\u044f\u0442 \u0441\u043f\u0440\u043e\u0441\u0438\u0442\u0435"
        ),
    },
)
bot = Bot(token=config.bot_token)
dp = build_dispatcher(config, db)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    polling_task: asyncio.Task | None = None
    if RUN_BOT:
        try:
            await configure_bot_menu(bot, config)
        except Exception:
            logger.exception("Could not configure bot menu button.")
        polling_task = await start_polling_task(bot, dp)
    try:
        yield
    finally:
        if polling_task is not None:
            polling_task.cancel()
            with suppress(asyncio.CancelledError):
                await polling_task
            with suppress(Exception):
                await dp.stop_polling()
        await bot.session.close()


app = FastAPI(title="OZON Oskemen Mini App", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(create_api_router(config=config, db=db, bot=bot))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


async def run_bot_only() -> None:
    db.init()
    try:
        await configure_bot_menu(bot, config)
    except Exception:
        logger.exception("Could not configure bot menu button.")

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        with suppress(Exception):
            await dp.stop_polling()
        await bot.session.close()


if __name__ == "__main__":
    if APP_MODE == "bot":
        asyncio.run(run_bot_only())
    else:
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
