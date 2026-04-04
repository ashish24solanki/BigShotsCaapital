import sqlite3
import time
import threading
from datetime import datetime, timedelta

from telegram import Update, ChatMember
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    ChatMemberHandler,
)

from config.paths import DB_DIR
from config.bot_config import BOT_TOKEN, ADMIN_CHAT_ID, PRO_CHAT_ID

# ==================================================
# CONFIG
# ==================================================
MEMBERS_DB = f"{DB_DIR}/members.db"

PLAN_DAYS = 365
REMIND_DAYS = [7, 3, 1]     # days before expiry
AUTO_REMOVE = False        # keep False initially

CHECK_INTERVAL_SECONDS = 60 * 60 * 6   # every 6 hours

# ==================================================
# DB INIT
# ==================================================
def init_db():
    db = sqlite3.connect(MEMBERS_DB)
    c = db.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS members (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            join_date TEXT,
            expiry_date TEXT,
            status TEXT
        )
    """)
    db.commit()
    db.close()

# ==================================================
# DB HELPERS
# ==================================================
def add_member(user_id, username):
    join_date = datetime.now()
    expiry_date = join_date + timedelta(days=PLAN_DAYS)

    db = sqlite3.connect(MEMBERS_DB)
    c = db.cursor()
    c.execute("""
        INSERT OR REPLACE INTO members
        VALUES (?, ?, ?, ?, ?)
    """, (
        user_id,
        username,
        join_date.strftime("%Y-%m-%d"),
        expiry_date.strftime("%Y-%m-%d"),
        "ACTIVE"
    ))
    db.commit()
    db.close()

def get_members():
    db = sqlite3.connect(MEMBERS_DB)
    rows = db.execute("SELECT * FROM members").fetchall()
    db.close()
    return rows

def update_status(user_id, status):
    db = sqlite3.connect(MEMBERS_DB)
    db.execute(
        "UPDATE members SET status=? WHERE user_id=?",
        (status, user_id)
    )
    db.commit()
    db.close()

# ==================================================
# JOIN / LEAVE TRACKING
# ==================================================
async def track_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.chat_member.chat
    if str(chat.id) != PRO_CHAT_ID:
        return

    old = update.chat_member.old_chat_member
    new = update.chat_member.new_chat_member
    user = new.user

    # USER JOINED
    if old.status in [ChatMember.LEFT, ChatMember.KICKED] and new.status == ChatMember.MEMBER:
        add_member(user.id, user.username or "")
        await context.bot.send_message(
            ADMIN_CHAT_ID,
            f"➕ New Member Joined\n"
            f"User: @{user.username}\n"
            f"ID: {user.id}"
        )

    # USER LEFT
    if old.status == ChatMember.MEMBER and new.status in [ChatMember.LEFT, ChatMember.KICKED]:
        update_status(user.id, "LEFT")
        await context.bot.send_message(
            ADMIN_CHAT_ID,
            f"➖ Member Left\n"
            f"User: @{user.username}\n"
            f"ID: {user.id}"
        )

# ==================================================
# EXPIRY CHECK WORKER (THREAD)
# ==================================================
def expiry_worker(app):
    while True:
        today = datetime.now().date()

        for user_id, username, join_dt, exp_dt, status in get_members():
            if status != "ACTIVE":
                continue

            expiry = datetime.strptime(exp_dt, "%Y-%m-%d").date()
            days_left = (expiry - today).days

            # REMINDERS
            if days_left in REMIND_DAYS:
                app.bot.send_message(
                    chat_id=user_id,
                    text=(
                        "⚠️ BigShots Capital Subscription\n\n"
                        f"Your access expires in {days_left} day(s).\n"
                        "Please renew to avoid removal."
                    )
                )

            # EXPIRED
            if days_left <= 0:
                app.bot.send_message(
                    chat_id=user_id,
                    text=(
                        "⛔ Your BigShots Capital subscription has expired.\n"
                        "Please renew to regain access."
                    )
                )

                update_status(user_id, "EXPIRED")

                if AUTO_REMOVE:
                    try:
                        app.bot.ban_chat_member(PRO_CHAT_ID, user_id)
                    except Exception:
                        pass

        time.sleep(CHECK_INTERVAL_SECONDS)

# ==================================================
# MAIN
# ==================================================
def main():
    print("🚀 BigShots Capital Membership Bot Started")

    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(ChatMemberHandler(track_member, ChatMemberHandler.CHAT_MEMBER))

    # Start expiry checker thread
    t = threading.Thread(target=expiry_worker, args=(app,), daemon=True)
    t.start()

    app.run_polling()

# ==================================================
if __name__ == "__main__":
    main()
