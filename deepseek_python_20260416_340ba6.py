import logging
import sqlite3
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

# ------------------------- Configuration -------------------------
BOT_TOKEN = "8462544892:AAGQAI6sKagE6KcrUNjekzlr4DfMwps_jCY"

# Hardcoded admin Telegram user IDs (no password needed)
ADMIN_IDS = [5424647855, 5758497311]

# Conversation states
ADD_NAME, ADD_DESCRIPTION, ADD_PRICE, ADD_IMAGE = range(4)
ORDER_NAME, ORDER_CABINET, ORDER_CLASSES = range(10, 13)
EDIT_PRICE = 20

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
                  cabinet INTEGER,
                  classes INTEGER,
                  phone_id INTEGER,
                  status TEXT DEFAULT 'new',
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def get_available_phones():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, description, image_file_id, price FROM phones WHERE in_stock=1")
    phones = c.fetchall()
    conn.close()
    return phones

def get_all_phones():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, description, image_file_id, price, in_stock FROM phones")
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

def add_order(user_id, full_name, cabinet, classes, phone_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO orders (user_id, full_name, cabinet, classes, phone_id) VALUES (?,?,?,?,?)",
              (user_id, full_name, cabinet, classes, phone_id))
    order_id = c.lastrowid
    conn.commit()
    conn.close()
    return order_id

def get_orders(limit=20):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT o.id, o.full_name, o.cabinet, o.classes, p.name, o.status, o.created_at
                 FROM orders o JOIN phones p ON o.phone_id = p.id
                 ORDER BY o.created_at DESC LIMIT ?""", (limit,))
    orders = c.fetchall()
    conn.close()
    return orders

async def notify_admins(context: ContextTypes.DEFAULT_TYPE, order_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT o.full_name, o.cabinet, o.classes, p.name, o.user_id
                 FROM orders o JOIN phones p ON o.phone_id = p.id
                 WHERE o.id = ?""", (order_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return
    full_name, cabinet, classes, phone_name, user_id = row
    text = (
        f"🛒 *Нове замовлення!*\n"
        f"👤 ПІБ: {full_name}\n"
        f"🚪 Кабінет: {cabinet}\n"
        f"📚 Кількість уроків: {classes}\n"
        f"📱 Телефон: {phone_name}\n"
        f"🆔 ID користувача: `{user_id}`"
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Failed to notify admin {admin_id}: {e}")

# ------------------------- Handlers -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Вітаю! Це бот для придбання телефонів.\n"
        "Використовуйте /menu щоб переглянути доступні моделі."
    )

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    phones = get_available_phones()
    keyboard = []
    for phone in phones:
        pid, name, desc, _, price = phone
        btn_text = f"{name} – {price} грн" if price else name
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"view_{pid}")])
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("🛠️ Панель адміністратора", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    if phones:
        await update.message.reply_text("📱 *Каталог телефонів:*", reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text("Наразі немає доступних телефонів.", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

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
        caption = f"*{name}*\n{desc}\nЦіна: {price} грн" if price else f"*{name}*\n{desc}"
        keyboard = [[InlineKeyboardButton("🛍️ Замовити", callback_data=f"order_{phone_id}")],
                    [InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
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

    elif data == "back_to_menu":
        phones = get_available_phones()
        keyboard = []
        for phone in phones:
            pid, name, desc, _, price = phone
            btn_text = f"{name} – {price} грн" if price else name
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"view_{pid}")])
        if is_admin(user_id):
            keyboard.append([InlineKeyboardButton("🛠️ Панель адміністратора", callback_data="admin_panel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("📱 *Каталог телефонів:*", reply_markup=reply_markup, parse_mode="Markdown")

    elif data == "admin_panel" and is_admin(user_id):
        keyboard = [
            [InlineKeyboardButton("➕ Додати телефон", callback_data="admin_add")],
            [InlineKeyboardButton("📋 Керувати телефонами", callback_data="admin_list_phones")],
            [InlineKeyboardButton("📦 Переглянути замовлення", callback_data="admin_view_orders")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]
        ]
        await query.edit_message_text("🛠️ *Панель адміністратора*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "admin_add" and is_admin(user_id):
        context.user_data['admin_add'] = {}
        await query.edit_message_text("Введіть назву телефону:")
        return ADD_NAME

    elif data == "admin_list_phones" and is_admin(user_id):
        phones = get_all_phones()
        if not phones:
            await query.edit_message_text("Телефонів немає.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")]]))
            return
        keyboard = []
        for phone in phones:
            pid, name, desc, _, price, in_stock = phone
            stock_text = "✅ В наявності" if in_stock else "❌ Немає"
            btn_text = f"{name} – {price} грн ({stock_text})"
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
        text = f"*{name}*\n{desc}\nЦіна: {price} грн\nСтатус: {stock_text}"
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
        # Refresh view
        phone = get_phone(phone_id)
        name, desc, image_id, price, in_stock = phone
        stock_text = "✅ В наявності" if in_stock else "❌ Немає"
        text = f"*{name}*\n{desc}\nЦіна: {price} грн\nСтатус: {stock_text}"
        keyboard = [
            [InlineKeyboardButton("🔄 Змінити наявність", callback_data=f"admin_togglestock_{phone_id}")],
            [InlineKeyboardButton("💰 Змінити ціну", callback_data=f"admin_editprice_{phone_id}")],
            [InlineKeyboardButton("❌ Видалити телефон", callback_data=f"admin_delete_{phone_id}")],
            [InlineKeyboardButton("◀️ Назад до списку", callback_data="admin_list_phones")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("admin_editprice_") and is_admin(user_id):
        phone_id = int(data.split("_")[2])
        context.user_data['edit_price_phone_id'] = phone_id
        await query.edit_message_text("Введіть нову ціну (число):")
        return EDIT_PRICE

    elif data.startswith("admin_delete_") and is_admin(user_id):
        phone_id = int(data.split("_")[2])
        delete_phone(phone_id)
        await query.answer("Телефон видалено.")
        # Return to list
        phones = get_all_phones()
        keyboard = []
        for phone in phones:
            pid, name, desc, _, price, in_stock = phone
            stock_text = "✅ В наявності" if in_stock else "❌ Немає"
            btn_text = f"{name} – {price} грн ({stock_text})"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"admin_edit_{pid}")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")])
        await query.edit_message_text("Виберіть телефон для редагування:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_view_orders" and is_admin(user_id):
        orders = get_orders()
        if not orders:
            await query.edit_message_text("Замовлень немає.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")]]))
            return
        text = "📦 *Останні замовлення:*\n\n"
        for oid, full_name, cabinet, classes, phone_name, status, created in orders:
            text += f"🔹 *{full_name}*, каб. {cabinet}, {classes} ур.\n   📱 {phone_name}\n   Статус: {status}\n   Дата: {created}\n\n"
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")]]))

    elif data.startswith("order_"):
        phone_id = int(data.split("_")[1])
        context.user_data['order_phone_id'] = phone_id
        await query.edit_message_text("Введіть ваше *повне ім'я* (ПІБ):", parse_mode="Markdown")
        return ORDER_NAME

