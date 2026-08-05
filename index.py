"""
GpsirEra Premium Giveaway Bot — Vercel webhook handler.
Self-contained (no external pip packages) to avoid Vercel Python import issues.
Storage: Upstash Redis (free tier) via its REST API.

Deploy notes are in README.md at the repo root.
"""

import json
import os
import random
import time
from http.server import BaseHTTPRequestHandler
from urllib import request as urlrequest

# ============================== CONFIG (all from Vercel Env Vars) ==================

BOT_TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]
RESULTS_CHANNEL_ID = os.environ.get("RESULTS_CHANNEL_ID")  # no longer used for posting; kept optional

CHANNEL1_ID = int(os.environ["CHANNEL1_ID"])
CHANNEL2_ID = int(os.environ["CHANNEL2_ID"])

FORCE_JOIN_CHANNELS = [
    {"name": "Gpsir ha4k Channel", "chat_id": CHANNEL1_ID, "link": "https://t.me/+74PC9DgmtN84NzFl"},
    {"name": "Gpsir Chat Group", "chat_id": CHANNEL2_ID, "link": "https://t.me/+VXs73pFfyEphMzJl"},
]

OWNER_INFO_TEXT = (
    "👑━━━━━━━━━━━━━👑\n"
    "🌟 <b>G P S I R E R A</b> 🌟\n"
    "👑━━━━━━━━━━━━━👑\n\n"
    "🧑‍💻 Full Name: <b>Gopal Parmar</b>\n\n"
    "🛠️ <i>Specialist Coder</i>\n"
    "💣 <i>Open Bullet Expert</i>\n"
    "🤖 <i>AI Coder</i>\n"
    "🔌 <i>API Builder</i>\n\n"
    "📩 Need help? Contact me 👉 <b>@GpsirEra</b> ✨"
)

UPSTASH_URL = os.environ["UPSTASH_REDIS_REST_URL"]
UPSTASH_TOKEN = os.environ["UPSTASH_REDIS_REST_TOKEN"]

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
    return tg_call("sendMessage", payload)


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
    rows.append([btn("✅ I've Joined — Verify", data="verify_join")])
    return kb(rows)


FORCE_JOIN_TEXT = (
    "🔐━━━━━━━━━━━━━🔐\n"
    "🚨 <b>Verification Required</b> 🚨\n"
    "🔐━━━━━━━━━━━━━🔐\n\n"
    "🚀 Join the channel(s) below to unlock premium access:\n\n"
    "👉 Then tap <b>✅ I've Joined</b>"
)


def main_menu_keyboard():
    return kb(
        [
            [btn("🎉 Active Giveaways", data="menu_active")],
            [btn("💎 Premium Account", data="menu_premium")],
            [btn("👑 Owner Info", data="menu_owner")],
        ]
    )


WELCOME_TEXT = (
    "✨━━━━━━━━━━━━━━✨\n"
    "🌟 <b>GpsirEra Premium Bot</b> 🌟\n"
    "✨━━━━━━━━━━━━━━✨\n\n"
    "✅ <b>Verified!</b> Welcome aboard 🚀\n\n"
    "<blockquote>🔒 Secure, fair &amp; transparent — every giveaway is decided by true random draw.</blockquote>\n\n"
    "👇 <i>Choose an option below to continue</i>"
)


def back_kb(target="menu_back"):
    return kb([[btn("🔙 Back", data=target)]])


# ============================== GIVEAWAY HELPERS ==================

def is_admin(user_id):
    return user_id in ADMIN_IDS


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
        f"🎉━━━━━━━━━━━━🎉\n"
        f"🎁 <b>{gw['title']}</b>\n"
        f"🎉━━━━━━━━━━━━🎉\n\n"
        f"📋 {gw['desc']}\n\n"
        f"🏆 Winners: <b>{gw['winners_count']}</b>\n"
        f"👥 Participants: <b>{len(gw['joiners'])}</b>\n"
        f"⏳ Time Left: <b>{mins}m {secs}s</b>\n\n"
        f"<blockquote>🔒 <b>100% Fair &amp; Secure</b> — winner(s) picked by true random draw. No manipulation, no cheating possible.</blockquote>\n\n"
        f"🍀 <i>Tap below to join!</i>"
    )


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
        f"🎊━━━━━━━━━━━━🎊\n"
        f"🏁 <b>Giveaway Ended!</b>\n"
        f"🎯 {gw['title']}\n"
        f"🎊━━━━━━━━━━━━🎊\n\n"
        f"👥 Total Participants: <b>{len(joiners)}</b>\n\n"
        f"🏆 <b>Winners:</b>\n{winner_lines}\n\n"
        f"<blockquote>🔒 Selected via secure random draw inside the bot — 100% fair, zero cheating possible.</blockquote>\n\n"
        f"🎉 Congratulations to all winners! 🎉"
    )

    # Result stays inside the bot — sent to admins in their bot chat, NOT posted to any channel.
    for admin_id in ADMIN_IDS:
        send_message(admin_id, result_text)

    for w in winners:
        send_message(
            w["id"],
            f"🎊━━━━━━━━━━━━🎊\n<b>Congratulations!</b> 🎊\n\n"
            f"You won the giveaway 🎁 <b>{gw['title']}</b>!\n\n"
            f"<blockquote>🔒 Picked by secure random draw — fair &amp; verified.</blockquote>\n\n"
            f"📩 Contact @GpsirEra to claim your prize.",
        )


