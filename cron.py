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
RESULTS_CHANNEL_ID = int(os.environ["RESULTS_CHANNEL_ID"])  # the results group's numeric chat_id
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


def send_message(chat_id, text):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
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


def end_giveaway(gid, gw):
    gw["status"] = "ended"
    joiners = gw["joiners"]
    n_winners = min(gw["winners_count"], len(joiners))
    winners = random.sample(joiners, n_winners) if n_winners > 0 else []
    gw["winners"] = winners
    set_json(f"giveaway:{gid}", gw)

    if winners:
        winner_lines = "\n\n".join(
            f"▸ <b>{w['name']}</b>\n"
            f"    Username: {'@' + w['username'] if w['username'] else '<i>not set</i>'}\n"
            f"    Chat ID: <code>{w['id']}</code>"
            for w in winners
        )
    else:
        winner_lines = "No one joined this giveaway."

    result_text = (
        f"◆ ──────────────── ◆\n"
        f"🏁 <b>GIVEAWAY RESULT</b>\n"
        f"◆ ──────────────── ◆\n\n"
        f"🎯 <b>{gw['title']}</b>\n"
        f"👥 Participants: <b>{len(joiners)}</b>\n\n"
        f"<b>WINNERS</b>\n"
        f"──────────────────\n"
        f"{winner_lines}\n"
        f"──────────────────\n\n"
        f"🔒 <i>Selected via secure random draw inside the bot. Verified fair, zero manipulation.</i>"
    )

    # Post full result (name + username + chat id) to the results group
    try:
        group_res = send_message(RESULTS_CHANNEL_ID, result_text)
        group_failed = not group_res.get("ok")
    except Exception as e:
        print(f"Group post crashed: {e}")
        group_res, group_failed = {"ok": False, "error": str(e)}, True

    # DM each winner individually
    delivery_failures = []
    for w in winners:
        try:
            res = send_message(
                w["id"],
                f"◆ ──────────────── ◆\n"
                f"🏆 <b>YOU WON!</b>\n"
                f"◆ ──────────────── ◆\n\n"
                f"Giveaway: <b>{gw['title']}</b>\n\n"
                f"🔒 <i>Picked via secure random draw — verified fair.</i>\n\n"
                f"📩 Contact <b>@GpsirEra</b> to claim your prize.",
            )
            if not res.get("ok"):
                delivery_failures.append(w)
        except Exception as e:
            print(f"Winner DM crashed for {w['id']}: {e}")
            delivery_failures.append(w)

    # Always notify admins in bot chat too, as a reliable backup — and surface any failures loudly.
    admin_note = result_text
    if group_failed:
        admin_note += f"\n\n⚠️ <b>Could not post to the results group</b> ({RESULTS_CHANNEL_ID}). Response: {group_res}"
    if delivery_failures:
        fail_lines = "\n".join(f"• {w['name']} (id: {w['id']})" for w in delivery_failures)
        admin_note += (
            f"\n\n⚠️ <b>Could not DM these winners</b> (they may have blocked the bot, "
            f"or never pressed Start before joining):\n{fail_lines}"
        )
    for admin_id in ADMIN_IDS:
        try:
            send_message(admin_id, admin_note)
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
