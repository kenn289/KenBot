"""
Ken ClawdBot — Flask API Bridge
The Python brain that the Node.js WhatsApp bot calls via HTTP.
Also exposes manual control endpoints.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from flask import Flask, jsonify, request
from flask_cors import CORS

from channels.twitter.poster import twitter
from channels.twitter.x_engagement import x_engagement
from channels.youtube.content_gen import yt_content
from channels.youtube.uploader import yt_uploader
from content.scheduler import scheduler
from core.ai_engine import ken_ai
from core.mood import mood_manager
from core.health_monitor import health_monitor, register_alert_callback
from memory.store import memory
from config.settings import settings
from utils.logger import logger

app = Flask(__name__)
CORS(app)

# ── Inbox log (in-memory, cleared every 3h when summary is fetched) ──
_inbox_lock = threading.Lock()
_inbox_log: list[dict] = []
_notify_queue: list[str] = []


# ════════════════════════════════════════════════════════
#  WHATSAPP ENDPOINTS (called from bot.js)
# ════════════════════════════════════════════════════════

@app.route("/api/whatsapp/reply", methods=["POST"])
def whatsapp_reply():
    """Generate Ken's reply to an incoming WhatsApp message."""
    data = request.get_json(force=True)
    text         = data.get("text", "").strip()
    sender_name  = data.get("sender_name", "")
    group_name   = data.get("group_name", "")
    chat_id      = data.get("chat_id", "")
    contact_id   = data.get("contact_id", chat_id)  # individual sender JID

    is_dm        = data.get("is_dm", not bool(group_name))
    is_mentioned = data.get("is_mentioned", False)

    if not text:
        return jsonify({"reply": ""}), 200

    # Resolve contact type: try JID first, then "name:<sender>" fallback
    contact_type = "unknown"
    if contact_id:
        contact_type = memory.get_contact_type(contact_id)
    if contact_type == "unknown" and sender_name:
        contact_type = memory.get_contact_type(f"name:{sender_name.lower()}")

    # Store the incoming message
    memory.add_message("whatsapp", chat_id, "user", f"{sender_name}: {text}")

    # Get recent context
    context = memory.get_context("whatsapp", chat_id, last_n=8)

    # Generate reply
    reply = ken_ai.reply_to_message(
        message=text,
        sender_name=sender_name,
        group_name=group_name,
        context_history=context,
        is_dm=not bool(group_name),
        chat_id=chat_id,
        is_mentioned=is_mentioned,
        contact_type=contact_type,
    )

    # Store Ken's reply
    memory.add_message("whatsapp", chat_id, "ken", reply)

    logger.info(f"WhatsApp reply [{group_name or sender_name}]: {reply[:80]}...")
    return jsonify({"reply": reply}), 200


# ════════════════════════════════════════════════════════
#  REMINDERS ENDPOINTS
# ════════════════════════════════════════════════════════

import re as _re

def _scrub_sensitive(text: str) -> str:
    """Strip phone numbers, emails, OTPs, bank-style amounts before storing."""
    text = _re.sub(r'\b[\+]?[\d\s\-\(\)]{10,15}\b', '[num]', text)          # phone numbers
    text = _re.sub(r'[\w\.\-]+@[\w\.\-]+\.\w{2,}', '[email]', text)          # emails
    text = _re.sub(r'\b\d{4,6}\b', '[code]', text)                            # OTPs / short codes
    text = _re.sub(r'(rs\.?\s*|inr\s*|₹\s*)[\d,]+', '[amount]', text, flags=_re.I)  # money
    text = _re.sub(r'\b(password|otp|pin|cvv|upi|neft)\b.*', '[redacted]', text, flags=_re.I)
    return text.strip()


@app.route("/api/learn", methods=["POST"])
def learn_style():
    """Feed a message Kenneth typed to the style-learning engine."""
    data = request.get_json(force=True) or {}
    msg = _scrub_sensitive(data.get("message", "").strip())
    if msg and len(msg) > 3:
        ken_ai.learn_from_message(msg)
        logger.debug(f"Style learning: {msg[:60]}")
    return jsonify({"ok": True}), 200


@app.route("/api/learn/convo", methods=["POST"])
def learn_convo():
    """Feed an incoming message (from others) to the convo-context learner."""
    data = request.get_json(force=True) or {}
    speaker = data.get("speaker", "friend").strip()
    msg = _scrub_sensitive(data.get("message", "").strip())
    if msg and len(msg) > 4:
        ken_ai.learn_from_convo(speaker, msg)
        logger.debug(f"Convo learning [{speaker}]: {msg[:60]}")
    return jsonify({"ok": True}), 200


