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
import re
import time
from http.server import BaseHTTPRequestHandler
from urllib import request as urlrequest
from urllib.parse import urlparse, parse_qs

BOT_TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{BOT_TOKEN}"
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]
RESULTS_CHANNEL_ID = os.environ.get("RESULTS_CHANNEL_ID")  # no longer used automatically; kept optional
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


def strip_html(text):
    return re.sub(r"<[^>]+>", "", text)


def send_message(chat_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard:
        payload["reply_markup"] = keyboard
    req = urlrequest.Request(
        f"{API}/sendMessage",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read())
    except Exception as e:
        print(f"Telegram send error: {e}")
        return {"ok": False, "error": str(e)}

    if not res.get("ok"):
        print(f"sendMessage failed for {chat_id}: {res}")
        # Fallback: retry as plain text in case HTML parsing was the problem.
        payload_plain = {"chat_id": chat_id, "text": strip_html(text)}
        if keyboard:
            payload_plain["reply_markup"] = keyboard
        req2 = urlrequest.Request(
            f"{API}/sendMessage",
            data=json.dumps(payload_plain).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlrequest.urlopen(req2, timeout=10) as resp2:
                res = json.loads(resp2.read())
        except Exception as e:
            print(f"Fallback sendMessage also failed for {chat_id}: {e}")
            res = {"ok": False, "error": str(e)}
    return res


def mark_awaiting_draw(gid, gw):
    """Giveaway's timer ran out. Don't pick a winner or post anywhere yet —
    just freeze the participant list (with serial numbers) and hand control
    to the admin via a 'Lucky Serial Roulette' button."""
    gw["status"] = "awaiting_draw"
    joiners = gw["joiners"]
    set_json(f"giveaway:{gid}", gw)

    awaiting_ids = get_json("awaiting_draw_ids", [])
    if gid not in awaiting_ids:
        awaiting_ids.append(gid)
        set_json("awaiting_draw_ids", awaiting_ids)

    if joiners:
        participant_lines = "\n".join(
            f"<b>{i + 1}.</b> {j['name']} — @{j['username'] if j['username'] else 'no_username'} — ID: <code>{j['id']}</code>"
            for i, j in enumerate(joiners)
        )
    else:
        participant_lines = "No one joined."

    text = (
        f"◆ ──────────────── ◆\n"
        f"⏰ <b>GIVEAWAY TIME UP</b>\n"
        f"◆ ──────────────── ◆\n\n"
        f"🎯 <b>{gw['title']}</b>\n"
        f"👥 Participants: <b>{len(joiners)}</b>\n"
        f"🏆 Winners to pick: <b>{gw['winners_count']}</b>\n\n"
        f"<b>FULL PARTICIPANT LIST</b>\n"
        f"──────────────────\n"
        f"{participant_lines}\n"
        f"──────────────────\n\n"
        f"Tap below when you're ready to draw 👇"
    )
    keyboard = {"inline_keyboard": [[{"text": "🎰 Lucky Serial Roulette", "callback_data": f"roulette_{gid}"}]]}

    for admin_id in ADMIN_IDS:
        try:
            send_message(admin_id, text, keyboard)
        except Exception as e:
            print(f"Admin notify crashed for {admin_id}: {e}")


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
            try:
                gw = get_json(f"giveaway:{gid}")
                if not gw or gw.get("status") != "active":
                    continue
                if gw["end_time"] <= now:
                    mark_awaiting_draw(gid, gw)
                    ended += 1
                else:
                    still_active.append(gid)
            except Exception as e:
                print(f"Error processing giveaway {gid}: {e}")
                still_active.append(gid)  # keep it, retry next minute instead of losing it
        set_json("active_ids", still_active)

        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(f"OK - checked {len(active_ids)}, ended {ended}".encode())            f"{i + 1}. {j['name']} — @{j['username'] if j['username'] else 'no_username'} — ID: {j['id']}"
            for i, j in enumerate(joiners)
        )
    else:
        participant_lines = "No one joined."

    result_text = (
        f"◆ ──────────────── ◆\n"
        f"🏁 <b>GIVEAWAY RESULT</b>\n"
        f"◆ ──────────────── ◆\n\n"
        f"🎯 <b>{gw['title']}</b>\n"
        f"👥 Participants: <b>{len(joiners)}</b>\n\n"
        f"<b>WINNERS</b>\n"
        f"──────────────────\n"
        f"{winner_lines_full}\n"
        f"──────────────────\n\n"
        f"🔒 <i>Selected via secure random draw inside the bot. Verified fair, zero manipulation.</i>"
    )

    admin_text = (
        result_text
        + f"\n\n<b>ALL PARTICIPANTS ({len(joiners)})</b>\n"
        + f"──────────────────\n{participant_lines}"
    )

    broadcast_text = (
        f"◆ ──────────────── ◆\n"
        f"🏁 <b>GIVEAWAY ENDED</b>\n"
        f"◆ ──────────────── ◆\n\n"
        f"🎯 <b>{gw['title']}</b>\n\n"
        f"<b>Winner(s):</b>\n{winner_lines_public}\n\n"
        f"🔒 <i>Picked via secure random draw — verified fair.</i>\n\n"
        f"Didn't win this time? More giveaways coming — stay tuned! 🎉"
    )

    # 1) Post full result to the results group
    try:
        group_res = send_message(RESULTS_CHANNEL_ID, result_text)
        group_failed = not group_res.get("ok")
    except Exception as e:
        print(f"Group post crashed: {e}")
        group_res, group_failed = {"ok": False, "error": str(e)}, True

    # 2) Notify admins in bot chat — with the FULL participant list, not just winners
    admin_text_final = admin_text
    if group_failed:
        admin_text_final += f"\n\n⚠️ <b>Could not post to the results group</b> ({RESULTS_CHANNEL_ID}). Response: {group_res}"
    for admin_id in ADMIN_IDS:
        try:
            send_message(admin_id, admin_text_final)
        except Exception as e:
            print(f"Admin notify crashed for {admin_id}: {e}")

    # 3) Broadcast the winner announcement to every user who has ever used the bot
    all_users = get_json("all_users", [])
    broadcast_failures = 0
    for uid in all_users:
        try:
            res = send_message(uid, broadcast_text)
            if not res.get("ok"):
                broadcast_failures += 1
        except Exception as e:
            print(f"Broadcast crashed for {uid}: {e}")
            broadcast_failures += 1

    if broadcast_failures and ADMIN_IDS:
        try:
            send_message(
                ADMIN_IDS[0],
                f"ℹ️ Broadcast sent to {len(all_users) - broadcast_failures}/{len(all_users)} users "
                f"({broadcast_failures} unreachable — blocked bot or never started it).",
            )
        except Exception as e:
            print(f"Broadcast summary notify crashed: {e}")


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
            try:
                gw = get_json(f"giveaway:{gid}")
                if not gw or gw.get("status") != "active":
                    continue
                if gw["end_time"] <= now:
                    end_giveaway(gid, gw)
                    ended += 1
                else:
                    still_active.append(gid)
            except Exception as e:
                print(f"Error processing giveaway {gid}: {e}")
                still_active.append(gid)  # keep it, retry next minute instead of losing it
        set_json("active_ids", still_active)

        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(f"OK - checked {len(active_ids)}, ended {ended}".encode())
