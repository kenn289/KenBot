# ClawdBot — Kenny

> A personal AI agent that lives on WhatsApp, X, and YouTube.  
> Replies like Kenneth, posts like Kenneth, keeps up with what's happening — and shuts up when asked.

---

## What it does

| Feature | Details |
|---|---|
| **WhatsApp replies** | Responds in groups only when called by name (`ken`/`kenny`) or @mentioned. Always replies in DMs. |
| **Style learning** | Watches how Kenneth texts in real groups and adapts to match his patterns over time. |
| **Proactive posts** | Drops shitposts or conversation starters in real groups 5x/day on a schedule. |
| **Mute / back off** | If told to stop, goes quiet for 30 minutes. Lifts automatically or when called back by name. |
| **Twitter / X** | Posts 5 tweets/day + 1 weekend thread on a cron schedule. |
| **YouTube** | Generates 2 video drafts/day — title, description, tags, and full script. |
| **Mood engine** | Mood shifts naturally based on conversation context (happy, low, valorant mode, cricket mode, etc.). |
| **News awareness** | Fetches live headlines hourly — knows what's happening and references it naturally. |
| **Kannada** | Uses Kannada slang naturally with close people (machha, hauda, bekilla, gottilla, yen aitu). |
| **Memory** | Remembers conversation history per chat. Never repeats itself. |
| **Mute / resume** | Per-chat 30-min mute. Resumes when name is mentioned or @tag used. |

---

## Stack

- **Python 3.13** — Flask API, AI engine, scheduler, memory
- **Node.js** — WhatsApp via `whatsapp-web.js` + Puppeteer
- **Anthropic Claude** — primary AI (`claude-haiku-4-5` for quick replies, `claude-sonnet-4-5` for serious mode and content)
- **APScheduler** — proactive posting, tweet cron, YouTube draft cron
- **SQLite** — conversation memory, response cache, key-value store, style profile
- **feedparser** — live news from BBC, Times of India, Sportstar (refreshed hourly)
- **Tweepy** — Twitter/X posting
- **Google APIs** — YouTube Data API v3

---

## Project structure

```
clawdbot/
├── api_bridge.py           # Flask app — all Python HTTP endpoints
├── run.py                  # Starts Flask + scheduler
├── run.bat                 # Windows launcher (disables sleep, opens both terminals)
│
├── channels/
│   ├── whatsapp/
│   │   └── bot.js          # WhatsApp bot (Node.js) — auth, routing, proactive cron
│   ├── twitter/
│   │   └── poster.py       # Tweet generation + Tweepy posting
│   └── youtube/
│       ├── content_gen.py  # Title / description / script generation
│       └── uploader.py     # YouTube Data API v3 upload
│
├── core/
│   ├── ai_engine.py        # All AI — routing, prompt building, style learning, news, mute
│   └── mood.py             # Mood engine + context-based drift
│
├── config/
│   ├── ken_personality.py  # Identity, moods, content pillars, response rules
│   └── settings.py         # Env vars, group config, paths
│
├── content/
│   └── scheduler.py        # APScheduler jobs — tweets, YouTube drafts, weekend thread
│
├── memory/
│   └── store.py            # SQLite — chat history, reminders, posted content, KV store
│
├── soul/                   # Personality reference / soul files
├── utils/                  # Logger, retry helpers, truncation
│
├── .env.example            # Copy to .env and fill in keys
├── requirements.txt        # Python dependencies
└── package.json            # Node.js dependencies
```

---

## Setup

### 1. Clone

```bash
git clone https://github.com/kenn289/clawdbot.git
cd clawdbot
```

### 2. Python environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
pip install -r requirements.txt

# macOS/Linux
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Node.js dependencies

```bash
npm install
npx puppeteer browsers install chrome
```

### 4. Environment variables

Copy `.env.example` to `.env` and fill in:

```env
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=...               # optional fallback
OPENAI_API_KEY=...               # optional fallback

MY_WHATSAPP_NUMBER=91XXXXXXXXXX  # your number with country code, no +
KEN_REAL_GROUPS=Jaatre bois,Bengaluru Big Ball Beasts👾👾,somalian day care center
FLASK_PORT=5050
TIMEZONE=Asia/Kolkata

# Twitter — set Read+Write permissions BEFORE generating tokens
TWITTER_API_KEY=
TWITTER_API_SECRET=
TWITTER_ACCESS_TOKEN=
TWITTER_ACCESS_TOKEN_SECRET=
TWITTER_BEARER_TOKEN=

# YouTube
GOOGLE_OAUTH_CREDENTIALS=./credentials/google_oauth.json
```

### 5. Run

```bat
run.bat
```

Or manually:

```bash
# Terminal 1 — Python brain
python run.py

# Terminal 2 — WhatsApp bot
node channels/whatsapp/bot.js
```

First run shows a QR code — scan with WhatsApp. Session is cached after that, no re-scan needed.

---

## How Kenny decides to reply

```
Incoming message
      │
      ├─ DM → always reply
      │
      ├─ Real group → only if "ken" or "kenny" in text, OR @mentioned
      │
      ├─ Other group → only if @mentioned
      │
      ├─ Muted? (someone said stop/stfu/go away)
      │       └─ Silent until 30min expires OR name/mention used again
      │
      ├─ Classify message: serious / rant / casual / skip / mute
      │       └─ skip  → stays quiet (short noise like "lol", "ok")
      │       └─ mute  → sets 30-min per-chat cooldown
      │       └─ rant  → listen-first mode, brief empathy
      │       └─ serious → full support, no banter
      │
      └─ Reply using: mood + live news context + learned style profile
```

---

## Style learning

Every message Kenneth types in a real group is captured and sent to `/api/learn`.  
Every 8 messages, the bot runs a Haiku analysis on the last 30 messages to extract:
- Vocabulary and slang patterns
- Sentence length and energy
- Emoji habits
- How he reacts to different things
- Recurring phrases

The profile is stored in SQLite and injected into every reply prompt automatically.  
The bot gets more accurate over time with zero manual tuning.

---

## Proactive posting

Kenny doesn't just react — he also initiates. 5 times a day at fixed IST times, he picks a real group and either:
- Drops a random shitpost (Bangalore life, Valorant take, football opinion, Kohli stan content)
- Starts a conversation (this-or-that debate, hypothetical, hot take that asks for responses)

---

## API endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/whatsapp/reply` | POST | Generate reply to incoming message |
| `/api/whatsapp/proactive` | POST | Random shitpost or convo starter |
| `/api/whatsapp/shitpost` | POST | Explicit shitpost |
| `/api/learn` | POST | Feed a Kenneth-typed message to style learner |
| `/api/reminder` | POST | Create a self-reminder |
| `/api/tweet` | POST | Generate + post a tweet |
| `/health` | GET | Status + current mood |

---

## What's excluded from git

```
.env                # secrets — use .env.example as template
.venv/              # Python virtual environment
node_modules/       # Node packages
.wwebjs_auth/       # WhatsApp session — re-scan will regenerate
.wwebjs_cache/      # WhatsApp media cache
memory/*.db         # SQLite databases
logs/               # Runtime logs
credentials/        # Google OAuth credentials
```

---

## Twitter setup

1. Go to [developer.twitter.com](https://developer.twitter.com)
2. Create a project and app
3. Set app permissions to **Read and Write** (do this BEFORE generating tokens)
4. Generate all 5 keys and paste into `.env`
5. Twitter starts posting immediately — no restart needed after key update

---

## Requirements

- Python 3.11+
- Node.js 18+
- An Anthropic API key with credits (primary AI — everything else is optional fallback)
- A WhatsApp account
