# KenBot OS

> A self-operating digital personality platform.
> Lives on WhatsApp, X (Twitter), and YouTube. Talks like Kenneth, posts like Kenneth, learns from how he actually communicates — and builds his brand autonomously while he's busy doing other things.

---

## What is KenBot OS?

KenBot OS is not a chatbot. It's an autonomous digital brain that:
- **Holds Kenneth's place** on WhatsApp (replies when tagged, gates strangers, logs everything)
- **Runs his content pipeline** end-to-end (tweets 8x/day, uploads YouTube Shorts, generates threads)
- **Learns his voice** continuously from every message he types
- **Tracks his social graph** — knows family, inner circle, friends, acquaintances, and adjusts tone accordingly
- **Scouts trends** from Reddit + niche feeds to surface what to post about
- **Generates daily content plans** so Kenneth wakes up knowing exactly what to post
- **Snipes viral opportunities** by detecting trending tweets from target accounts and generating on-brand replies
- **Monitors itself** — alerts Kenneth via WhatsApp if any service goes down

---

## Feature Overview

| Module | What it does |
|---|---|
| **WhatsApp Bridge** | Replies in real groups when name-dropped or @tagged. Always replies in DMs. Silent everywhere else. |
| **Away-mode gateway** | First contact gets a status intro. Say `sho` to opt out. |
| **Self-chat commands** | Kenneth messages himself to control everything — post tweets, make YT shorts, check inbox, set mood. |
| **Public commands** | Anyone can request trivia, roasts, debates, polls, cricket updates, or trending topics. |
| **Style learning** | Watches every message Kenneth types in real groups + DMs. Builds a living voice profile. |
| **Convo context learning** | Also reads incoming messages to build a picture of his social world. |
| **Social graph** | Tiers contacts (Inner Circle / Friends / Acquaintances / Family / Public). Tone adapts per tier automatically. |
| **Twitter / X posting** | 8 tweets/day + 1 weekend thread. Style-aware — pulls from trending topics, content brain, and idea factory. |
| **YouTube Shorts** | Full pipeline: AI script -> slides -> ffmpeg re-encode -> music layer -> auto-upload with #Shorts. |
| **Trend scanner** | Scrapes Reddit + contextual seeds. Scores topics for Ken's brand relevance. 30min cache TTL. |
| **Idea factory** | Generates a fresh daily content plan: 5 tweet ideas, 3 thread starters, 4 video concepts. Cached per day. |
| **Content brain** | Template-based engine for hot takes, debate starters, poll options, meme ideas, thread hooks. |
| **Humor engine** | Tracks which humor styles get the best engagement (tech satire, cricket hot take, Bangalore observations, etc.). |
| **Influencer reply sniper** | Detects viral tweets from target accounts and generates on-brand replies to ride their reach. |
| **Thread generator** | Full pre-written thread templates for Bangalore / Valorant / AI-and-work topics. |
| **Meme generator** | Generates drake / two_buttons / expanding_brain meme templates. Optional PIL rendering. |
| **Reddit miner** | Scrapes 8 subreddits for viral posts and classifies them as tweet / thread / video ideas. |
| **Podcast clip engine** | Generates podcast-style AI scripts. Optional ElevenLabs TTS voiceover output. |
| **Repurpose engine** | Converts existing content across platforms: YT -> tweet, YT -> thread, tweet -> reel script. |
| **Analytics** | Records tweet and YT performance. Tracks top performers. |
| **Engagement optimizer** | Reads analytics + humor engine to output concrete strategy recommendations. |
| **Reddit engine** | Finds posting opportunities in relevant subreddits and drafts genuine comments. |
| **Knowledge graph** | Lightweight graph linking people, topics, and events for context enrichment. |
| **Facts store** | Visibility-tagged personal fact store shared by WhatsApp contacts or Kenneth himself. |
| **Health monitor** | Background heartbeat monitor. Alerts Kenneth via WhatsApp if any service goes down. |
| **Proactive shitposting** | Drops unprompted posts in real groups every 2h during active hours (10am-11pm IST). |
| **Inbox summary** | Every 3h, DMs Kenneth a summary of who messaged + what they said. |
| **Mood engine** | Mood drifts naturally from context. Manually lockable via command or API. |
| **News awareness** | Fetches live headlines (BBC, Times of India, Sportstar) hourly. Surfaced naturally in replies. |
| **Notification queue** | Tweets, YT uploads, health alerts, daily briefings — all pushed to Kenneth's WhatsApp. |

