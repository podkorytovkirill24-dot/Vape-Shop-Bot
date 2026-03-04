from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import extract_identity_headers, resolve_identity
from app.config import Config
from app.db import Database

logger = logging.getLogger(__name__)

KZ_TIMEZONE = ZoneInfo("Asia/Almaty")
SHOP_OPEN_HOUR = 14
SHOP_CLOSE_HOUR = 22
DEFAULT_STORE_RULES = "Работа с 14:00 до 22:00\nВкусы,позвонят спросите"


@dataclass
class UserContext:
    tg_user_id: int
    first_name: str
    username: str | None
    language: str
    is_admin: bool


class CartQuantityIn(BaseModel):
    quantity: int = Field(ge=0, le=999)


class OrderCreateIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=3, max_length=32)
    comment: str = Field(default="", max_length=300)
    street: str = Field(min_length=1, max_length=160)
    house: str = Field(min_length=1, max_length=40)
    entrance: str = Field(default="", max_length=40)
    apartment: str = Field(default="", max_length=40)
    payment_method: str = Field(default="cash", max_length=20)


class ProductUpsertIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2_000)
    price_kt: int = Field(ge=0, le=100_000_000)
    image_url: str = Field(default="", max_length=8_000_000)
    stock: int = Field(default=0, ge=0, le=100_000)
    category: str = Field(default="", max_length=100)
    is_active: int | None = Field(default=None)


class StoreSettingsIn(BaseModel):
    store_name: str | None = Field(default=None, max_length=120)
    store_logo_url: str | None = Field(default=None, max_length=1_000)
    currency_symbol: str | None = Field(default=None, max_length=10)
    city_name: str | None = Field(default=None, max_length=120)
    delivery_fee: int | None = Field(default=None, ge=0, le=10_000_000)
    delivery_note: str | None = Field(default=None, max_length=300)
    support_contact: str | None = Field(default=None, max_length=200)
    store_rules: str | None = Field(default=None, max_length=2_000)


class PromotionCreateIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)


class LanguageIn(BaseModel):
    language: str = Field(min_length=2, max_length=5)


class OrderStatusUpdateIn(BaseModel):
    status: str = Field(min_length=2, max_length=20)


def _shop_status(now: datetime | None = None) -> dict[str, Any]:
    current = now.astimezone(KZ_TIMEZONE) if now else datetime.now(KZ_TIMEZONE)
    minutes_now = current.hour * 60 + current.minute
    open_minutes = SHOP_OPEN_HOUR * 60
    close_minutes = SHOP_CLOSE_HOUR * 60
    is_open = open_minutes <= minutes_now < close_minutes
    if is_open:
        message = ""
    elif minutes_now < open_minutes:
        message = "Магазин еще не работает. Работаем с 14:00."
    else:
        message = "Магазин уже закрыт. Работаем с 14:00 до 22:00."
    return {
        "is_open": is_open,
        "message": message,
        "opens_at": "14:00",
        "closes_at": "22:00",
        "timezone": "Asia/Almaty",
        "local_time": current.strftime("%H:%M"),
    }


def _safe_store_settings(raw: dict[str, str], config: Config) -> dict[str, Any]:
    return {
        "store_name": raw.get("store_name", config.mini_app_title),
        "store_logo_url": raw.get("store_logo_url", config.mini_app_logo_url),
        "currency_symbol": raw.get("currency_symbol", "₸"),
        "city_name": raw.get("city_name", "Усть-Каменогорск"),
        "delivery_fee": int(raw.get("delivery_fee", "1000") or "1000"),
        "delivery_note": raw.get(
            "delivery_note",
            "Зависит от количества заказов и может длиться не более 5 часов",
        ),
        "support_contact": raw.get("support_contact", "@support"),
        "store_rules": raw.get("store_rules", DEFAULT_STORE_RULES),
    }


def _cart_summary(items: list[dict[str, Any]], *, delivery_fee: int) -> dict[str, int]:
    items_total = sum(int(item["line_total"]) for item in items)
    total_qty = sum(int(item["quantity"]) for item in items)
    grand_total = items_total + delivery_fee if items_total > 0 else 0
    return {
        "items_total": items_total,
        "total_qty": total_qty,
        "grand_total": grand_total,
        "delivery_fee": delivery_fee if items_total > 0 else 0,
    }


