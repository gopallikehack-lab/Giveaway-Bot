"""
GpsirEra Premium Giveaway Bot — single-file Vercel webhook handler.
Fully self-contained (stdlib only) to avoid Vercel Python import issues.

NO CRON. NO EXTERNAL SCHEDULER. Everything is manual and admin-controlled:
  - Admin creates a giveaway (title, details, duration shown as info only)
  - Users join from inside the bot
  - Whenever the admin wants, they open /roulette (or /admin → Manage Giveaways),
    pick the giveaway, and tap "Draw Winner" — the bot instantly picks winner(s)
    and shows their FULL details (name, username, chat ID) to the admin ONLY.
    Nothing is ever posted publicly or to any group/channel.

Storage: Upstash Redis (free tier) via its REST API.
"""

import json
import os
import random
import re
import time
from http.server import BaseHTTPRequestHandler
from urllib import request as urlrequest

# ============================== CONFIG (Vercel Env Vars) ==================

BOT_TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]

CHANNEL1_ID = int(os.environ["CHANNEL1_ID"])
CHANNEL2_ID = int(os.environ["CHANNEL2_ID"])
CHANNEL3_ID = int(os.environ["CHANNEL3_ID"])
FORCE_JOIN_CHANNELS = [
    {"name": "Gpsir Giveaway Channel", "chat_id": CHANNEL3_ID, "link": "https://t.me/+0w8ATlAukVA1MWU1"},
    {"name": "Gpsir ha4k Channel", "chat_id": CHANNEL1_ID, "link": "https://t.me/+74PC9DgmtN84NzFl"},
    {"name": "Gpsir Chat Group", "chat_id": CHANNEL2_ID, "link": "https://t.me/+VXs73pFfyEphMzJl"},
]

WELCOME_PHOTO_URL = "https://i.ibb.co/WpcdVFP0/file-0000000079dc81f5b57e72408da59449.png"

UPSTASH_URL = os.environ["UPSTASH_REDIS_REST_URL"]
UPSTASH_TOKEN = os.environ["UPSTASH_REDIS_REST_TOKEN"]

# ============================== TEXT STYLE (single place to tweak the look) ========

def header(title):
    return f"『 {title} 』\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬"


DIV = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬"

# Premium animated/custom emoji (Telegram Premium sticker-set emoji, rendered via
# <tg-emoji> — visible to ALL users, sending doesn't require the bot to have
# Premium). Note: Telegram does NOT support custom emoji inside inline button
# labels (Bot API only allows plain text there) — these are for message text only.
EMOJI_MONEY = '<tg-emoji emoji-id="4965219701572503640">💰</tg-emoji>'
EMOJI_GIFT = '<tg-emoji emoji-id="5280615440928758599">🎁</tg-emoji>'
EMOJI_FLOWER = '<tg-emoji emoji-id="5208726561796146418">💐</tg-emoji>'
EMOJI_RIBBON = '<tg-emoji emoji-id="5190725129792929407">🎀</tg-emoji>'
EMOJI_GIFT2 = '<tg-emoji emoji-id="5449577822265840863">🎁</tg-emoji>'
EMOJI_GIFT3 = '<tg-emoji emoji-id="6093780439439249308">🎁</tg-emoji>'

# ============================== STORAGE (Upstash Redis REST) ==================

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


def delete_key(key):
    redis_cmd("DEL", key)


# ============================== TELEGRAM API HELPERS ==================

def strip_html(text):
    return re.sub(r"<[^>]+>", "", text)


