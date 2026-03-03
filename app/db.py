from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


class Database:
    ALLOWED_SETTINGS = {
        "store_name",
        "store_logo_url",
        "currency_symbol",
        "city_name",
        "delivery_fee",
        "delivery_note",
        "support_contact",
    }
    ALLOWED_ORDER_STATUSES = {"new", "confirmed", "delivering", "done", "cancelled"}

    def __init__(self, db_path: Path, *, defaults: dict[str, str]) -> None:
        self._db_path = db_path
        self._defaults = defaults
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def init(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS users (
            tg_user_id INTEGER PRIMARY KEY,
            first_name TEXT NOT NULL DEFAULT '',
            username TEXT,
            language TEXT NOT NULL DEFAULT 'ru',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            price_kt INTEGER NOT NULL CHECK (price_kt >= 0),
            image_url TEXT NOT NULL DEFAULT '',
            stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
            category TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, product_id),
            FOREIGN KEY (user_id) REFERENCES users(tg_user_id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS cart_items (
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL CHECK (quantity >= 1),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, product_id),
            FOREIGN KEY (user_id) REFERENCES users(tg_user_id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            comment TEXT NOT NULL DEFAULT '',
            street TEXT NOT NULL,
            house TEXT NOT NULL,
            entrance TEXT NOT NULL DEFAULT '',
            apartment TEXT NOT NULL DEFAULT '',
            payment_method TEXT NOT NULL,
            delivery_fee INTEGER NOT NULL CHECK (delivery_fee >= 0),
            items_total INTEGER NOT NULL CHECK (items_total >= 0),
            grand_total INTEGER NOT NULL CHECK (grand_total >= 0),
            status TEXT NOT NULL DEFAULT 'new',
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(tg_user_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            unit_price INTEGER NOT NULL CHECK (unit_price >= 0),
            quantity INTEGER NOT NULL CHECK (quantity >= 1),
            line_total INTEGER NOT NULL CHECK (line_total >= 0),
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
        with self._lock, self._connect() as conn:
            conn.executescript(schema)
            for key, value in self._defaults.items():
                conn.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (key, value),
                )
            conn.commit()

    def upsert_user(self, *, tg_user_id: int, first_name: str, username: str | None) -> dict[str, Any]:
        stamp = now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (tg_user_id, first_name, username, language, created_at, updated_at)
                VALUES (?, ?, ?, 'ru', ?, ?)
                ON CONFLICT(tg_user_id) DO UPDATE SET
                    first_name=excluded.first_name,
                    username=excluded.username,
                    updated_at=excluded.updated_at
                """,
                (tg_user_id, first_name, username, stamp, stamp),
            )
            row = conn.execute("SELECT * FROM users WHERE tg_user_id = ?", (tg_user_id,)).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("Could not upsert user.")
        return _row_to_dict(row)

    def update_user_language(self, tg_user_id: int, language: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE users SET language = ?, updated_at = ? WHERE tg_user_id = ?",
                (language, now_iso(), tg_user_id),
            )
            row = conn.execute("SELECT * FROM users WHERE tg_user_id = ?", (tg_user_id,)).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("User not found.")
        return _row_to_dict(row)

    def list_user_ids(self) -> list[int]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT tg_user_id FROM users ORDER BY tg_user_id ASC").fetchall()
        return [int(row["tg_user_id"]) for row in rows]

    def get_settings(self) -> dict[str, str]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def update_settings(self, updates: dict[str, str]) -> dict[str, str]:
        filtered = {k: v for k, v in updates.items() if k in self.ALLOWED_SETTINGS}
        if not filtered:
            return self.get_settings()
        with self._lock, self._connect() as conn:
            for key, value in filtered.items():
                conn.execute(
                    """
                    INSERT INTO settings (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, value),
                )
            conn.commit()
        return self.get_settings()

    def list_products(self, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        where = "" if include_inactive else "WHERE is_active = 1"
        query = f"""
            SELECT id, name, description, price_kt, image_url, stock, category, is_active, created_at, updated_at
            FROM products
            {where}
            ORDER BY id DESC
        """
        with self._lock, self._connect() as conn:
            rows = conn.execute(query).fetchall()
        return [_row_to_dict(row) for row in rows]

    def get_product(self, product_id: int, *, include_inactive: bool = False) -> dict[str, Any] | None:
        where = "" if include_inactive else "AND is_active = 1"
        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT id, name, description, price_kt, image_url, stock, category, is_active, created_at, updated_at
                FROM products
                WHERE id = ? {where}
                """,
                (product_id,),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def create_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        stamp = now_iso()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO products (name, description, price_kt, image_url, stock, category, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    payload["name"],
                    payload.get("description", ""),
                    int(payload["price_kt"]),
                    payload.get("image_url", ""),
                    int(payload.get("stock", 0)),
                    payload.get("category", ""),
                    stamp,
                    stamp,
                ),
            )
            product_id = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM products WHERE id = ?",
                (product_id,),
            ).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("Could not create product.")
        return _row_to_dict(row)

    def update_product(self, product_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.get_product(product_id, include_inactive=True)
        if not existing:
            return None
        merged = {
            "name": payload.get("name", existing["name"]),
            "description": payload.get("description", existing["description"]),
            "price_kt": int(payload.get("price_kt", existing["price_kt"])),
            "image_url": payload.get("image_url", existing["image_url"]),
            "stock": int(payload.get("stock", existing["stock"])),
            "category": payload.get("category", existing["category"]),
            "is_active": int(payload.get("is_active", existing["is_active"])),
        }
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE products
                SET name = ?, description = ?, price_kt = ?, image_url = ?, stock = ?, category = ?, is_active = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    merged["name"],
                    merged["description"],
                    merged["price_kt"],
                    merged["image_url"],
                    merged["stock"],
                    merged["category"],
                    merged["is_active"],
                    now_iso(),
                    product_id,
                ),
            )
            row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            conn.commit()
        return _row_to_dict(row) if row else None

    def disable_product(self, product_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE products SET is_active = 0, updated_at = ? WHERE id = ?",
                (now_iso(), product_id),
            )
            conn.commit()
        return cursor.rowcount > 0

    def list_favorite_ids(self, user_id: int) -> list[int]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT product_id FROM favorites WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [int(row["product_id"]) for row in rows]

    def toggle_favorite(self, user_id: int, product_id: int) -> bool:
        with self._lock, self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM favorites WHERE user_id = ? AND product_id = ?",
                (user_id, product_id),
            ).fetchone()
            if exists:
                conn.execute(
                    "DELETE FROM favorites WHERE user_id = ? AND product_id = ?",
                    (user_id, product_id),
                )
                conn.commit()
                return False
            conn.execute(
                "INSERT INTO favorites (user_id, product_id, created_at) VALUES (?, ?, ?)",
                (user_id, product_id, now_iso()),
            )
            conn.commit()
            return True

    def list_cart_items(self, user_id: int) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.product_id,
                    c.quantity,
                    p.name,
                    p.description,
                    p.price_kt,
                    p.image_url,
                    p.stock,
                    p.category,
                    (c.quantity * p.price_kt) AS line_total
                FROM cart_items c
                JOIN products p ON p.id = c.product_id
                WHERE c.user_id = ? AND p.is_active = 1
                ORDER BY c.updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def set_cart_quantity(self, user_id: int, product_id: int, quantity: int) -> list[dict[str, Any]]:
        if quantity <= 0:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "DELETE FROM cart_items WHERE user_id = ? AND product_id = ?",
                    (user_id, product_id),
                )
                conn.commit()
            return self.list_cart_items(user_id)

        product = self.get_product(product_id, include_inactive=False)
        if not product:
            raise ValueError("Product not found or inactive.")
        if quantity > int(product["stock"]):
            raise ValueError("Requested quantity exceeds stock.")

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cart_items (user_id, product_id, quantity, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, product_id) DO UPDATE SET
                    quantity = excluded.quantity,
                    updated_at = excluded.updated_at
                """,
                (user_id, product_id, quantity, now_iso(), now_iso()),
            )
            conn.commit()
        return self.list_cart_items(user_id)

    def clear_cart(self, user_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
            conn.commit()

    def create_order(
        self,
        *,
        user_id: int,
        full_name: str,
        phone: str,
        comment: str,
        street: str,
        house: str,
        entrance: str,
        apartment: str,
        payment_method: str,
    ) -> dict[str, Any]:
        settings = self.get_settings()
        delivery_fee = int(settings.get("delivery_fee", "1000") or "1000")
        cart_items = self.list_cart_items(user_id)
        if not cart_items:
            raise ValueError("Cart is empty.")

        items_total = sum(int(item["line_total"]) for item in cart_items)
        grand_total = items_total + delivery_fee
        created = now_iso()

        with self._lock, self._connect() as conn:
            # Re-check stock in transaction window.
            for item in cart_items:
                row = conn.execute(
                    "SELECT stock, is_active FROM products WHERE id = ?",
                    (item["product_id"],),
                ).fetchone()
                if row is None or int(row["is_active"]) != 1:
                    raise ValueError("One of products is unavailable now.")
                if int(item["quantity"]) > int(row["stock"]):
                    raise ValueError(f"Not enough stock for: {item['name']}")

            cursor = conn.execute(
                """
                INSERT INTO orders (
                    user_id, full_name, phone, comment, street, house, entrance, apartment,
                    payment_method, delivery_fee, items_total, grand_total, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)
                """,
                (
                    user_id,
                    full_name,
                    phone,
                    comment,
                    street,
                    house,
                    entrance,
                    apartment,
                    payment_method,
                    delivery_fee,
                    items_total,
                    grand_total,
                    created,
                ),
            )
            order_id = int(cursor.lastrowid)
            for item in cart_items:
                conn.execute(
                    """
                    INSERT INTO order_items (order_id, product_id, product_name, unit_price, quantity, line_total)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order_id,
                        item["product_id"],
                        item["name"],
                        item["price_kt"],
                        item["quantity"],
                        item["line_total"],
                    ),
                )
                conn.execute(
                    "UPDATE products SET stock = stock - ?, updated_at = ? WHERE id = ?",
                    (item["quantity"], now_iso(), item["product_id"]),
                )
            conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
            conn.commit()

        return self.get_order(order_id)

    def get_order(self, order_id: int) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            order_row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if order_row is None:
                raise ValueError("Order not found.")
            item_rows = conn.execute(
                "SELECT product_id, product_name, unit_price, quantity, line_total FROM order_items WHERE order_id = ?",
                (order_id,),
            ).fetchall()

        order = _row_to_dict(order_row)
        order["items"] = [_row_to_dict(item_row) for item_row in item_rows]
        return order

    def list_user_orders(self, user_id: int) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            order_rows = conn.execute(
                """
                SELECT *
                FROM orders
                WHERE user_id = ?
                ORDER BY id DESC
                """,
                (user_id,),
            ).fetchall()
            orders: list[dict[str, Any]] = []
            for order_row in order_rows:
                order_dict = _row_to_dict(order_row)
                item_rows = conn.execute(
                    """
                    SELECT product_id, product_name, unit_price, quantity, line_total
                    FROM order_items
                    WHERE order_id = ?
                    ORDER BY id ASC
                    """,
                    (order_dict["id"],),
                ).fetchall()
                order_dict["items"] = [_row_to_dict(item_row) for item_row in item_rows]
                orders.append(order_dict)
        return orders

    def list_all_orders(self, *, limit: int = 250) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1_000))
        with self._lock, self._connect() as conn:
            order_rows = conn.execute(
                """
                SELECT
                    o.*,
                    u.first_name AS user_first_name,
                    u.username AS user_username
                FROM orders o
                LEFT JOIN users u ON u.tg_user_id = o.user_id
                ORDER BY o.id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
            orders: list[dict[str, Any]] = []
            for order_row in order_rows:
                order_dict = _row_to_dict(order_row)
                item_rows = conn.execute(
                    """
                    SELECT product_id, product_name, unit_price, quantity, line_total
                    FROM order_items
                    WHERE order_id = ?
                    ORDER BY id ASC
                    """,
                    (order_dict["id"],),
                ).fetchall()
                order_dict["items"] = [_row_to_dict(item_row) for item_row in item_rows]
                orders.append(order_dict)
        return orders

    def update_order_status(self, order_id: int, status: str) -> dict[str, Any] | None:
        normalized = status.strip().lower()
        if normalized not in self.ALLOWED_ORDER_STATUSES:
            raise ValueError("Unsupported order status.")
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE orders SET status = ? WHERE id = ?",
                (normalized, order_id),
            )
            conn.commit()
        if cursor.rowcount <= 0:
            return None
        return self.get_order(order_id)