# ============================== ROUTES: /start, /admin, /myid ==================

def handle_start(chat_id, user_id):
    not_joined = check_membership(user_id)
    if not_joined:
        send_message(chat_id, FORCE_JOIN_TEXT, force_join_keyboard(not_joined))
        return
    send_message(chat_id, WELCOME_TEXT, main_menu_keyboard())


def handle_admin_command(chat_id, user_id):
    if not is_admin(user_id):
        send_message(chat_id, "⛔ You are not authorized to use the admin panel.")
        return
    send_message(
        chat_id,
        "🛠️━━━━━━━━━━━━🛠️\n⚙️ <b>Admin Control Panel</b> ⚙️\n🛠️━━━━━━━━━━━━🛠️\n\n<i>Choose an action:</i>",
        kb(
            [
                [btn("🎯 Add Giveaway", data="admin_add_gw")],
                [btn("💎 Set Premium Content", data="admin_set_premium")],
                [btn("📊 List Active Giveaways", data="admin_list_gw")],
                [btn("🗑️ Delete Giveaway", data="admin_delete_gw")],
            ]
        ),
    )


# ============================== TEXT MESSAGE (admin conversation state machine) ====

def handle_text_message(chat_id, user_id, text):
    if text == "/start":
        handle_start(chat_id, user_id)
        return
    if text == "/admin":
        handle_admin_command(chat_id, user_id)
        return
    if text == "/myid":
        send_message(chat_id, f"Your Telegram ID: <code>{user_id}</code>")
        return
    if text == "/cancel":
        clear_admin_state(user_id)
        send_message(chat_id, "❌ Cancelled.")
        return

    if not is_admin(user_id):
        return  # ignore random text from non-admins

    state = get_admin_state(user_id)
    if not state:
        return

    step = state["step"]
    data = state.get("data", {})

    if step == "title":
        data["title"] = text.strip()
        set_admin_state(user_id, {"step": "desc", "data": data})
        send_message(chat_id, "📝 Now send the <b>giveaway details</b> (prize, rules, whatever you want shown):")

    elif step == "desc":
        data["desc"] = text.strip()
        set_admin_state(user_id, {"step": "duration", "data": data})
        send_message(
            chat_id,
            "⏳ <b>Choose the giveaway duration:</b>",
            kb(
                [
                    [btn("⏱️ 15 min", data="dur_15"), btn("⏱️ 20 min", data="dur_20")],
                    [btn("✏️ Custom Time", data="dur_custom")],
                ]
            ),
        )

    elif step == "custom_duration":
        try:
            minutes = int(text.strip())
            if minutes <= 0:
                raise ValueError
        except ValueError:
            send_message(chat_id, "❌ Please send a valid positive number of minutes.")
            return
        data["duration_min"] = minutes
        set_admin_state(user_id, {"step": "winners", "data": data})
        send_message(chat_id, "🏆 How many winners should this giveaway have? Send a number:")

    elif step == "winners":
        try:
            winners = int(text.strip())
            if winners <= 0:
                raise ValueError
        except ValueError:
            send_message(chat_id, "❌ Please send a valid positive number.")
            return
        create_giveaway(data["title"], data["desc"], data["duration_min"], winners)
        clear_admin_state(user_id)
        send_message(
            chat_id,
            f"🎉 <b>Giveaway Live!</b>\n\n🎁 {data['title']}\n⏳ Running for {data['duration_min']} minutes\n\n✅ It's now visible under Active Giveaways.",
        )

    elif step == "premium_text":
        set_json("premium_text", text.strip())
        clear_admin_state(user_id)
        send_message(chat_id, "✅ Premium Account content updated.")


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
    active_ids = get_json("active_ids", [])
    active_ids.append(gid)
    set_json("active_ids", active_ids)


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
        text = (
            f"💎━━━━━━━━━━━━💎\n"
            f"🌟 <b>Premium Account</b> 🌟\n"
            f"💎━━━━━━━━━━━━💎\n\n"
            f"{premium}\n\n"
            f"📩 Contact Me: <b>@GpsirEra</b>"
        )
        edit_message(chat_id, message_id, text, back_kb())
        return

    if data == "menu_active":
        answer_callback(callback["id"])
        active_ids = get_json("active_ids", [])
        rows = []
        for gid in active_ids:
            gw = get_json(f"giveaway:{gid}")
            if gw and gw["status"] == "active":
                rows.append([btn(f"🎁 {gw['title']}", data=f"view_gw_{gid}")])
        if not rows:
            edit_message(
                chat_id, message_id,
                "🎉 <b>Active Giveaways</b>\n\n😔 No giveaways running right now. Check back soon!",
                back_kb(),
            )
            return
        rows.append([btn("🔙 Back", data="menu_back")])
        edit_message(chat_id, message_id, "🎉 <b>Active Giveaways</b>\n\n👇 Select one to view details:", kb(rows))
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
        answer_callback(callback["id"], "✅ You joined this giveaway! Good luck 🍀", alert=True)
        rows = [[btn("✅ Joined", data=f"join_{gid}")], [btn("🔙 Back", data="menu_active")]]
        edit_message(chat_id, message_id, giveaway_detail_text(gw), kb(rows))
        return

    # ---- Admin-only callbacks ----
    if data == "admin_add_gw":
        answer_callback(callback["id"])
        if not is_admin(user_id):
            return
        set_admin_state(user_id, {"step": "title", "data": {}})
        edit_message(chat_id, message_id, "📝 Send the <b>giveaway title</b>:")
        return

    if data == "admin_set_premium":
        answer_callback(callback["id"])
        if not is_admin(user_id):
            return
        set_admin_state(user_id, {"step": "premium_text", "data": {}})
        edit_message(chat_id, message_id, "💎 Send the new <b>Premium Account</b> content/text:")
        return

    if data == "admin_list_gw":
        answer_callback(callback["id"])
        if not is_admin(user_id):
            return
        active_ids = get_json("active_ids", [])
        lines = []
        for gid in active_ids:
            gw = get_json(f"giveaway:{gid}")
            if gw and gw["status"] == "active":
                remaining = max(0, int(gw["end_time"] - time.time()))
                lines.append(f"🎁 <b>{gw['title']}</b> — 👥 {len(gw['joiners'])} joined — ⏳ {remaining // 60}m left")
        edit_message(chat_id, message_id, "📊 <b>Active Giveaways</b>\n\n" + ("\n\n".join(lines) if lines else "😴 No active giveaways right now."))
        return

    if data == "admin_delete_gw":
        answer_callback(callback["id"])
        if not is_admin(user_id):
            return
        active_ids = get_json("active_ids", [])
        rows = []
        for gid in active_ids:
            gw = get_json(f"giveaway:{gid}")
            if gw and gw["status"] == "active":
                rows.append([btn(f"🗑️ {gw['title']}", data=f"delconfirm_{gid}")])
        if not rows:
            edit_message(chat_id, message_id, "😴 No active giveaways to delete.")
            return
        rows.append([btn("🔙 Cancel", data="admin_list_gw")])
        edit_message(chat_id, message_id, "🗑️ <b>Select a giveaway to delete:</b>", kb(rows))
        return

    if data.startswith("delconfirm_"):
        gid = data.split("_", 1)[1]
        answer_callback(callback["id"])
        if not is_admin(user_id):
            return
        gw = get_json(f"giveaway:{gid}")
        title = gw["title"] if gw else "this giveaway"
        rows = [
            [btn("✅ Yes, Delete", data=f"delyes_{gid}"), btn("❌ No, Keep It", data="admin_delete_gw")],
        ]
        edit_message(chat_id, message_id, f"⚠️ Delete <b>{title}</b>? This cannot be undone.", kb(rows))
        return

    if data.startswith("delyes_"):
        gid = data.split("_", 1)[1]
        if not is_admin(user_id):
            answer_callback(callback["id"])
            return
        delete_key(f"giveaway:{gid}")
        active_ids = get_json("active_ids", [])
        active_ids = [g for g in active_ids if g != gid]
        set_json("active_ids", active_ids)
        answer_callback(callback["id"], "🗑️ Giveaway deleted.", alert=True)
        edit_message(chat_id, message_id, "✅ <b>Giveaway deleted successfully.</b>")
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
            edit_message(chat_id, message_id, "🏆 How many winners should this giveaway have? Send a number:")
        elif data == "dur_20":
            gdata["duration_min"] = 20
            set_admin_state(user_id, {"step": "winners", "data": gdata})
            edit_message(chat_id, message_id, "🏆 How many winners should this giveaway have? Send a number:")
        else:
            set_admin_state(user_id, {"step": "custom_duration", "data": gdata})
            edit_message(chat_id, message_id, "✏️ Send the custom duration in minutes (e.g. 45):")
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
                handle_text_message(msg["chat"]["id"], msg["from"]["id"], msg["text"])
            elif "callback_query" in update:
                handle_callback(update["callback_query"])
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
