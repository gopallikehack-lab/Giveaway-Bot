"""
GpsirEra Giveaway Bot — Cron endpoint.
Must be pinged every ~1 minute by an EXTERNAL scheduler (e.g. cron-job.org, free)
because Vercel's own free-tier Cron only runs once per day, which is useless
for 15/20-minute giveaways.

GET /api/cron?key=<CRON_SECRET>
"""

import json
import os
import random
import time
from http.server import BaseHTTPRequestHandler
from urllib import request as urlrequest
from urllib.parse import urlparse, parse_qs

BOT_TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{BOT_TOKEN}"
RESULTS_CHANNEL_ID = int(os.environ["RESULTS_CHANNEL_ID"])
CRON_SECRET = os.environ.get("CRON_SECRET", "")

UPSTASH_URL = os.environ["UPSTASH_REDIS_REST_URL"]
UPSTASH_TOKEN = os.environ["UPSTASH_REDIS_REST_TOKEN"]


def redis_cmd(*args):
    req = urlrequest.Request(
        UPSTASH_URL,
        data=json.dumps(list(args)).encode(),
        headers={"Authorization": f"Bearer {UPSTASH_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read()).get("result")


def get_json(key, default=None):
    val = redis_cmd("GET", key)
    return json.loads(val) if val else default


def set_json(key, value):
    redis_cmd("SET", key, json.dumps(value))


def send_message(chat_id, text):
    req = urlrequest.Request(
        f"{API}/sendMessage",
        data=json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"Telegram send error: {e}")


def end_giveaway(gid, gw):
    gw["status"] = "ended"
    joiners = gw["joiners"]
    n_winners = min(gw["winners_count"], len(joiners))
    winners = random.sample(joiners, n_winners) if n_winners > 0 else []
    gw["winners"] = winners
    set_json(f"giveaway:{gid}", gw)

    if winners:
        winner_lines = "\n".join(
            f"🏆 {w['name']} (@{w['username']})" if w["username"] else f"🏆 {w['name']} (id: {w['id']})"
            for w in winners
        )
    else:
        winner_lines = "No one joined this giveaway. 😔"

    result_text = (
        f"🎉 <b>Giveaway Ended: {gw['title']}</b>\n\n"
        f"👥 Total Participants: {len(joiners)}\n\n<b>Winners:</b>\n{winner_lines}\n\nCongratulations! 🎊"
    )
    send_message(RESULTS_CHANNEL_ID, result_text)
    for w in winners:
        send_message(
            w["id"],
            f"🎉 Congratulations! You won the giveaway <b>{gw['title']}</b>!\n\nContact @GpsirEra to claim your prize.",
        )


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        key = query.get("key", [""])[0]
        if not CRON_SECRET or key != CRON_SECRET:
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"Unauthorized")
            return

        active_ids = get_json("active_ids", [])
        now = time.time()
        still_active = []
        ended = 0
        for gid in active_ids:
            gw = get_json(f"giveaway:{gid}")
            if not gw or gw.get("status") != "active":
                continue
            if gw["end_time"] <= now:
                end_giveaway(gid, gw)
                ended += 1
            else:
                still_active.append(gid)
        set_json("active_ids", still_active)

        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(f"OK - checked {len(active_ids)}, ended {ended}".encode())    not_joined = []
    for ch in FORCE_JOIN_CHANNELS:
        try:
            member = await context.bot.get_chat_member(ch["chat_id"], user_id)
            if member.status in ("left", "kicked"):
                not_joined.append(ch)
        except Exception as e:
            log.warning("Membership check failed for %s: %s", ch["name"], e)
            not_joined.append(ch)
    return not_joined


def force_join_keyboard(not_joined: list) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"➕ Join {ch['name']}", url=ch["link"])] for ch in not_joined]
    rows.append([InlineKeyboardButton("✅ I've Joined — Verify", callback_data="verify_join")])
    return InlineKeyboardMarkup(rows)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎁 Active Giveaway", callback_data="menu_active")],
            [InlineKeyboardButton("💎 Premium Account", callback_data="menu_premium")],
            [InlineKeyboardButton("👤 Owner Info", callback_data="menu_owner")],
        ]
    )


WELCOME_TEXT = (
    "✨ <b>Welcome to GpsirEra Premium Bot</b> ✨\n\n"
    "You're verified! Choose an option below to continue. 👇"
)


