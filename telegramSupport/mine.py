from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
import datetime
import os
import sys
import asyncio
from telegram.error import Conflict

# Импортируем keep_alive только если нужно
try:
    from keep_alive import keep_alive
    USE_KEEP_ALIVE = True
except ImportError:
    USE_KEEP_ALIVE = False

TELEGRAM_TOKEN = "8087167425:AAGmHlcpIzO-iQ5kWgP33Tx-f7kED_wdSew"
ADMIN_GROUP_ID = -1002531818197  # Обычная группа тикетов
HIGH_ADMIN_GROUP_ID = -1002535654536  # Группа высшей администрации

ADMINS = {
    5425914820: "NikitusPROFUS",
}

HIGH_ADMINS = {
    5425914820: "NikitusPROFUS",
}

active_tickets = {
}  # user_id: {thread_id, current_admin, timeout_task, group_id}
active_tickets_high = {}  # user_id: {thread_id, current_admin, timeout_task}

banned_users = {}
started_users = set(
)  # Множество пользователей, которые уже использовали /start


def is_banned(user_id: int) -> bool:
    ban_expire = banned_users.get(user_id)
    if ban_expire and ban_expire > datetime.datetime.now():
        return True
    if ban_expire and ban_expire <= datetime.datetime.now():
        del banned_users[user_id]
    return False


async def log_action(context: ContextTypes.DEFAULT_TYPE, text: str):
    # Логи только в группу высшей администрации
    await context.bot.send_message(chat_id=HIGH_ADMIN_GROUP_ID,
                                   text=f"📝 {text}")