def tg_call(method, payload):
    req = urlrequest.Request(
        f"{API}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"Telegram API error ({method}): {e}")
        return {"ok": False, "error": str(e)}


def send_message(chat_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard:
        payload["reply_markup"] = keyboard
    res = tg_call("sendMessage", payload)
    if not res.get("ok"):
        print(f"sendMessage failed for {chat_id}: {res}")
        payload_plain = {"chat_id": chat_id, "text": strip_html(text)}
        if keyboard:
            payload_plain["reply_markup"] = keyboard
        res = tg_call("sendMessage", payload_plain)
    return res


def send_photo(chat_id, photo_url, caption=None):
    payload = {"chat_id": chat_id, "photo": photo_url, "parse_mode": "HTML"}
    if caption:
        payload["caption"] = caption
    return tg_call("sendPhoto", payload)


def edit_message(chat_id, message_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if keyboard:
        payload["reply_markup"] = keyboard
    return tg_call("editMessageText", payload)


def answer_callback(callback_id, text=None, alert=False):
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = alert
    return tg_call("answerCallbackQuery", payload)


def get_chat_member(chat_id, user_id):
    return tg_call("getChatMember", {"chat_id": chat_id, "user_id": user_id})


def kb(rows):
    return {"inline_keyboard": rows}


def btn(text, data=None, url=None):
    return {"text": text, "callback_data": data} if data else {"text": text, "url": url}


def back_kb(target="menu_back"):
    return kb([[btn("🔙 Back", data=target)]])


def cancel_kb():
    return kb([[btn("🔙 Cancel", data="admin_cancel")]])


def is_admin(user_id):
    return user_id in ADMIN_IDS


def track_user(user):
    """Remember every user who has ever interacted with the bot, and map their
    username -> id so admin can ban/unban by username later."""
    uid = user["id"]
    users = get_json("all_users", [])
    if uid not in users:
        users.append(uid)
        set_json("all_users", users)
    username = user.get("username")
    if username:
        set_json(f"username_map:{username.lower()}", uid)


def is_banned(user_id):
    return user_id in get_json("banned_users", [])


# ============================== FORCE JOIN ==================

def check_membership(user_id):
    not_joined = []
    for ch in FORCE_JOIN_CHANNELS:
        res = get_chat_member(ch["chat_id"], user_id)
        status = res.get("result", {}).get("status") if res.get("ok") else None
        if status not in ("member", "administrator", "creator"):
            not_joined.append(ch)
    return not_joined


def force_join_keyboard(not_joined):
    rows = [[btn(f"📢 Join {ch['name']}", url=ch["link"])] for ch in not_joined]
    rows.append([btn("✅ Verify", data="verify_join")])
    return kb(rows)


FORCE_JOIN_TEXT = (
    f"{header('ACCESS LOCKED')}\n\n"
    "🔐 Join the channel(s) below to unlock the bot.\n\n"
    "Then tap <b>✅ Verify</b>."
)

WELCOME_TEXT = (
    f"{header('MAIN MENU')}\n\n"
    "✅ Verified — you're in.\n\n"
    "Select an option below 👇"
)

WELCOME_CAPTION = (
    f"{header('GPSIRERA')}\n\n"
    "✦ Premium Giveaway &amp; Rewards Bot ✦\n\n"
    f"{EMOJI_GIFT} Fair, verified giveaways\n"
    f"{EMOJI_MONEY} Premium account access\n"
    "🔒 Every winner picked by true random draw\n\n"
    f"{DIV}\n"
    "Maintained by <b>@GpsirEra</b>"
)

OWNER_INFO_TEXT = (
    f"{header('OWNER')}\n\n"
    "<b>Gopal Parmar</b>\n"
    "<i>GpsirEra</i>\n\n"
    "▸ Specialist Coder\n"
    "▸ Open Bullet Expert\n"
    "▸ AI Coder\n"
    "▸ API Builder\n\n"
    f"{DIV}\n"
    "📩 <b>@GpsirEra</b>"
)


def main_menu_keyboard():
    return kb(
        [
            [btn("🎉 Active Giveaways", data="menu_active")],
            [btn("💎 Premium Account", data="menu_premium")],
            [btn("👑 Owner Info", data="menu_owner")],
        ]
    )


# ============================== GIVEAWAY HELPERS ==================

def get_admin_state(user_id):
    return get_json(f"admin_state:{user_id}")


def set_admin_state(user_id, state):
    set_json(f"admin_state:{user_id}", state)


def clear_admin_state(user_id):
    delete_key(f"admin_state:{user_id}")


def giveaway_detail_text(gw):
    remaining = max(0, int(gw["end_time"] - time.time()))
    mins, secs = divmod(remaining, 60)
    return (
        f"{header(gw['title'])}\n\n"
        f"{gw['desc']}\n\n"
        f"{EMOJI_RIBBON} Winners: <b>{gw['winners_count']}</b>\n"
        f"▸ Participants: <b>{len(gw['joiners'])}</b>\n"
        f"▸ Time Left: <b>{mins}m {secs}s</b>\n\n"
        f"🔒 <i>Winner picked live by the admin via random draw — never public.</i>"
    )


def participant_list_text(joiners):
    if not joiners:
        return "No one has joined yet."
    return "\n".join(
        f"<b>{i + 1}.</b> {j['name']} — @{j['username'] if j['username'] else 'no_username'} — ID: <code>{j['id']}</code>"
        for i, j in enumerate(joiners)
    )


def manage_detail_text(gw):
    status_label = "🟢 Active" if gw["status"] == "active" else "✅ Completed"
    text = (
        f"{header(gw['title'])}\n\n"
        f"Status: {status_label}\n"
        f"👥 Participants: <b>{len(gw['joiners'])}</b>\n"
        f"🏆 Winners to pick: <b>{gw['winners_count']}</b>\n\n"
        f"<b>PARTICIPANTS</b>\n{DIV}\n"
        f"{participant_list_text(gw['joiners'])}\n{DIV}"
    )
    if gw["status"] == "completed" and gw.get("winners"):
        winner_lines = "\n".join(
            f"{EMOJI_GIFT2} {w['name']} (@{w['username'] if w['username'] else 'no_username'}) — ID: {w['id']}"
            for w in gw["winners"]
        )
        text += f"\n\n<b>WINNER(S)</b>\n{DIV}\n{winner_lines}"
    return text


def create_giveaway(title, desc, duration_min, winners):
    next_id = get_json("next_id", 1)
    gid = str(next_id)
    set_json("next_id", next_id + 1)
    gw = {
        "title": title,
        "desc": desc,
        "winners_count": winners,
        "joiners": [],
        "status": "active",
        "end_time": time.time() + duration_min * 60,
    }
    set_json(f"giveaway:{gid}", gw)
    all_ids = get_json("all_giveaway_ids", [])
    all_ids.append(gid)
    set_json("all_giveaway_ids", all_ids)


def draw_winner(gid, gw):
    """Instantly pick winner(s) — admin-only, never posted anywhere else."""
    joiners = gw["joiners"]
    n_winners = min(gw["winners_count"], len(joiners))
    winners = random.sample(joiners, n_winners) if n_winners > 0 else []
    gw["status"] = "completed"
    gw["winners"] = winners
    set_json(f"giveaway:{gid}", gw)

    if winners:
        winner_lines = "\n\n".join(
            f"{EMOJI_GIFT3} <b>{w['name']}</b>\n"
            f"    Username: {'@' + w['username'] if w['username'] else '<i>not set</i>'}\n"
            f"    Chat ID: <code>{w['id']}</code>"
            for w in winners
        )
    else:
        winner_lines = "No one joined this giveaway."

    return (
        f"{header('WINNER DRAWN')}\n\n"
        f"🎯 <b>{gw['title']}</b>\n"
        f"👥 Participants: <b>{len(joiners)}</b>\n\n"
        f"🌀 <i>Drawing…</i>\n\n"
        f"<b>WINNER{'S' if len(winners) != 1 else ''}</b>\n{DIV}\n"
        f"{winner_lines}\n{DIV}\n\n"
        f"🔒 <i>Visible only to you — nothing was posted publicly.</i>\n\n"
        f"{EMOJI_FLOWER} 🤞🥀"
    )


# ============================== ROUTES: /start, /admin, /myid, /roulette ==================

def handle_start(chat_id, user_id):
    send_photo(chat_id, WELCOME_PHOTO_URL, WELCOME_CAPTION)
    not_joined = check_membership(user_id)
    if not_joined:
        send_message(chat_id, FORCE_JOIN_TEXT, force_join_keyboard(not_joined))
        return
    send_message(chat_id, WELCOME_TEXT, main_menu_keyboard())


def admin_menu_keyboard():
    return kb(
        [
            [btn("🎯 Add Giveaway", data="admin_add_gw")],
            [btn("💎 Set Premium Content", data="admin_set_premium")],
            [btn("📋 Manage Giveaways", data="admin_manage")],
            [btn("🚫 Ban / Unban User", data="admin_ban")],
            [btn("📢 Broadcast Message", data="admin_broadcast")],
        ]
    )


def handle_admin_command(chat_id, user_id):
    if not is_admin(user_id):
        send_message(chat_id, "⛔ You are not authorized to use the admin panel.")
        return
    send_message(chat_id, f"{header('ADMIN PANEL')}\n\nChoose an action:", admin_menu_keyboard())


def manage_list_keyboard():
    ids = get_json("all_giveaway_ids", [])
    rows = []
    for gid in reversed(ids):  # newest first
        gw = get_json(f"giveaway:{gid}")
        if not gw:
            continue
        icon = "🟢" if gw["status"] == "active" else "✅"
        rows.append([btn(f"{icon} {gw['title']} ({len(gw['joiners'])} joined)", data=f"manage_{gid}")])
    rows.append([btn("🔙 Cancel", data="admin_cancel")])
    return rows


def handle_roulette_command(chat_id, user_id):
    if not is_admin(user_id):
        return
    rows = manage_list_keyboard()
    if len(rows) == 1:
        send_message(chat_id, "😴 No giveaways yet. Create one first with /admin → Add Giveaway.")
        return
    send_message(chat_id, f"{header('MANAGE GIVEAWAYS')}\n\nSelect one:", kb(rows))


# ============================== TEXT MESSAGE (admin conversation state machine) ====

def handle_text_message(chat_id, user_id, text):
    text = (text or "").strip()
    if text.startswith("/start"):
        handle_start(chat_id, user_id)
        return
    if text.startswith("/admin"):
        handle_admin_command(chat_id, user_id)
        return
    if text.startswith("/roulette"):
        handle_roulette_command(chat_id, user_id)
        return
    if text.startswith("/myid"):
        send_message(chat_id, f"Your Telegram ID: <code>{user_id}</code>")
        return
    if text.startswith("/cancel"):
        clear_admin_state(user_id)
        send_message(chat_id, "❌ Cancelled.")
        return

    if not is_admin(user_id):
        return

    state = get_admin_state(user_id)
    if not state:
        return
    step = state["step"]
    data = state.get("data", {})

    if step == "title":
        data["title"] = text
        set_admin_state(user_id, {"step": "desc", "data": data})
        send_message(chat_id, "📝 Now send the <b>giveaway details</b> (prize, rules, etc.):", cancel_kb())

    elif step == "desc":
        data["desc"] = text
        set_admin_state(user_id, {"step": "duration", "data": data})
        send_message(
            chat_id,
            "⏳ <b>Choose the giveaway duration</b> (shown to users as a countdown):",
            kb(
                [
                    [btn("⏱️ 15 min", data="dur_15"), btn("⏱️ 20 min", data="dur_20")],
                    [btn("✏️ Custom Time", data="dur_custom")],
                    [btn("🔙 Cancel", data="admin_cancel")],
                ]
            ),
        )

    elif step == "custom_duration":
        try:
            minutes = int(text)
            if minutes <= 0:
                raise ValueError
        except ValueError:
            send_message(chat_id, "❌ Please send a valid positive number of minutes.", cancel_kb())
            return
        data["duration_min"] = minutes
        set_admin_state(user_id, {"step": "winners", "data": data})
        send_message(chat_id, "🏆 How many winners should this giveaway have? Send a number:", cancel_kb())

    elif step == "winners":
        try:
            winners = int(text)
            if winners <= 0:
                raise ValueError
        except ValueError:
            send_message(chat_id, "❌ Please send a valid positive number.", cancel_kb())
            return
        create_giveaway(data["title"], data["desc"], data["duration_min"], winners)
        clear_admin_state(user_id)
        send_message(
            chat_id,
            f"🎉 <b>Giveaway Live!</b>\n\n🎁 {data['title']}\n\n"
            f"✅ Visible under Active Giveaways now. Use /roulette anytime to draw a winner — no need to wait.",
        )

    elif step == "premium_text":
        set_json("premium_text", text)
        clear_admin_state(user_id)
        send_message(chat_id, "✅ Premium Account content updated.")

    elif step == "ban_target":
        target = text.strip().lstrip("@")
        if target.isdigit():
            target_uid = int(target)
        else:
            target_uid = get_json(f"username_map:{target.lower()}")
        clear_admin_state(user_id)
        if target_uid is None:
            send_message(
                chat_id,
                "❌ User not found. They must have used the bot at least once with that "
                "username, or send their numeric ID instead (use /myid to test with your own).",
            )
            return
        banned = get_json("banned_users", [])
        if target_uid in banned:
            banned.remove(target_uid)
            send_message(chat_id, f"✅ User <code>{target_uid}</code> has been <b>unbanned</b>.")
        else:
            banned.append(target_uid)
            send_message(chat_id, f"🚫 User <code>{target_uid}</code> has been <b>banned</b>.")
        set_json("banned_users", banned)

    elif step == "broadcast_text":
        clear_admin_state(user_id)
        all_users = get_json("all_users", [])
        banned = set(get_json("banned_users", []))
        sent, failed = 0, 0
        for uid in all_users:
            if uid in banned:
                continue
            res = send_message(uid, text)
            if res.get("ok"):
                sent += 1
            else:
                failed += 1
        send_message(chat_id, f"📢 <b>Broadcast complete.</b>\n\n✅ Delivered: {sent}\n❌ Failed: {failed}")


# ============================== CALLBACK QUERY HANDLING ==================

def handle_callback(callback):
    data = callback["data"]
    user = callback["from"]
    user_id = user["id"]
    msg = callback["message"]
    chat_id = msg["chat"]["id"]
    message_id = msg["message_id"]

    if data == "verify_join":
        not_joined = check_membership(user_id)
        if not_joined:
            answer_callback(callback["id"], "❌ You haven't joined all channels yet.", alert=True)
            edit_message(chat_id, message_id, FORCE_JOIN_TEXT, force_join_keyboard(not_joined))
            return
        answer_callback(callback["id"], "✅ Verified!")
        edit_message(chat_id, message_id, WELCOME_TEXT, main_menu_keyboard())
        return

    if data == "menu_back":
        answer_callback(callback["id"])
        edit_message(chat_id, message_id, WELCOME_TEXT, main_menu_keyboard())
        return

    if data == "menu_owner":
        answer_callback(callback["id"])
        edit_message(chat_id, message_id, OWNER_INFO_TEXT, back_kb())
        return

    if data == "menu_premium":
        answer_callback(callback["id"])
        premium = get_json("premium_text") or "No premium account info has been added yet."
        text = f"{header('PREMIUM ACCESS')}\n\n{premium}\n\n{DIV}\n📩 <b>@GpsirEra</b>"
        edit_message(chat_id, message_id, text, back_kb())
        return

    if data == "menu_active":
        answer_callback(callback["id"])
        ids = get_json("all_giveaway_ids", [])
        rows = []
        for gid in reversed(ids):
            gw = get_json(f"giveaway:{gid}")
            if gw and gw["status"] == "active":
                rows.append([btn(f"🎁 {gw['title']}", data=f"view_gw_{gid}")])
        if not rows:
            edit_message(chat_id, message_id, f"{header('ACTIVE GIVEAWAYS')}\n\n😴 No giveaways running right now.", back_kb())
            return
        rows.append([btn("🔙 Back", data="menu_back")])
        edit_message(chat_id, message_id, f"{header('ACTIVE GIVEAWAYS')}\n\nSelect one:", kb(rows))
        return

    if data.startswith("view_gw_"):
        gid = data.split("_")[-1]
        gw = get_json(f"giveaway:{gid}")
        answer_callback(callback["id"])
        if not gw or gw["status"] != "active":
            edit_message(chat_id, message_id, "This giveaway has ended.", back_kb("menu_active"))
            return
        joined_ids = {j["id"] for j in gw["joiners"]}
        already = user_id in joined_ids
        rows = [
            [btn("✅ Joined" if already else "🎉 Join Giveaway", data=f"join_{gid}")],
            [btn("🔙 Back", data="menu_active")],
        ]
        edit_message(chat_id, message_id, giveaway_detail_text(gw), kb(rows))
        return

    if data.startswith("join_"):
        gid = data.split("_")[-1]
        gw = get_json(f"giveaway:{gid}")
        if not gw or gw["status"] != "active":
            answer_callback(callback["id"], "This giveaway has ended.", alert=True)
            return
        joined_ids = {j["id"] for j in gw["joiners"]}
        if user_id in joined_ids:
            answer_callback(callback["id"], "You already joined this giveaway!", alert=True)
            return
        gw["joiners"].append({"id": user_id, "name": user.get("first_name", "User"), "username": user.get("username", "")})
        set_json(f"giveaway:{gid}", gw)
        answer_callback(callback["id"], "✅ You joined! Good luck 🍀", alert=True)
        rows = [[btn("✅ Joined", data=f"join_{gid}")], [btn("🔙 Back", data="menu_active")]]
        edit_message(chat_id, message_id, giveaway_detail_text(gw), kb(rows))
        return

    # ---- Admin-only ----
    if data == "admin_add_gw":
        answer_callback(callback["id"])
        if not is_admin(user_id):
            return
        set_admin_state(user_id, {"step": "title", "data": {}})
        edit_message(chat_id, message_id, "📝 Send the <b>giveaway title</b>:", cancel_kb())
        return

    if data == "admin_set_premium":
        answer_callback(callback["id"])
        if not is_admin(user_id):
            return
        set_admin_state(user_id, {"step": "premium_text", "data": {}})
        edit_message(chat_id, message_id, "💎 Send the new <b>Premium Account</b> content/text:", cancel_kb())
        return

    if data == "admin_ban":
        answer_callback(callback["id"])
        if not is_admin(user_id):
            return
        set_admin_state(user_id, {"step": "ban_target", "data": {}})
        edit_message(
            chat_id, message_id,
            "🚫 Send the <b>username</b> (with or without @) or <b>numeric user ID</b> to ban/unban.\n\n"
            "<i>Note: if it's already banned, this will unban them instead.</i>",
            cancel_kb(),
        )
        return

    if data == "admin_broadcast":
        answer_callback(callback["id"])
        if not is_admin(user_id):
            return
        set_admin_state(user_id, {"step": "broadcast_text", "data": {}})
        edit_message(chat_id, message_id, "📢 Send the message you want to broadcast to every bot user:", cancel_kb())
        return

    if data == "admin_cancel":
        answer_callback(callback["id"], "❌ Cancelled")
        if not is_admin(user_id):
            return
        clear_admin_state(user_id)
        edit_message(chat_id, message_id, f"{header('ADMIN PANEL')}\n\nChoose an action:", admin_menu_keyboard())
        return

    if data == "admin_manage":
        answer_callback(callback["id"])
        if not is_admin(user_id):
            return
        rows = manage_list_keyboard()
        if len(rows) == 1:
            edit_message(chat_id, message_id, "😴 No giveaways yet.", cancel_kb())
            return
        edit_message(chat_id, message_id, f"{header('MANAGE GIVEAWAYS')}\n\nSelect one:", kb(rows))
        return

    if data.startswith("manage_"):
        gid = data.split("_", 1)[1]
        answer_callback(callback["id"])
        if not is_admin(user_id):
            return
        gw = get_json(f"giveaway:{gid}")
        if not gw:
            edit_message(chat_id, message_id, "⚠️ This giveaway no longer exists.", cancel_kb())
            return
        rows = []
        if gw["status"] == "active":
            rows.append([btn("🎰 Draw Winner Now", data=f"draw_{gid}")])
        rows.append([btn("🗑️ Delete", data=f"delconfirm_{gid}")])
        rows.append([btn("🔙 Back", data="admin_manage")])
        edit_message(chat_id, message_id, manage_detail_text(gw), kb(rows))
        return

    if data.startswith("draw_"):
        gid = data.split("_", 1)[1]
        if not is_admin(user_id):
            answer_callback(callback["id"])
            return
        answer_callback(callback["id"], "🎰 Drawing…")
        gw = get_json(f"giveaway:{gid}")
        if not gw:
            edit_message(chat_id, message_id, "⚠️ This giveaway no longer exists.", cancel_kb())
            return
        if gw["status"] != "active":
            edit_message(chat_id, message_id, "⚠️ This giveaway's winner has already been drawn.", cancel_kb())
            return
        reveal_text = draw_winner(gid, gw)
        edit_message(chat_id, message_id, reveal_text, cancel_kb())
        return

    if data.startswith("delconfirm_"):
        gid = data.split("_", 1)[1]
        answer_callback(callback["id"])
        if not is_admin(user_id):
            return
        gw = get_json(f"giveaway:{gid}")
        title = gw["title"] if gw else "this giveaway"
        rows = [[btn("✅ Yes, Delete", data=f"delyes_{gid}"), btn("❌ No", data=f"manage_{gid}")]]
        edit_message(chat_id, message_id, f"⚠️ Delete <b>{title}</b>? This cannot be undone.", kb(rows))
        return

    if data.startswith("delyes_"):
        gid = data.split("_", 1)[1]
        if not is_admin(user_id):
            answer_callback(callback["id"])
            return
        delete_key(f"giveaway:{gid}")
        all_ids = get_json("all_giveaway_ids", [])
        all_ids = [g for g in all_ids if g != gid]
        set_json("all_giveaway_ids", all_ids)
        answer_callback(callback["id"], "🗑️ Deleted.", alert=True)
        edit_message(chat_id, message_id, "✅ <b>Giveaway deleted successfully.</b>", cancel_kb())
        return

    if data in ("dur_15", "dur_20", "dur_custom"):
        answer_callback(callback["id"])
        if not is_admin(user_id):
            return
        state = get_admin_state(user_id)
        if not state or state["step"] != "duration":
            return
        gdata = state["data"]
        if data == "dur_15":
            gdata["duration_min"] = 15
            set_admin_state(user_id, {"step": "winners", "data": gdata})
            edit_message(chat_id, message_id, "🏆 How many winners should this giveaway have? Send a number:", cancel_kb())
        elif data == "dur_20":
            gdata["duration_min"] = 20
            set_admin_state(user_id, {"step": "winners", "data": gdata})
            edit_message(chat_id, message_id, "🏆 How many winners should this giveaway have? Send a number:", cancel_kb())
        else:
            set_admin_state(user_id, {"step": "custom_duration", "data": gdata})
            edit_message(chat_id, message_id, "✏️ Send the custom duration in minutes (e.g. 45):", cancel_kb())
        return


# ============================== VERCEL ENTRYPOINT ==================

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            update = json.loads(body)
            if "message" in update and "text" in update["message"]:
                msg = update["message"]
                uid = msg["from"]["id"]
                track_user(msg["from"])
                if is_banned(uid) and not is_admin(uid):
                    send_message(msg["chat"]["id"], "🚫 You have been banned from using this bot.")
                else:
                    handle_text_message(msg["chat"]["id"], uid, msg["text"])
            elif "callback_query" in update:
                cb = update["callback_query"]
                uid = cb["from"]["id"]
                track_user(cb["from"])
                if is_banned(uid) and not is_admin(uid):
                    answer_callback(cb["id"], "🚫 You have been banned from using this bot.", alert=True)
                else:
                    handle_callback(cb)
        except Exception as e:
            print(f"Webhook error: {e}")

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode())

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"GpsirEra Giveaway Bot webhook is alive.")