@app.route("/api/fun-fact", methods=["POST"])
def store_fun_fact():
    """Store a fun fact about Kenneth shared in a specific chat."""
    data = request.get_json(force=True) or {}
    chat_id = data.get("chat_id", "").strip()
    speaker = data.get("speaker", "someone").strip()
    fact    = _scrub_sensitive(data.get("fact", "").strip())
    if fact and chat_id:
        memory.store_fun_fact(chat_id, speaker, fact)
        logger.info(f"Fun fact stored [{chat_id}] from {speaker}: {fact[:60]}")
    return jsonify({"ok": True}), 200


@app.route("/api/contact/type", methods=["POST"])
def set_contact_type():
    """Tag a contact as friend / family / adult / colleague."""
    data = request.get_json(force=True) or {}
    contact_id   = data.get("contact_id", "").strip()
    contact_type = data.get("type", "unknown").strip().lower()
    if contact_id:
        memory.set_contact_type(contact_id, contact_type)
        logger.info(f"Contact type set: {contact_id} -> {contact_type}")
    return jsonify({"ok": True, "contact_id": contact_id, "type": contact_type}), 200


@app.route("/api/contact/type", methods=["GET"])
def get_contact_type():
    contact_id = request.args.get("contact_id", "")
    return jsonify({"contact_id": contact_id, "type": memory.get_contact_type(contact_id)}), 200


@app.route("/api/whatsapp/shitpost", methods=["POST"])
def whatsapp_shitpost():
    """Generate an unprompted shitpost for Ken to drop in a group."""
    data = request.get_json(force=True) or {}
    group_name = data.get("group_name", "")
    post = ken_ai.generate_shitpost(group_name)
    logger.info(f"Shitpost [{group_name}]: {post[:80]}\u2026")
    return jsonify({"post": post}), 200


@app.route("/api/whatsapp/proactive", methods=["POST"])
def whatsapp_proactive():
    """Randomly pick between shitpost, convo starter, or hot take."""
    import random
    data = request.get_json(force=True) or {}
    group_name = data.get("group_name", "")
    mode = random.choices(
        ["shitpost", "convo", "convo"],  # convo weighted 2x — more discussion, less pure chaos
        k=1
    )[0]
    if mode == "convo":
        post = ken_ai.generate_convo_starter(group_name)
        label = "convo_starter"
    else:
        post = ken_ai.generate_shitpost(group_name)
        label = "shitpost"
    logger.info(f"Proactive [{label}] [{group_name}]: {post[:80]}\u2026")
    return jsonify({"post": post, "mode": label}), 200


# ════════════════════════════════════════════════════════
#  INBOX ENDPOINTS (away-mode message logging)
# ════════════════════════════════════════════════════════

@app.route("/api/inbox/log", methods=["POST"])
def inbox_log():
    """Log an incoming message for the 3-hour summary."""
    data = request.get_json(force=True) or {}
    entry = {
        "sender":  data.get("sender", "unknown"),
        "group":   data.get("group", ""),
        "message": data.get("message", "")[:120],
        "chat_id": data.get("chat_id", ""),
        "time":    datetime.utcnow().strftime("%H:%M"),
    }
    with _inbox_lock:
        # Avoid duplicate consecutive messages from same sender
        if not _inbox_log or _inbox_log[-1]["chat_id"] != entry["chat_id"] or _inbox_log[-1]["message"] != entry["message"]:
            _inbox_log.append(entry)
    return jsonify({"ok": True}), 200


@app.route("/api/inbox/summary", methods=["GET"])
def inbox_summary():
    """Return formatted summary of all messages since last call, then clear."""
    with _inbox_lock:
        snapshot = list(_inbox_log)
        _inbox_log.clear()
    if not snapshot:
        return jsonify({"summary": "", "count": 0}), 200
    lines = []
    for e in snapshot:
        where = f" ({e['group']})" if e["group"] else " (DM)"
        lines.append(f"• {e['sender']}{where} [{e['time']}]: {e['message']}")
    summary = f"📬 inbox — last 3h ({len(snapshot)} msgs):\n\n" + "\n".join(lines)
    return jsonify({"summary": summary, "count": len(snapshot)}), 200

@app.route("/api/notify", methods=["POST"])
def notify_kenneth():
    """Queue a WhatsApp DM to Kenneth — called after posting content."""
    data = request.get_json(force=True) or {}
    msg = data.get("message", "").strip()
    if msg:
        memory.queue_notification(msg)
    return jsonify({"ok": True}), 200


