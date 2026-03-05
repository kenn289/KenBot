"""
Ken ClawdBot — Flask API Bridge
The Python brain that the Node.js WhatsApp bot calls via HTTP.
Also exposes manual control endpoints.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from flask import Flask, jsonify, request
from flask_cors import CORS

from channels.twitter.poster import twitter
from channels.youtube.content_gen import yt_content
from channels.youtube.uploader import yt_uploader
from content.scheduler import scheduler
from core.ai_engine import ken_ai
from core.mood import mood_manager
from memory.store import memory
from config.settings import settings
from utils.logger import logger

app = Flask(__name__)
CORS(app)


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

    is_dm        = data.get("is_dm", not bool(group_name))
    is_mentioned = data.get("is_mentioned", False)

    if not text:
        return jsonify({"reply": ""}), 200

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
    )

    # Store Ken's reply
    memory.add_message("whatsapp", chat_id, "ken", reply)

    logger.info(f"WhatsApp reply [{group_name or sender_name}]: {reply[:80]}…")
    return jsonify({"reply": reply}), 200


# ════════════════════════════════════════════════════════
#  REMINDERS ENDPOINTS
# ════════════════════════════════════════════════════════

@app.route("/api/learn", methods=["POST"])
def learn_style():
    """Feed a message Kenneth typed to the style-learning engine."""
    data = request.get_json(force=True) or {}
    msg = data.get("message", "").strip()
    if msg and len(msg) > 3:
        ken_ai.learn_from_message(msg)
        logger.debug(f"Style learning: {msg[:60]}")
    return jsonify({"ok": True}), 200


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
#  HEALTH CHECK
# ════════════════════════════════════════════════════════

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "bot": "Ken ClawdBot",
        "mood": mood_manager.current(),
        "twitter_ready": twitter.ready,
        "time": datetime.utcnow().isoformat(),
    }), 200


def run_api(port: int = 5050) -> None:
    logger.info(f"🌐 Flask API starting on port {port}")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