---

## Architecture

```
KenBot OS
+-- channels/
|   +-- whatsapp/bot.js          WhatsApp bridge (whatsapp-web.js, Node.js)
|   +-- twitter/poster.py        Twitter posting (Playwright headless Chrome)
+-- core/
|   +-- ai_engine.py             Claude integration + command dispatcher
|   +-- social_graph.py          Relationship tier awareness
|   +-- content_brain.py         Template-based content seeds
|   +-- humor_engine.py          Humor category performance tracker
|   +-- health_monitor.py        Service heartbeat monitor
+-- memory/
|   +-- store.py                 SQLite KV store + memory singleton
|   +-- facts_store.py           Visibility-tagged fact store
|   +-- knowledge_graph.py       Person/topic/event graph
+-- content/
|   +-- scheduler.py             APScheduler job orchestrator
|   +-- trend_scanner.py         Reddit + contextual trend aggregation
|   +-- idea_factory.py          Daily content plan generator
|   +-- thread_generator.py      Pre-written thread templates
|   +-- meme_generator.py        Drake/expanding_brain meme engine
|   +-- reddit_miner.py          Viral idea scraper
|   +-- podcast_clip_engine.py   AI script + ElevenLabs TTS
|   +-- repurpose_engine.py      Cross-platform content repurposing
+-- analytics/
|   +-- performance.py           Tweet + video metrics tracker
+-- growth/
|   +-- influencer_reply_engine.py  Viral reply sniper
|   +-- engagement_optimizer.py     Strategy recommendations
|   +-- reddit_engine.py            Reddit presence management
+-- config/
|   +-- ken_personality.py          Voice rules, tone rules, contact tiers
+-- api_bridge.py                   Flask REST API (port 5050)
+-- memory/ken_memory.db            SQLite database (auto-created)
```

---

## Setup

### Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | Tested on 3.13 |
| Node.js 18+ | For WhatsApp bot |
| ffmpeg | Must be in PATH -- needed for YT Shorts |
| Chrome / Chromium | For WhatsApp QR auth and Twitter posting |
| Anthropic API key | For Claude (haiku / sonnet / opus) |
| Twitter account | Logged in via Playwright session |
| YouTube account | OAuth credentials for upload |
| ElevenLabs key | Optional -- only needed for podcast TTS |

### 1. Clone and install