async def pin_commands(context: ContextTypes.DEFAULT_TYPE, chat_id: int,
                       thread_id: int):
    if chat_id == HIGH_ADMIN_GROUP_ID:
        # В группе высшей администрации нет команды передачи тикета
        commands_text = ("/takeReport — Присоединиться к обращению\n"
                         "/closeReport — Закрыть обращение\n"
                         "/banReport — Заблокировать пользователя на 7 дней")
    else:
        # В обычной группе администрации есть все команды
        commands_text = ("/takeReport — Присоединиться к обращению\n"
                         "/closeReport — Закрыть обращение\n"
                         "/banReport — Заблокировать пользователя на 7 дней\n"
                         "/nextStepReport — Передать на высшую администрацию")

    pin_msg = await context.bot.send_message(chat_id=chat_id,
                                             message_thread_id=thread_id,
                                             text=commands_text)
    await context.bot.pin_chat_message(chat_id=chat_id,
                                       message_id=pin_msg.message_id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверяем, что команда используется в личных сообщениях
    if update.message.chat.type != 'private':
        return

    user = update.effective_user

    # Проверяем, использовал ли пользователь уже команду /start
    if user.id in started_users:
        await update.message.reply_text(
            "Вы уже получили инструкции по использованию бота.\n"
            "Для создания обращения используйте команду `/support`")
        return

    # Добавляем пользователя в список тех, кто использовал /start
    started_users.add(user.id)

    welcome_text = f"""
👋 Добро пожаловать, {user.first_name}!

🤖 **Как пользоваться ботом поддержки:**

📝 **Создание обращения:**
• Отправьте команду `/support` для создания нового тикета
• Опишите вашу проблему или вопрос
• Ожидайте подключения администратора

💬 **Общение с администратором:**
• После подключения администратора вы можете отправлять сообщения, фото, документы
• Все ваши сообщения будут переданы администратору
• Администратор сможет отвечать вам напрямую

⚠️ **Важные правила:**
• Одновременно можно иметь только один открытый тикет
• Будьте вежливы и описывайте проблему подробно
• Не спамьте сообщениями

📜 **Для создания обращения используйте:** `/support`
"""

    await update.message.reply_text(welcome_text,
                                    parse_mode=ParseMode.MARKDOWN)


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверяем, что команда используется в личных сообщениях
    if update.message.chat.type != 'private':
        return

    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text(
            "<blockquote>Вы заблокированы и не можете создавать обращения.</blockquote>"
        )
        return
    if user.id in active_tickets or user.id in active_tickets_high:
        await update.message.reply_text("У вас уже есть открытый тикет.")
        return

    topic = await context.bot.create_forum_topic(chat_id=ADMIN_GROUP_ID,
                                                 name=f"ID: {user.id}")
    thread_id = topic.message_thread_id

    active_tickets[user.id] = {
        "thread_id": thread_id,
        "current_admin": None,
        "timeout_task": None,
        "group_id": ADMIN_GROUP_ID,
    }

    await pin_commands(context, ADMIN_GROUP_ID, thread_id)

    await update.message.reply_text(
        "Вы успешно создали обращение!\n<blockquote>Ожидайте подключения администратора.</blockquote>",
        parse_mode=ParseMode.HTML)

    await log_action(context,
                     f"Пользователь {user.id} создал тикет #{thread_id}")


async def relay_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in active_tickets:
        ticket = active_tickets[user.id]
    elif user.id in active_tickets_high:
        ticket = active_tickets_high[user.id]
    else:
        return

    thread_id = ticket["thread_id"]
    group_id = ticket.get(
        "group_id", HIGH_ADMIN_GROUP_ID)  # по умолчанию высшая группа если нет

    msg = update.message
    try:
        if msg.text:
            await context.bot.send_message(chat_id=group_id,
                                           message_thread_id=thread_id,
                                           text=msg.text)
        elif msg.photo:
            await context.bot.send_photo(chat_id=group_id,
                                         message_thread_id=thread_id,
                                         photo=msg.photo[-1].file_id,
                                         caption=msg.caption or None)
        elif msg.document:
            await context.bot.send_document(chat_id=group_id,
                                            message_thread_id=thread_id,
                                            document=msg.document.file_id,
                                            caption=msg.caption or None)
        elif msg.sticker:
            await context.bot.send_sticker(chat_id=group_id,
                                           message_thread_id=thread_id,
                                           sticker=msg.sticker.file_id)
        elif msg.video:
            await context.bot.send_video(chat_id=group_id,
                                         message_thread_id=thread_id,
                                         video=msg.video.file_id,
                                         caption=msg.caption or None)
        elif msg.voice:
            await context.bot.send_voice(chat_id=group_id,
                                         message_thread_id=thread_id,
                                         voice=msg.voice.file_id,
                                         caption=msg.caption or None)
    except:
        if user.id in active_tickets:
            del active_tickets[user.id]
        if user.id in active_tickets_high:
            del active_tickets_high[user.id]


async def take_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMINS:
        await update.message.reply_text("У вас нет доступа.")
        return

    thread_id = update.message.message_thread_id

    # Ищем тикет в обеих группах
    found = False
    for user_id, data in active_tickets.items():
        if data["thread_id"] == thread_id:
            # Проверяем, не является ли администратор уже текущим администратором этого тикета
            if data["current_admin"] == admin_id:
                await update.message.reply_text("Вы уже ведете это обращение.")
                return

            data["current_admin"] = admin_id
            try:
                await context.bot.edit_forum_topic(
                    chat_id=ADMIN_GROUP_ID,
                    message_thread_id=thread_id,
                    name=f"ID: {user_id} - {ADMINS[admin_id]}")
            except:
                pass

            await context.bot.send_message(
                chat_id=ADMIN_GROUP_ID,
                message_thread_id=thread_id,
                text=f"<b>{ADMINS[admin_id]}</b> теперь ведет это обращение.",
                parse_mode=ParseMode.HTML)
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=
                    f"<blockquote>К вашему обращению подключился администратор {ADMINS[admin_id]}.</blockquote>",
                    parse_mode=ParseMode.HTML)
            except:
                pass
            await log_action(
                context,
                f"Администратор {ADMINS[admin_id]} подключился к тикету пользователя {user_id}"
            )
            found = True
            break

    if not found:
        for user_id, data in active_tickets_high.items():
            if data["thread_id"] == thread_id:
                # Проверяем, не является ли администратор уже текущим администратором этого тикета
                if data["current_admin"] == admin_id:
                    await update.message.reply_text(
                        "Вы уже ведете это обращение.")
                    return

                data["current_admin"] = admin_id
                try:
                    await context.bot.edit_forum_topic(
                        chat_id=HIGH_ADMIN_GROUP_ID,
                        message_thread_id=thread_id,
                        name=f"ID: {user_id} - {ADMINS[admin_id]}")
                except:
                    pass

                await context.bot.send_message(
                    chat_id=HIGH_ADMIN_GROUP_ID,
                    message_thread_id=thread_id,
                    text=
                    f"<b>{ADMINS[admin_id]}</b> теперь ведет это обращение.",
                    parse_mode=ParseMode.HTML)
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=
                        f"<blockquote>К вашему обращению подключился администратор {ADMINS[admin_id]}.</blockquote>",
                        parse_mode=ParseMode.HTML)
                except:
                    pass
                await log_action(
                    context,
                    f"Администратор {ADMINS[admin_id]} подключился к тикету пользователя {user_id}"
                )
                found = True
                break


