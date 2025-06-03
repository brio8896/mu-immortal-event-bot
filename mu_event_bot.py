import discord
from discord.ext import commands, tasks
import pytz
from datetime import datetime, timedelta
import json
import math
import os
from keep_alive import run

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("❌ DISCORD_TOKEN is missing from environment variables!")
else:
    print("✅ Token found, starting bot...")
    run()
    bot.run(TOKEN)
GUILD_ID = 1379030612949860398
ANNOUNCE_CHANNEL_ID = 1379031561718075402

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

user_timezones_file = 'user_timezones.json'

# Load user timezones
if os.path.exists(user_timezones_file):
    with open(user_timezones_file, 'r') as f:
        user_timezones = json.load(f)
else:
    user_timezones = {}


# Save timezones
def save_timezones():
    with open(user_timezones_file, 'w') as f:
        json.dump(user_timezones, f)


# Command to set timezone
@bot.command()
async def settimezone(ctx, timezone_name: str):
    if timezone_name not in pytz.all_timezones:
        await ctx.send(
            "❌ Invalid timezone. Use: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
        )
        return
    user_timezones[str(ctx.author.id)] = timezone_name
    save_timezones()
    await ctx.send(f"✅ Your timezone has been set to `{timezone_name}`.")


# Event schedule format: (name, start times in UK, interval, open duration, day filter)
event_definitions = [
    # Blood Castle
    {
        "name": "Blood Castle",
        "start_hour": 1,
        "interval_hours": 2,
        "start_minute": 0,
        "open_minutes": 15,
        "days": range(7),
    },
    # Devil Square
    {
        "name": "Devil Square",
        "start_hour": 0,
        "interval_hours": 2,
        "start_minute": 0,
        "open_minutes": 15,
        "days": range(7),
    },
    # Chaos Castle
    {
        "name": "Chaos Castle",
        "start_hour": 20,
        "interval_hours": None,
        "start_minute": 0,
        "open_minutes": 5,
        "days": [1],  # Tuesday
    },
    # Red Dragon Invasion
    {
        "name": "Red Dragon Invasion",
        "fixed_times": ["10:30", "13:30", "16:30", "21:30"],
        "open_minutes": 60,
        "days": range(7),
    },
    # Guild Master Event
    {
        "name": "Guild Master Event",
        "fixed_times": ["11:30", "19:30"],
        "open_minutes": 30,
        "days": range(7),
    },
    # Cross-Server Dragon
    {
        "name": "Cross-Server Dragon",
        "fixed_times": ["10:30", "13:30", "16:30", "21:30"],
        "open_minutes": 60,
        "days": range(7),
        "unlock_after_days": 25,  # from May 20
    },
    # Minion EXP +30%
    {
        "name": "Minion EXP +30%",
        "is_buff": True,
        "active_from": "00:00",
        "active_until": "08:00",
        "days": range(7),
    }
]