```bash
git clone https://github.com/yourname/clawdbot.git
cd clawdbot

# Python venv
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

Install Node dependencies:

```bash
cd channels/whatsapp
npm install
cd ../..
```

### 2. Create your `.env`

Copy the template and fill in your values:

```bash
cp .env.example .env
```

> **Critical:** Never commit `.env` to git. It is in `.gitignore` but double-check with `git status` before every push.

Below is a full walkthrough of every key and exactly where to get it.

---

### 3. API Keys — where to get each one

#### A. Anthropic (Claude) — **Required**

Claude powers all AI replies, content generation, trivia, roasts, etc.

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Sign up / log in
3. Click **API Keys** in the left sidebar
4. Click **Create Key** → give it a name → copy the key
5. Add to `.env`:
   ```
   ANTHROPIC_API_KEY=sk-ant-api03-...
   ```

Cost: Pay-as-you-go. haiku-4-5 is used for most replies (~$0.001 per message). Sonnet/Opus only for heavy content tasks.

---

#### B. OpenAI — Optional

Only used as a fallback if Anthropic is unavailable.

1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Click **Create new secret key** → copy it
3. Add to `.env`:
   ```
   OPENAI_API_KEY=sk-proj-...
   ```

Leave blank to skip.

---

#### C. Google Gemini — Optional

Alternative AI model for content generation.

1. Go to [aistudio.google.com](https://aistudio.google.com)
2. Click **Get API key** → Create API key in new project
3. Add to `.env`:
   ```
   GEMINI_API_KEY=AIzaSy...
   ```

Leave blank to skip.

---

#### D. Twitter / X — Required for posting

There are two methods. **You only need one**, but having both is most reliable.

**Method 1: API Keys** (for programmatic posting via tweepy)

1. Go to [developer.twitter.com](https://developer.twitter.com)
2. Click **+ Create Project** → name it anything → choose **Production** use case
3. Click **+ Add App** inside the project → name it
4. Go to **Keys and Tokens** tab:
   - Copy **API Key** and **API Secret** → `TWITTER_API_KEY` / `TWITTER_API_SECRET`
   - Click **Generate** under Access Token → copy both values → `TWITTER_ACCESS_TOKEN` / `TWITTER_ACCESS_TOKEN_SECRET`
   - Copy **Bearer Token** → `TWITTER_BEARER_TOKEN`
5. Under **App Settings → User authentication settings**: set **App permissions** to **Read and Write**
6. Add to `.env`:
   ```
   TWITTER_API_KEY=
   TWITTER_API_SECRET=
   TWITTER_ACCESS_TOKEN=
   TWITTER_ACCESS_TOKEN_SECRET=
   TWITTER_BEARER_TOKEN=
   ```

**Method 2: Browser login** (Playwright headless Chrome — used as fallback)

Add your Twitter login credentials to `.env`:
```
TWITTER_USERNAME=your_handle
TWITTER_PASSWORD=your_password
TWITTER_EMAIL=your_email@example.com
```

Then save a session (run this once):
```powershell
# Windows
$env:PYTHONUTF8="1"; .venv\Scripts\python.exe -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto('https://x.com/login')
    input('Log in manually in the browser window, then press Enter here...')
    browser.contexts[0].storage_state(path='credentials/twitter_session.json')
    print('Session saved to credentials/twitter_session.json')
    browser.close()
"
```

The session file is gitignored and auto-refreshed.

---

#### E. YouTube — Required for Shorts upload

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click the project dropdown (top bar) → **New Project** → give it a name → Create
3. In the left menu: **APIs & Services → Library**
   - Search **YouTube Data API v3** → click it → **Enable**
4. Go to **APIs & Services → OAuth consent screen**
   - User type: **External** → Create
   - Fill in App name (anything), support email, developer email → Save
   - Under **Scopes**: click **Add or Remove Scopes** → search `youtube` → tick `youtube.upload` → Update → Save
   - Under **Test users**: click **Add Users** → add your YouTube account email → Save
5. Go to **APIs & Services → Credentials**
   - Click **+ Create Credentials → OAuth client ID**
   - Application type: **Desktop app** → Name it → Create
   - Click **Download JSON** on the created credential
   - Save the downloaded file as: `credentials/google_oauth.json`
6. The first time the bot uploads a video, a browser window will open for consent. After that, the token is auto-saved to `credentials/youtube_token.pickle` and refreshed automatically.

> **Free quota:** YouTube Data API gives 10,000 units/day. Each upload costs ~1,600 units, so you can safely upload ~6 videos/day. The scheduler only does 2/day by default.

---

#### F. ElevenLabs — Optional (podcast TTS)

Only needed if you want AI voiceover for podcast clips.

1. Go to [elevenlabs.io](https://elevenlabs.io) → Sign up
2. Click your profile (bottom left) → **Profile Settings → API Key** → Copy
3. Add to `.env`:
   ```
   ELEVENLABS_API_KEY=sk_...
   ```

Leave blank to disable TTS (scripts are still generated, just no audio).

---

#### G. Pexels — Optional (background images for YT Shorts)

1. Go to [pexels.com/api](https://www.pexels.com/api/) → Sign up → Request Access
2. Copy your API key from the dashboard
3. Add to `.env`:
   ```
   PEXELS_API_KEY=...
   ```

Leave blank to use solid-colour fallback backgrounds.

---

#### H. Google Places — Optional

Used for location-aware content (Bangalore references, etc.).

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → same project as YouTube
2. **APIs & Services → Library** → search **Places API** → Enable
3. **APIs & Services → Credentials → Create Credentials → API Key**
4. Restrict the key to **Places API** only (click the key → API restrictions)
5. Add to `.env`:
   ```
   GOOGLE_PLACES_API_KEY=AIzaSy...
   ```

---

#### I. Notion — Optional

Used for saving content ideas and briefings to a Notion database.

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations) → New integration
2. Name it, select your workspace, give it **Read + Write** content capabilities → Submit
3. Copy the **Internal Integration Secret** → `NOTION_API_KEY`
4. For `NOTION_CLIENT_ID` and `NOTION_CLIENT_SECRET`: you only need these for OAuth (multi-user). For personal use, just `NOTION_API_KEY` is enough — leave the other two blank.
5. Add to `.env`:
   ```
   NOTION_API_KEY=secret_...
   NOTION_CLIENT_ID=
   NOTION_CLIENT_SECRET=
   ```

---

### 4. App config in `.env`

```env
# Port for internal Flask API
FLASK_PORT=5050

