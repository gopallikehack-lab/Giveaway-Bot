GpsirEra Giveaway Bot — Vercel Deployment
⚠️ Read this fully before deploying — two things about Vercel are fundamentally
different from running the bot on Termux, and the bot won't work correctly if
you skip them.
Why the old bot.py doesn't work on Vercel as-is
No polling. run_polling() runs forever — Vercel functions run for a few
seconds and then die. This version uses a webhook instead: Telegram pushes
updates to api/index.py directly.
No local files / no timers. Vercel gives every function invocation a fresh,
throwaway environment — data.json and JobQueue.run_once() would both be
gone by the next request. So:
All data (giveaways, joiners, premium text, admin conversation state) now
lives in Upstash Redis (free tier), not a local file.
Instead of a scheduled timer, there's a second endpoint api/cron.py that
checks "has any giveaway's time run out?" — but it only runs when something
calls it.
⚠️ Important: Vercel's free Cron ≠ what you need
Vercel's own built-in Cron Jobs are limited to once per day on the free
Hobby plan — completely useless for a 15/20-minute giveaway. So don't rely on
vercel.json's crons field. Instead, use a free external pinger to hit
api/cron.py every minute:
Go to cron-job.org (free) → create account.
Create a new cron job:
URL: https://<your-vercel-domain>/api/cron?key=<CRON_SECRET>
Schedule: every 1 minute
That's it — this single external ping is what actually ends giveaways on time.
(If you'd rather pay for Vercel Pro, its per-minute Cron can replace this —
but the free external pinger works just as well for this use case.)
Setup steps
1. Create a free Upstash Redis database
Go to upstash.com → create a Redis database (free tier is plenty).
Copy the REST URL and REST TOKEN shown in the dashboard.
2. Set Environment Variables in Vercel
Project → Settings → Environment Variables. Add:
Variable
Value
BOT_TOKEN
from @BotFather
ADMIN_IDS
your numeric Telegram ID (comma-separated if more than one)
RESULTS_CHANNEL_ID
numeric ID of the channel where winners get posted
CHANNEL1_ID
numeric ID of "Gpsir ha4k Channel"
CHANNEL2_ID
numeric ID of "Gpsir Chat Group"
UPSTASH_REDIS_REST_URL
from Upstash dashboard
UPSTASH_REDIS_REST_TOKEN
from Upstash dashboard
CRON_SECRET
any random string you make up yourself, e.g. gpsir_x92kd
🔒 Never put these values directly in the code in your public GitHub repo —
that's exactly what env vars are for. Get numeric IDs the same way as before:
add the bot as admin in each channel, forward a message from it to
@userinfobot, and it shows the numeric -100... id. For your own ID, once
deployed, DM the bot /myid.
3. Deploy
Push to GitHub → Vercel auto-deploys (you've already connected the repo).
4. Set the Telegram webhook
Once deployed, call this once in your browser (replace both placeholders):
Code
You should get {"ok":true,"result":true,...}.
5. Set up the external cron pinger
Follow the cron-job.org steps above. Without this step, giveaways will never
end automatically.
How it behaves (same as before)
/start → force-join check on both channels → verify button → main menu
(🎁 Active Giveaway / 💎 Premium Account / 👤 Owner Info)
/admin (admin IDs only) → Add Giveaway (title → details → 15/20 min or
Custom → winners count) / Set Premium Content / List Active Giveaways
Users tap Join Giveaway → their id + name is stored in Redis
Every minute, api/cron.py checks for expired giveaways, picks random
winners, DMs them, and posts the full result to RESULTS_CHANNEL_ID
Testing locally first (recommended)
Since debugging webhook issues live on Vercel is slow, test with Termux +
polling (the previous bot.py) first to confirm your flow/text/copy is right,
then deploy this webhook version for production. Ping me if you want both kept
in sync going forward.