async def build_upcoming_embed(upcoming, days_since_open, now_uk):
    embed = discord.Embed(title="🗓️ MU Immortal Events",
                          color=discord.Color.blurple())

    # ── Active Buffs ──
    for event in event_definitions:
        if not event.get("is_buff"):
            continue
        from_hour, from_min = map(int, event["active_from"].split(":"))
        to_hour, to_min = map(int, event["active_until"].split(":"))
        start = now_uk.replace(hour=from_hour,
                               minute=from_min,
                               second=0,
                               microsecond=0)
        end = now_uk.replace(hour=to_hour,
                             minute=to_min,
                             second=0,
                             microsecond=0)
        if start <= now_uk <= end:
            embed.add_field(
                name="🟨 Active Buffs",
                value=f"• {event['name']} (ends <t:{int(end.timestamp())}:R>)",
                inline=False)

    # ── Closing Soon ──
    closing_soon = []
    for event in event_definitions:
        if event.get("is_buff"):
            continue
        if event[
                "name"] == "Cross-Server Dragon" and days_since_open < event.get(
                    "unlock_after_days", 0):
            continue

        duration = event["open_minutes"]
        for t in generate_event_times(event, now_uk.date()):
            end_dt = t + timedelta(minutes=duration)
            # if we're inside the open window
            if t <= now_uk <= end_dt:
                # compute total seconds remaining
                total_secs = int((end_dt - now_uk).total_seconds())
                mins = total_secs // 60
                secs = total_secs % 60
                closing_soon.append((event["name"], mins, secs))
                break

    if closing_soon:
        lines = []
        for name, mins, secs in closing_soon:
            lines.append(f"• **{name}** closes in {mins}m {secs}s")
        embed.add_field(name="🕒 Closing Soon",
                        value="\n".join(lines),
                        inline=False)

    # ── Upcoming Events Today ──
    upcoming_events = []
    seen = set()
    combined = sorted(upcoming["< 15 min"] + upcoming["< 1 hour"] +
                      upcoming["Later today"],
                      key=lambda x: x[1])

    for name, time_ in combined:
        if name in seen:
            continue
        seen.add(name)
        ts = int(time_.timestamp())

        # Calculate hours+minutes remaining
        total_secs = int((time_ - now_uk).total_seconds())
        hours = total_secs // 3600
        mins = (total_secs % 3600) // 60

        if hours > 0:
            rel = f"{hours}h {mins}m"
        else:
            rel = f"{mins}m"

        upcoming_events.append(f"• **{name}** at <t:{ts}:t> (in {rel})")

    if upcoming_events:
        embed.add_field(name="🗓️ Upcoming Events",
                        value="\n".join(upcoming_events),
                        inline=False)

    # ── Tomorrow’s Starting Events ──
    if len(combined) <= 2 and upcoming["Tomorrow"]:
        tomorrow_events = []
        seen2 = set()
        for name, time_ in sorted(upcoming["Tomorrow"], key=lambda x: x[1]):
            if name in seen2:
                continue
            seen2.add(name)
            ts = int(time_.timestamp())
            tomorrow_events.append(f"• **{name}** at <t:{ts}:t> (<t:{ts}:R>)")

        embed.add_field(name="🌅 Tomorrow’s Starting Events",
                        value="\n".join(tomorrow_events),
                        inline=False)

    # ── Locked Events ──
    unlock_date = datetime(
        2025, 5, 20,
        tzinfo=pytz.timezone("Europe/London")) + timedelta(days=25)
    if now_uk < unlock_date:
        days_left = (unlock_date - now_uk).days
        embed.add_field(
            name="🔒 Locked Events",
            value=f"• Cross-Server Dragon unlocks in {days_left} days",
            inline=False)

    embed.set_footer(text="All times auto-adjust to your local time")
    return embed


# Store last sent status per event to avoid spamming
last_status = {}

last_summary_message = None
last_embed_hash = None


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    event_reminder.start()


@tasks.loop(seconds=1)
async def event_reminder():
    global last_summary_message, last_embed_hash

    now_uk = datetime.now(pytz.timezone("Europe/London"))
    weekday = now_uk.weekday()

    # Build the 'upcoming' dict exactly as before
    upcoming = {
        "< 15 min": [],
        "< 1 hour": [],
        "Later today": [],
        "Tomorrow": []
    }
    server_start_date = datetime(2025,
                                 5,
                                 20,
                                 tzinfo=pytz.timezone("Europe/London"))
    days_since_open = (now_uk - server_start_date).days
    tomorrow = (now_uk + timedelta(days=1)).date()

    for event in event_definitions:
        if event.get("is_buff"):
            continue
        if weekday not in event["days"]:
            continue
        if event[
                "name"] == "Cross-Server Dragon" and days_since_open < event.get(
                    "unlock_after_days", 0):
            continue

        times_today = generate_event_times(event, now_uk.date())
        times_tomorrow = generate_event_times(event, tomorrow)

        for event_time in times_today:
            if event_time > now_uk:
                delta_minutes = (event_time - now_uk).total_seconds() / 60
                if delta_minutes <= 15:
                    upcoming["< 15 min"].append((event["name"], event_time))
                elif delta_minutes <= 60:
                    upcoming["< 1 hour"].append((event["name"], event_time))
                else:
                    upcoming["Later today"].append((event["name"], event_time))

        total_today_events = (len(upcoming["< 15 min"]) +
                              len(upcoming["< 1 hour"]) +
                              len(upcoming["Later today"]))
        if total_today_events <= 2:
            for event_time in times_tomorrow:
                upcoming["Tomorrow"].append((event["name"], event_time))

    # Now build the embed via our helper
    embed = await build_upcoming_embed(upcoming, days_since_open, now_uk)

    # Hash all field name:value lines to detect changes
    embed_text = "\n".join(f"{f.name}:{f.value}" for f in embed.fields)
    embed_hash = hash(embed_text)

    # Only send/edit if something changed
    if embed_hash != last_embed_hash:
        channel = bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if last_summary_message:
            try:
                await last_summary_message.edit(embed=embed)
            except:
                last_summary_message = await channel.send(embed=embed)
        else:
            last_summary_message = await channel.send(embed=embed)

        last_embed_hash = embed_hash