# ------------------------- Add Phone Conversation -------------------------
async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['admin_add']['name'] = update.message.text
    await update.message.reply_text("Введіть опис телефону:")
    return ADD_DESCRIPTION

async def add_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['admin_add']['description'] = update.message.text
    await update.message.reply_text("Введіть ціну (число, наприклад 4500):")
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

# ------------------------- Order Conversation -------------------------
async def order_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    full_name = update.message.text.strip()
    if len(full_name) < 5:
        await update.message.reply_text("Будь ласка, введіть повне ім'я.")
        return ORDER_NAME
    context.user_data['order_full_name'] = full_name
    await update.message.reply_text("Введіть номер кабінету (від 1 до 45):")
    return ORDER_CABINET

async def order_cabinet(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def order_classes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        classes = int(update.message.text.strip())
        if not 1 <= classes <= 5:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Введіть число від 1 до 5.")
        return ORDER_CLASSES

    user_id = update.effective_user.id
    full_name = context.user_data['order_full_name']
    cabinet = context.user_data['order_cabinet']
    phone_id = context.user_data['order_phone_id']

    order_id = add_order(user_id, full_name, cabinet, classes, phone_id)
    await update.message.reply_text("✅ Замовлення прийнято! Адміністратор зв'яжеться з вами найближчим часом.")
    await notify_admins(context, order_id)

    context.user_data.pop('order_full_name', None)
    context.user_data.pop('order_cabinet', None)
    context.user_data.pop('order_phone_id', None)
    return ConversationHandler.END

async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Замовлення скасовано.")
    for key in ['order_full_name', 'order_cabinet', 'order_phone_id']:
        context.user_data.pop(key, None)
    return ConversationHandler.END

# ------------------------- Main -------------------------
def main():
    init_db()
    logging.basicConfig(level=logging.INFO)

    app = Application.builder().token(BOT_TOKEN).build()

    # Add phone conversation
    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^admin_add$")],
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

    # Edit price conversation
    edit_price_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^admin_editprice_")],
        states={
            EDIT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_price_input)],
        },
        fallbacks=[CommandHandler("cancel", cancel_add)],
    )

    # Order conversation
    order_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^order_")],
        states={
            ORDER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_name)],
            ORDER_CABINET: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_cabinet)],
            ORDER_CLASSES: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_classes)],
        },
        fallbacks=[CommandHandler("cancel", cancel_order)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(add_conv)
    app.add_handler(edit_price_conv)
    app.add_handler(order_conv)
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Бот запущено...")
    app.run_polling()

if __name__ == "__main__":
    main()