async def send_main_menu(update_or_query, edit: bool = False):
    if edit:
        await update_or_query.edit_message_text(
            WELCOME_TEXT, reply_markup=main_menu_keyboard(), parse_mode=ParseMode.HTML
        )
    else:
        await update_or_query.message.reply_text(
            WELCOME_TEXT, reply_markup=main_menu_keyboard(), parse_mode=ParseMode.HTML
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    not_joined = await check_membership(user_id, context)
    if not_joined:
        await update.message.reply_text(
            "🔐 <b>Verification Required</b>\n\n"
            "Please join the channel(s) below, then tap <b>I've Joined</b>.",
            reply_markup=force_join_keyboard(not_joined),
            parse_mode=ParseMode.HTML,
        )
        return
    await send_main_menu(update)


async def verify_join_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    not_joined = await check_membership(user_id, context)
    if not_joined:
        await query.answer("❌ You haven't joined all channels yet.", show_alert=True)
        await query.edit_message_text(
            "🔐 <b>Verification Required</b>\n\n"
            "Please join the channel(s) below, then tap <b>I've Joined</b>.",
            reply_markup=force_join_keyboard(not_joined),
            parse_mode=ParseMode.HTML,
        )
        return
    await query.answer("✅ Verified!")
    await send_main_menu(query, edit=True)


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your Telegram ID: `{update.effective_user.id}`", parse_mode=ParseMode.MARKDOWN)


def back_button(target="menu_back"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=target)]])


# ============================== OWNER INFO / PREMIUM (user side) =====================================

async def menu_owner_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(OWNER_INFO_TEXT, reply_markup=back_button(), parse_mode=ParseMode.HTML)


async def menu_premium_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = load_data()
    text = data.get("premium_text") or "No premium account info has been added yet."
    text += "\n\n📩 Contact Me: @GpsirEra"
    await query.edit_message_text(
        f"💎 <b>Premium Account</b>\n\n{text}", reply_markup=back_button(), parse_mode=ParseMode.HTML
    )


async def menu_back_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await send_main_menu(query, edit=True)


# ============================== ACTIVE GIVEAWAY (user side) =====================================

def giveaway_list_keyboard(data: dict) -> InlineKeyboardMarkup:
    rows = []
    for gid, gw in data["giveaways"].items():
        if gw["status"] == "active":
            rows.append([InlineKeyboardButton(f"🎁 {gw['title']}", callback_data=f"view_gw_{gid}")])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="menu_back")])
    return InlineKeyboardMarkup(rows)


async def menu_active_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = load_data()
    active = [g for g in data["giveaways"].values() if g["status"] == "active"]
    if not active:
        await query.edit_message_text(
            "🎁 <b>Active Giveaway</b>\n\nNo giveaways running right now. Check back soon!",
            reply_markup=back_button(),
            parse_mode=ParseMode.HTML,
        )
        return
    await query.edit_message_text(
        "🎁 <b>Active Giveaway</b>\n\nSelect a giveaway to view details:",
        reply_markup=giveaway_list_keyboard(data),
        parse_mode=ParseMode.HTML,
    )


def giveaway_detail_text(gw: dict) -> str:
    remaining = max(0, int(gw["end_time"] - time.time()))
    mins, secs = divmod(remaining, 60)
    return (
        f"🎁 <b>{gw['title']}</b>\n\n"
        f"{gw['desc']}\n\n"
        f"🏆 Winners: {gw['winners_count']}\n"
        f"👥 Joined: {len(gw['joiners'])}\n"
        f"⏳ Time Left: {mins}m {secs}s"
    )


async def view_gw_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    gid = query.data.split("_")[-1]
    data = load_data()
    gw = data["giveaways"].get(gid)
    if not gw or gw["status"] != "active":
        await query.answer("This giveaway has ended.", show_alert=True)
        await menu_active_cb(update, context)
        return
    await query.answer()
    joined_ids = {j["id"] for j in gw["joiners"]}
    already = query.from_user.id in joined_ids
    kb = [
        [InlineKeyboardButton(
            "✅ Joined" if already else "🎉 Join Giveaway",
            callback_data=f"join_{gid}",
        )],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_active")],
    ]
    await query.edit_message_text(
        giveaway_detail_text(gw), reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML
    )