def _order_message(
    order: dict[str, Any],
    settings: dict[str, Any],
    *,
    tg_user_id: int,
    tg_username: str | None,
) -> str:
    telegram_user = f"@{tg_username}" if tg_username else "(no username)"
    telegram_link = f"https://t.me/{tg_username}" if tg_username else ""
    lines = [
        f"Новый заказ #{order['id']}",
        "",
        f"Telegram: {telegram_user}",
        f"Telegram ID: {tg_user_id}",
        f"Telegram link: {telegram_link}" if telegram_link else "Telegram link: not available",
        f"Имя: {order['full_name']}",
        f"Телефон: {order['phone']}",
        f"Адрес: {order['street']}, дом {order['house']}",
    ]
    if order.get("entrance"):
        lines.append(f"Подъезд: {order['entrance']}")
    if order.get("apartment"):
        lines.append(f"Квартира: {order['apartment']}")
    if order.get("comment"):
        lines.append(f"Комментарий: {order['comment']}")
    lines.extend([
        "",
        "Товары:",
    ])
    for item in order["items"]:
        lines.append(
            f"- {item['product_name']} x{item['quantity']} = {item['line_total']} {settings['currency_symbol']}"
        )
    lines.extend([
        "",
        f"Товары: {order['items_total']} {settings['currency_symbol']}",
        f"Доставка: {order['delivery_fee']} {settings['currency_symbol']}",
        f"Итого: {order['grand_total']} {settings['currency_symbol']}",
        f"Оплата: {order['payment_method']}",
    ])
    return "\n".join(lines)


def _order_destination_ids(raw_group_id: int | None) -> list[int]:
    if raw_group_id is None:
        return []

    candidates = [raw_group_id]
    abs_raw = str(abs(raw_group_id))
    # Common Telegram mistake: supergroup id saved without "-100" prefix.
    if raw_group_id < 0 and not str(raw_group_id).startswith("-100") and len(abs_raw) >= 10:
        normalized = int(f"-100{abs_raw}")
        if normalized not in candidates:
            candidates.append(normalized)
    return candidates


async def _notify_orders_group(
    *,
    bot: Bot,
    config: Config,
    message_text: str,
    event_name: str,
    event_id: int,
) -> None:
    if not config.has_order_destination:
        return

    sent = False
    for chat_id in _order_destination_ids(config.orders_group_id):
        try:
            await bot.send_message(chat_id, message_text)
            sent = True
            if chat_id != config.orders_group_id:
                logger.warning(
                    "%s #%s sent to fallback chat_id=%s. Update ORDERS_GROUP_ID to this value.",
                    event_name,
                    event_id,
                    chat_id,
                )
            break
        except Exception:
            logger.warning(
                "Failed to send %s #%s to chat_id=%s.",
                event_name,
                event_id,
                chat_id,
                exc_info=True,
            )
    if not sent:
        logger.error(
            "%s #%s happened, but notification was not delivered. ORDERS_GROUP_ID=%s",
            event_name,
            event_id,
            config.orders_group_id,
        )


def _deleted_order_message(
    *,
    order: dict[str, Any],
    settings: dict[str, Any],
    admin: UserContext,
) -> str:
    admin_name = f"@{admin.username}" if admin.username else admin.first_name
    lines = [
        f"Админ удалил заказ #{order['id']}",
        f"Админ: {admin_name} (ID {admin.tg_user_id})",
        f"Клиент: {order['full_name']}",
        f"Телефон: {order['phone']}",
        f"Сумма: {order['grand_total']} {settings['currency_symbol']}",
        f"Создан: {order['created_at']}",
    ]
    if order.get("items"):
        lines.extend(["", "Товары:"])
        for item in order["items"]:
            lines.append(f"- {item['product_name']} x{item['quantity']} = {item['line_total']} {settings['currency_symbol']}")
    return "\n".join(lines)


def _require_admin(ctx: UserContext) -> None:
    if not ctx.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")


def _public_product(product: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(product["id"]),
        "name": product["name"],
        "description": product["description"],
        "price_kt": int(product["price_kt"]),
        "image_url": product["image_url"],
        "stock": int(product["stock"]),
        "category": product["category"],
        "is_active": int(product["is_active"]),
    }