async def close_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMINS:
        await update.message.reply_text("У вас нет доступа.")
        return

    thread_id = update.message.message_thread_id

    # Проверяем обе группы
    for tickets_dict, group_id in [(active_tickets, ADMIN_GROUP_ID),
                                   (active_tickets_high, HIGH_ADMIN_GROUP_ID)]:
        for user_id, data in tickets_dict.items():
            if data["thread_id"] == thread_id:
                if data["current_admin"] != admin_id:
                    await update.message.reply_text(
                        "Ты не ведешь это обращение.")
                    return

                if data["timeout_task"]:
                    data["timeout_task"].cancel()

                del tickets_dict[user_id]

                await context.bot.send_message(
                    chat_id=group_id,
                    message_thread_id=thread_id,
                    text=f"<b>{ADMINS[admin_id]}</b> закрыл тикет.",
                    parse_mode=ParseMode.HTML)
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=
                        f"<blockquote>Администратор {ADMINS[admin_id]} закрыл ваше обращение!</blockquote>",
                        parse_mode=ParseMode.HTML)
                except:
                    pass
                await context.bot.delete_forum_topic(
                    chat_id=group_id, message_thread_id=thread_id)
                await log_action(
                    context,
                    f"Администратор {ADMINS[admin_id]} закрыл тикет пользователя {user_id}"
                )
                return


async def ban_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id

    if admin_id not in ADMINS:
        await update.message.reply_text("У вас нет доступа.")
        return

    thread_id = update.message.message_thread_id

    # Ищем тикет в основной группе
    for user_id, data in list(active_tickets.items()):
        if data["thread_id"] == thread_id:
            ban_until = datetime.datetime.now() + datetime.timedelta(days=7)
            banned_users[user_id] = ban_until

            if data["timeout_task"]:
                data["timeout_task"].cancel()
            del active_tickets[user_id]

            await context.bot.send_message(
                chat_id=ADMIN_GROUP_ID,
                message_thread_id=thread_id,
                text=
                f"<b>{ADMINS[admin_id]}</b> заблокировал пользователя {user_id} на 7 дней.",
                parse_mode=ParseMode.HTML)
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=
                    f"Вы были заблокированы в поддержке на 7 дней администратором {ADMINS[admin_id]}."
                )
            except:
                pass
            await context.bot.delete_forum_topic(chat_id=ADMIN_GROUP_ID,
                                                 message_thread_id=thread_id)
            await log_action(
                context,
                f"Администратор {ADMINS[admin_id]} заблокировал пользователя {user_id} на 7 дней"
            )
            return

    # Если не нашли в основной группе, ищем в группе высшей администрации
    for user_id, data in list(active_tickets_high.items()):
        if data["thread_id"] == thread_id:
            ban_until = datetime.datetime.now() + datetime.timedelta(days=7)
            banned_users[user_id] = ban_until

            if data["timeout_task"]:
                data["timeout_task"].cancel()
            del active_tickets_high[user_id]

            await context.bot.send_message(
                chat_id=HIGH_ADMIN_GROUP_ID,
                message_thread_id=thread_id,
                text=
                f"<b>{ADMINS[admin_id]}</b> заблокировал пользователя {user_id} на 7 дней.",
                parse_mode=ParseMode.HTML)
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=
                    f"Вы были заблокированы в поддержке на 7 дней администратором {ADMINS[admin_id]}."
                )
            except:
                pass
            await context.bot.delete_forum_topic(chat_id=HIGH_ADMIN_GROUP_ID,
                                                 message_thread_id=thread_id)
            await log_action(
                context,
                f"Администратор {ADMINS[admin_id]} заблокировал пользователя {user_id} на 7 дней"
            )
            return

    await update.message.reply_text(
        "Тикет для бана не найден в текущих группах.")


async def unban_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Разбан работает ТОЛЬКО в группе высшей администрации
    if update.message.chat_id != HIGH_ADMIN_GROUP_ID:
        await update.message.reply_text(
            "Разбан доступен только в группе высшей администрации.")
        return

    admin_id = update.effective_user.id
    if admin_id not in ADMINS:
        await update.message.reply_text("У тебя нет доступа.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /unbanReport <user_id>"
                                        )
        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Неверный user_id.")
        return

    if user_id not in banned_users:
        await update.message.reply_text(
            "Пользователь не в списке заблокированных.")
        return

    del banned_users[user_id]

    await update.message.reply_text(f"Пользователь {user_id} разблокирован.")

    await log_action(
        context,
        f"Администратор {ADMINS[admin_id]} разблокировал пользователя {user_id}"
    )