async def send_event_message(event_name, event_time, status):
    channel = bot.get_channel(ANNOUNCE_CHANNEL_ID)
    if not channel:
        print(f"❌ Could not find channel {ANNOUNCE_CHANNEL_ID}")
        return

    unix_ts = int(event_time.timestamp())

    if status == "soon":
        emoji = "⏳"
        msg = f"{emoji} **{event_name}** opens in 15 minutes — <t:{unix_ts}:t> your time."
    elif status == "open":
        emoji = "✅"
        msg = f"{emoji} **{event_name}** is now **OPEN**! Join before <t:{unix_ts + 60 * (5 if event_name == 'Chaos Castle' else 15)}:t>."
    else:
        emoji = "❌"
        msg = f"{emoji} **{event_name}** is now **CLOSED**."

    await channel.send(msg)


async def announce_event(event):
    channel = bot.get_channel(ANNOUNCE_CHANNEL_ID)
    if not channel:
        print("❌ Announcement channel not found.")
        return

    # Get the event time in London (base timezone)
    london = pytz.timezone('Europe/London')
    now_london = datetime.now(london)
    event_dt = now_london.replace(hour=event["hour"],
                                  minute=event["minute"],
                                  second=0,
                                  microsecond=0)

    # Convert to a Unix timestamp for Discord dynamic time formatting
    unix_ts = int(event_dt.timestamp())

    # Example: 📣 Blood Castle starts <t:1694991600:t> (<t:1694991600:R>)
    # Which Discord renders as: "starts at 9:00 PM" or "in 15 minutes"
    message = (f"📣 **{event['name']}** is starting soon!\n"
               f"🕒 <t:{unix_ts}:t> your time — <t:{unix_ts}:R>")

    await channel.send(message)


def generate_event_times(event, date):
    tz = pytz.timezone("Europe/London")
    times = []

    if "fixed_times" in event:
        for t in event["fixed_times"]:
            h, m = map(int, t.split(":"))
            times.append(
                tz.localize(datetime(date.year, date.month, date.day, h, m)))
    elif "interval_hours" in event and event["interval_hours"] is not None:
        start_hour = event["start_hour"]
        interval = event["interval_hours"]
        minute = event.get("start_minute", 0)
        for i in range(24 // interval):
            hour = (start_hour + i * interval) % 24
            times.append(
                tz.localize(
                    datetime(date.year, date.month, date.day, hour, minute)))
    elif "start_hour" in event:
        h = event["start_hour"]
        m = event.get("start_minute", 0)
        times.append(
            tz.localize(datetime(date.year, date.month, date.day, h, m)))

    return times


@bot.command()
async def events(ctx):
    now_uk = datetime.now(pytz.timezone("Europe/London")).replace(
        second=0, microsecond=0)
    weekday = now_uk.weekday()
    upcoming = {
        "< 15 min": [],
        "< 1 hour": [],
        "Later today": [],
        "Tomorrow": []
    }

    server_start_date = datetime(2025,
                                 5,
                                 20,
                                 tzinfo=pytz.timezone("Europe/London"))
    days_since_open = (now_uk - server_start_date).days
    tomorrow = (now_uk + timedelta(days=1)).date()

    for event in event_definitions:
        if event.get("is_buff"):
            continue
        if weekday not in event["days"]:
            continue
        if event[
                "name"] == "Cross-Server Dragon" and days_since_open < event.get(
                    "unlock_after_days", 0):
            continue

        times_today = generate_event_times(event, now_uk.date())
        times_tomorrow = generate_event_times(event, tomorrow)

        for event_time in times_today:
            if event_time > now_uk:
                delta_minutes = (event_time - now_uk).total_seconds() / 60
                if delta_minutes <= 15:
                    upcoming["< 15 min"].append((event["name"], event_time))
                elif delta_minutes <= 60:
                    upcoming["< 1 hour"].append((event["name"], event_time))
                else:
                    upcoming["Later today"].append((event["name"], event_time))

        total_today_events = len(upcoming["< 15 min"]) + len(
            upcoming["< 1 hour"]) + len(upcoming["Later today"])
        if total_today_events <= 2:
            for event_time in times_tomorrow:
                upcoming["Tomorrow"].append((event["name"], event_time))

    # This is the key: pass user ID here to get their timezone in the embed title
    await post_upcoming_embed(upcoming,
                              days_since_open,
                              now_uk,
                              user_id=ctx.author.id)


bot.run(TOKEN)