@app.route("/api/notify/pending", methods=["GET"])
def notify_pending():
    """Return and clear pending notification messages for bot.js to send."""
    msgs = memory.pop_notifications()
    return jsonify({"messages": msgs}), 200

@app.route("/api/reminders/pending", methods=["GET"])
def get_pending_reminders():
    """Return reminders due now (polled by WhatsApp bot)."""
    pending = memory.pending_reminders()
    result = []
    for r in pending:
        # Generate message in Ken's voice
        msg = ken_ai.generate_reminder(r["task"])
        result.append({"id": r["id"], "message": msg, "task": r["task"]})
    return jsonify({"reminders": result}), 200


@app.route("/api/reminders/mark_sent/<int:reminder_id>", methods=["POST"])
def mark_reminder_sent(reminder_id: int):
    memory.mark_reminder_sent(reminder_id)
    return jsonify({"ok": True}), 200


@app.route("/api/reminders/add", methods=["POST"])
def add_reminder():
    """Add a new reminder. Body: {task, due_minutes (int) or due_iso (str)}"""
    data = request.get_json(force=True)
    task = data.get("task", "").strip()
    if not task:
        return jsonify({"error": "task required"}), 400

    due_minutes: Optional[int] = data.get("due_minutes")
    due_iso: Optional[str] = data.get("due_iso")

    if due_minutes is not None:
        due_at = datetime.utcnow() + timedelta(minutes=int(due_minutes))
    elif due_iso:
        due_at = datetime.fromisoformat(due_iso)
    else:
        due_at = datetime.utcnow() + timedelta(minutes=30)

    reminder_id = memory.add_reminder(task, due_at)
    return jsonify({"ok": True, "id": reminder_id, "due_at": due_at.isoformat()}), 200


# ════════════════════════════════════════════════════════
#  TWITTER ENDPOINTS (manual triggers)
# ════════════════════════════════════════════════════════

@app.route("/api/twitter/tweet", methods=["POST"])
def post_tweet():
    data = request.get_json(force=True)
    topic = data.get("topic", "")
    tweet_id = twitter.post_content_tweet(topic or None)
    return jsonify({"ok": bool(tweet_id), "tweet_id": tweet_id}), 200


@app.route("/api/twitter/thread", methods=["POST"])
def post_thread():
    data = request.get_json(force=True)
    topic = data.get("topic", "")
    num = int(data.get("num_tweets", 5))
    ids = twitter.post_content_thread(topic or None, num_tweets=num)
    return jsonify({"ok": bool(ids), "tweet_ids": ids}), 200


@app.route("/api/twitter/engage", methods=["POST"])
def run_engagement():
    """Scrape feed → like + reply on Valorant/Kohli/F1 posts."""
    data    = request.get_json(force=True) or {}
    topics  = data.get("topics")  # optional list override
    def _bg():
        x_engagement.run_engagement(topics or None)
    threading.Thread(target=_bg, daemon=True).start()
    return jsonify({"ok": True, "msg": "engagement run started"}), 200


@app.route("/api/twitter/shitpost", methods=["POST"])
def post_shitpost():
    """Generate + post a gen-z shitpost about Ken's interests."""
    data  = request.get_json(force=True) or {}
    topic = data.get("topic")  # optional specific topic
    result = x_engagement.post_shitpost(topic or None)
    return jsonify({"ok": bool(result), "result": result}), 200


@app.route("/api/twitter/shitpost/preview", methods=["GET"])
def preview_shitpost():
    """Preview a shitpost without posting."""
    topic = request.args.get("topic")
    tweet = x_engagement.generate_shitpost(topic or None)
    return jsonify({"tweet": tweet}), 200


# ════════════════════════════════════════════════════════
#  YOUTUBE ENDPOINTS (manual triggers)
# ════════════════════════════════════════════════════════

@app.route("/api/youtube/generate", methods=["POST"])
def generate_yt():
    data = request.get_json(force=True)
    topic = data.get("topic", "")
    minutes = int(data.get("duration_minutes", 5))
    package = yt_content.generate_video_package(topic or None, duration_minutes=minutes)
    return jsonify(package), 200


@app.route("/api/youtube/upload", methods=["POST"])
def upload_yt():
    data = request.get_json(force=True)
    package = data.get("package", {})
    if not package:
        return jsonify({"error": "package required"}), 400
    video_id = yt_uploader.upload_package(package)
    return jsonify({"ok": bool(video_id), "video_id": video_id}), 200