async def next_step_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Передача тикета высшей администрации
    admin_id = update.effective_user.id
    if admin_id not in ADMINS:
        await update.message.reply_text("У тебя нет доступа.")
        return

    thread_id = update.message.message_thread_id

    # Ищем тикет в обычной группе
    for user_id, data in list(active_tickets.items()):
        if data["thread_id"] == thread_id:
            # Удаляем тему из обычной группы
            await context.bot.delete_forum_topic(chat_id=ADMIN_GROUP_ID,
                                                 message_thread_id=thread_id)

            # Создаём новую тему в группе высшей администрации
            topic = await context.bot.create_forum_topic(
                chat_id=HIGH_ADMIN_GROUP_ID,
                name=f"ID: {user_id} - Администратор {ADMINS[admin_id]}")
            new_thread_id = topic.message_thread_id

            # Пингуем команды в новой теме
            await pin_commands(context, HIGH_ADMIN_GROUP_ID, new_thread_id)

            active_tickets_high[user_id] = {
                "thread_id": new_thread_id,
                "current_admin": None,
                "timeout_task": None,
            }
            del active_tickets[user_id]

            await context.bot.send_message(
                chat_id=HIGH_ADMIN_GROUP_ID,
                message_thread_id=new_thread_id,
                text=
                f"<b>{ADMINS[admin_id]}</b> передал тикет пользователя {user_id} на высшую администрацию.",
                parse_mode=ParseMode.HTML)
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=
                    "<blockquote>Ваш тикет передан на высшую администрацию.</blockquote>",
                    parse_mode=ParseMode.HTML)
            except:
                pass

            await log_action(
                context,
                f"Администратор {ADMINS[admin_id]} передал тикет пользователя {user_id} на высшую администрацию"
            )

            return


async def admin_relay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    thread_id = update.message.message_thread_id
    sender_id = update.effective_user.id

    if chat_id == ADMIN_GROUP_ID:
        tickets_dict = active_tickets
    elif chat_id == HIGH_ADMIN_GROUP_ID:
        tickets_dict = active_tickets_high
    else:
        return

    for user_id, data in tickets_dict.items():
        if data["thread_id"] == thread_id and data[
                "current_admin"] == sender_id:
            msg = update.message
            try:
                if msg.text:
                    await context.bot.send_message(chat_id=user_id,
                                                   text=msg.text)
                elif msg.photo:
                    await context.bot.send_photo(chat_id=user_id,
                                                 photo=msg.photo[-1].file_id,
                                                 caption=msg.caption or None)
                elif msg.document:
                    await context.bot.send_document(
                        chat_id=user_id,
                        document=msg.document.file_id,
                        caption=msg.caption or None)
                elif msg.sticker:
                    await context.bot.send_sticker(chat_id=user_id,
                                                   sticker=msg.sticker.file_id)
                elif msg.video:
                    await context.bot.send_video(chat_id=user_id,
                                                 video=msg.video.file_id,
                                                 caption=msg.caption or None)
                elif msg.voice:
                    await context.bot.send_voice(chat_id=user_id,
                                                 voice=msg.voice.file_id,
                                                 caption=msg.caption or None)
            except:
                pass
            return


def main():
    # Проверяем, запущен ли уже другой экземпляр
    pid_file = '/tmp/telegram_bot.pid'

    if os.path.exists(pid_file):
        with open(pid_file, 'r') as f:
            old_pid = f.read().strip()
        try:
            # Проверяем, активен ли процесс
            os.kill(int(old_pid), 0)
            print(f"Бот уже запущен с PID {old_pid}")
            sys.exit(1)
        except (OSError, ValueError):
            # Процесс не активен, удаляем старый PID файл
            os.remove(pid_file)

    # Записываем PID текущего процесса
    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))

    try:
        # Запускаем keep_alive если доступен
        if USE_KEEP_ALIVE:
            keep_alive()

        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("support", support))
        app.add_handler(CommandHandler("takeReport", take_report))
        app.add_handler(CommandHandler("closeReport", close_report))
        app.add_handler(CommandHandler("banReport", ban_report))
        app.add_handler(CommandHandler("unbanReport", unban_report))
        app.add_handler(CommandHandler("nextStepReport", next_step_report))

        app.add_handler(
            MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND,
                           relay_messages))
        app.add_handler(
            MessageHandler(filters.ChatType.SUPERGROUP & ~filters.COMMAND,
                           admin_relay))

        print("Запуск бота...")
        app.run_polling(drop_pending_updates=True)

    except Conflict as e:
        print(f"Конфликт: {e}")
        print("Другой экземпляр бота уже запущен. Завершение работы.")
        sys.exit(1)
    except Exception as e:
        print(f"Ошибка при запуске бота: {e}")
        sys.exit(1)
    finally:
        # Удаляем PID файл при завершении
        if os.path.exists(pid_file):
            os.remove(pid_file)


if __name__ == '__main__':
    main()