def create_api_router(*, config: Config, db: Database, bot: Bot) -> APIRouter:
    router = APIRouter(prefix="/api")

    async def current_user(headers: tuple[str | None, str | None] = Depends(extract_identity_headers)) -> UserContext:
        init_data, dev_user_id = headers
        identity = resolve_identity(
            config=config,
            telegram_init_data=init_data,
            dev_user_id_header=dev_user_id,
        )
        user = db.upsert_user(
            tg_user_id=identity.user_id,
            first_name=identity.first_name,
            username=identity.username,
        )
        return UserContext(
            tg_user_id=identity.user_id,
            first_name=user["first_name"],
            username=user.get("username"),
            language=user.get("language", "ru"),
            is_admin=identity.user_id in config.admin_user_ids,
        )

    @router.get("/bootstrap")
    async def bootstrap(ctx: UserContext = Depends(current_user)) -> dict[str, Any]:
        raw_settings = db.get_settings()
        settings = _safe_store_settings(raw_settings, config)
        shop_status = _shop_status()
        products = [_public_product(row) for row in db.list_products()]
        promotions = db.list_promotions()
        favorite_ids = db.list_favorite_ids(ctx.tg_user_id)
        cart_items = db.list_cart_items(ctx.tg_user_id)
        cart = {
            "items": cart_items,
            "summary": _cart_summary(cart_items, delivery_fee=settings["delivery_fee"]),
        }
        orders = db.list_user_orders(ctx.tg_user_id)
        return {
            "user": {
                "id": ctx.tg_user_id,
                "first_name": ctx.first_name,
                "username": ctx.username,
                "language": ctx.language,
                "is_admin": ctx.is_admin,
            },
            "settings": settings,
            "shop_status": shop_status,
            "promotions": promotions,
            "products": products,
            "favorite_ids": favorite_ids,
            "cart": cart,
            "orders": orders,
        }

    @router.get("/config")
    async def app_config(ctx: UserContext = Depends(current_user)) -> dict[str, Any]:
        raw_settings = db.get_settings()
        settings = _safe_store_settings(raw_settings, config)
        shop_status = _shop_status()
        return {
            "user": {
                "id": ctx.tg_user_id,
                "first_name": ctx.first_name,
                "username": ctx.username,
                "language": ctx.language,
                "is_admin": ctx.is_admin,
            },
            "settings": settings,
            "shop_status": shop_status,
        }

    @router.get("/products")
    async def products(_: UserContext = Depends(current_user)) -> dict[str, Any]:
        rows = db.list_products()
        return {"items": [_public_product(row) for row in rows]}

    @router.get("/promotions")
    async def promotions(_: UserContext = Depends(current_user)) -> dict[str, Any]:
        return {"items": db.list_promotions()}

    @router.get("/products/{product_id}")
    async def product_details(product_id: int, _: UserContext = Depends(current_user)) -> dict[str, Any]:
        product = db.get_product(product_id, include_inactive=False)
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
        return {"item": _public_product(product)}

    @router.get("/favorites")
    async def favorites(ctx: UserContext = Depends(current_user)) -> dict[str, Any]:
        return {"ids": db.list_favorite_ids(ctx.tg_user_id)}

    @router.post("/favorites/{product_id}/toggle")
    async def toggle_favorite(product_id: int, ctx: UserContext = Depends(current_user)) -> dict[str, Any]:
        product = db.get_product(product_id, include_inactive=False)
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
        state = db.toggle_favorite(ctx.tg_user_id, product_id)
        return {"is_favorite": state, "ids": db.list_favorite_ids(ctx.tg_user_id)}

    @router.get("/cart")
    async def cart(ctx: UserContext = Depends(current_user)) -> dict[str, Any]:
        settings = _safe_store_settings(db.get_settings(), config)
        items = db.list_cart_items(ctx.tg_user_id)
        return {"items": items, "summary": _cart_summary(items, delivery_fee=settings["delivery_fee"])}

    @router.put("/cart/{product_id}")
    async def set_cart_quantity(
        product_id: int,
        payload: CartQuantityIn,
        ctx: UserContext = Depends(current_user),
    ) -> dict[str, Any]:
        settings = _safe_store_settings(db.get_settings(), config)
        try:
            items = db.set_cart_quantity(ctx.tg_user_id, product_id, payload.quantity)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return {"items": items, "summary": _cart_summary(items, delivery_fee=settings["delivery_fee"])}

    @router.delete("/cart")
    async def clear_cart(ctx: UserContext = Depends(current_user)) -> dict[str, Any]:
        db.clear_cart(ctx.tg_user_id)
        settings = _safe_store_settings(db.get_settings(), config)
        return {"items": [], "summary": _cart_summary([], delivery_fee=settings["delivery_fee"])}

    @router.get("/orders")
    async def order_history(ctx: UserContext = Depends(current_user)) -> dict[str, Any]:
        return {"items": db.list_user_orders(ctx.tg_user_id)}

    @router.post("/orders")
    async def create_order(payload: OrderCreateIn, ctx: UserContext = Depends(current_user)) -> dict[str, Any]:
        shop_status = _shop_status()
        if not shop_status["is_open"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=shop_status["message"])
        if payload.payment_method.lower() not in {"cash", "наличные", "cash_only"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only cash payment is supported.")
        try:
            order = db.create_order(
                user_id=ctx.tg_user_id,
                full_name=payload.full_name.strip(),
                phone=payload.phone.strip(),
                comment=payload.comment.strip(),
                street=payload.street.strip(),
                house=payload.house.strip(),
                entrance=payload.entrance.strip(),
                apartment=payload.apartment.strip(),
                payment_method="Наличные",
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        settings = _safe_store_settings(db.get_settings(), config)
        order_text = _order_message(
            order,
            settings,
            tg_user_id=ctx.tg_user_id,
            tg_username=ctx.username,
        )
        await _notify_orders_group(
            bot=bot,
            config=config,
            message_text=order_text,
            event_name="Order",
            event_id=int(order["id"]),
        )

        return {"item": order}

    @router.put("/profile/language")
    async def set_language(payload: LanguageIn, ctx: UserContext = Depends(current_user)) -> dict[str, Any]:
        language = payload.language.lower()
        if language not in {"ru", "kz", "en"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Language is not supported.")
        user = db.update_user_language(ctx.tg_user_id, language)
        return {"user": user}

    @router.get("/admin/products")
    async def admin_products(ctx: UserContext = Depends(current_user)) -> dict[str, Any]:
        _require_admin(ctx)
        rows = db.list_products(include_inactive=True)
        return {"items": [_public_product(row) for row in rows]}

    @router.post("/admin/products")
    async def admin_create_product(payload: ProductUpsertIn, ctx: UserContext = Depends(current_user)) -> dict[str, Any]:
        _require_admin(ctx)
        created = db.create_product(payload.model_dump())
        return {"item": _public_product(created)}

    @router.put("/admin/products/{product_id}")
    async def admin_update_product(
        product_id: int,
        payload: ProductUpsertIn,
        ctx: UserContext = Depends(current_user),
    ) -> dict[str, Any]:
        _require_admin(ctx)
        updated = db.update_product(product_id, payload.model_dump(exclude_unset=True))
        if not updated:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
        return {"item": _public_product(updated)}

    @router.delete("/admin/products/{product_id}")
    async def admin_delete_product(product_id: int, ctx: UserContext = Depends(current_user)) -> dict[str, Any]:
        _require_admin(ctx)
        ok = db.delete_product(product_id)
        if not ok:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
        return {"ok": True}

    @router.get("/admin/promotions")
    async def admin_promotions(ctx: UserContext = Depends(current_user)) -> dict[str, Any]:
        _require_admin(ctx)
        return {"items": db.list_promotions(include_inactive=True)}

    @router.post("/admin/promotions")
    async def admin_create_promotion(
        payload: PromotionCreateIn,
        ctx: UserContext = Depends(current_user),
    ) -> dict[str, Any]:
        _require_admin(ctx)
        try:
            created = db.create_promotion(payload.text)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return {"item": created}

    @router.delete("/admin/promotions/{promotion_id}")
    async def admin_delete_promotion(promotion_id: int, ctx: UserContext = Depends(current_user)) -> dict[str, Any]:
        _require_admin(ctx)
        ok = db.delete_promotion(promotion_id)
        if not ok:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion not found.")
        return {"ok": True}

    @router.get("/admin/settings")
    async def admin_settings(ctx: UserContext = Depends(current_user)) -> dict[str, Any]:
        _require_admin(ctx)
        return {"settings": _safe_store_settings(db.get_settings(), config)}

    @router.put("/admin/settings")
    async def admin_update_settings(payload: StoreSettingsIn, ctx: UserContext = Depends(current_user)) -> dict[str, Any]:
        _require_admin(ctx)
        body = payload.model_dump(exclude_none=True)
        updates: dict[str, str] = {}
        for key, value in body.items():
            if value is None:
                continue
            updates[key] = str(value)
        settings = db.update_settings(updates)
        return {"settings": _safe_store_settings(settings, config)}

    @router.get("/admin/orders")
    async def admin_orders(ctx: UserContext = Depends(current_user)) -> dict[str, Any]:
        _require_admin(ctx)
        return {"items": db.list_all_orders(limit=300)}

    @router.put("/admin/orders/{order_id}/status")
    async def admin_update_order_status(
        order_id: int,
        payload: OrderStatusUpdateIn,
        ctx: UserContext = Depends(current_user),
    ) -> dict[str, Any]:
        _require_admin(ctx)
        try:
            updated = db.update_order_status(order_id, payload.status)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        if not updated:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
        return {"item": updated}

    @router.delete("/admin/orders/{order_id}")
    async def admin_delete_order(order_id: int, ctx: UserContext = Depends(current_user)) -> dict[str, Any]:
        _require_admin(ctx)
        deleted = db.delete_order(order_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

        settings = _safe_store_settings(db.get_settings(), config)
        deletion_message = _deleted_order_message(order=deleted, settings=settings, admin=ctx)
        await _notify_orders_group(
            bot=bot,
            config=config,
            message_text=deletion_message,
            event_name="Order deletion",
            event_id=int(deleted["id"]),
        )
        return {"item": deleted, "ok": True}

    return router