async def join_gw_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    gid = query.data.split("_")[-1]
    data = load_data()
    gw = data["giveaways"].get(gid)
    if not gw or gw["status"] != "active":
        await query.answer("This giveaway has ended.", show_alert=True)
        return
    user = query.from_user
    joined_ids = {j["id"] for j in gw["joiners"]}
    if user.id in joined_ids:
        await query.answer("You already joined this giveaway!", show_alert=True)
        return
    gw["joiners"].append(
        {"id": user.id, "name": user.full_name, "username": user.username or ""}
    )
    save_data(data)
    await query.answer("✅ You joined this giveaway! Good luck 🍀", show_alert=True)
    kb = [
        [InlineKeyboardButton("✅ Joined", callback_data=f"join_{gid}")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_active")],
    ]
    await query.edit_message_text(
        giveaway_detail_text(gw), reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML
    )


# ============================== ADMIN PANEL =====================================

def admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Add Giveaway", callback_data="admin_add_gw")],
            [InlineKeyboardButton("💎 Set Premium Content", callback_data="admin_set_premium")],
            [InlineKeyboardButton("📋 List Active Giveaways", callback_data="admin_list_gw")],
        ]
    )


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ You are not authorized to use the admin panel.")
        return
    await update.message.reply_text(
        "🛠 <b>Admin Panel</b>\n\nChoose an action:", reply_markup=admin_menu_keyboard(), parse_mode=ParseMode.HTML
    )


async def admin_list_gw_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    data = load_data()
    active = [g for g in data["giveaways"].values() if g["status"] == "active"]
    if not active:
        text = "No active giveaways."
    else:
        lines = []
        for gw in active:
            remaining = max(0, int(gw["end_time"] - time.time()))
            lines.append(f"🎁 {gw['title']} — {len(gw['joiners'])} joined — {remaining // 60}m left")
        text = "\n".join(lines)
    await query.edit_message_text(text, reply_markup=admin_menu_keyboard())


# ---- Add Giveaway conversation ----

async def admin_add_gw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return ConversationHandler.END
    context.user_data["new_gw"] = {}
    await query.edit_message_text("📝 Send the <b>giveaway title</b>:", parse_mode=ParseMode.HTML)
    return GW_TITLE


async def admin_add_gw_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_gw"]["title"] = update.message.text.strip()
    await update.message.reply_text(
        "📝 Now send the <b>giveaway details</b> (prize, rules, whatever you want shown):",
        parse_mode=ParseMode.HTML,
    )
    return GW_DESC


async def admin_add_gw_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_gw"]["desc"] = update.message.text.strip()
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⏱ 15 min", callback_data="dur_15"),
                InlineKeyboardButton("⏱ 20 min", callback_data="dur_20"),
            ],
            [InlineKeyboardButton("✏️ Custom Time", callback_data="dur_custom")],
        ]
    )
    await update.message.reply_text("⏳ Choose the giveaway duration:", reply_markup=kb)
    return GW_DURATION


async def admin_add_gw_duration_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data
    if choice == "dur_15":
        context.user_data["new_gw"]["duration_min"] = 15
        await query.edit_message_text("🏆 How many winners should this giveaway have? Send a number:")
        return GW_WINNERS
    if choice == "dur_20":
        context.user_data["new_gw"]["duration_min"] = 20
        await query.edit_message_text("🏆 How many winners should this giveaway have? Send a number:")
        return GW_WINNERS
    # custom
    await query.edit_message_text("✏️ Send the custom duration in minutes (e.g. 45):")
    context.user_data["awaiting_custom_duration"] = True
    return GW_DURATION


async def admin_add_gw_custom_duration_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_custom_duration"):
        return GW_DURATION
    try:
        minutes = int(update.message.text.strip())
        if minutes <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Please send a valid positive number of minutes.")
        return GW_DURATION
    context.user_data["new_gw"]["duration_min"] = minutes
    context.user_data["awaiting_custom_duration"] = False
    await update.message.reply_text("🏆 How many winners should this giveaway have? Send a number:")
    return GW_WINNERS