# Your WhatsApp number — international format, no + or spaces or @c.us
# Example for India: 919876543210
MY_WHATSAPP_NUMBER=91XXXXXXXXXX

# Exact WhatsApp group names where you ARE the real person talking
# Comma-separated, must match the group name exactly (case-insensitive)
KEN_REAL_GROUPS=Your Group Name,Another Group

# Timezone for scheduler (see pytz timezone list)
TIMEZONE=Asia/Kolkata

# Chrome path — only needed if Puppeteer can't find Chrome automatically
# Windows: C:\Users\YourName\.cache\puppeteer\chrome\win64-XXX\chrome-win64\chrome.exe
# macOS:   /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
CHROME_EXECUTABLE_PATH=
```

---

### 5. Configure personality

Open [config/ken_personality.py](config/ken_personality.py) and update:

- The personality description block at the top — describe the real person's voice
- `CONTACT_TONE_RULES` — how to speak to each contact type (family, friends, etc.)

---

### 6. Run

**Terminal 1 -- Flask API:**

```powershell
# Windows (ALWAYS set PYTHONUTF8 first):
$env:PYTHONUTF8="1"; .venv\Scripts\python.exe api_bridge.py
```

```bash
# macOS/Linux:
PYTHONUTF8=1 python api_bridge.py
```

**Terminal 2 -- WhatsApp Bot:**

```bash
cd channels/whatsapp
node bot.js
# Scan the QR code with WhatsApp > Linked Devices > Link a Device
```

Verify both are running:
```bash
curl http://localhost:5050/health
# Expected: {"bot": "KenBot OS", "status": "ok", ...}
```

**Terminal 1 -- Flask API:**

```powershell
# Windows (ALWAYS set PYTHONUTF8 first):
$env:PYTHONUTF8="1"; .venv\Scripts\python.exe api_bridge.py
```

```bash
# macOS/Linux:
PYTHONUTF8=1 python api_bridge.py
```

**Terminal 2 -- WhatsApp Bot:**

```bash
cd channels/whatsapp
node bot.js
# Scan the QR code with WhatsApp > Linked Devices > Link a Device
```

Verify both are running:

```bash
curl http://localhost:5050/health
# Expected: {"bot": "KenBot OS", "status": "ok", ...}
```

> **Windows note:** Always set `PYTHONUTF8=1` before starting Flask. Without it you'll get
> `SyntaxError: invalid character` on files that use Unicode characters in comments.

---

## WhatsApp Commands

### Public commands -- anyone in any chat

| Command | What it does |
|---|---|
| `hey ken help` | Shows command list |
| `hey ken fun fact: [fact about ken]` | Saves a fact about Kenneth |
| `hey ken trivia` | Generates a random trivia question |
| `hey ken roast me` | Ken roasts you |
| `hey ken debate [topic]` | Hot take + debate starter on any topic |
| `hey ken poll [topic]` | Generates a poll on any topic |
| `hey ken cricket update` | Latest cricket news |
| `hey ken what's trending` | Top 5 trending topics right now |
| `sho` | Opt out -- bot goes silent for that chat |

### Private commands -- Kenneth messaging himself only