# ════════════════════════════════════════════════════════
#  SCHEDULER ENDPOINTS
# ════════════════════════════════════════════════════════

@app.route("/api/scheduler/jobs", methods=["GET"])
def list_jobs():
    return jsonify({"jobs": scheduler.list_jobs()}), 200


@app.route("/api/scheduler/trigger/<job_id>", methods=["POST"])
def trigger_job(job_id: str):
    ok = scheduler.trigger_now(job_id)
    return jsonify({"ok": ok}), 200


# ════════════════════════════════════════════════════════
#  MOOD ENDPOINTS
# ════════════════════════════════════════════════════════

@app.route("/api/mood", methods=["GET"])
def get_mood():
    return jsonify(mood_manager.current_profile()), 200


@app.route("/api/mood/set", methods=["POST"])
def set_mood():
    data = request.get_json(force=True)
    mood = data.get("mood", "neutral")
    lock = int(data.get("lock_minutes", 60))
    mood_manager.force_mood(mood, lock_minutes=lock)
    return jsonify({"ok": True, "mood": mood}), 200


# ════════════════════════════════════════════════════════
#  STATUS — what Kenneth is doing right now
# ════════════════════════════════════════════════════════

@app.route("/api/status", methods=["GET"])
def get_status():
    from memory.store import memory
    status = memory.get("ken_status", "")
    return jsonify({"status": status}), 200


@app.route("/api/status", methods=["POST"])
def set_status():
    from memory.store import memory
    data = request.get_json(force=True) or {}
    status = data.get("status", "").strip()
    memory.set("ken_status", status)
    return jsonify({"ok": True, "status": status}), 200


# ════════════════════════════════════════════════════════
#  COMMAND — Kenneth's self-chat "hey ken ..." handler
# ════════════════════════════════════════════════════════

@app.route("/api/command", methods=["POST"])
def handle_command():
    data = request.get_json(force=True) or {}
    instruction = data.get("instruction", "").strip()
    if not instruction:
        return jsonify({"reply": "what do u want me to do"}), 200
    # Soul learning: record what Kenneth explicitly commanded
    try:
        from core.soul_engine import soul as _soul
        _soul.learn_from_command(instruction)
    except Exception:
        pass
    reply = ken_ai.handle_command(instruction)
    return jsonify({"reply": reply}), 200


# ════════════════════════════════════════════════════════
#  HEALTH CHECK
# ════════════════════════════════════════════════════════

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "bot": "KenBot OS",
        "mood": mood_manager.current(),
        "twitter_ready": twitter.ready,
        "time": datetime.utcnow().isoformat(),
    }), 200


# ============================================================
#  KENBOT OS — NEW ENDPOINTS
# ============================================================

