from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    KeyboardButton,
    MenuButtonWebApp,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)

from app.config import Config
from app.db import Database

logger = logging.getLogger(__name__)
BROADCAST_BUTTON_TEXT = "Рассылка"


def build_admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BROADCAST_BUTTON_TEXT)]],
        resize_keyboard=True,
    )


def build_router(config: Config, db: Database) -> Router:
    router = Router(name="main_router")
    pending_broadcast_admins: set[int] = set()

    def _is_admin(user_id: int) -> bool:
        return user_id in config.admin_user_ids

    async def _broadcast_text(origin_message: Message, broadcast_text: str) -> None:
        sender = origin_message.from_user
        if sender is None:
            return

        user_ids = db.list_user_ids()
        if not user_ids:
            await origin_message.answer("Нет пользователей для рассылки.")
            return

        sent_count = 0
        failed_count = 0
        for user_id in user_ids:
            try:
                await origin_message.bot.send_message(user_id, broadcast_text)
                sent_count += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed_count += 1
                logger.warning("Broadcast send failed for user_id=%s", user_id, exc_info=True)

        await origin_message.answer(
            "Рассылка завершена.\n"
            f"Отправлено: {sent_count}\n"
            f"Ошибок: {failed_count}"
        )

    async def _broadcast_copy(origin_message: Message) -> None:
        sender = origin_message.from_user
        if sender is None:
            return

        user_ids = db.list_user_ids()
        if not user_ids:
            await origin_message.answer("Нет пользователей для рассылки.")
            return

        sent_count = 0
        failed_count = 0
        for user_id in user_ids:
            try:
                await origin_message.copy_to(chat_id=user_id)
                sent_count += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed_count += 1
                logger.warning("Broadcast copy failed for user_id=%s", user_id, exc_info=True)

        await origin_message.answer(
            "Рассылка завершена.\n"
            f"Отправлено: {sent_count}\n"
            f"Ошибок: {failed_count}"
        )

    @router.message(CommandStart())
    async def cmd_start(message: Message) -> None:
        if message.from_user is not None:
            db.upsert_user(
                tg_user_id=message.from_user.id,
                first_name=message.from_user.first_name or "",
                username=message.from_user.username,
            )

        text = (
            "Добро пожаловать в OZON Oskemen.\n\n"
            "Магазин работает в формате Mini App. "
            "Нажмите синюю кнопку слева от поля сообщения, чтобы открыть витрину."
        )

        if message.from_user is not None and _is_admin(message.from_user.id):
            await message.answer(text, reply_markup=build_admin_keyboard())
            return
        await message.answer(text, reply_markup=ReplyKeyboardRemove())

    @router.message(Command("broadcast"))
    async def cmd_broadcast(message: Message) -> None:
        sender = message.from_user
        if sender is None or not _is_admin(sender.id):
            await message.answer("Команда доступна только администратору.")
            return

        command_text = message.text or ""
        parts = command_text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            pending_broadcast_admins.add(sender.id)
            await message.answer("Отправьте сообщение для рассылки. Для отмены: /cancel")
            return

        pending_broadcast_admins.discard(sender.id)
        await _broadcast_text(message, parts[1].strip())

    @router.message(F.text == BROADCAST_BUTTON_TEXT)
    async def broadcast_button(message: Message) -> None:
        sender = message.from_user
        if sender is None or not _is_admin(sender.id):
            await message.answer("Кнопка доступна только администратору.")
            return

        pending_broadcast_admins.add(sender.id)
        await message.answer("Отправьте сообщение для рассылки. Для отмены: /cancel")

    @router.message(Command("cancel"))
    async def cancel_broadcast(message: Message) -> None:
        sender = message.from_user
        if sender is None:
            return

        if sender.id in pending_broadcast_admins:
            pending_broadcast_admins.discard(sender.id)
            await message.answer("Рассылка отменена.")

    @router.message(lambda message: message.from_user is not None and message.from_user.id in pending_broadcast_admins)
    async def broadcast_payload(message: Message) -> None:
        sender = message.from_user
        if sender is None:
            return

        pending_broadcast_admins.discard(sender.id)
        if not _is_admin(sender.id):
            await message.answer("Нужны права администратора.")
            return

        if message.text and message.text.strip():
            await _broadcast_text(message, message.text.strip())
            return
        await _broadcast_copy(message)

    @router.message(F.text)
    async def fallback(message: Message) -> None:
        text = (
            "Этот бот работает только через Mini App.\n"
            "Нажмите синюю кнопку слева от поля сообщения, чтобы открыть витрину."
        )

        if message.from_user is not None and _is_admin(message.from_user.id):
            await message.answer(text, reply_markup=build_admin_keyboard())
            return
        await message.answer(text, reply_markup=ReplyKeyboardRemove())

    return router


def build_dispatcher(config: Config, db: Database) -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(build_router(config, db))
    return dp


async def configure_bot_menu(bot: Bot, config: Config) -> None:
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="OZON Oskemen",
            web_app=WebAppInfo(url=config.webapp_url),
        )
    )


async def start_polling_task(bot: Bot, dp: Dispatcher) -> asyncio.Task:
    # If webhook was set earlier (for another host), polling will not receive updates.
    await bot.delete_webhook(drop_pending_updates=False)
    task = asyncio.create_task(
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
        name="aiogram_polling_task",
    )
    logger.info("Aiogram polling task started")
    return task