| Command | What it does |
|---|---|
| `hey ken status <text>` | Updates status shown in all intro messages |
| `hey ken mood hype/chill/tired/focused` | Locks mood for 2h |
| `hey ken tag <name/number> as <family/friend/adult/colleague>` | Tags a contact's relationship tier |
| `hey ken post about <topic>` | Posts a tweet immediately |
| `hey ken yt short about <topic>` | Starts YT Short pipeline, DMs when live |
| `hey ken inbox` | Shows who messaged and what they said |
| `hey ken what did u learn` | Shows current style profile + convo context |
| `hey ken <anything else>` | Claude answers directly |

---

## API Reference

All endpoints run on `http://localhost:5050`.

### Core

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Health check -- returns bot name, mood, status |
| GET | `/api/health/services` | Detailed service heartbeat status |
| GET | `/api/status` | Current Kenneth status message |
| POST | `/api/command` | Dispatch a self-command `{instruction}` |

### AI + WhatsApp

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/whatsapp/reply` | Generate a WhatsApp reply |
| POST | `/api/whatsapp/proactive` | Generate a proactive group post |
| POST | `/api/learn` | Submit Kenneth's outgoing message for style learning |
| POST | `/api/learn/convo` | Submit incoming message for convo context |
| GET | `/api/inbox/summary` | 3h inbox summary |
| POST | `/api/inbox/log` | Log a message to inbox |

### Games + Trending

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/game/trivia` | Random trivia question |
| GET | `/api/game/roast` | Roast generator |
| POST | `/api/game/debate` | Debate starter `{topic}` |
| POST | `/api/game/poll` | Poll generator `{topic}` |
| GET | `/api/trending` | Trending topics from Reddit + contextual seeds |
| GET | `/api/cricket/update` | Latest cricket context |

### Content + Ideas

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/ideas` | Daily content plan (tweets, threads, videos) |
| GET | `/api/daily-briefing` | Full morning briefing: trends + ideas + strategy |
| POST | `/api/meme` | Generate meme data `{format?, topic?}` |
| GET | `/api/reddit/opportunities` | Reddit posting opportunities |

### Analytics + Social Graph

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/analytics` | Twitter + YouTube performance summary |
| POST | `/api/analytics/record` | Record a new post |
| POST | `/api/social-graph/set-tier` | Set contact relationship tier `{contact_id, tier}` |

### Contact + Facts

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/contact/type` | Tag contact type `{contact_id, type}` |
| GET | `/api/contact/type?contact_id=...` | Get contact type |
| POST | `/api/fun-fact` | Save a fun fact `{chat_id, speaker, fact}` |

### Reminders + Notifications

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/reminders/set` | Set a reminder |
| GET | `/api/reminders/pending` | Get due reminders |
| GET | `/api/notify/pending` | Poll for pending WhatsApp notifications |

---

## Scheduled Jobs (IST)

| Job | Schedule | Description |
|---|---|---|
| Daily idea generation | 7:00 AM | Fresh tweet/thread/video ideas for the day |
| Daily briefing | 8:30 AM | Morning briefing pushed to Kenneth's WhatsApp |
| Tweet 1 | 8:00 AM | Post tweet |
| Tweet 2 | 9:30 AM | Post tweet |
| Reply sniper | 10:00 AM | Scan influencer accounts for viral reply opportunities |
| Tweet 3 | 12:00 PM | Post tweet |
| Tweet 4 | 2:00 PM | Post tweet |
| Tweet 5 | 3:30 PM | Post tweet |
| Reply sniper | 3:00 PM | Scan influencer accounts |
| YT Draft AM | 10:00 AM | Generate + upload YouTube Short |
| Tweet 6 | 7:00 PM | Post tweet |
| Reply sniper | 8:00 PM | Scan influencer accounts |
| YT Draft PM | 4:00 PM | Generate + upload YouTube Short |
| Tweet 7 | 9:00 PM | Post tweet |
| Tweet 8 | 10:30 PM | Post tweet |
| Weekly thread | Saturday 11:00 AM | Post a 5-tweet thread |
| Inbox summary | Every 3h | DM Kenneth a summary of all messages |
| Proactive shitpost | Every 2h (active hours) | Drop unprompted post in a real group (50% chance) |
| Reminder poller | Every 1 min | Fire any due reminders |
| Notify poller | Every 1 min | Push pending notifications |

