"""
KenBot OS -- End-to-End Test Suite
Run with: .venv/Scripts/python tests/e2e_test.py
Flask must be running on port 5050 before running this.
"""

import json
import os
import sys
import time
import traceback
from typing import Any

# Ensure project root is on sys.path so local modules can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

BASE = "http://127.0.0.1:5050"
TIMEOUT_FAST = 6
TIMEOUT_AI = 25
TIMEOUT_CONTENT = 20

results = []
_pass = 0
_fail = 0


def test(name: str, fn, *, timeout_ok=True):
    global _pass, _fail
    try:
        detail = fn()
        _pass += 1
        results.append(("PASS", name, str(detail)[:90]))
        print(f"  \033[32mPASS\033[0m  {name}")
        if detail:
            print(f"        {str(detail)[:100]}")
    except Exception as exc:
        _fail += 1
        msg = str(exc).split("\n")[0][:100]
        results.append(("FAIL", name, msg))
        print(f"  \033[31mFAIL\033[0m  {name}")
        print(f"        {msg}")


def get(path, timeout=TIMEOUT_FAST):
    r = requests.get(BASE + path, timeout=timeout)
    r.raise_for_status()
    return r.json()


def post(path, body=None, timeout=TIMEOUT_FAST):
    r = requests.post(BASE + path, json=body or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ── Group separator ──────────────────────────────────────────────────────────
def section(title):
    print(f"\n\033[36m{'=' * 55}\033[0m")
    print(f"\033[36m  {title}\033[0m")
    print(f"\033[36m{'=' * 55}\033[0m")


# ============================================================
# 1. CORE HEALTH
# ============================================================
section("1. CORE HEALTH")

test("GET /health", lambda: (
    lambda r: f"bot={r['bot']} status={r['status']} twitter={r['twitter_ready']}"
)(get("/health")))

test("GET /api/status", lambda: (
    lambda r: f"status={r.get('status','?')[:50]}"
)(get("/api/status")))

test("GET /api/health/services", lambda: (
    lambda r: f"flask={r['flask']['healthy']} scheduler={r['scheduler']['healthy']}"
)(get("/api/health/services")))

# ============================================================
# 2. MOOD + STATUS
# ============================================================
section("2. MOOD + STATUS")

test("POST /api/mood/set (set to hype)", lambda: (
    lambda r: f"mood={r.get('mood','?')}"
)(post("/api/mood/set", {"mood": "hype"})))

test("POST /api/status (set status)", lambda: (
    lambda r: f"ok={r.get('ok',False)}"
)(post("/api/status", {"status": "testing kenbot os"})))

test("GET /api/status (verify)", lambda: (
    lambda r: f"status={r.get('status','?')[:50]}"
)(get("/api/status")))

# ============================================================
# 3. WHATSAPP AI
# ============================================================
section("3. WHATSAPP AI")

test("POST /api/whatsapp/reply (group DM)", lambda: (
    lambda r: f"reply={r['reply'][:60]}..."
)(post("/api/whatsapp/reply", {
    "text": "yo what's good bro",
    "sender_name": "Ranjit",
    "group_name": "jaatre bois",
    "chat_id": "test1@g.us",
    "contact_id": "91test1@c.us",
    "is_mentioned": True,
}, timeout=TIMEOUT_AI)))

test("POST /api/whatsapp/reply (unknown DM)", lambda: (
    lambda r: f"reply={r['reply'][:60]}..."
)(post("/api/whatsapp/reply", {
    "text": "hey can you help me with something",
    "sender_name": "stranger",
    "group_name": "",
    "chat_id": "stranger@c.us",
    "contact_id": "stranger@c.us",
    "is_mentioned": False,
}, timeout=TIMEOUT_AI)))

test("POST /api/whatsapp/proactive", lambda: (
    lambda r: f"post={r['post'][:60]}..."
)(post("/api/whatsapp/proactive", {"group_name": "jaatre bois"}, timeout=TIMEOUT_AI)))

test("POST /api/learn (outgoing)", lambda: (
    lambda r: f"ok={r.get('ok')}"
)(post("/api/learn", {"message": "bro valorant ranked is absolutely cooked rn"})))

test("POST /api/learn/convo (incoming)", lambda: (
    lambda r: f"ok={r.get('ok')}"
)(post("/api/learn/convo", {"speaker": "Aryan", "message": "did you watch IPL last night"})))

test("POST /api/command (self-command)", lambda: (
    lambda r: f"reply={r['reply'][:60]}..."
)(post("/api/command", {"instruction": "what's my current mood"}, timeout=TIMEOUT_AI)))

# ============================================================
# 4. CONTACT + SOCIAL GRAPH
# ============================================================
section("4. CONTACT + SOCIAL GRAPH")

test("POST /api/contact/type (tag family)", lambda: (
    lambda r: f"ok={r.get('ok')} type={r.get('type')}"
)(post("/api/contact/type", {"contact_id": "91test@c.us", "type": "family"})))

test("GET /api/contact/type (verify)", lambda: (
    lambda r: f"type={r.get('type')}"
)(get("/api/contact/type?contact_id=91test@c.us")))

test("POST /api/social-graph/set-tier (INNER_CIRCLE)", lambda: (
    lambda r: f"ok={r.get('ok')} tier={r.get('tier')}"
)(post("/api/social-graph/set-tier", {"contact_id": "91ranjit@c.us", "tier": "INNER_CIRCLE"})))

test("POST /api/fun-fact (save a fact)", lambda: (
    lambda r: f"ok={r.get('ok')}"
)(post("/api/fun-fact", {
    "chat_id": "91test@c.us",
    "speaker": "mum",
    "fact": "ken hates waking up before 10am",
})))

# ============================================================
# 5. REMINDERS + NOTIFICATIONS
# ============================================================
section("5. REMINDERS + NOTIFICATIONS")

test("POST /api/reminders/add", lambda: (
    lambda r: f"id={r.get('id')} ok={r.get('ok')}"
)(post("/api/reminders/add", {
    "task": "test reminder from e2e",
    "due_iso": "2099-12-31T23:59:00",
})))

test("GET /api/reminders/pending (none due)", lambda: (
    lambda r: f"count={len(r.get('reminders', []))}"
)(get("/api/reminders/pending")))

test("GET /api/notify/pending", lambda: (
    lambda r: f"count={len(r.get('messages', []))}"
)(get("/api/notify/pending")))

# ============================================================
# 6. INBOX
# ============================================================
section("6. INBOX")

test("POST /api/inbox/log", lambda: (
    lambda r: f"ok={r.get('ok')}"
)(post("/api/inbox/log", {
    "sender": "Ranjit",
    "group": "jaatre bois",
    "message": "test message for inbox",
    "chat_id": "test1@g.us",
})))

test("GET /api/inbox/summary", lambda: (
    lambda r: f"summary_len={len(r.get('summary',''))}"
)(get("/api/inbox/summary", timeout=TIMEOUT_AI)))

# ============================================================
# 7. GAMES + ENTERTAINMENT
# ============================================================
section("7. GAMES + ENTERTAINMENT")

test("GET /api/game/trivia", lambda: (
    lambda r: f"{r['trivia'][:70]}..."
)(get("/api/game/trivia", timeout=TIMEOUT_AI)))

test("GET /api/game/roast", lambda: (
    lambda r: f"{r['roast'][:70]}..."
)(get("/api/game/roast", timeout=TIMEOUT_AI)))

test("POST /api/game/debate (tabs vs spaces)", lambda: (
    lambda r: f"{r['debate'][:70]}..."
)(post("/api/game/debate", {"topic": "tabs vs spaces"}, timeout=TIMEOUT_AI)))

test("POST /api/game/poll (best Valorant agent)", lambda: (
    lambda r: f"{r['poll'][:70]}..."
)(post("/api/game/poll", {"topic": "best Valorant agent"}, timeout=TIMEOUT_AI)))

test("POST /api/game/debate (empty topic)", lambda: (
    lambda r: f"{r['debate'][:70]}..."
)(post("/api/game/debate", {"topic": ""}, timeout=TIMEOUT_AI)))

# ============================================================
# 8. TRENDING + CRICKET
# ============================================================
section("8. TRENDING + CRICKET")

test("GET /api/trending", lambda: (
    lambda r: f"count={len(r['trends'])} top={r['trends'][0]['topic'][:40] if r['trends'] else 'none'}"
)(get("/api/trending", timeout=12)))

test("GET /api/cricket/update", lambda: (
    lambda r: f"{r['update'][:70]}..."
)(get("/api/cricket/update", timeout=TIMEOUT_AI)))

# ============================================================
# 9. CONTENT IDEAS
# ============================================================
section("9. CONTENT IDEAS")

test("GET /api/ideas", lambda: (
    lambda r: f"tweets={len(r.get('tweet_ideas',[]))} threads={len(r.get('thread_ideas',[]))} videos={len(r.get('video_ideas',[]))}"
)(get("/api/ideas", timeout=TIMEOUT_CONTENT)))

test("GET /api/daily-briefing", lambda: (
    lambda r: f"briefing_len={len(r.get('briefing',''))}"
)(get("/api/daily-briefing", timeout=TIMEOUT_AI)))

test("POST /api/meme (drake format)", lambda: (
    lambda r: f"format={r['format']} rendered={r['rendered']}"
)(post("/api/meme", {"format": "drake", "topic": "sleep schedule"}, timeout=10)))

test("POST /api/meme (expanding_brain)", lambda: (
    lambda r: f"format={r['format']} rendered={r['rendered']} path={r.get('path','')[:30]}"
)(post("/api/meme", {"format": "expanding_brain", "topic": "valorant ranked"}, timeout=10)))

test("POST /api/meme (no topic)", lambda: (
    lambda r: f"format={r['format']} tweet_len={len(r.get('fallback_tweet',''))}"
)(post("/api/meme", {}, timeout=10)))

# ============================================================
# 10. REDDIT
# ============================================================
section("10. REDDIT")

test("GET /api/reddit/opportunities", lambda: (
    lambda r: f"count={len(r.get('opportunities', []))}"
)(get("/api/reddit/opportunities", timeout=15)))

# ============================================================
# 11. ANALYTICS
# ============================================================
section("11. ANALYTICS")

test("GET /api/analytics", lambda: (
    lambda r: f"twitter_total={r['twitter']['total']} yt_total={r['youtube']['total']}"
)(get("/api/analytics")))

test("POST /api/analytics/record (tweet)", lambda: (
    lambda r: f"ok={r.get('ok')}"
)(post("/api/analytics/record", {
    "platform": "twitter",
    "content": "test tweet from e2e suite",
    "post_id": "e2e_test_001",
})))

test("POST /api/analytics/record (youtube)", lambda: (
    lambda r: f"ok={r.get('ok')}"
)(post("/api/analytics/record", {
    "platform": "youtube",
    "content": "test video from e2e suite",
    "post_id": "e2e_yt_001",
    "title": "Test YT Short",
})))

test("GET /api/analytics (after records)", lambda: (
    lambda r: f"twitter_total={r['twitter']['total']} yt_total={r['youtube']['total']}"
)(get("/api/analytics")))

# ============================================================
# 12. MODULE IMPORTS
# ============================================================
section("12. MODULE IMPORTS (all new modules)")

MODULES = [
    "core.social_graph",
    "memory.facts_store",
    "core.content_brain",
    "core.humor_engine",
    "core.health_monitor",
    "memory.knowledge_graph",
    "content.trend_scanner",
    "content.idea_factory",
    "content.thread_generator",
    "content.meme_generator",
    "content.reddit_miner",
    "content.podcast_clip_engine",
    "content.repurpose_engine",
    "analytics.performance",
    "growth.influencer_reply_engine",
    "growth.engagement_optimizer",
    "growth.reddit_engine",
    "content.scheduler",
]

for mod in MODULES:
    def _import(m=mod):
        __import__(m)
        return "imported ok"
    test(f"import {mod}", _import)

# ============================================================
# 13. SCHEDULER JOBS
# ============================================================
section("13. SCHEDULER JOBS")

def check_scheduler():
    from content.scheduler import scheduler
    jobs = scheduler.list_jobs()
    ids = [j["id"] for j in jobs]
    required = [
        "tweet_0800", "tweet_0930", "tweet_1200", "tweet_1400",
        "tweet_1530", "tweet_1900", "tweet_2100", "tweet_2230",
        "weekly_thread", "yt_draft_am", "yt_draft_pm",
        "daily_ideas", "daily_briefing",
        "reply_sniper_10", "reply_sniper_15", "reply_sniper_20",
    ]
    missing = [r for r in required if r not in ids]
    if missing:
        raise AssertionError(f"Missing jobs: {missing}")
    return f"{len(jobs)} jobs registered, all required present"

test("Scheduler has all required jobs", check_scheduler)

# ============================================================
# 14. SOCIAL GRAPH LOGIC
# ============================================================
section("14. SOCIAL GRAPH LOGIC")

def check_social_graph():
    from core.social_graph import social_graph, Tier
    social_graph.upsert("test_inner@c.us", name="TestInner", tier=Tier.INNER_CIRCLE)
    social_graph.upsert("test_fam@c.us", name="TestFam", tier=Tier.FAMILY)
    rules_inner = social_graph.get_speech_rules("test_inner@c.us")
    rules_fam = social_graph.get_speech_rules("test_fam@c.us")
    assert rules_inner != rules_fam, "Tier rules should differ"
    tone = social_graph.build_tone_instruction("test_inner@c.us")
    assert len(tone) > 10
    return f"inner_tier=INNER_CIRCLE fam_tier=FAMILY tone_len={len(tone)}"

test("Social graph tier rules", check_social_graph)

# ============================================================
# 15. CONTENT BRAIN
# ============================================================
section("15. CONTENT BRAIN + THREAD GENERATOR")

def check_content_brain():
    from core.content_brain import content_brain
    take = content_brain.hot_take()          # returns dict with 'seed' key
    debate = content_brain.debate_starter()
    poll = content_brain.poll_options("valorant vs apex")
    thread = content_brain.thread_ideas()
    meme = content_brain.meme_idea()
    assert take and debate and poll and thread and meme
    seed = take.get("seed", str(take))
    return f"hot_take_seed={seed[:40]}..."

test("ContentBrain generates all content types", check_content_brain)

def check_thread_gen():
    from content.thread_generator import thread_generator
    tmpl = thread_generator.get_template("bangalore")
    seed = thread_generator.seed_for_ai("valorant_ranked")
    assert tmpl and seed
    return f"template_tweets={len(tmpl)} seed_len={len(seed)}"

test("ThreadGenerator templates", check_thread_gen)

# ============================================================
# 16. KNOWLEDGE GRAPH
# ============================================================
section("16. KNOWLEDGE GRAPH")

def check_kg():
    from memory.knowledge_graph import knowledge_graph
    knowledge_graph.add_person("Ranjit", role="best friend")
    knowledge_graph.add_topic("valorant", category="gaming")
    knowledge_graph.link_person_topic("Ranjit", "valorant")
    related = knowledge_graph.related_topics("Ranjit")
    assert "valorant" in related
    summary = knowledge_graph.summary()
    return f"nodes={summary['total_nodes']} edges={summary['total_edges']}"

test("KnowledgeGraph add + query", check_kg)

# ============================================================
# 17. HUMOR ENGINE
# ============================================================
section("17. HUMOR ENGINE")

def check_humor():
    from core.humor_engine import humor_engine
    humor_engine.record_performance("tech_satire", "ai taking dev jobs lol", likes=120, retweets=45)
    humor_engine.record_performance("cricket_hot_take", "kohli dropping form again", likes=85, retweets=30)
    best = humor_engine.best_category()
    top = humor_engine.top_patterns(n=2)
    assert best and top
    return f"best_category={best} top_count={len(top)}"

test("HumorEngine records + queries", check_humor)

# ============================================================
# 18. REPURPOSE ENGINE
# ============================================================
section("18. REPURPOSE ENGINE")

def check_repurpose():
    from content.repurpose_engine import repurpose_engine
    tweet = repurpose_engine.yt_to_tweet(
        title="Why Valorant ranked is broken in 2026",
        description="A deep dive into the ranking system",
    )
    thread = repurpose_engine.yt_to_thread(
        title="Why Bangalore traffic will never get better",
        script="The actual reason, not what you think",
    )
    assert tweet and thread
    return f"tweet_len={len(tweet)} thread_tweets={len(thread)}"

test("RepurposeEngine yt_to_tweet + yt_to_thread", check_repurpose)

# ============================================================
# 19. ENGAGEMENT OPTIMIZER
# ============================================================
section("19. ENGAGEMENT OPTIMIZER")

def check_optimizer():
    from growth.engagement_optimizer import engagement_optimizer
    recs = engagement_optimizer.get_recommendations()
    briefing = engagement_optimizer.format_briefing()
    assert recs and briefing
    return f"recommendations={len(recs)} briefing_len={len(briefing)}"

test("EngagementOptimizer recommendations", check_optimizer)

# ============================================================
# 20. FACTS STORE
# ============================================================
section("20. FACTS STORE")

def check_facts():
    from memory.facts_store import facts_store
    facts_store.add("loves Bangalore coffee", source_user="test", chat_id="test_chat@c.us", visibility="friends_only")
    facts_store.add("plays Valorant daily", source_user="test", chat_id="test_chat@c.us", visibility="public_safe")
    facts = facts_store.get_for_chat("test_chat@c.us")   # uses default limit
    assert len(facts) >= 2
    block = facts_store.get_prompt_block("test_chat@c.us")
    return f"facts_count={len(facts)} prompt_block_len={len(block)}"

test("FactsStore add + retrieve by visibility", check_facts)

# ============================================================
# FINAL REPORT
# ============================================================
print(f"\n{'=' * 55}")
print(f"  TOTAL: {_pass + _fail}   PASS: \033[32m{_pass}\033[0m   FAIL: \033[31m{_fail}\033[0m")
print(f"{'=' * 55}\n")

if _fail:
    print("FAILED TESTS:")
    for status, name, detail in results:
        if status == "FAIL":
            print(f"  - {name}: {detail}")
    print()

sys.exit(0 if _fail == 0 else 1)