async def admin_add_gw_winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        winners = int(update.message.text.strip())
        if winners <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Please send a valid positive number.")
        return GW_WINNERS

    gw_info = context.user_data.pop("new_gw")
    gw_info["winners_count"] = winners
    duration_seconds = gw_info.pop("duration_min") * 60

    data = load_data()
    gid = str(data["next_id"])
    data["next_id"] += 1
    data["giveaways"][gid] = {
        "title": gw_info["title"],
        "desc": gw_info["desc"],
        "winners_count": winners,
        "joiners": [],
        "status": "active",
        "end_time": time.time() + duration_seconds,
    }
    save_data(data)

    context.job_queue.run_once(end_giveaway_job, duration_seconds, data={"gid": gid}, name=f"gw_end_{gid}")

    await update.message.reply_text(
        f"✅ Giveaway <b>{gw_info['title']}</b> created and is now live for {duration_seconds // 60} minutes!",
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


# ---- Set Premium Content conversation ----

async def admin_set_premium_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return ConversationHandler.END
    await query.edit_message_text(
        "💎 Send the new <b>Premium Account</b> content/text (this is shown to all users):",
        parse_mode=ParseMode.HTML,
    )
    return PREMIUM_TEXT_STATE


async def admin_set_premium_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    data["premium_text"] = update.message.text.strip()
    save_data(data)
    await update.message.reply_text("✅ Premium Account content updated.")
    return ConversationHandler.END


async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END


# ============================== GIVEAWAY END JOB =====================================

async def end_giveaway_job(context: ContextTypes.DEFAULT_TYPE):
    gid = context.job.data["gid"]
    data = load_data()
    gw = data["giveaways"].get(gid)
    if not gw or gw["status"] != "active":
        return
    gw["status"] = "ended"

    joiners = gw["joiners"]
    n_winners = min(gw["winners_count"], len(joiners))
    winners = random.sample(joiners, n_winners) if n_winners > 0 else []
    gw["winners"] = winners
    save_data(data)

    if winners:
        winner_lines = "\n".join(
            f"🏆 {w['name']} (@{w['username']})" if w["username"] else f"🏆 {w['name']} (id: {w['id']})"
            for w in winners
        )
    else:
        winner_lines = "No one joined this giveaway. 😔"

    result_text = (
        f"🎉 <b>Giveaway Ended: {gw['title']}</b>\n\n"
        f"👥 Total Participants: {len(joiners)}\n\n"
        f"<b>Winners:</b>\n{winner_lines}\n\n"
        f"Congratulations! 🎊"
    )

    try:
        await context.bot.send_message(RESULTS_CHANNEL_ID, result_text, parse_mode=ParseMode.HTML)
    except Exception as e:
        log.error("Failed to post results to channel: %s", e)

    for w in winners:
        try:
            await context.bot.send_message(
                w["id"],
                f"🎉 Congratulations! You won the giveaway <b>{gw['title']}</b>!\n\n"
                f"Contact @GpsirEra to claim your prize.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


# ============================== MAIN =====================================

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("myid", myid))

    app.add_handler(CallbackQueryHandler(verify_join_cb, pattern="^verify_join$"))
    app.add_handler(CallbackQueryHandler(menu_back_cb, pattern="^menu_back$"))
    app.add_handler(CallbackQueryHandler(menu_owner_cb, pattern="^menu_owner$"))
    app.add_handler(CallbackQueryHandler(menu_premium_cb, pattern="^menu_premium$"))
    app.add_handler(CallbackQueryHandler(menu_active_cb, pattern="^menu_active$"))
    app.add_handler(CallbackQueryHandler(view_gw_cb, pattern="^view_gw_"))
    app.add_handler(CallbackQueryHandler(join_gw_cb, pattern="^join_"))
    app.add_handler(CallbackQueryHandler(admin_list_gw_cb, pattern="^admin_list_gw$"))

    add_gw_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_gw_start, pattern="^admin_add_gw$")],
        states={
            GW_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_gw_title)],
            GW_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_gw_desc)],
            GW_DURATION: [
                CallbackQueryHandler(admin_add_gw_duration_cb, pattern="^dur_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_gw_custom_duration_text),
            ],
            GW_WINNERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_gw_winners)],
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)],
    )
    app.add_handler(add_gw_conv)

    set_premium_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_set_premium_start, pattern="^admin_set_premium$")],
        states={
            PREMIUM_TEXT_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_set_premium_text)],
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)],
    )
    app.add_handler(set_premium_conv)

    log.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
