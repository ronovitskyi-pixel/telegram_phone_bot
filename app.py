import logging
import os
import sqlite3
import threading
import asyncio
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)

# ------------------------- Flask Health Check -------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "Бот працює!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ------------------------- Configuration -------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN environment variable not set!")

ADMIN_IDS = [5424647855]  # Replace with your actual Telegram user ID(s)

ADD_NAME, ADD_DESCRIPTION, ADD_PRICE, ADD_IMAGE = range(4)
ORDER_NAME, ORDER_HOMECLASS, ORDER_CABINET, ORDER_CLASSES = range(10, 14)
EDIT_PRICE = 20

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ------------------------- Database -------------------------
DB_PATH = "phones.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS phones
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  description TEXT,
                  image_file_id TEXT,
                  price REAL,
                  in_stock INTEGER DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS orders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  full_name TEXT,
                  homeclass TEXT,
                  cabinet INTEGER,
                  classes INTEGER,
                  phone_id INTEGER,
                  status TEXT DEFAULT 'new',
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  full_name TEXT,
                  homeclass TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY, value TEXT)''')
    conn.commit()
    conn.close()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def get_available_phones():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, description, image_file_id, price FROM phones WHERE in_stock=1 ORDER BY id")
    phones = c.fetchall()
    conn.close()
    return phones

def get_all_phones():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, description, image_file_id, price, in_stock FROM phones ORDER BY id")
    phones = c.fetchall()
    conn.close()
    return phones

def add_phone_to_db(name, desc, price, image_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO phones (name, description, price, image_file_id, in_stock) VALUES (?,?,?,?,1)",
              (name, desc, price, image_id))
    conn.commit()
    conn.close()

def delete_phone(phone_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM phones WHERE id=?", (phone_id,))
    conn.commit()
    conn.close()

def update_stock(phone_id, in_stock):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE phones SET in_stock=? WHERE id=?", (in_stock, phone_id))
    conn.commit()
    conn.close()

def update_price(phone_id, price):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE phones SET price=? WHERE id=?", (price, phone_id))
    conn.commit()
    conn.close()

def get_phone(phone_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name, description, image_file_id, price, in_stock FROM phones WHERE id=?", (phone_id,))
    row = c.fetchone()
    conn.close()
    return row

def add_order(user_id, full_name, homeclass, cabinet, classes, phone_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO orders (user_id, full_name, homeclass, cabinet, classes, phone_id) VALUES (?,?,?,?,?,?)",
              (user_id, full_name, homeclass, cabinet, classes, phone_id))
    order_id = c.lastrowid
    conn.commit()
    conn.close()
    save_user_profile(user_id, full_name, homeclass)
    return order_id

def get_orders(limit=20):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT o.id, o.full_name, o.homeclass, o.cabinet, o.classes, p.name, o.status, o.created_at
                 FROM orders o JOIN phones p ON o.phone_id = p.id
                 ORDER BY o.created_at DESC LIMIT ?""", (limit,))
    orders = c.fetchall()
    conn.close()
    return orders

def get_user_orders(user_id, limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT o.id, o.full_name, o.homeclass, o.cabinet, o.classes, p.name, o.status, o.created_at
                 FROM orders o JOIN phones p ON o.phone_id = p.id
                 WHERE o.user_id = ?
                 ORDER BY o.created_at DESC LIMIT ?""", (user_id, limit))
    orders = c.fetchall()
    conn.close()
    return orders

def save_user_profile(user_id, full_name, homeclass):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, full_name, homeclass) VALUES (?,?,?)",
              (user_id, full_name, homeclass))
    conn.commit()
    conn.close()

def get_user_profile(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT full_name, homeclass FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def get_group_id():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='group_id'")
    row = c.fetchone()
    conn.close()
    return int(row[0]) if row else None

def set_group_id(group_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('group_id', ?)", (str(group_id),))
    conn.commit()
    conn.close()

# ------------------------- Notification Function -------------------------
async def notify_order(context: ContextTypes.DEFAULT_TYPE, order_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT o.full_name, o.homeclass, o.cabinet, o.classes, p.name, p.image_file_id, o.user_id
                 FROM orders o JOIN phones p ON o.phone_id = p.id
                 WHERE o.id = ?""", (order_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return
    full_name, homeclass, cabinet, classes, phone_name, image_id, user_id = row
    caption = (
        f"🛒 *Нове замовлення!*\n"
        f"👤 ПІБ: {full_name}\n"
        f"🏫 Клас: {homeclass}\n"
        f"🚪 Кабінет: {cabinet}\n"
        f"📚 Кількість уроків: {classes}\n"
        f"📱 Телефон: {phone_name}\n"
        f"🆔 ID користувача: `{user_id}`"
    )

    # 1. Send to group (if set)
    group_id = get_group_id()
    if group_id:
        try:
            if image_id:
                await context.bot.send_photo(chat_id=group_id, photo=image_id, caption=caption, parse_mode="Markdown")
            else:
                await context.bot.send_message(chat_id=group_id, text=caption, parse_mode="Markdown")
            logger.info(f"✅ Order notification sent to group {group_id}")
        except Exception as e:
            logger.error(f"❌ Failed to send to group {group_id}: {e}")

    # 2. Send to each admin DM (only if they have started the bot)
    for admin_id in ADMIN_IDS:
        try:
            if image_id:
                await context.bot.send_photo(chat_id=admin_id, photo=image_id, caption=caption, parse_mode="Markdown")
            else:
                await context.bot.send_message(chat_id=admin_id, text=caption, parse_mode="Markdown")
            logger.info(f"✅ Order notification sent to admin {admin_id}")
        except Exception as e:
            logger.warning(f"⚠️ Could not DM admin {admin_id}: {e} (Have they /start'ed the bot?)")

# ------------------------- Homeclass Buttons -------------------------
def homeclass_keyboard(selected=None):
    classes = [5,6,7,8,9,10,11]
    letters = ['А','Б','В','Г']
    keyboard = []
    row = []
    for cl in classes:
        for let in letters:
            hc = f"{cl}-{let}"
            text = f"✅ {hc}" if hc == selected else hc
            row.append(InlineKeyboardButton(text, callback_data=f"homeclass_{hc}"))
            if len(row) == 4:
                keyboard.append(row)
                row = []
    if row:
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

# ------------------------- Command Handlers -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name or "користувач"
    welcome_text = (
        f"👋 Вітаю, *{user_name}*!\n\n"
        f"Це бот для замовлення телефонів.\n"
        f"Оберіть дію:"
    )
    keyboard = [
        [InlineKeyboardButton("📱 Перейти до меню", callback_data="goto_menu")],
        [InlineKeyboardButton("👤 Мій акаунт", callback_data="account")],
        [InlineKeyboardButton("📦 Мої замовлення", callback_data="my_orders")],
        [InlineKeyboardButton("❓ Допомога", callback_data="help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "❓ *Допомога*\n\n"
        "• /start – Головне меню\n"
        "• /menu – Каталог телефонів\n"
        "• /help – Це повідомлення\n\n"
        "🛒 *Як замовити:*\n"
        "1. Перейдіть до меню\n"
        "2. Виберіть телефон\n"
        "3. Натисніть «Замовити»\n"
        "4. Введіть ПІБ, клас, кабінет, кількість уроків\n\n"
        "📦 Замовлення надсилаються адміністратору."
    )
    message = update.effective_message
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")]]
    await message.reply_text(help_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def set_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ У вас немає прав адміністратора.")
        return
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        await update.message.reply_text("❌ Цю команду потрібно виконати в групі, куди додано бота.")
        return
    set_group_id(chat_id)
    await update.message.reply_text(f"✅ Групу встановлено! Chat ID: `{chat_id}`\nЗамовлення будуть надсилатися сюди.")

async def test_notify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ У вас немає прав адміністратора.")
        return
    try:
        await context.bot.send_message(chat_id=user_id, text="✅ Тестове сповіщення. Якщо ви бачите це, DM працюють.")
    except Exception as e:
        await update.message.reply_text(f"❌ Не вдалося надіслати DM: {e}")
        return
    group_id = get_group_id()
    if group_id:
        try:
            await context.bot.send_message(chat_id=group_id, text="✅ Тестове сповіщення в групу.")
            await update.message.reply_text("✅ Тестове сповіщення надіслано в групу.")
        except Exception as e:
            await update.message.reply_text(f"❌ Не вдалося надіслати в групу: {e}")
    else:
        await update.message.reply_text("ℹ️ Групу ще не встановлено. Використайте /setgroup у групі.")

async def new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            group_id = update.effective_chat.id
            set_group_id(group_id)
            await update.message.reply_text(f"✅ Я доданий до групи! Chat ID: `{group_id}`\nЗамовлення будуть надходити сюди.")
            break

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    user_id = update.effective_user.id
    phones = get_available_phones()
    items_per_page = 5
    total_pages = (len(phones) + items_per_page - 1) // items_per_page if phones else 1
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_phones = phones[start_idx:end_idx]

    keyboard = []
    for phone in page_phones:
        pid, name, desc, _, price = phone
        btn_text = f"{name} – {price} грн/урок" if price else name
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"view_{pid}")])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"page_{page-1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"page_{page+1}"))
    if nav_row:
        keyboard.append(nav_row)

    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("🛠️ Панель адміністратора", callback_data="admin_panel")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    message = update.effective_message
    if phones:
        header = f"📱 *Каталог телефонів* (стор. {page+1}/{total_pages})"
        await message.reply_text(header, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await message.reply_text("Наразі немає доступних телефонів.", reply_markup=reply_markup)

# ------------------------- Global Callback Handler (only for non-conversation buttons) -------------------------
async def global_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    # Pagination
    if data.startswith("page_"):
        page = int(data.split("_")[1])
        await query.message.delete()
        await menu_command(update, context, page=page)
        return

    # Navigation
    if data == "goto_menu":
        await query.message.delete()
        await menu_command(update, context, page=0)
        return
    elif data == "account":
        user = query.from_user
        profile = get_user_profile(user_id)
        saved_name = profile[0] if profile else "не вказано"
        saved_class = profile[1] if profile else "не вказано"
        text = (
            f"👤 *Ваш акаунт*\n\n"
            f"Ім'я: {user.first_name or ''} {user.last_name or ''}\n"
            f"Username: @{user.username or 'немає'}\n"
            f"ID: `{user.id}`\n\n"
            f"📋 *Збережені дані:*\n"
            f"ПІБ: {saved_name}\n"
            f"Клас: {saved_class}"
        )
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return
    elif data == "my_orders":
        orders = get_user_orders(user_id)
        if not orders:
            text = "У вас ще немає замовлень."
        else:
            text = "📦 *Ваші останні замовлення:*\n\n"
            for oid, full_name, homeclass, cabinet, classes, phone_name, status, created in orders:
                text += f"🔹 *{phone_name}*\n   Клас: {homeclass}, Кабінет: {cabinet}, Уроків: {classes}\n   Статус: {status}\n   Дата: {created}\n\n"
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return
    elif data == "help":
        await help_command(update, context)
        return
    elif data == "back_to_start":
        user_name = query.from_user.first_name or "користувач"
        welcome_text = (
            f"👋 Вітаю, *{user_name}*!\n\n"
            f"Це бот для замовлення телефонів.\n"
            f"Оберіть дію:"
        )
        keyboard = [
            [InlineKeyboardButton("📱 Перейти до меню", callback_data="goto_menu")],
            [InlineKeyboardButton("👤 Мій акаунт", callback_data="account")],
            [InlineKeyboardButton("📦 Мої замовлення", callback_data="my_orders")],
            [InlineKeyboardButton("❓ Допомога", callback_data="help")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
        return
    elif data == "back_to_menu":
        await query.message.delete()
        await menu_command(update, context, page=0)
        return

    # Phone viewing
    if data.startswith("view_"):
        phone_id = int(data.split("_")[1])
        phone = get_phone(phone_id)
        if not phone:
            await query.edit_message_text("Телефон не знайдено.")
            return
        name, desc, image_id, price, in_stock = phone
        if in_stock == 0:
            await query.answer("Цей телефон зараз недоступний.", show_alert=True)
            return
        caption = f"*{name}*\n{desc}\nЦіна: {price} грн/урок" if price else f"*{name}*\n{desc}"
        keyboard = [
            [InlineKeyboardButton("🛍️ Замовити", callback_data=f"order_{phone_id}")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if image_id:
            await query.message.delete()
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=image_id,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(caption, reply_markup=reply_markup, parse_mode="Markdown")

    # Admin panel
    elif data == "admin_panel" and is_admin(user_id):
        keyboard = [
            [InlineKeyboardButton("➕ Додати телефон", callback_data="admin_add")],
            [InlineKeyboardButton("📋 Керувати телефонами", callback_data="admin_list_phones")],
            [InlineKeyboardButton("📦 Переглянути замовлення", callback_data="admin_view_orders")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]
        ]
        await query.edit_message_text("🛠️ *Панель адміністратора*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "admin_list_phones" and is_admin(user_id):
        phones = get_all_phones()
        if not phones:
            await query.edit_message_text("Телефонів немає.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")]]))
            return
        keyboard = []
        for phone in phones:
            pid, name, desc, _, price, in_stock = phone
            stock_text = "✅ В наявності" if in_stock else "❌ Немає"
            btn_text = f"{name} – {price} грн/урок ({stock_text})"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"admin_edit_{pid}")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")])
        await query.edit_message_text("Виберіть телефон для редагування:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("admin_edit_") and is_admin(user_id):
        phone_id = int(data.split("_")[2])
        context.user_data['edit_phone_id'] = phone_id
        phone = get_phone(phone_id)
        if not phone:
            await query.edit_message_text("Телефон не знайдено.")
            return
        name, desc, image_id, price, in_stock = phone
        stock_text = "✅ В наявності" if in_stock else "❌ Немає"
        text = f"*{name}*\n{desc}\nЦіна: {price} грн/урок\nСтатус: {stock_text}"
        keyboard = [
            [InlineKeyboardButton("🔄 Змінити наявність", callback_data=f"admin_togglestock_{phone_id}")],
            [InlineKeyboardButton("💰 Змінити ціну", callback_data=f"admin_editprice_{phone_id}")],
            [InlineKeyboardButton("❌ Видалити телефон", callback_data=f"admin_delete_{phone_id}")],
            [InlineKeyboardButton("◀️ Назад до списку", callback_data="admin_list_phones")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("admin_togglestock_") and is_admin(user_id):
        phone_id = int(data.split("_")[2])
        phone = get_phone(phone_id)
        new_stock = 0 if phone[4] else 1
        update_stock(phone_id, new_stock)
        await query.answer(f"Статус змінено на {'в наявності' if new_stock else 'немає'}")
        phone = get_phone(phone_id)
        name, desc, image_id, price, in_stock = phone
        stock_text = "✅ В наявності" if in_stock else "❌ Немає"
        text = f"*{name}*\n{desc}\nЦіна: {price} грн/урок\nСтатус: {stock_text}"
        keyboard = [
            [InlineKeyboardButton("🔄 Змінити наявність", callback_data=f"admin_togglestock_{phone_id}")],
            [InlineKeyboardButton("💰 Змінити ціну", callback_data=f"admin_editprice_{phone_id}")],
            [InlineKeyboardButton("❌ Видалити телефон", callback_data=f"admin_delete_{phone_id}")],
            [InlineKeyboardButton("◀️ Назад до списку", callback_data="admin_list_phones")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("admin_delete_") and is_admin(user_id):
        phone_id = int(data.split("_")[2])
        delete_phone(phone_id)
        await query.answer("Телефон видалено.")
        phones = get_all_phones()
        keyboard = []
        for phone in phones:
            pid, name, desc, _, price, in_stock = phone
            stock_text = "✅ В наявності" if in_stock else "❌ Немає"
            btn_text = f"{name} – {price} грн/урок ({stock_text})"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"admin_edit_{pid}")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")])
        await query.edit_message_text("Виберіть телефон для редагування:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_view_orders" and is_admin(user_id):
        orders = get_orders()
        if not orders:
            await query.edit_message_text("Замовлень немає.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")]]))
            return
        text = "📦 *Останні замовлення:*\n\n"
        for oid, full_name, homeclass, cabinet, classes, phone_name, status, created in orders:
            text += f"🔹 *{full_name}*, {homeclass}, каб. {cabinet}, {classes} ур.\n   📱 {phone_name}\n   Статус: {status}\n   Дата: {created}\n\n"
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")]]))

# ------------------------- Order Conversation Handlers (have priority) -------------------------
async def order_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data.startswith("order_"):
        phone_id = int(data.split("_")[1])
        phone = get_phone(phone_id)
        if not phone or phone[4] == 0:
            await query.edit_message_text("❌ Цей телефон більше не доступний.")
            return ConversationHandler.END
        context.user_data['order_phone_id'] = phone_id
        profile = get_user_profile(user_id)
        if profile and profile[0]:
            context.user_data['order_full_name'] = profile[0]
            context.user_data['order_homeclass'] = profile[1] if profile[1] else None
            await query.edit_message_text(
                f"Ваше збережене ім'я: *{profile[0]}*\n"
                f"Клас: *{profile[1] or 'не вказано'}*\n\n"
                f"Бажаєте використати ці дані?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Так", callback_data="use_saved")],
                    [InlineKeyboardButton("✏️ Ввести нові", callback_data="new_profile")],
                ]),
                parse_mode="Markdown"
            )
            return ORDER_NAME
        else:
            await query.edit_message_text("Введіть ваше *повне ім'я* (ПІБ):", parse_mode="Markdown")
            return ORDER_NAME

async def order_name_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        data = query.data
        if data == "use_saved":
            if not context.user_data.get('order_homeclass'):
                await query.edit_message_text("Оберіть ваш клас:", reply_markup=homeclass_keyboard())
                return ORDER_HOMECLASS
            else:
                await query.edit_message_text(f"Ваш клас: *{context.user_data['order_homeclass']}*\nВведіть номер кабінету (1-45):", parse_mode="Markdown")
                return ORDER_CABINET
        elif data == "new_profile":
            context.user_data.pop('order_full_name', None)
            context.user_data.pop('order_homeclass', None)
            await query.edit_message_text("Введіть ваше *повне ім'я* (ПІБ):", parse_mode="Markdown")
            return ORDER_NAME
    else:
        full_name = update.message.text.strip()
        if len(full_name) < 5:
            await update.message.reply_text("Будь ласка, введіть повне ім'я.")
            return ORDER_NAME
        context.user_data['order_full_name'] = full_name
        await update.message.reply_text("Оберіть ваш клас:", reply_markup=homeclass_keyboard())
        return ORDER_HOMECLASS

async def order_homeclass_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("homeclass_"):
        hc = data.split("_")[1]
        context.user_data['order_homeclass'] = hc
        await query.edit_message_text(f"Ви обрали клас: *{hc}*\nТепер введіть номер кабінету (від 1 до 45):", parse_mode="Markdown")
        return ORDER_CABINET

async def order_cabinet_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cabinet = int(update.message.text.strip())
        if not 1 <= cabinet <= 45:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Невірний номер. Введіть число від 1 до 45.")
        return ORDER_CABINET
    context.user_data['order_cabinet'] = cabinet
    await update.message.reply_text("Скільки уроків вам потрібно? (від 1 до 5):")
    return ORDER_CLASSES

async def order_classes_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        classes = int(update.message.text.strip())
        if not 1 <= classes <= 5:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Введіть число від 1 до 5.")
        return ORDER_CLASSES

    user_id = update.effective_user.id
    full_name = context.user_data['order_full_name']
    homeclass = context.user_data['order_homeclass']
    cabinet = context.user_data['order_cabinet']
    phone_id = context.user_data['order_phone_id']

    phone = get_phone(phone_id)
    if not phone or phone[4] == 0:
        await update.message.reply_text("❌ На жаль, цей телефон більше не доступний.")
        return ConversationHandler.END

    order_id = add_order(user_id, full_name, homeclass, cabinet, classes, phone_id)
    await update.message.reply_text("✅ Замовлення прийнято! Адміністратор зв'яжеться з вами найближчим часом.")
    await notify_order(context, order_id)

    context.user_data.pop('order_full_name', None)
    context.user_data.pop('order_homeclass', None)
    context.user_data.pop('order_cabinet', None)
    context.user_data.pop('order_phone_id', None)
    return ConversationHandler.END

async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Замовлення скасовано.")
    for key in ['order_full_name', 'order_homeclass', 'order_cabinet', 'order_phone_id']:
        context.user_data.pop(key, None)
    return ConversationHandler.END

# ------------------------- Add Phone Conversation -------------------------
async def admin_add_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['admin_add'] = {}
    await query.edit_message_text("Введіть назву телефону:")
    return ADD_NAME

async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['admin_add']['name'] = update.message.text
    await update.message.reply_text("Введіть опис телефону:")
    return ADD_DESCRIPTION

async def add_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['admin_add']['description'] = update.message.text
    await update.message.reply_text("Введіть ціну за один урок (грн):")
    return ADD_PRICE

async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.strip())
        context.user_data['admin_add']['price'] = price
        await update.message.reply_text("Надішліть фотографію телефону (або /skip щоб пропустити):")
        return ADD_IMAGE
    except ValueError:
        await update.message.reply_text("Невірний формат ціни. Введіть число.")
        return ADD_PRICE

async def add_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        context.user_data['admin_add']['image_id'] = file_id
    else:
        context.user_data['admin_add']['image_id'] = None
    data = context.user_data['admin_add']
    add_phone_to_db(data['name'], data['description'], data['price'], data['image_id'])
    await update.message.reply_text("✅ Телефон успішно додано!")
    context.user_data.pop('admin_add', None)
    return ConversationHandler.END

async def skip_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['admin_add']['image_id'] = None
    data = context.user_data['admin_add']
    add_phone_to_db(data['name'], data['description'], data['price'], data['image_id'])
    await update.message.reply_text("✅ Телефон додано без фото!")
    context.user_data.pop('admin_add', None)
    return ConversationHandler.END

async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Додавання скасовано.")
    context.user_data.pop('admin_add', None)
    return ConversationHandler.END

# ------------------------- Edit Price Conversation -------------------------
async def edit_price_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    phone_id = int(data.split("_")[2])
    context.user_data['edit_price_phone_id'] = phone_id
    await query.edit_message_text("Введіть нову ціну (число, грн/урок):")
    return EDIT_PRICE

async def edit_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        new_price = float(update.message.text.strip())
        phone_id = context.user_data['edit_price_phone_id']
        update_price(phone_id, new_price)
        await update.message.reply_text("✅ Ціну оновлено.")
        context.user_data.pop('edit_price_phone_id', None)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Невірний формат. Введіть число.")
        return EDIT_PRICE

# ------------------------- Main -------------------------
async def run_bot():
    init_db()
    logger.info("✅ Database initialized")

    application = Application.builder().token(BOT_TOKEN).build()

    # Order conversation (MUST be added before global handler)
    order_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(order_entry, pattern="^order_")],
        states={
            ORDER_NAME: [
                CallbackQueryHandler(order_name_state, pattern="^(use_saved|new_profile)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, order_name_state),
            ],
            ORDER_HOMECLASS: [CallbackQueryHandler(order_homeclass_state, pattern="^homeclass_")],
            ORDER_CABINET: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_cabinet_state)],
            ORDER_CLASSES: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_classes_state)],
        },
        fallbacks=[CommandHandler("cancel", cancel_order)],
    )

    # Add phone conversation (admin)
    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_entry, pattern="^admin_add$")],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            ADD_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_description)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_price)],
            ADD_IMAGE: [
                MessageHandler(filters.PHOTO, add_image),
                CommandHandler("skip", skip_image)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_add)],
    )

    # Edit price conversation (admin)
    edit_price_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_price_entry, pattern="^admin_editprice_")],
        states={
            EDIT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_price_input)],
        },
        fallbacks=[CommandHandler("cancel", cancel_add)],
    )

    # Register conversation handlers FIRST
    application.add_handler(order_conv)
    application.add_handler(add_conv)
    application.add_handler(edit_price_conv)

    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("setgroup", set_group_command))
    application.add_handler(CommandHandler("testnotify", test_notify_command))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_members))

    # Global callback handler (LAST, for all other callbacks)
    application.add_handler(CallbackQueryHandler(global_button_handler))

    logger.info("🤖 Starting bot polling...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    while True:
        await asyncio.sleep(3600)

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    finally:
        loop.close()

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    main()
