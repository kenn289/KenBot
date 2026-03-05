# HEARTBEAT.md — Ken's Scheduled Pulse
_Automated tasks that run even when you're away._

---

## Daily Jobs

### Morning Tweet — 09:30 IST
- Pick content topic from pillars
- Generate hot-take tweet via Claude Haiku
- Post to X (if Twitter API configured)
- Budget: 1 tweet out of 8/day limit

### YouTube Draft — 15:00 IST
- Pick content topic
- Generate full script (5 min video)
- Generate title, description, tags
- Save to `media/youtube/`
- No upload (manual review first or trigger via API)

### Evening Tweet — 20:00 IST
- Same as morning but different angle/topic
- Budget: 1 tweet out of 8/day limit

---

## Weekly Jobs

### Thread Saturday — 11:00 IST
- Pick a meaty topic (Valorant analysis, MCU theory, Man City season review, etc.)
- Generate 5-tweet thread
- Post as thread on X
- Budget: 5 tweets

---

## Continuous Jobs (every 1 minute, via WhatsApp bot)

### Reminder Poller
- Check `memory/ken_memory.db` for pending reminders
- Send due reminders to self via WhatsApp
- Mark sent

---

## Manual Triggers (via API)

POST `/api/twitter/tweet`       — immediate tweet
POST `/api/twitter/thread`      — immediate thread  
POST `/api/youtube/generate`    — generate YT package now
POST `/api/youtube/upload`      — upload a package to YouTube
POST `/api/scheduler/trigger/{job_id}` — trigger any scheduled job
POST `/api/reminders/add`       — add a new reminder
POST `/api/mood/set`            — override current mood

---

## Notes

- All jobs are rate-limited and deduped (won't post same content twice)
- If quota is hit, job silently skips and logs warning
- Mood state persists across restarts (SQLite)
