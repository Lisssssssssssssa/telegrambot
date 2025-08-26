# Запускать в 32 разрядном приложении

import telebot
import sqlite3
import re

# Конфигурация
TOKEN = "ваш токен"
CHANNEL = "ваш канал"  # Основной канал для подписки

# Инициализация бота
bot = telebot.TeleBot(TOKEN)
types = telebot.types

# Глобальная переменная для хранения рассылок
pending_broadcasts = {}


# Инициализация базы данных
def init_database():
    conn = sqlite3.connect('.venv/Lib/ships.db')
    c = conn.cursor()

    # Создание основной таблицы
    c.execute('''CREATE TABLE IF NOT EXISTS ships (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                discounts TEXT NOT NULL)''')

    # Создание виртуальной таблицы для полнотекстового поиска
    c.execute('''CREATE VIRTUAL TABLE IF NOT EXISTS ships_fts 
                USING fts5(name, discounts)''')
    # Таблица пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    chat_id INTEGER PRIMARY KEY,
                    username TEXT)''')
    conn.commit()
    conn.close()
    print("База создана")


# Создание кнопок для подтверждения рассылки
def create_broadcast_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    yes_btn = types.InlineKeyboardButton("Да", callback_data="broadcast_yes")
    no_btn = types.InlineKeyboardButton("Нет", callback_data="broadcast_no")
    markup.add(yes_btn, no_btn)
    return markup


# Добавление нового
def add_new(message, name, discounts):
    # Удаляем лишние пробелы и разделяем строку в список по ","
    clean_list = [name.strip() for name in name.split(',')]
    added_in_this_session = []
    for i in clean_list:
        if i == "":
            continue
        conn = sqlite3.connect('.venv/Lib/ships.db')
        c = conn.cursor()
        try:
            c.execute("INSERT INTO ships (name, discounts) VALUES (?, ?)",
                      (i, discounts))
            c.execute("INSERT INTO ships_fts (name, discounts) VALUES (?, ?)",
                      (i, discounts))
            conn.commit()
            bot.send_message(message.chat.id, f'✅Новый теплоход {i} добавлен')
            added_in_this_session.append(i)
        except sqlite3.IntegrityError:
            bot.send_message(message.chat.id, f'❌ Теплоход {i} уже существует, пропускаем.')
        finally:
            conn.close()

    if not added_in_this_session:
        bot.send_message(message.chat.id, "Не было добавлено ни одного нового теплохода.")
        return send_welcome(message)

    # Формируем текст для рассылки
    broadcast_text = "🎉 *Добавлены новые теплоходы со скидками!*\n\n"
    for ship in added_in_this_session:
        broadcast_text += f"🚢 *{ship}*: {discounts}\n\n"
    broadcast_text += "Узнайте больше: /start"

    # Отправляем сообщение администратору с кнопками
    markup = create_broadcast_keyboard()
    sent_msg = bot.send_message(
        message.chat.id,
        f"✅ Теплоход(ы) добавлен(ы). Сделать рассылку всем пользователям?",
        reply_markup=markup
    )

    # Сохраняем текст рассылки
    pending_broadcasts[sent_msg.message_id] = broadcast_text


# Редактирование
def edit_existing_name(message, name, new_name):
    name = name.strip()
    name = name.replace(',', '')
    conn = sqlite3.connect('.venv/Lib/ships.db')
    c = conn.cursor()
    try:
        c.execute("UPDATE ships SET name=? WHERE (name=?)",
                  (new_name, name))
        c.execute("UPDATE ships_fts SET name=? WHERE (name=?)",
                  (new_name, name))
    except sqlite3.IntegrityError:
        pass  # Уже существует

    conn.commit()
    conn.close()
    bot.send_message(message.chat.id, f'✅Теплоход {name} переименован в {new_name}')
    send_welcome(message)


def edit_existing_discounts(message, name, discounts):
    clean_list = [name.strip() for name in name.split(',')]
    updated_ships = []  # Список теплоходов с обновленными скидками
    for i in clean_list:
        conn = sqlite3.connect('.venv/Lib/ships.db')
        c = conn.cursor()
        try:
            # Получаем старые скидки для сравнения
            c.execute("SELECT discounts FROM ships WHERE name=?", (i,))
            old_discounts = c.fetchone()
            old_discounts = old_discounts[0] if old_discounts else ""

            # Обновляем скидки
            c.execute("UPDATE ships SET discounts=? WHERE (name=?)",
                      (discounts, i))
            c.execute("UPDATE ships_fts SET discounts=? WHERE (name=?)",
                      (discounts, i))
            conn.commit()
            updated_ships.append(i)
            if i != "":
                # Если скидки изменились
                if old_discounts != discounts:
                    bot.send_message(message.chat.id, f'✅Установлены новые скидки для теплохода {i}')

                    # Формируем текст для рассылки
                    broadcast_text = f"🎉 *Обновлены скидки для теплохода {i}!*\n\n"
                    broadcast_text += f"🚢 *Старые скидки*: {old_discounts}\n"
                    broadcast_text += f"🔥 *Новые скидки*: {discounts}\n\n"
                    broadcast_text += "Узнайте больше: /start"

                    # Отправляем сообщение администратору с кнопками
                    markup = create_broadcast_keyboard()
                    sent_msg = bot.send_message(
                        message.chat.id,
                        f"✅ Скидки для {i} обновлены. Сделать рассылку всем пользователям?",
                        reply_markup=markup
                    )

                    # Сохраняем текст рассылки
                    pending_broadcasts[sent_msg.message_id] = broadcast_text
                else:
                    bot.send_message(message.chat.id, f'ℹ️ Скидки для теплохода {i} не изменились')

        except Exception as e:
            bot.send_message(message.chat.id, f'❌ Ошибка при обновлении скидок для теплохода {i}: {str(e)}')
        finally:
            conn.close()

    if not updated_ships:
        bot.send_message(message.chat.id, f'Не обновлено ни одного теплохода')
    else:
        # Если были изменения, но без рассылки (если скидки не менялись)
        send_welcome(message)


# Удаление
def delete(message, name):
    # Удаляем лишние пробелы и разделяем строку в список по ","
    clean_list = [name.strip() for name in name.split(',')]
    for i in clean_list:
        conn = sqlite3.connect('.venv/Lib/ships.db')
        c = conn.cursor()
        try:
            c.execute("DELETE FROM ships WHERE (name=?)",
                      ([i]))
            c.execute("DELETE FROM ships_fts WHERE (name=?)",
                      ([i]))
            if i != "":
                bot.send_message(message.chat.id, f'✅Теплоход {i} удален')
        except sqlite3.IntegrityError:
            pass  # Уже существует

        conn.commit()
        conn.close()

    send_welcome(message)


# Поиск теплохода
def search_ship(query):
    conn = sqlite3.connect('.venv/Lib/ships.db')
    c = conn.cursor()

    # Поиск с использованием FTS5
    c.execute('''
    SELECT name, discounts 
    FROM ships_fts 
    WHERE name MATCH ? 
    ORDER BY rank
    LIMIT 1
    ''', (f'"{query}"',))

    result = c.fetchone()
    conn.close()

    return result


# Проверка подписки на канал
def is_subscribed(chat_id):
    try:
        chat_member = bot.get_chat_member(CHANNEL, chat_id)
        return chat_member.status in ['member', 'administrator', 'creator']
    except Exception:
        print("Что-то не то")
        return False


# Создание кнопок на редактирование базы
## Основное меню редактирования
def button_inline_menu(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton(
            text='Добавить новый',
            callback_data='add_new'
        ),
        types.InlineKeyboardButton(
            text='Редактировать',
            callback_data='edit_existing'
        ),
        types.InlineKeyboardButton(
            text='❌ Удалить',
            callback_data='delete'
        ),
        types.InlineKeyboardButton(
            text='Назад',
            callback_data='back_to_main'
        )
    ]
    markup.add(*buttons)
    bot.send_message(message.chat.id, 'Выберите действие', reply_markup=markup)


###  Дополнительное меню Редактирования
def button_inline_menu_edit(message, name):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton(
            text='Изменить имя',
            callback_data='change_name'
        ),
        types.InlineKeyboardButton(
            text='Изменитить скидку',
            callback_data='change_discounts'
        ),
        types.InlineKeyboardButton(
            text='Назад',
            callback_data='back_to_main'
        )
    ]
    markup.add(*buttons)
    bot.send_message(message.chat.id, 'Выберите действие', reply_markup=markup)


# Обработчики команд
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if not is_subscribed(message.chat.id):
        markup = types.InlineKeyboardMarkup()
        subscribe_btn = types.InlineKeyboardButton(
            "Подписаться на канал",
            url=f"https://t.me/{CHANNEL[1:]}")
        check_btn = types.InlineKeyboardButton(
            "Проверить подписку",
            callback_data="check_subscription")
        markup.add(subscribe_btn, check_btn)

        bot.send_message(
            message.chat.id,
            f"🚢 Добро пожаловать в бот речных круизов!\n\n"
            f"🔐 Для доступа к скидкам подпишитесь на наш канал: {CHANNEL}\n"
            "После подписки нажмите кнопку ниже:",
            parse_mode='Markdown',
            reply_markup=markup)
        return

        # Основное меню
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("Все теплоходы"))
    markup.add(types.KeyboardButton("Поиск скидок"))

    # Если пользователь в списке администраторов бота
    if bot.get_chat_member(CHANNEL, message.chat.id).status in ['creator',
                                                                'administrator'] or message.chat.id in id_admin:
        markup.add(types.KeyboardButton("Изменить базу данных"))
        print(bot.get_chat_member(CHANNEL, message.chat.id).status)

    # Отправляем сообщение с двумя клавиатурами
    bot.send_message(
        message.chat.id,
        "🚢 Выберите действие:\n"
        "• Напишите название теплохода\n"
        "• Используйте кнопку 'Все теплоходы'\n"
        "• Или 'Поиск скидок' для помощи\n\n"
        "Бронируйте круизы онлайн на нашем сайте😉",
        reply_markup=markup)

    # Добавляем пользователя в базу
    conn = sqlite3.connect('.venv/Lib/ships.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (chat_id) VALUES (?)", (message.chat.id,))
    conn.commit()
    conn.close()

    # Добавляем инлайн-кнопку в отдельном сообщении
    inline_markup = types.InlineKeyboardMarkup()
    site_btn = types.InlineKeyboardButton(
        "🌐 Наш сайт",
        url="ваш сайт")
    inline_markup.add(site_btn)
    bot.send_message(
        message.chat.id,
        "👉 Нажмите кнопку ниже, чтобы перейти на наш сайт и забронировать круиз",
        reply_markup=inline_markup)


#############
# Обработчик инлайн-кнопок
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if call.data == "check_subscription":
        if is_subscribed(call.message.chat.id):
            bot.answer_callback_query(call.id, "✅ Вы подписаны! Доступ открыт.")
            send_welcome(call.message)
        else:
            bot.answer_callback_query(
                call.id,
                "❌ Вы ещё не подписались на канал",
                show_alert=True)
    elif call.data == "back_to_main":
        send_welcome(call.message)
    # Добавление нового
    elif call.data == "add_new":
        bot.send_message(call.message.chat.id, "Выбрано добавление нового")
        markup = types.ForceReply(selective=False)
        # Вводим название теплохода
        bot.send_message(call.message.chat.id, "Введите название теплохода", reply_markup=markup)

        @bot.message_handler(content_types=['text'])
        def message_input_step(message):
            global name_tepl
            name_tepl = message.text
            bot.send_message(call.message.chat.id, "Введите скидку", reply_markup=markup)

            # Вводим скидку
            def message_input_discount(message):
                global discount_tepl
                discount_tepl = message.text
                add_new(message, name_tepl, discount_tepl)

            bot.register_next_step_handler(call.message, message_input_discount)

        bot.register_next_step_handler(call.message, message_input_step)

    # Редактирование существующего
    elif call.data == "edit_existing":
        bot.send_message(call.message.chat.id, "Выбрано редактирование существующего")
        markup = types.ForceReply(selective=False)
        # Вводим название теплохода
        bot.send_message(call.message.chat.id, "Введите название теплохода для редактирования", reply_markup=markup)

        @bot.message_handler(content_types=['text'])
        def message_input_step(message):
            global name_tepl
            global name_list
            name_tepl = message.text
            # Удаляем лишние пробелы и разделяем строку в список по ","
            clean_list = [name_tepl.strip() for name_tepl in name_tepl.split(',')]
            # Поищем теплоход в базе. Если не найдем, то сообщим об этом.
            # Сформируем строку из найденных теплоходов и передадим дальше в обработку
            name_list = ""
            for i in clean_list:
                result = search_ship(i)
                if result:
                    name, discounts = result
                    response = f"🚢 {name} найден"
                    bot.send_message(message.chat.id, response)
                    name_list = f'{name_list} {name},'
                else:
                    bot.send_message(message.chat.id, f'❌ Теплоход {i} не найден в качестве объекта для редактирования')
            if name_list != "":
                button_inline_menu_edit(call.message, name_list)
            else:
                bot.send_message(message.chat.id, f'Нет теплоходов для изменения')
                send_welcome(message)

        bot.register_next_step_handler(call.message, message_input_step)

    elif call.data == "change_name":
        bot.send_message(call.message.chat.id, f'Редактируем имя теплохода {name_list}')
        clean_list = [name_list.strip() for name_list in name_list.split(',')]
        if len(clean_list) > 2:
            bot.send_message(call.message.chat.id, f'Пакетное переименование теплоходов невозможно!')
            return send_welcome(call.message)
        markup = types.ForceReply(selective=False)
        # Вводим новое название теплохода
        bot.send_message(call.message.chat.id, "Введите новое название теплохода", reply_markup=markup)

        @bot.message_handler(content_types=['text'])
        def message_input_step(message):
            global new_name
            new_name = message.text
            edit_existing_name(message, name_list, new_name)

        bot.register_next_step_handler(call.message, message_input_step)

    elif call.data == "change_discounts":
        bot.send_message(call.message.chat.id, "Редактируем скидки теплохода")
        markup = types.ForceReply(selective=False)
        # Вводим новые скидки
        bot.send_message(call.message.chat.id, "Введите новые скидки для теплохода", reply_markup=markup)

        @bot.message_handler(content_types=['text'])
        def message_input_step(message):
            global discounts
            discounts = message.text
            edit_existing_discounts(message, name_list, discounts)

        bot.register_next_step_handler(call.message, message_input_step)


    # Удаление
    elif call.data == "delete":
        bot.send_message(call.message.chat.id, "Вы выбрали удалить теплоход")
        markup = types.ForceReply(selective=False)
        # Вводим название теплохода
        bot.send_message(call.message.chat.id, "Введите название теплоход, который хотите удалить", reply_markup=markup)

        @bot.message_handler(content_types=['text'])
        def message_input_step(message):
            global name_tepl
            name_tepl = message.text
            # Удаляем лишние пробелы и разделяем строку в список по ","
            clean_list = [name_tepl.strip() for name_tepl in name_tepl.split(',')]
            # Поищем теплоход в базе. Если не найдем, то сообщим об этом.
            # Сформируем строку из найденных теплоходов и передадим дальше в обработку
            name_list = ""
            for i in clean_list:
                result = search_ship(i)
                if result:
                    name, discounts = result
                    response = f"🚢 {name} найден"
                    bot.send_message(message.chat.id, response)
                    name_list = f'{name_list} {name},'
                else:
                    bot.send_message(message.chat.id, f'❌ Теплоход {i} не найден в базе данных и не может быть удалён')
            if name_list != "":
                delete(message, name_list)
            else:
                bot.send_message(message.chat.id, f'Нет теплоходов для удаления')
                send_welcome(message)

        bot.register_next_step_handler(call.message, message_input_step)
        # Рассылка
    elif call.data == "broadcast_yes":
        message_id = call.message.message_id
        broadcast_text = pending_broadcasts.get(message_id)
        if broadcast_text is None:
            bot.answer_callback_query(call.id, "Извините, информация о рассылке устарела.")
            return

        conn = sqlite3.connect('.venv/Lib/ships.db')
        c = conn.cursor()
        c.execute("SELECT chat_id FROM users")
        users = c.fetchall()
        conn.close()

        count = 0
        errors = 0
        for user in users:
            chat_id = user[0]
            try:
                bot.send_message(chat_id, broadcast_text, parse_mode='Markdown')
                count += 1
            except Exception as e:
                errors += 1

        # Удаляем из словаря
        if message_id in pending_broadcasts:
            del pending_broadcasts[message_id]

        bot.send_message(
            call.message.chat.id,
            f"✅ Рассылка выполнена. Успешно: {count}"
        )
        send_welcome(call.message)

    elif call.data == "broadcast_no":
        message_id = call.message.message_id
        if message_id in pending_broadcasts:
            del pending_broadcasts[message_id]
        bot.send_message(call.message.chat.id, "❌ Рассылка отменена.")
        send_welcome(call.message)
    ################


# Обработка текстовых сообщений
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    # Проверка подписки
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip()

    # Проверка подписки
    if not is_subscribed(chat_id):
        markup = types.InlineKeyboardMarkup()
        subscribe_btn = types.InlineKeyboardButton(
            "Подписаться на канал",
            url=f"https://t.me/{CHANNEL[1:]}")
        check_btn = types.InlineKeyboardButton(
            "Проверить подписку",
            callback_data="check_subscription")
        markup.add(subscribe_btn, check_btn)

        bot.send_message(
            chat_id,
            f"🔐 Для доступа к скидкам подпишитесь на наш канал: {CHANNEL}",
            parse_mode='Markdown',
            reply_markup=markup)
        return
    conn = sqlite3.connect('.venv/Lib/ships.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (chat_id) VALUES (?)", (chat_id,))
    conn.commit()
    conn.close()
    text = message.text.strip()

    # Обработка кнопки "Все теплоходы"
    if text.lower() == "все теплоходы":
        inline_markup = types.InlineKeyboardMarkup()
        site_btn = types.InlineKeyboardButton(
            "🌐 Наш сайт",
            url="https://www.moretravel.ru/ts/#country=22222246&type=cruises")
        inline_markup.add(site_btn)
        bot.send_message(
            message.chat.id,
            "👉 Нажмите кнопку ниже, чтобы перейти на наш сайт и забронировать круиз",
            reply_markup=inline_markup)
        conn = sqlite3.connect('.venv/Lib/ships.db')
        c = conn.cursor()
        c.execute("SELECT name FROM ships ORDER BY name")
        ships = [row[0] for row in c.fetchall()]
        conn.close()

        response = "🚢 Список всех теплоходов:\n\n" + "\n".join(
            f"• {ship}" for ship in ships)
        bot.send_message(message.chat.id, response, parse_mode='Markdown')
        return

    # Обработка кнопки "поиск скидок"
    if text.lower() == "поиск скидок":
        bot.send_message(
            message.chat.id,
            "🔍 Как искать скидки:\n\n"
            "Просто напишите название теплохода, например:\n"
            "• Волга Дрим\n"
            "• Северная сказка\n"
            "• Александр Невский\n\n"
            "Бот найдёт актуальные скидки для выбранного теплохода!",
            parse_mode='Markdown')
        return

    # Кнопка "изменить базу данных"
    if text.lower() == "изменить базу данных":
        button_inline_menu(message)
        return

    # Поиск теплохода
    result = search_ship(text)

    if result:
        name, discounts = result
        response = f"🚢 {name}\n\n{discounts}\n\n Для нового поиска введите название"
        # bot.send_message(message.chat.id, response, parse_mode='Markdown')
        bot.send_message(message.chat.id, response)
    else:
        bot.send_message(
            message.chat.id,
            "❌ Теплоход не найден. Попробуйте:\n"
            "• Проверить написание\n"
            "• Использовать часть названия\n"
            "• Посмотреть весь список командой /start",
            parse_mode='Markdown')


# Запуск бота
# Раскомментировать ниже при первом запуске, потом закомментировать
#init_database()

bot.infinity_polling()