---

## Relationship Tiers

KenBot OS tracks relationship tiers and adjusts tone automatically:

| Tier | Who | Tone |
|---|---|---|
| INNER_CIRCLE | Closest friends | Full unfiltered Kenneth -- fire roasts, all slang, zero filter |
| FRIENDS | Regular friends | Casual, fun, slang, light roasts allowed |
| ACQUAINTANCES | People Kenneth knows but isn't close to | Friendly but measured |
| FAMILY | Family members | Warm, respectful, toned-down slang |
| PUBLIC | Strangers | Professional enough but still Kenneth |

Set via WhatsApp:
```
hey ken tag Ranjit as inner_circle
hey ken tag +91XXXXXXXXXX as family
```

Or via API:
```bash
curl -X POST http://localhost:5050/api/social-graph/set-tier \
  -H "Content-Type: application/json" \
  -d '{"contact_id": "91XXXXXXXXXX@c.us", "tier": "FRIENDS"}'
```

---

## Troubleshooting

**SyntaxError: invalid character on Windows**
Always start Flask with `$env:PYTHONUTF8="1"` prefix. Without it Python defaults to cp1252 
encoding and can't read files that have Unicode in comments.

**WhatsApp bot disconnects**
Session is stored in `channels/whatsapp/.wwebjs_auth/`. If it keeps disconnecting, 
delete that folder and re-scan the QR code.

**Flask port already in use**
```powershell
netstat -ano | findstr :5050
Stop-Process -Id <PID> -Force
```

**Twitter Playwright auth fails**
Delete `credentials/twitter_session.json` and re-run the login helper.

**YouTube upload fails -- token expired**
Delete `credentials/youtube_token.json` and restart Flask -- it will prompt for re-auth.

**ModuleNotFoundError for new modules**
Make sure you're running from the project root with the venv active:
```bash
cd c:\Project\clawdbot
.venv\Scripts\activate
python api_bridge.py
```

---

## Tech Stack

| Layer | Tech |
|---|---|
| AI | Anthropic Claude (haiku-4-5 / sonnet-4-5 / opus-4) |
| WhatsApp | whatsapp-web.js (Node.js, QR auth) |
| Twitter | Playwright headless Chrome |
| YouTube | YouTube Data API v3 + ffmpeg |
| API | Flask 3.x |
| Scheduler | APScheduler (CronTrigger, Asia/Kolkata) |
| Database | SQLite (KV store abstraction) |
| TTS | ElevenLabs API (optional) |
| Images | Pillow / PIL (optional, for meme rendering) |
| Trends | Reddit public JSON API (no auth needed) |

---

---

## Security — what's protected from git

The following are in `.gitignore` and will never be committed:

| Path | Contains |
|---|---|
| `.env` | All API keys, passwords, phone number |
| `credentials/*.json` | Google OAuth client secrets |
| `credentials/*.pickle` | YouTube access tokens |
| `credentials/twitter_session.json` | Saved Twitter browser session |
| `.wwebjs_auth/` | WhatsApp QR session (root) |
| `channels/whatsapp/.wwebjs_auth/` | WhatsApp QR session (bot dir) |
| `memory/*.db` | Local database with message history |
| `output/` | Generated memes, clips, images |
| `logs/` | Runtime logs |
| `.venv/` | Python virtual environment |
| `node_modules/` | Node packages |

### Before every `git push` — run this checklist

```bash
# 1. Check nothing sensitive is staged
git status

# 2. Make sure .env is NOT in the diff
git diff --cached --name-only | grep -i env

# 3. Check for any accidentally staged credential files
git diff --cached --name-only | grep -i "credentials\|token\|secret\|key"

# 4. Scan for potential hardcoded secrets (optional but safe)
grep -r "sk-ant\|sk-proj\|AIzaSy\|secret_\|AAAAAAA" --include="*.py" --include="*.js" --include="*.json" .
```

If `git status` shows `.env` as untracked (not staged), you're safe.  
If it somehow shows as tracked, run: `git rm --cached .env`

---

## License

Personal use only -- this is a personal automation platform. Do not deploy it impersonating someone else.