@app.route("/api/trending", methods=["GET"])
def get_trending():
    try:
        from content.trend_scanner import trend_scanner
        trends = trend_scanner.get_trends()
        return jsonify({"trends": trends[:10]}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cricket/update", methods=["GET"])
def cricket_update():
    from core.news_fetcher import news_fetcher
    force = request.args.get("force", "false").lower() == "true"
    return jsonify({"update": news_fetcher.get_cricket_update(force=force)}), 200


@app.route("/api/news", methods=["GET"])
def get_news():
    """
    Live news headlines.
    Query params:
      category = top | cricket | tech | india | gaming | f1 | sports  (default: top)
      n        = number of items                                        (default: 5)
      force    = true to bypass cache                                   (default: false)
    """
    from core.news_fetcher import news_fetcher
    category = request.args.get("category", "top")
    n        = int(request.args.get("n", 5))
    force    = request.args.get("force", "false").lower() == "true"
    text     = request.args.get("format", "text") == "text"
    if text:
        return jsonify({"result": news_fetcher.format_headlines(category, n, force)}), 200
    items = news_fetcher.get_headlines(category, n, force)
    return jsonify({"category": category, "count": len(items), "items": items}), 200


@app.route("/api/news/search", methods=["GET"])
def search_news():
    """
    Search live news for ANY topic via Google News RSS.
    Query params:
      q  = search query (e.g. "man city", "TenZ valorant", "Tesla layoffs")
      n  = number of results  (default: 5)
    """
    from core.news_fetcher import news_fetcher
    q = request.args.get("q", "").strip()
    n = int(request.args.get("n", 5))
    if not q:
        return jsonify({"error": "q parameter required"}), 400
    result = news_fetcher.format_search_results(q, n)
    return jsonify({"query": q, "result": result}), 200


@app.route("/api/analytics", methods=["GET"])
def get_analytics():
    from analytics.performance import analytics
    from growth.engagement_optimizer import engagement_optimizer
    return jsonify({
        "twitter":     analytics.twitter_summary(),
        "youtube":     analytics.youtube_summary(),
        "top_tweets":  analytics.top_tweets(3),
        "strategy":    engagement_optimizer.get_recommendations(),
    }), 200


@app.route("/api/analytics/record", methods=["POST"])
def record_analytics():
    """Record post metrics. Body: {type, id, text, topic, likes, retweets, comments}"""
    data = request.get_json(force=True) or {}
    platform = data.get("type", "tweet")
    try:
        from analytics.performance import analytics
        if platform == "tweet":
            analytics.record_tweet(
                data.get("id", ""),
                data.get("text", ""),
                topic=data.get("topic", ""),
                humor_category=data.get("humor_category", ""),
            )
        elif platform == "video":
            analytics.record_video(
                data.get("id", ""),
                data.get("text", ""),
                topic=data.get("topic", ""),
            )
    except Exception as e:
        logger.error(f"Analytics record error: {e}")
    return jsonify({"ok": True}), 200


@app.route("/api/game/trivia", methods=["GET"])
def game_trivia():
    return jsonify({"trivia": ken_ai._generate_trivia()}), 200


@app.route("/api/game/roast", methods=["GET"])
def game_roast():
    target = request.args.get("target", "").strip()
    instr = f"roast {target}" if target else "roast me"
    return jsonify({"roast": ken_ai._generate_roast(instr)}), 200


@app.route("/api/game/debate", methods=["POST"])
def game_debate():
    data = request.get_json(force=True) or {}
    topic = data.get("topic", "")
    return jsonify({"debate": ken_ai._generate_debate(topic)}), 200


@app.route("/api/game/poll", methods=["POST"])
def game_poll():
    data = request.get_json(force=True) or {}
    topic = data.get("topic", "")
    return jsonify({"poll": ken_ai._generate_poll(topic)}), 200


@app.route("/api/ideas", methods=["GET"])
def get_ideas():
    from content.idea_factory import idea_factory
    force = request.args.get("refresh", "false").lower() == "true"
    return jsonify(idea_factory.get_daily_ideas(force_refresh=force)), 200


@app.route("/api/daily-briefing", methods=["GET"])
def daily_briefing():
    """Full morning briefing: trends + ideas + analytics + cricket."""
    briefing = ken_ai._daily_briefing()
    return jsonify({"briefing": briefing}), 200


@app.route("/api/health/services", methods=["GET"])
def health_services():
    return jsonify(health_monitor.status_report()), 200


@app.route("/api/social-graph/set-tier", methods=["POST"])
def social_graph_set_tier():
    """Set relationship tier for a contact."""
    data = request.get_json(force=True) or {}
    contact_id = data.get("contact_id", "").strip()
    tier       = data.get("tier", "public").strip()
    if contact_id:
        from core.social_graph import social_graph
        social_graph.set_tier(contact_id, tier)
    return jsonify({"ok": True, "contact_id": contact_id, "tier": tier}), 200


@app.route("/api/reddit/opportunities", methods=["GET"])
def reddit_opportunities():
    from growth.reddit_engine import reddit_engine
    return jsonify({"opportunities": reddit_engine.get_posting_opportunities()}), 200


@app.route("/api/meme", methods=["POST"])
def generate_meme():
    data = request.get_json(force=True) or {}
    situation = data.get("situation", "")
    from content.meme_generator import meme_generator
    result = meme_generator.generate(situation)
    return jsonify(result), 200


def run_api(port: int = 5050) -> None:
    # Wire health monitor alert → queue WhatsApp DM to Kenneth
    def _alert_ken(msg: str) -> None:
        memory.queue_notification(msg)
    register_alert_callback(_alert_ken)
    # Give flask a very generous threshold — the self-ping thread below fires every 5min
    health_monitor.register("flask", max_silence_seconds=86400)
    health_monitor.register("scheduler", max_silence_seconds=7200)
    health_monitor.start()
    health_monitor.ping("flask")

    # Keep Flask heartbeat alive — ping on every request
    @app.before_request
    def _flask_heartbeat():
        health_monitor.ping("flask")

    # Background self-ping: ensures Flask stays healthy even with zero traffic
    def _self_ping_loop():
        while True:
            time.sleep(300)  # every 5 minutes
            health_monitor.ping("flask")
    threading.Thread(target=_self_ping_loop, daemon=True, name="flask-heartbeat").start()

    logger.info(f"Flask API starting on port {port}")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    run_api()
