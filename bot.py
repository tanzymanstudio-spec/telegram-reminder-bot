import asyncio
import sys
import sqlite3
import re
from datetime import datetime, timedelta

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor

import os
API_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
DB = "reminders.db"

# ================= DB =================

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            text TEXT,
            run_at REAL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            tz_offset REAL DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()


def add_db(chat_id, text, run_at):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute(
        "INSERT INTO reminders (chat_id, text, run_at) VALUES (?, ?, ?)",
        (chat_id, text, run_at)
    )
    conn.commit()
    rem_id = c.lastrowid
    conn.close()
    return rem_id


def load_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT id, chat_id, text, run_at FROM reminders")
    rows = c.fetchall()
    conn.close()
    return rows


def delete_db(rem_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM reminders WHERE id=?", (rem_id,))
    conn.commit()
    conn.close()

# ================= TZ =================

def get_tz(chat_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT tz_offset FROM users WHERE chat_id=?", (chat_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0


def set_tz(chat_id, offset):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users(chat_id, tz_offset) VALUES (?,?)", (chat_id, offset))
    conn.commit()
    conn.close()

# ================= UI =================

kb = ReplyKeyboardMarkup(resize_keyboard=True)
kb.add("➕ Создать")
kb.add("📋 Мои напоминания")
kb.add("🌍 Часовой пояс")
kb.add("❓ Помощь")

create_kb = ReplyKeyboardMarkup(resize_keyboard=True)
create_kb.add("⏱ Через секунды", "⏳ Через минуты")
create_kb.add("🕒 Через часы", "📅 Выбрать день")
create_kb.add("⬅️ Назад")

# 🌍 ГОРОДА + UTC
tz_kb = ReplyKeyboardMarkup(resize_keyboard=True)
tz_kb.add("🇺🇸 Лос-Анджелес (UTC-8)", "🇺🇸 Нью-Йорк (UTC-5)")
tz_kb.add("🇬🇧 Лондон (UTC+0)", "🇩🇪 Берлин (UTC+1)")
tz_kb.add("🇺🇦 Киев (UTC+2)", "🇷🇺 Москва (UTC+3)")
tz_kb.add("🇦🇪 Дубай (UTC+4)", "🇮🇳 Дели (UTC+5.5)")
tz_kb.add("🇰🇿 Алматы (UTC+6)", "🇷🇺 Новосибирск (UTC+7)")
tz_kb.add("🇨🇳 Пекин (UTC+8)", "🇯🇵 Токио (UTC+9)")
tz_kb.add("🇦🇺 Сидней (UTC+10)", "🇳🇿 Окленд (UTC+12)")

# ================= STATE =================

user_state = {}

# ================= WORKER =================

async def reminder_worker(rem_id, chat_id, text, delay, run_at):
    await asyncio.sleep(delay)

    rows = load_db()
    if rem_id not in [r[0] for r in rows]:
        return

    tz = get_tz(chat_id)
    dt = datetime.fromtimestamp(run_at) + timedelta(hours=tz)

    msg = (
        "🗂 <b>Напоминание</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"🕒 <b>{dt.strftime('%d.%m %H:%M')}</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"📝 {text}\n"
        "━━━━━━━━━━━━━━"
    )

    await bot.send_message(chat_id, msg, parse_mode="HTML")
    delete_db(rem_id)

# ================= RESTORE =================

async def restore():
    now = datetime.utcnow().timestamp()
    for rem_id, chat_id, text, run_at in load_db():
        delay = run_at - now
        if delay > 0:
            asyncio.create_task(reminder_worker(rem_id, chat_id, text, delay, run_at))

# ================= HANDLERS =================

@dp.message_handler(lambda m: m.text and m.text.lower() in ["/start", "start"])
async def start(m):
    await m.answer("👋 Бот напоминаний", reply_markup=kb)

# 🌍 TZ MENU
@dp.message_handler(lambda m: m.text and "часовой" in m.text.lower())
async def tz_menu(m):
    await m.answer("🌍 Выбери город:", reply_markup=tz_kb)

# 🌍 SET TZ
@dp.message_handler(lambda m: m.text and "(" in m.text and "UTC" in m.text)
async def set_timezone(m):
    match = re.search(r"UTC([+-]?\d+\.?\d*)", m.text)
    if not match:
        return await m.answer("❌ Ошибка")

    offset = float(match.group(1))
    set_tz(m.chat.id, offset)

    city = m.text.split("(")[0].strip()

    await m.answer(
        f"🌍 Установлено\n📍 {city}\n🕒 UTC{offset:+}",
        reply_markup=kb
    )

# ================= CREATE =================

@dp.message_handler(lambda m: m.text and "создать" in m.text.lower())
async def create(m):
    user_state[m.chat.id] = {"step": "choose_time"}
    await m.answer("Выбери тип времени 👇", reply_markup=create_kb)

@dp.message_handler(lambda m: m.text and "назад" in m.text.lower())
async def back(m):
    user_state.pop(m.chat.id, None)
    await m.answer("Главное меню", reply_markup=kb)

@dp.message_handler(lambda m: m.text and m.chat.id in user_state)
async def flow(m):
    st = user_state[m.chat.id]
    tz = get_tz(m.chat.id)

    if st["step"] == "choose_time":
        if "секунд" in m.text:
            st["unit"] = "seconds"
            st["step"] = "value"
            return await m.answer("Введи секунды")

        if "минут" in m.text:
            st["unit"] = "minutes"
            st["step"] = "value"
            return await m.answer("Введи минуты")

        if "час" in m.text:
            st["unit"] = "hours"
            st["step"] = "value"
            return await m.answer("Введи часы")

        if "день" in m.text:
            st["step"] = "date"
            return await m.answer("Введи дату ДД.ММ")

    if st.get("step") == "date":
        day, month = map(int, m.text.split("."))
        st["date"] = (day, month)
        st["step"] = "time"
        return await m.answer("Теперь время (12:30)")

    if st.get("step") == "time":
        h, mn = map(int, re.split("[:.]", m.text))
        now = datetime.utcnow() + timedelta(hours=tz)

        day, month = st["date"]
        run = datetime(now.year, month, day, h, mn)

        if run < now:
            run = datetime(now.year + 1, month, day, h, mn)

        run = run - timedelta(hours=tz)

        st["run"] = run
        st["step"] = "text"
        return await m.answer("Теперь текст")

    if st["step"] == "value":
        now = datetime.utcnow()

        if re.match(r"\d{1,2}[:.]\d{2}", m.text):
            h, mn = map(int, re.split("[:.]", m.text))
            run = (now + timedelta(hours=tz)).replace(hour=h, minute=mn, second=0, microsecond=0)

            if run < now + timedelta(hours=tz):
                run += timedelta(days=1)

            run = run - timedelta(hours=tz)
        else:
            val = int(m.text)

            if st["unit"] == "seconds":
                run = now + timedelta(seconds=val)
            elif st["unit"] == "minutes":
                run = now + timedelta(minutes=val)
            elif st["unit"] == "hours":
                run = now + timedelta(hours=val)

        st["run"] = run
        st["step"] = "text"
        return await m.answer("Теперь текст")

    if st["step"] == "text":
        text = m.text
        run = st["run"]

        ts = run.timestamp()
        rid = add_db(m.chat.id, text, ts)

        delay = ts - datetime.utcnow().timestamp()

        asyncio.create_task(
            reminder_worker(rid, m.chat.id, text, delay, ts)
        )

        user_state.pop(m.chat.id)

        show = run + timedelta(hours=tz)

        await m.answer(
            f"🗂 Создано\n🕒 {show.strftime('%d.%m %H:%M')}\n📝 {text}",
            reply_markup=kb
        )

# ================= LIST =================

@dp.message_handler(lambda m: m.text and "мои" in m.text.lower())
async def my(m):
    rows = [r for r in load_db() if r[1] == m.chat.id]

    if not rows:
        return await m.answer("📭 пусто")

    tz = get_tz(m.chat.id)

    txt = "🗂 Напоминания\n\n"

    for i, (_, _, t, rt) in enumerate(rows, 1):
        dt = datetime.fromtimestamp(rt) + timedelta(hours=tz)
        txt += f"{i}. 🕒 {dt.strftime('%d.%m %H:%M')}\n📝 {t}\n\n"

    await m.answer(txt)

# ================= DELETE =================

@dp.message_handler(lambda m: m.text and m.text.lower().startswith("удали"))
async def delete(m):
    rows = [r for r in load_db() if r[1] == m.chat.id]

    idx = int(m.text.split()[1]) - 1
    delete_db(rows[idx][0])

    await m.answer("🗑 удалено")

# ================= HELP =================

@dp.message_handler(lambda m: m.text and "помощь" in m.text.lower())
async def help(m):
    await m.answer(
        "❓ Как пользоваться\n\n"
        "➕ Создание:\n"
        "1. Нажми 'Создать'\n"
        "2. Выбери тип времени\n"
        "3. Введи данные\n"
        "4. Введи текст\n\n"
        "🕒 Время:\n"
        "• можно писать 12:30 или 12.30\n\n"
        "📅 Дата:\n"
        "• сначала вводишь 25.12\n"
        "• потом время 14:00\n\n"
        "🗑 Удаление:\n"
        "1. Нажми 'Мои напоминания'\n"
        "2. Посмотри номер (например 1)\n"
        "3. Напиши: удали 1\n"
    )

# ================= BOOT =================

if __name__ == "__main__":
    init_db()

    async def on_startup(dp):
        asyncio.create_task(restore())

    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)