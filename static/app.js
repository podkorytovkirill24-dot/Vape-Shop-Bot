const tg = window.Telegram?.WebApp ?? null;
const FALLBACK_IMAGE = "https://placehold.co/800x800/eaeef5/3a4257?text=OZON";

const state = {
  tab: "home",
  user: null,
  settings: null,
  products: [],
  favoriteIds: new Set(),
  cartItems: [],
  cartSummary: { items_total: 0, total_qty: 0, delivery_fee: 0, grand_total: 0 },
  orders: [],
  overlay: null,
  checkout: {
    step: 0,
    form: {
      full_name: "",
      phone: "",
      comment: "",
      street: "",
      house: "",
      entrance: "",
      apartment: "",
      payment_method: "cash",
    },
  },
  admin: {
    products: [],
    orders: [],
    settings: null,
    editProductId: null,
  },
};

const viewEl = document.getElementById("view");
const overlayRoot = document.getElementById("overlayRoot");
const toastEl = document.getElementById("toast");
const brandLogoEl = document.getElementById("brandLogo");
const brandNameEl = document.getElementById("brandName");

function resolveTelegramInitData() {
  if (tg?.initData && String(tg.initData).trim()) {
    return String(tg.initData);
  }
  const tryDecode = (value) => {
    let current = String(value || "");
    for (let i = 0; i < 2; i += 1) {
      if (!current.includes("%")) break;
      try {
        current = decodeURIComponent(current);
      } catch (error) {
        break;
      }
    }
    return current;
  };

  const readFrom = (raw) => {
    if (!raw) return "";
    const clean = String(raw).replace(/^[?#]/, "");
    const params = new URLSearchParams(clean);
    const value = params.get("tgWebAppData") || "";
    return value ? tryDecode(value) : "";
  };

  const fromHash = readFrom(window.location.hash || "");
  if (fromHash) return fromHash;

  const fromSearch = readFrom(window.location.search || "");
  if (fromSearch) return fromSearch;

  return "";
}

function escapeHtml(value) {
  const str = String(value ?? "");
  return str
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatMoney(amount) {
  const value = Number(amount || 0);
  const symbol = state.settings?.currency_symbol ?? "₸";
  return `${new Intl.NumberFormat("ru-RU").format(value)} ${symbol}`;
}

function orderStatusLabel(status) {
  const map = {
    new: "Новый",
    confirmed: "Подтвержден",
    delivering: "В доставке",
    done: "Завершен",
    cancelled: "Отменен",
  };
  return map[String(status || "").toLowerCase()] || "Неизвестно";
}

function showToast(message) {
  toastEl.textContent = message;
  toastEl.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toastEl.classList.remove("show"), 2200);
}

async function api(path, options = {}) {
  const headers = {};
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  const initData = resolveTelegramInitData();
  if (initData) {
    headers["X-Telegram-Init-Data"] = initData;
  } else {
    headers["X-Dev-User-Id"] = "777000";
  }

  const response = await fetch(`/api${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload?.detail || `API error ${response.status}`;
    throw new Error(detail);
  }
  return payload;
}

function setBrand() {
  const storeName = state.settings?.store_name || "OZON Oskemen";
  const logo = state.settings?.store_logo_url || FALLBACK_IMAGE;
  brandNameEl.textContent = storeName;
  brandLogoEl.src = logo;
  brandLogoEl.onerror = () => {
    brandLogoEl.onerror = null;
    brandLogoEl.src = FALLBACK_IMAGE;
  };
}

function setActiveTab(tab) {
  state.tab = tab;
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  renderMain();
}

function getProductById(productId) {
  return state.products.find((item) => Number(item.id) === Number(productId)) || null;
}

function getCartItem(productId) {
  return state.cartItems.find((item) => Number(item.product_id) === Number(productId)) || null;
}

function getCartQty(productId) {
  const item = getCartItem(productId);
  return item ? Number(item.quantity) : 0;
}

function productCard(item) {
  const isFav = state.favoriteIds.has(Number(item.id));
  return `
    <article class="product-card" data-action="open-product" data-id="${item.id}">
      <div class="product-thumb-wrap">
        <img class="product-thumb" src="${escapeHtml(item.image_url || FALLBACK_IMAGE)}" alt="${escapeHtml(item.name)}" loading="lazy" onerror="this.onerror=null;this.src='${FALLBACK_IMAGE}'" />
        <button class="fav-btn ${isFav ? "active" : ""}" data-action="toggle-favorite" data-id="${item.id}">
          ${isFav ? "♥" : "♡"}
        </button>
      </div>
      <div class="product-price">${formatMoney(item.price_kt)}</div>
      <div class="product-name">${escapeHtml(item.name)}</div>
    </article>
  `;
}

function renderHome() {
  if (!state.products.length) {
    return `
      <h1 class="section-title">Главная</h1>
      <section class="empty-box">
        <div class="empty-emoji">📦</div>
        <div class="empty-title">Каталог пуст</div>
        <div class="empty-text">Админ может добавить товары в админке раздела Профиль.</div>
      </section>
    `;
  }

  return `
    <h1 class="section-title">Главная</h1>
    <section class="products-grid">
      ${state.products.map((item) => productCard(item)).join("")}
    </section>
  `;
}

function renderFavorites() {
  const favorites = state.products.filter((item) => state.favoriteIds.has(Number(item.id)));
  if (!favorites.length) {
    return `
      <h1 class="section-title">Избранное</h1>
      <section class="empty-box">
        <div class="empty-emoji">🦆</div>
        <div class="empty-title">В избранном пусто</div>
        <div class="empty-text">Добавляйте понравившиеся товары, чтобы не потерять.</div>
        <div style="margin-top:14px;">
          <button class="btn-primary" data-action="go-tab" data-tab="home">Вернуться к покупкам</button>
        </div>
      </section>
    `;
  }
  return `
    <h1 class="section-title">Избранное</h1>
    <section class="products-grid">
      ${favorites.map((item) => productCard(item)).join("")}
    </section>
  `;
}

function renderCart() {
  if (!state.cartItems.length) {
    return `
      <h1 class="section-title">Корзина</h1>
      <section class="empty-box">
        <div class="empty-emoji">🦆</div>
        <div class="empty-title">В корзине пусто</div>
        <div class="empty-text">Посмотрите каталог и добавьте товары в корзину.</div>
        <div style="margin-top:14px;">
          <button class="btn-primary" data-action="go-tab" data-tab="home">Вернуться к покупкам</button>
        </div>
      </section>
    `;
  }

  return `
    <h1 class="section-title">Корзина</h1>
    <section class="cart-list">
      ${state.cartItems
        .map(
          (item) => `
        <article class="cart-item">
          <img src="${escapeHtml(item.image_url || FALLBACK_IMAGE)}" alt="${escapeHtml(item.name)}" onerror="this.onerror=null;this.src='${FALLBACK_IMAGE}'" />
          <div class="cart-main">
            <div class="cart-name">${escapeHtml(item.name)}</div>
            <div class="cart-price">${formatMoney(item.price_kt)}</div>
          </div>
          <div>
            <div class="stepper">
              <button data-action="cart-dec" data-id="${item.product_id}">−</button>
              <span>${item.quantity}</span>
              <button data-action="cart-inc" data-id="${item.product_id}">+</button>
            </div>
            <div class="cart-price" style="margin-top:8px;text-align:right;">${formatMoney(item.line_total)}</div>
          </div>
        </article>
      `
        )
        .join("")}
    </section>

    <section class="cart-summary">
      <input class="form-field" type="text" placeholder="Промокод (пока без логики)" disabled />
      <div class="summary-line"><span>Товары (${state.cartSummary.total_qty})</span><strong>${formatMoney(state.cartSummary.items_total)}</strong></div>
      <div class="summary-line"><span>Доставка</span><strong>${formatMoney(state.cartSummary.delivery_fee)}</strong></div>
      <div class="summary-total"><span>Итого</span><span>${formatMoney(state.cartSummary.grand_total)}</span></div>
      <div style="margin-top:12px;display:flex;gap:8px;">
        <button class="btn-ghost" data-action="cart-clear">Очистить</button>
        <button class="btn-primary" data-action="checkout-open">Перейти к оформлению</button>
      </div>
    </section>
  `;
}

function renderProfile() {
  const name = state.user?.first_name || "User";
  const initials = name.charAt(0).toUpperCase();
  const support = escapeHtml(state.settings?.support_contact || "@support");
  return `
    <h1 class="section-title">Профиль</h1>

    <section class="profile-card">
      <div class="profile-head">
        <div class="profile-avatar">${escapeHtml(initials)}</div>
        <div>
          <div class="profile-name">${escapeHtml(name)}</div>
          <div class="muted">@${escapeHtml(state.user?.username || "username")}</div>
        </div>
      </div>
      <div class="profile-actions">
        <button class="list-btn" data-action="open-history">История заказов</button>
        <button class="list-btn" data-action="open-language">Язык: ${escapeHtml((state.user?.language || "ru").toUpperCase())}</button>
        <button class="list-btn" data-action="open-support">Связаться с поддержкой (${support})</button>
      </div>
    </section>

    <section class="profile-card">
      <button class="btn-ghost" data-action="add-home">Добавить на Главный Экран</button>
      <div class="muted" style="margin-top:10px;">
        Добавьте ярлык магазина на главный экран смартфона, чтобы всегда быстро открывать Mini App.
      </div>
    </section>

    ${
      state.user?.is_admin
        ? `
      <section class="profile-card">
        <div class="pill">Администратор</div>
        <div style="margin-top:10px;">
          <button class="btn-primary" data-action="open-admin">Открыть админку</button>
        </div>
      </section>
    `
        : ""
    }
  `;
}

function renderMain() {
  if (!state.settings) {
    viewEl.innerHTML = `<section class="empty-box"><div class="empty-title">Загрузка...</div></section>`;
    return;
  }

  if (state.tab === "home") {
    viewEl.innerHTML = renderHome();
  } else if (state.tab === "favorites") {
    viewEl.innerHTML = renderFavorites();
  } else if (state.tab === "cart") {
    viewEl.innerHTML = renderCart();
  } else {
    viewEl.innerHTML = renderProfile();
  }
}

function openOverlay(type, payload = {}) {
  state.overlay = { type, payload };
  renderOverlay();
}

function closeOverlay() {
  state.overlay = null;
  overlayRoot.innerHTML = "";
}

function checkoutProgress(step) {
  return `
    <div class="checkout-steps">
      <div class="checkout-step ${step >= 0 ? "active" : ""}"></div>
      <div class="checkout-step ${step >= 1 ? "active" : ""}"></div>
      <div class="checkout-step ${step >= 2 ? "active" : ""}"></div>
    </div>
  `;
}

function checkoutStepContent() {
  const step = state.checkout.step;
  const form = state.checkout.form;

  if (step === 0) {
    return `
      ${checkoutProgress(step)}
      <h2 class="sheet-title">Контактная информация</h2>
      <div class="subtitle">Заполните данные для доставки по Усть-Каменогорску.</div>
      <div style="margin-top:12px;">
        <input id="co_full_name" class="form-field" type="text" placeholder="Имя" value="${escapeHtml(form.full_name)}" />
        <input id="co_phone" class="form-field" type="tel" placeholder="Телефон" value="${escapeHtml(form.phone)}" />
        <input id="co_street" class="form-field" type="text" placeholder="Улица" value="${escapeHtml(form.street)}" />
        <input id="co_house" class="form-field" type="text" placeholder="Дом" value="${escapeHtml(form.house)}" />
        <div class="row">
          <input id="co_entrance" class="form-field" type="text" placeholder="Подъезд" value="${escapeHtml(form.entrance)}" />
          <input id="co_apartment" class="form-field" type="text" placeholder="Квартира" value="${escapeHtml(form.apartment)}" />
        </div>
        <textarea id="co_comment" class="form-field" rows="3" placeholder="Комментарий к заказу">${escapeHtml(form.comment)}</textarea>
      </div>
      <button class="btn-primary" data-action="checkout-next">Выбрать способ доставки</button>
    `;
  }

  if (step === 1) {
    return `
      ${checkoutProgress(step)}
      <h2 class="sheet-title">Информация о доставке</h2>
      <section class="profile-card">
        <div style="font-size:1.2rem;font-weight:800;">${escapeHtml(state.settings.city_name)}</div>
        <div class="muted" style="margin-top:6px;">${escapeHtml(state.settings.delivery_note)}</div>
        <div style="margin-top:10px;font-weight:800;">от ${formatMoney(state.settings.delivery_fee)}</div>
      </section>
      <div class="row">
        <button class="btn-ghost" data-action="checkout-prev">Назад</button>
        <button class="btn-primary" data-action="checkout-next">Дальше</button>
      </div>
    `;
  }

  return `
    ${checkoutProgress(step)}
    <h2 class="sheet-title">Информация об оплате</h2>
    <section class="profile-card">
      <label style="display:flex;align-items:center;gap:10px;font-weight:700;">
        <input type="radio" checked disabled />
        Оплата наличными
      </label>
    </section>

    <section class="profile-card">
      <div class="summary-line"><span>Товары (${state.cartSummary.total_qty})</span><strong>${formatMoney(state.cartSummary.items_total)}</strong></div>
      <div class="summary-line"><span>Доставка</span><strong>${formatMoney(state.cartSummary.delivery_fee)}</strong></div>
      <div class="summary-total"><span>Итого</span><span>${formatMoney(state.cartSummary.grand_total)}</span></div>
    </section>

    <div class="row">
      <button class="btn-ghost" data-action="checkout-prev">Назад</button>
      <button class="btn-primary" data-action="checkout-submit">Оформить заказ</button>
    </div>
  `;
}

function renderHistoryOverlay() {
  const orders = state.orders || [];
  const body =
    orders.length === 0
      ? `<section class="empty-box"><div class="empty-emoji">🧾</div><div class="empty-title">Заказов пока нет</div></section>`
      : orders
          .map(
            (order) => `
        <section class="admin-row">
          <div class="admin-row-head">
            <strong>Заказ #${order.id}</strong>
            <span class="admin-price">${formatMoney(order.grand_total)}</span>
          </div>
          <div class="muted">${escapeHtml(order.created_at)}</div>
          <div class="muted" style="margin-top:6px;">${escapeHtml(order.street)}, дом ${escapeHtml(order.house)}</div>
          <div style="margin-top:8px;">
            ${order.items
              .map(
                (item) =>
                  `<div class="muted">• ${escapeHtml(item.product_name)} x${item.quantity} = ${formatMoney(item.line_total)}</div>`
              )
              .join("")}
          </div>
        </section>
      `
          )
          .join("");

  return `
    <div class="overlay">
      <section class="sheet">
        <div class="sheet-head">
          <div class="sheet-title">История заказов</div>
          <button class="close-btn" data-action="overlay-close">×</button>
        </div>
        ${body}
      </section>
    </div>
  `;
}

function renderLanguageOverlay() {
  const current = state.user?.language || "ru";
  return `
    <div class="overlay">
      <section class="sheet">
        <div class="sheet-head">
          <div class="sheet-title">Выбор языка</div>
          <button class="close-btn" data-action="overlay-close">×</button>
        </div>
        <div class="admin-actions">
          <button class="small-btn ${current === "ru" ? "active" : ""}" data-action="set-language" data-lang="ru">Русский</button>
          <button class="small-btn ${current === "kz" ? "active" : ""}" data-action="set-language" data-lang="kz">Қазақша</button>
          <button class="small-btn ${current === "en" ? "active" : ""}" data-action="set-language" data-lang="en">English</button>
        </div>
      </section>
    </div>
  `;
}

function adminProductFormValues() {
  const get = (id) => document.getElementById(id);
  return {
    id: Number(get("ad_id").value || 0),
    name: get("ad_name").value.trim(),
    description: get("ad_desc").value.trim(),
    price_kt: Number(get("ad_price").value || 0),
    image_url: get("ad_image").value.trim(),
    stock: Number(get("ad_stock").value || 0),
    category: get("ad_category").value.trim(),
    is_active: get("ad_active").checked ? 1 : 0,
  };
}

function renderAdminOverlay() {
  const settings = state.admin.settings || state.settings;
  const editProduct =
    state.admin.editProductId != null
      ? state.admin.products.find((item) => Number(item.id) === Number(state.admin.editProductId))
      : null;
  const form = editProduct || {
    id: 0,
    name: "",
    description: "",
    price_kt: 0,
    image_url: "",
    stock: 0,
    category: "",
    is_active: 1,
  };

  return `
    <div class="overlay">
      <section class="page-modal">
        <div class="sheet-head">
          <div class="sheet-title">Админка</div>
          <button class="close-btn" data-action="overlay-close">×</button>
        </div>

        <section class="profile-card">
          <div style="font-weight:800;font-size:1.1rem;">Товар ${form.id ? `#${form.id}` : "(новый)"}</div>
          <input id="ad_id" type="hidden" value="${form.id}" />
          <input id="ad_name" class="form-field" placeholder="Название товара" value="${escapeHtml(form.name)}" />
          <textarea id="ad_desc" class="form-field" rows="3" placeholder="Описание">${escapeHtml(form.description)}</textarea>
          <input id="ad_price" class="form-field" type="number" min="0" placeholder="Цена (₸)" value="${form.price_kt}" />
          <input id="ad_image" class="form-field" placeholder="URL фото" value="${escapeHtml(form.image_url)}" />
          <div class="row">
            <input id="ad_stock" class="form-field" type="number" min="0" placeholder="Остаток" value="${form.stock}" />
            <input id="ad_category" class="form-field" placeholder="Категория" value="${escapeHtml(form.category)}" />
          </div>
          <label class="muted" style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
            <input id="ad_active" type="checkbox" ${form.is_active ? "checked" : ""} />
            Товар активен
          </label>
          <div class="row">
            <button class="btn-ghost" data-action="admin-new-product">Очистить форму</button>
            <button class="btn-primary" data-action="admin-save-product">${form.id ? "Сохранить" : "Добавить"}</button>
          </div>
        </section>

        <section class="profile-card">
          <div style="font-weight:800;font-size:1.1rem;">Настройки магазина</div>
          <input id="st_store_name" class="form-field" value="${escapeHtml(settings.store_name || "")}" placeholder="Название магазина" />
          <input id="st_store_logo_url" class="form-field" value="${escapeHtml(settings.store_logo_url || "")}" placeholder="URL логотипа" />
          <input id="st_city_name" class="form-field" value="${escapeHtml(settings.city_name || "")}" placeholder="Город доставки" />
          <input id="st_delivery_fee" class="form-field" type="number" min="0" value="${Number(settings.delivery_fee || 0)}" placeholder="Стоимость доставки" />
          <input id="st_support_contact" class="form-field" value="${escapeHtml(settings.support_contact || "")}" placeholder="Контакт поддержки (@username/URL)" />
          <textarea id="st_delivery_note" class="form-field" rows="2" placeholder="Описание доставки">${escapeHtml(settings.delivery_note || "")}</textarea>
          <button class="btn-primary" data-action="admin-save-settings">Сохранить настройки</button>
        </section>

        <section class="profile-card">
          <div style="font-weight:800;font-size:1.1rem;">Список товаров</div>
          <div class="admin-list">
            ${
              state.admin.products.length
                ? state.admin.products
                    .map(
                      (item) => `
                <article class="admin-row">
                  <div class="admin-row-head">
                    <div>
                      <strong>${escapeHtml(item.name)}</strong>
                      <div class="muted">Остаток: ${item.stock} • ${escapeHtml(item.category || "без категории")}</div>
                    </div>
                    <div class="admin-price">${formatMoney(item.price_kt)}</div>
                  </div>
                  <div class="admin-actions">
                    <button class="small-btn" data-action="admin-edit-product" data-id="${item.id}">Редактировать</button>
                    <button class="small-btn danger" data-action="admin-disable-product" data-id="${item.id}">Отключить</button>
                    <span class="muted">${item.is_active ? "Активен" : "Скрыт"}</span>
                  </div>
                </article>
              `
                    )
                    .join("")
                : `<div class="muted">Товаров пока нет.</div>`
            }
          </div>
        </section>
      </section>
    </div>
  `;
}

function buildAdminOrdersSection() {
  const orders = state.admin.orders || [];
  if (!orders.length) {
    return `
      <section class="profile-card" data-admin-orders>
        <div class="admin-row-head">
          <div style="font-weight:800;font-size:1.1rem;">Заказы</div>
          <button class="small-btn" data-action="admin-refresh-orders">Обновить</button>
        </div>
        <div class="admin-list">
          <div class="muted">Заказов пока нет.</div>
        </div>
      </section>
    `;
  }

  return `
    <section class="profile-card" data-admin-orders>
      <div class="admin-row-head">
        <div style="font-weight:800;font-size:1.1rem;">Заказы</div>
        <button class="small-btn" data-action="admin-refresh-orders">Обновить</button>
      </div>
      <div class="admin-list">
        ${orders
          .map(
            (order) => `
          <article class="admin-row">
            <div class="admin-row-head">
              <div>
                <strong>Заказ #${order.id}</strong>
                <div class="muted">${escapeHtml(order.full_name)} • ${escapeHtml(order.phone)}</div>
                <div class="muted">${escapeHtml(order.street)}, дом ${escapeHtml(order.house)}</div>
              </div>
              <div class="admin-price">${formatMoney(order.grand_total)}</div>
            </div>
            <div class="muted" style="margin-top:6px;">Статус: ${orderStatusLabel(order.status)}</div>
            <div class="admin-actions">
              <button class="small-btn" data-action="admin-set-order-status" data-id="${order.id}" data-status="confirmed">Подтвердить</button>
              <button class="small-btn" data-action="admin-set-order-status" data-id="${order.id}" data-status="delivering">В доставку</button>
              <button class="small-btn" data-action="admin-set-order-status" data-id="${order.id}" data-status="done">Готово</button>
              <button class="small-btn danger" data-action="admin-set-order-status" data-id="${order.id}" data-status="cancelled">Отменить</button>
            </div>
          </article>
        `
          )
          .join("")}
      </div>
    </section>
  `;
}

function injectAdminOrdersSection() {
  const modal = overlayRoot.querySelector(".page-modal");
  if (!modal) return;
  const current = modal.querySelector("[data-admin-orders]");
  if (current) {
    current.remove();
  }
  modal.insertAdjacentHTML("beforeend", buildAdminOrdersSection());
}

function renderProductOverlay(productId) {
  const product = getProductById(productId);
  if (!product) return "";
  const qty = getCartQty(product.id);
  const addArea =
    qty > 0
      ? `
      <div class="row">
        <div class="stepper">
          <button data-action="product-dec" data-id="${product.id}">−</button>
          <span>${qty}</span>
          <button data-action="product-inc" data-id="${product.id}">+</button>
        </div>
        <button class="btn-primary" data-action="go-tab" data-tab="cart">Перейти в корзину</button>
      </div>
    `
      : `<button class="btn-primary" data-action="product-add" data-id="${product.id}">Добавить в корзину</button>`;

  return `
    <div class="overlay">
      <section class="sheet">
        <div class="sheet-head">
          <div class="sheet-title">Товар</div>
          <button class="close-btn" data-action="overlay-close">×</button>
        </div>
        <img class="product-detail-image" src="${escapeHtml(product.image_url || FALLBACK_IMAGE)}" alt="${escapeHtml(product.name)}" onerror="this.onerror=null;this.src='${FALLBACK_IMAGE}'" />
        <h2>${escapeHtml(product.name)}</h2>
        <div style="font-size:2rem;font-weight:800;">${formatMoney(product.price_kt)}</div>
        <div class="subtitle">${escapeHtml(product.description || "Описание товара")}</div>
        <div style="margin-top:12px;">${addArea}</div>
      </section>
    </div>
  `;
}

function renderCheckoutOverlay() {
  return `
    <div class="overlay">
      <section class="page-modal">
        <div class="sheet-head">
          <div class="sheet-title">Оформление заказа</div>
          <button class="close-btn" data-action="overlay-close">×</button>
        </div>
        ${checkoutStepContent()}
      </section>
    </div>
  `;
}

function renderOverlay() {
  if (!state.overlay) {
    overlayRoot.innerHTML = "";
    return;
  }

  if (state.overlay.type === "product") {
    overlayRoot.innerHTML = renderProductOverlay(state.overlay.payload.productId);
    return;
  }
  if (state.overlay.type === "checkout") {
    overlayRoot.innerHTML = renderCheckoutOverlay();
    return;
  }
  if (state.overlay.type === "history") {
    overlayRoot.innerHTML = renderHistoryOverlay();
    return;
  }
  if (state.overlay.type === "language") {
    overlayRoot.innerHTML = renderLanguageOverlay();
    return;
  }
  if (state.overlay.type === "admin") {
    overlayRoot.innerHTML = renderAdminOverlay();
    injectAdminOrdersSection();
    return;
  }

  overlayRoot.innerHTML = "";
}

async function refreshBootstrap() {
  const data = await api("/bootstrap");
  state.user = data.user;
  state.settings = data.settings;
  state.products = data.products;
  state.favoriteIds = new Set((data.favorite_ids || []).map(Number));
  state.cartItems = data.cart?.items || [];
  state.cartSummary = data.cart?.summary || { items_total: 0, total_qty: 0, delivery_fee: 0, grand_total: 0 };
  state.orders = data.orders || [];
  setBrand();
  renderMain();
}

function syncCart(payload) {
  state.cartItems = payload.items || [];
  state.cartSummary = payload.summary || { items_total: 0, total_qty: 0, delivery_fee: 0, grand_total: 0 };
}

async function updateCartQuantity(productId, quantity) {
  try {
    const payload = await api(`/cart/${productId}`, { method: "PUT", body: { quantity } });
    syncCart(payload);
    renderMain();
    if (state.overlay?.type === "product") {
      renderOverlay();
    }
  } catch (error) {
    showToast(error.message);
  }
}

async function toggleFavorite(productId) {
  try {
    const payload = await api(`/favorites/${productId}/toggle`, { method: "POST" });
    state.favoriteIds = new Set((payload.ids || []).map(Number));
    renderMain();
    if (state.overlay?.type === "product") {
      renderOverlay();
    }
  } catch (error) {
    showToast(error.message);
  }
}

function readCheckoutStep0() {
  const values = {
    full_name: (document.getElementById("co_full_name")?.value || "").trim(),
    phone: (document.getElementById("co_phone")?.value || "").trim(),
    street: (document.getElementById("co_street")?.value || "").trim(),
    house: (document.getElementById("co_house")?.value || "").trim(),
    entrance: (document.getElementById("co_entrance")?.value || "").trim(),
    apartment: (document.getElementById("co_apartment")?.value || "").trim(),
    comment: (document.getElementById("co_comment")?.value || "").trim(),
  };
  const required = ["full_name", "phone", "street", "house"];
  for (const key of required) {
    if (!values[key]) {
      showToast("Заполните обязательные поля.");
      return null;
    }
  }
  return values;
}

async function submitOrder() {
  try {
    const payload = {
      ...state.checkout.form,
      payment_method: "cash",
    };
    const res = await api("/orders", { method: "POST", body: payload });
    showToast(`Заказ #${res.item.id} оформлен`);
    state.checkout.step = 0;
    closeOverlay();
    await refreshBootstrap();
    setActiveTab("profile");
  } catch (error) {
    showToast(error.message);
  }
}

async function loadAdminData() {
  const [productsRes, settingsRes, ordersRes] = await Promise.all([
    api("/admin/products"),
    api("/admin/settings"),
    api("/admin/orders"),
  ]);
  state.admin.products = productsRes.items || [];
  state.admin.settings = settingsRes.settings || state.settings;
  state.admin.orders = ordersRes.items || [];
}

async function saveAdminProduct() {
  const values = adminProductFormValues();
  if (!Number.isFinite(values.price_kt) || values.price_kt < 0) {
    showToast("Введите корректную цену.");
    return;
  }
  if (!Number.isFinite(values.stock) || values.stock < 0) {
    showToast("Введите корректный остаток.");
    return;
  }
  if (!values.name) {
    showToast("Название товара обязательно.");
    return;
  }
  const payload = {
    name: values.name,
    description: values.description,
    price_kt: values.price_kt,
    image_url: values.image_url,
    stock: values.stock,
    category: values.category,
    is_active: values.is_active,
  };
  try {
    if (values.id > 0) {
      await api(`/admin/products/${values.id}`, { method: "PUT", body: payload });
      showToast("Товар обновлен.");
    } else {
      await api("/admin/products", { method: "POST", body: payload });
      showToast("Товар добавлен.");
    }
    state.admin.editProductId = null;
    await loadAdminData();
    await refreshBootstrap();
    renderOverlay();
  } catch (error) {
    showToast(error.message);
  }
}

async function saveAdminSettings() {
  const deliveryFee = Number(document.getElementById("st_delivery_fee")?.value || 0);
  if (!Number.isFinite(deliveryFee) || deliveryFee < 0) {
    showToast("Стоимость доставки должна быть 0 или больше.");
    return;
  }
  const payload = {
    store_name: (document.getElementById("st_store_name")?.value || "").trim(),
    store_logo_url: (document.getElementById("st_store_logo_url")?.value || "").trim(),
    city_name: (document.getElementById("st_city_name")?.value || "").trim(),
    delivery_fee: deliveryFee,
    support_contact: (document.getElementById("st_support_contact")?.value || "").trim(),
    delivery_note: (document.getElementById("st_delivery_note")?.value || "").trim(),
  };
  try {
    const res = await api("/admin/settings", { method: "PUT", body: payload });
    state.admin.settings = res.settings;
    state.settings = res.settings;
    setBrand();
    renderMain();
    renderOverlay();
    showToast("Настройки сохранены.");
  } catch (error) {
    showToast(error.message);
  }
}

async function adminUpdateOrderStatus(orderId, status) {
  try {
    await api(`/admin/orders/${orderId}/status`, { method: "PUT", body: { status } });
    await loadAdminData();
    await refreshBootstrap();
    renderOverlay();
    showToast("Статус заказа обновлен.");
  } catch (error) {
    showToast(error.message);
  }
}

function openSupport() {
  const raw = String(state.settings?.support_contact || "").trim();
  if (!raw) {
    showToast("Контакт поддержки не настроен.");
    return;
  }
  let url = raw;
  if (raw.startsWith("@")) {
    url = `https://t.me/${raw.slice(1)}`;
  } else if (!raw.startsWith("http://") && !raw.startsWith("https://")) {
    url = `https://t.me/${raw}`;
  }
  if (tg?.openTelegramLink && url.includes("t.me/")) {
    tg.openTelegramLink(url);
    return;
  }
  if (tg?.openLink) {
    tg.openLink(url);
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

async function onActionClick(action, target) {
  if (action === "go-tab") {
    const tab = target.dataset.tab;
    if (state.overlay) {
      closeOverlay();
    }
    if (tab) setActiveTab(tab);
    return;
  }
  if (action === "open-product") {
    const id = Number(target.dataset.id);
    if (id) openOverlay("product", { productId: id });
    return;
  }
  if (action === "overlay-close") {
    closeOverlay();
    return;
  }
  if (action === "toggle-favorite") {
    const id = Number(target.dataset.id);
    if (id) await toggleFavorite(id);
    return;
  }
  if (action === "cart-inc") {
    const id = Number(target.dataset.id);
    const product = getProductById(id);
    if (!product) return;
    const next = getCartQty(id) + 1;
    if (next > Number(product.stock)) {
      showToast("Больше добавить нельзя, лимит остатка.");
      return;
    }
    await updateCartQuantity(id, next);
    return;
  }
  if (action === "cart-dec") {
    const id = Number(target.dataset.id);
    const next = Math.max(0, getCartQty(id) - 1);
    await updateCartQuantity(id, next);
    return;
  }
  if (action === "cart-clear") {
    try {
      const res = await api("/cart", { method: "DELETE" });
      syncCart(res);
      renderMain();
      showToast("Корзина очищена.");
    } catch (error) {
      showToast(error.message);
    }
    return;
  }
  if (action === "checkout-open") {
    state.checkout.step = 0;
    openOverlay("checkout");
    return;
  }
  if (action === "checkout-next") {
    if (state.checkout.step === 0) {
      const values = readCheckoutStep0();
      if (!values) return;
      state.checkout.form = { ...state.checkout.form, ...values };
      state.checkout.step = 1;
      renderOverlay();
      return;
    }
    if (state.checkout.step === 1) {
      state.checkout.step = 2;
      renderOverlay();
      return;
    }
  }
  if (action === "checkout-prev") {
    state.checkout.step = Math.max(0, state.checkout.step - 1);
    renderOverlay();
    return;
  }
  if (action === "checkout-submit") {
    await submitOrder();
    return;
  }
  if (action === "product-add") {
    const id = Number(target.dataset.id);
    await updateCartQuantity(id, 1);
    showToast("Товар добавлен в корзину.");
    return;
  }
  if (action === "product-inc") {
    const id = Number(target.dataset.id);
    const product = getProductById(id);
    const next = getCartQty(id) + 1;
    if (next > Number(product?.stock || 0)) {
      showToast("Недостаточно остатка.");
      return;
    }
    await updateCartQuantity(id, next);
    return;
  }
  if (action === "product-dec") {
    const id = Number(target.dataset.id);
    const next = Math.max(0, getCartQty(id) - 1);
    await updateCartQuantity(id, next);
    return;
  }
  if (action === "open-history") {
    openOverlay("history");
    return;
  }
  if (action === "open-language") {
    openOverlay("language");
    return;
  }
  if (action === "set-language") {
    const lang = target.dataset.lang;
    try {
      const res = await api("/profile/language", { method: "PUT", body: { language: lang } });
      state.user.language = res.user.language;
      renderMain();
      renderOverlay();
      showToast("Язык сохранен.");
    } catch (error) {
      showToast(error.message);
    }
    return;
  }
  if (action === "open-support") {
    openSupport();
    return;
  }
  if (action === "add-home") {
    showToast("Добавьте через меню Telegram: «⋯ -> Добавить на главный экран».");
    return;
  }
  if (action === "open-admin") {
    try {
      await loadAdminData();
      openOverlay("admin");
    } catch (error) {
      showToast(error.message);
    }
    return;
  }
  if (action === "admin-new-product") {
    state.admin.editProductId = null;
    renderOverlay();
    return;
  }
  if (action === "admin-edit-product") {
    state.admin.editProductId = Number(target.dataset.id);
    renderOverlay();
    return;
  }
  if (action === "admin-disable-product") {
    const id = Number(target.dataset.id);
    if (!Number.isFinite(id) || id <= 0) return;
    if (!window.confirm("Отключить товар?")) return;
    try {
      await api(`/admin/products/${id}`, { method: "DELETE" });
      await loadAdminData();
      await refreshBootstrap();
      renderOverlay();
      showToast("Товар отключен.");
    } catch (error) {
      showToast(error.message);
    }
    return;
  }
  if (action === "admin-save-product") {
    await saveAdminProduct();
    return;
  }
  if (action === "admin-refresh-orders") {
    try {
      await loadAdminData();
      renderOverlay();
      showToast("Список заказов обновлен.");
    } catch (error) {
      showToast(error.message);
    }
    return;
  }
  if (action === "admin-set-order-status") {
    const orderId = Number(target.dataset.id);
    const status = String(target.dataset.status || "");
    if (!Number.isFinite(orderId) || orderId <= 0 || !status) return;
    await adminUpdateOrderStatus(orderId, status);
    return;
  }
  if (action === "admin-save-settings") {
    await saveAdminSettings();
    return;
  }
}

function bindGlobalEvents() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => setActiveTab(btn.dataset.tab));
  });

  document.getElementById("backBtn").addEventListener("click", () => {
    if (state.overlay) {
      closeOverlay();
      return;
    }
    if (state.tab !== "home") {
      setActiveTab("home");
      return;
    }
    if (tg?.close) tg.close();
  });

  document.getElementById("moreBtn").addEventListener("click", () => setActiveTab("profile"));

  document.addEventListener("click", async (event) => {
    const target = event.target.closest("[data-action]");
    if (!target) return;
    event.preventDefault();
    event.stopPropagation();
    const action = target.dataset.action;
    if (!action) return;
    await onActionClick(action, target);
  });
}

async function bootstrap() {
  if (tg) {
    tg.ready();
    tg.expand();
    tg.setHeaderColor?.("#1b2130");
    tg.setBackgroundColor?.("#10131a");
  }

  bindGlobalEvents();
  try {
    await refreshBootstrap();
    setActiveTab("home");
  } catch (error) {
    viewEl.innerHTML = `
      <section class="empty-box">
        <div class="empty-title">Ошибка загрузки</div>
        <div class="empty-text">${escapeHtml(error.message)}</div>
        <div style="margin-top:12px;"><button class="btn-primary" data-action="reload-app">Обновить</button></div>
      </section>
    `;
    document.querySelector('[data-action="reload-app"]')?.addEventListener("click", () => window.location.reload());
  }
}

bootstrap();
