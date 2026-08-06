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
            f"🏆 <b>{w['name']}</b>\n"
            f"   • Username: {'@' + w['username'] if w['username'] else '<i>no username set</i>'}\n"
            f"   • Chat ID: <code>{w['id']}</code>"
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
    delivery_failures = []
    for w in winners:
        res = send_message(
            w["id"],
            f"🎊━━━━━━━━━━━━🎊\n<b>Congratulations!</b> 🎊\n\n"
            f"You won the giveaway 🎁 <b>{gw['title']}</b>!\n\n"
            f"<blockquote>🔒 Picked by secure random draw — fair &amp; verified.</blockquote>\n\n"
            f"📩 Contact @GpsirEra to claim your prize.",
        )
        if not res.get("ok"):
            delivery_failures.append(w)

    if delivery_failures:
        fail_lines = "\n".join(f"• {w['name']} (id: {w['id']})" for w in delivery_failures)
        result_text += (
            f"\n\n⚠️ <b>Could not DM these winners</b> (they may have blocked the bot, "
            f"or never pressed Start before joining):\n{fail_lines}"
        )

    for admin_id in ADMIN_IDS:
        send_message(admin_id, result_text)


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
