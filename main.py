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
APP_MODE = (os.getenv("APP_MODE", "all") or "all").strip().lower()
if APP_MODE not in {"all", "web", "bot"}:
    raise RuntimeError("APP_MODE must be one of: all, web, bot.")

RUN_WEB = APP_MODE in {"all", "web"}
RUN_BOT = APP_MODE in {"all", "bot"}

db = Database(
    config.db_path,
    defaults={
        "store_name": config.mini_app_title,
        "store_logo_url": config.mini_app_logo_url,
        "currency_symbol": "₸",
        "city_name": "Усть-Каменогорск",
        "delivery_fee": "1000",
        "delivery_note": "зависит от количества заказов и может длиться не более 5 часов",
        "support_contact": "@support",
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
        await dp.start_polling(bot)
    finally:
        with suppress(Exception):
            await dp.stop_polling()
        await bot.session.close()


if __name__ == "__main__":
    if APP_MODE == "bot":
        asyncio.run(run_bot_only())
    else:
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
