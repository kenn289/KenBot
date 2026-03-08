/**
 * Ken ClawdBot â€” WhatsApp Bridge
 * Uses whatsapp-web.js (QR auth). Calls the Python Flask API for AI replies.
 *
 * Behaviour rules:
 *  â€¢ DMs â†’ always reply
 *  â€¢ REAL GROUPS (exact 3) â†’ always reply + proactive shitposting every ~2h
 *  â€¢ All other groups â†’ ONLY reply when Ken's contact is explicitly @mentioned
 *                       (NOT @all, NOT @everyone â€” must be a real tag on Ken)
 *  â€¢ Reminders â†’ send to self on schedule
 */

require("dotenv").config({ path: require("path").resolve(__dirname, "../../.env") });

const fs            = require("fs");
const path          = require("path");
const { execSync }  = require("child_process");
const { Client, LocalAuth } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");
const axios = require("axios");
const cron = require("node-cron");

// â”€â”€ Config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
const FLASK_BASE = `http://localhost:${process.env.FLASK_PORT || 5050}`;
const MY_NUMBER  = (process.env.MY_WHATSAPP_NUMBER || "").trim();

// Exact real group names (lowercase for matching)
const REAL_GROUP_NAMES = [
  "jaatre bois",
  "bengaluru big ball beasts\uD83D\uDC7E\uD83D\uDC7E",
  "somalian day care center",
];

// Cache of { lowerName -> chatObject } for proactive messaging
const realGroupChats = {};

// Away-mode: track who got the intro, who opted out
const greetedChats = new Set();
const optedOut     = new Set();

// â”€â”€ Client init â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
const client = new Client({
  authStrategy: new LocalAuth({ dataPath: ".wwebjs_auth" }),
  puppeteer: {
    headless: true,
    executablePath: process.env.CHROME_EXECUTABLE_PATH || undefined,
    protocolTimeout: 60_000,   // raise from default 30s to 60s
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-accelerated-2d-canvas",
      "--no-first-run",
      "--no-zygote",
      "--disable-gpu",
    ],
  },
});

// â”€â”€ QR â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
client.on("qr", (qr) => {
  console.log("\nðŸ¾ Scan this with WhatsApp â†’ Linked Devices â†’ Link a Device\n");
  qrcode.generate(qr, { small: true });
});

client.on("authenticated", () => console.log("âœ… WhatsApp authenticated"));
client.on("auth_failure", (err) => console.error("âŒ Auth failed:", err));
client.on("disconnected", (reason) => {
  console.error("âš  Disconnected:", reason);
  setTimeout(() => client.initialize(), 5000);
});

client.on("ready", () => {
  console.log("Ken WhatsApp bot is live!\n");
  // Start pollers immediately — don't block on group caching
  startReminderPoller();
  startNotifyPoller();
  startShitpostCron();
  startSummaryCron();
  // Cache real groups in background with retries (WA needs a few seconds to fully load chats)
  cacheRealGroupsWithRetry();
});

// ── Cache real group chat objects for proactive use ──────────
async function cacheRealGroups() {
  const chats = await client.getChats();
  let found = 0;
  for (const chat of chats) {
    if (!chat.isGroup) continue;
    const nameLower = (chat.name || "").toLowerCase();
    for (const g of REAL_GROUP_NAMES) {
      if (nameLower.includes(g)) {
        realGroupChats[g] = chat;
        console.log(`[groups] cached: ${chat.name}`);
        found++;
      }
    }
  }
  console.log(`[groups] ${found}/${REAL_GROUP_NAMES.length} real groups cached`);
  return found;
}

async function cacheRealGroupsWithRetry(attempts = 4, delayMs = 8000) {
  for (let i = 1; i <= attempts; i++) {
    // Wait before each attempt (longer on first try to let WA load)
    await new Promise(r => setTimeout(r, i === 1 ? 6000 : delayMs));
    try {
      const found = await cacheRealGroups();
      if (found > 0) return; // success
      console.log(`[groups] 0 found on attempt ${i}/${attempts}, retrying...`);
    } catch (err) {
      console.warn(`[groups] attempt ${i}/${attempts} failed: ${err.message}`);
      if (i === attempts) {
        console.error("[groups] all retries failed — proactive posting disabled until restart.");
      }
    }
  }
}

// â”€â”€ Message handler â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// message_create fires for ALL messages (including fromMe / self-chat).
// message only fires for incoming (fromMe=false). We need message_create
// so that "hey ken ..." commands sent by Kenneth to himself are received.
client.on("message_create", async (msg) => {
  try {
    await handleMessage(msg);
  } catch (err) {
    console.error("Message handler error:", err.message);
  }
});

async function handleMessage(msg) {
  console.log(`[msg] type=${msg.type} fromMe=${msg.fromMe} body=${(msg.body||"").slice(0,60)}`);

  // ── Patch msg.reply so it works even for fromMe=true group messages ──
  // WhatsApp Web.js throws when quote-replying your own message in a group.
  // Fallback: send a plain message to the same chat instead.
  const _origReply = msg.reply.bind(msg);
  msg.reply = async (text) => {
    try {
      await _origReply(text);
    } catch (_) {
      // For fromMe=true: msg.from = Ken's own JID, msg.to = group/recipient JID
      // For fromMe=false: msg.from = sender/group JID (correct target)
      const _fallbackTarget = msg.fromMe ? (msg.to || msg.from) : msg.from;
      try { await client.sendMessage(_fallbackTarget, text); } catch (e2) {
        console.error("[reply-fallback] failed:", e2.message);
      }
    }
  };
  // getMentions/getContact throw internally on these
  const SUPPORTED_TYPES = ["chat", "image", "video", "ptt", "audio"];
  if (!SUPPORTED_TYPES.includes(msg.type)) return;

  // ── Learn from Kenneth's typing: only real groups + DMs + personal chat ──
  if (msg.fromMe && !msg.isStatus && msg.type === "chat" && msg.body && msg.body.length > 4) {
    try {
      const _lc = await msg.getChat();
      const _isRealOrDM = !_lc.isGroup || REAL_GROUP_NAMES.some(g => (_lc.name || "").toLowerCase().includes(g));
      if (_isRealOrDM) {
        axios.post(`${FLASK_BASE}/api/learn`, { message: msg.body }).catch(() => {});
      }
    } catch (_) {}
  }

  // ── Self-command: Kenneth messages himself "hey ken ..." ──
  // In personal chat → handleSelfCommand (private commands)
  // In a group → let it fall through to public command handlers below
  let _fromMeGroupCommand = false;
  if (msg.fromMe && !msg.isStatus && msg.type === "chat" && /^hey\s*ken\b/i.test(msg.body || "")) {
    try {
      const sc = await msg.getChat();
      if (!sc.isGroup) {
        const instruction = (msg.body || "").replace(/^hey\s*ken\s*/i, "").trim();
        if (instruction) await handleSelfCommand(msg, instruction);
        return;
      } else {
        // It's a group — let it fall through to the public "hey ken" handlers below
        _fromMeGroupCommand = true;
      }
    } catch (_) {}
  }

  // Drop all other fromMe messages (learn-only), but NOT fromMe group "hey ken" commands
  if (msg.isStatus || (msg.fromMe && !_fromMeGroupCommand)) return;

  // ── Learn from incoming messages too (convo context) ──
  // Captures what people say TO Kenneth so the bot understands his social world
  if (msg.type === "chat" && msg.body && msg.body.length > 4) {
    try {
      const _c = await msg.getChat();
      const _contact = await msg.getContact();
      const _isReal = _c.isGroup
        ? REAL_GROUP_NAMES.some(g => (_c.name || "").toLowerCase().includes(g))
        : true; // DMs always qualify
      if (_isReal) {
        const _speaker = _contact.pushname || _contact.name || "friend";
        axios.post(`${FLASK_BASE}/api/learn/convo`, { speaker: _speaker, message: msg.body }).catch(() => {});
      }
    } catch (_) {}
  }

  const chat    = await msg.getChat();
  let contact;
  try { contact = await msg.getContact(); } catch (_) { contact = {}; }
  const isGroup = chat.isGroup;
  const groupNameRaw  = isGroup ? (chat.name || "") : "";
  const groupNameLower = groupNameRaw.toLowerCase();
  const senderName    = contact?.pushname || contact?.name || "someone";
  const body          = (msg.body || "").trim();

  if (!body) return;

  // ── Group gate: only respond in the 3 real groups; DMs are always open ──
  // If someone mentions Ken in any other group chat → stay completely silent.
  if (isGroup && !REAL_GROUP_NAMES.some(g => groupNameLower.includes(g))) return;

  // ── Public: "hey ken fun fact: ..." — anyone can share a fact about Kenneth ──
  const funFactMatch = body.match(/^hey\s*ken\s+(?:fun\s*fact|i\s+have\s+a\s+fun\s+fact|u\s+should\s+know)[:\s]+(.+)/i);
  if (funFactMatch) {
    const fact = funFactMatch[1].trim();
    if (fact) {
      axios.post(`${FLASK_BASE}/api/fun-fact`, {
        chat_id: msg.from,
        speaker: senderName,
        fact,
      }).catch(() => {});
      await msg.reply("got it, added that 📝");
    }
    return;
  }

  // ── Public: "hey ken trivia" ──────────────────────────────────
  if (/^hey\s*ken\s+trivia/i.test(body)) {
    try {
      const { data } = await axios.get(`${FLASK_BASE}/api/game/trivia`, { timeout: 15_000 });
      await msg.reply(data?.trivia || "couldn't load trivia rn");
    } catch (e) { await msg.reply("trivia's down rn"); }
    return;
  }

  // ── Public: "hey ken roast <name/me>" ─────────────────────────
  const roastMatch = body.match(/^hey\s*ken\s+roast\s*(\S.*)?/i);
  if (roastMatch) {
    const roastTarget = (roastMatch[1] || "me").trim() || "me";
    try {
      const { data } = await axios.get(`${FLASK_BASE}/api/game/roast`, {
        params: { target: roastTarget },
        timeout: 15_000
      });
      await msg.reply(data?.roast || "not today 😅");
    } catch (e) { await msg.reply("can't roast rn lol"); }
    return;
  }

  // ── Public: "hey ken debate [topic]" ──────────────────────────
  const debateMatch = body.match(/^hey\s*ken\s+debate\s*(.*)?/i);
  if (debateMatch) {
    const topic = (debateMatch[1] || "").trim();
    try {
      const { data } = await axios.post(`${FLASK_BASE}/api/game/debate`, { topic }, { timeout: 50_000 });
      await msg.reply(data?.debate || "can't debate rn");
    } catch (e) { await msg.reply("debate thing's broken rn"); }
    return;
  }

  // ── Public: "hey ken poll [topic]" ───────────────────────────
  const pollMatch = body.match(/^hey\s*ken\s+poll\s*(.*)?/i);
  if (pollMatch) {
    const topic = (pollMatch[1] || "").trim();
    try {
      const { data } = await axios.post(`${FLASK_BASE}/api/game/poll`, { topic }, { timeout: 10_000 });
      await msg.reply(data?.poll || "poll failed");
    } catch (e) { await msg.reply("poll's broken rn"); }
    return;
  }

  // ── Public: "hey ken cricket update" ─────────────────────────
  if (/^hey\s*ken\s+(cricket\s*(update|news|score)?|score)/i.test(body)) {
    try {
      const { data } = await axios.get(`${FLASK_BASE}/api/cricket/update`, { timeout: 10_000 });
      await msg.reply(data?.update || "no cricket update rn");
    } catch (e) { await msg.reply("cricket api's down"); }
    return;
  }

  // ── Public: "hey ken what's trending" ──────────────────────
  if (/^hey\s*ken\s+(what'?s?\s*trending|trending|whats\s+hot)/i.test(body)) {
    try {
      const { data } = await axios.get(`${FLASK_BASE}/api/news?category=top&n=7&format=text`, { timeout: 15_000 });
      await msg.reply(data?.result || "couldn't fetch trends");
    } catch (e) { await msg.reply("trends thing's broken"); }
    return;
  }

  // ── Public: "hey ken f1" / "hey ken qualifying" / "hey ken gp" ──────────
  if (/^hey\s*ken\s+(f1|formula\s*1|formula\s*one|grand\s*prix|\bgp\b|race\s*result|qualifying|motorsport)/i.test(body)) {
    try {
      const { data } = await axios.get(`${FLASK_BASE}/api/news?category=f1&n=5&format=text`, { timeout: 15_000 });
      await msg.reply(data?.result || "couldn't get F1 news rn");
    } catch (e) { await msg.reply("f1 feed's down"); }
    return;
  }

  // ── Public: "hey ken sports news" / "hey ken football" ──────────────────
  if (/^hey\s*ken\s+(sports?\s*news|football|soccer|\bnba\b|\bnfl\b|\bufc\b|tennis)/i.test(body)) {
    try {
      const { data } = await axios.get(`${FLASK_BASE}/api/news?category=sports&n=5&format=text`, { timeout: 15_000 });
      await msg.reply(data?.result || "couldn't get sports news rn");
    } catch (e) { await msg.reply("sports feed's down"); }
    return;
  }

  // ── Public: generic live news search — "hey ken <anything> news/update/latest" ──
  // Catches: "hey ken man city updates", "hey ken TenZ valorant news",
  //          "hey ken latest on Arsenal", "hey ken what's happening with Tesla"
  // Works in ALL groups and DMs — always returns once the pattern matches.
  {
    let _topic = null;
    const _mA = body.match(/^hey\s*ken\s+(.+?)\s+(?:news|updates?|latest)\s*$/i);
    const _mB = body.match(/^hey\s*ken\s+(?:latest\s+(?:on|about)|update\s+on|what(?:'s|\s+is)\s+(?:the\s+latest\s+on|happening\s+(?:with|in)?|going\s+on\s+with))\s+(.+?)\s*$/i);
    if (_mA) _topic = _mA[1].trim();
    else if (_mB) _topic = _mB[1].trim();

    if (_topic && _topic.length > 1) {
      // Pattern matched — always return from here, even on error
      try {
        const { data } = await axios.get(`${FLASK_BASE}/api/news/search`, {
          params: { q: _topic, n: 5 },
          timeout: 20_000,
        });
        await msg.reply(data?.result || `no news found on "${_topic}" rn`);
      } catch (e) {
        await msg.reply(`couldn't fetch news on "${_topic}" rn, try again`);
      }
      return;
    }
  }

  // ── Public help: anyone types "hey ken help" in any chat ──
  if (/^hey\s*ken\s*(help|commands?|what can u do|what do u do)[?!.]?$/i.test(body)) {
    await msg.reply(
      "*ken's bot — what i can do:*\n\n" +
      "\u2022 just talk to me — i'll reply as ken\n" +
      "\u2022 say *sho* to stop getting replies\n\n" +
      "*news & live updates:*\n" +
      "\u2022 hey ken *<topic> news* — latest on anything\n" +
      "   e.g. 'hey ken man city news', 'hey ken tesla latest'\n" +
      "\u2022 hey ken *latest on <topic>* — same thing\n" +
      "\u2022 hey ken *cricket update* — live cricket news\n" +
      "\u2022 hey ken *f1* — F1 & motorsport headlines\n" +
      "\u2022 hey ken *sports news* — general sports headlines\n" +
      "\u2022 hey ken *what's trending* — top stories rn\n\n" +
      "*fun stuff:*\n" +
      "\u2022 hey ken *trivia* — random trivia q\n" +
      "\u2022 hey ken *roast me* — i'll roast u\n" +
      "\u2022 hey ken *debate <topic>* — hot take\n" +
      "\u2022 hey ken *poll <topic>* — generate a poll\n" +
      "\u2022 hey ken *fun fact: <fact about ken>* — teach me something\n" +
      "\u2022 hey ken *help* — this list"
    );
    return;
  }

  if (!isGroup) {
    // DM → always reply
    await gatewayAndReply(msg, body, senderName, "");
    return;
  }

  const isRealGroup = REAL_GROUP_NAMES.some((g) => groupNameLower.includes(g));

  if (isRealGroup) {
    // Real group: only reply if name is mentioned or @tagged
    const mentions = (await msg.getMentions?.()) || [];
    const taggedMe = mentions.some((c) => c.isMe);
    const namedMe  = /\bken(ny)?\b/i.test(body);

    if (taggedMe) {
      // Explicit @mention — gateway intro
      await gatewayAndReply(msg, body, senderName, groupNameRaw, true);
    } else if (namedMe) {
      // Name-dropped in group — just reply normally, no public intro
      logToInbox(senderName, groupNameRaw, body, msg.from);
      await replyWithKen(msg, body, senderName, groupNameRaw, false);
    }
  } else {
    // Other groups: only if Ken's contact is EXPLICITLY @mentioned
    // getMentions() returns individual contacts — isMe is true only for Ken
    // This correctly excludes @all/@everyone tags
    const mentions = (await msg.getMentions?.()) || [];
    const taggedMe = mentions.some((c) => c.isMe);

    if (taggedMe) {
      await gatewayAndReply(msg, body, senderName, groupNameRaw, true);
    }
    // else: Ken is silent. No butt-ins.
  }
}

// â”€â”€ AI reply via Flask â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

// ── Self-command handler ─────────────────────────────────────────
async function handleSelfCommand(msg, instruction) {
  const cmd = instruction.toLowerCase().trim();
  console.log(`[CMD] ${cmd}`);

  try {
    // ── hey ken help ──────────────────────────────────────────
    if (/^help$|^commands?$/.test(cmd)) {
      await msg.reply(
        "*your private commands:*\n\n" +
        "\u2022 *hey ken help* \u2014 this list\n" +
        "\u2022 *hey ken status <text>* \u2014 update your status message\n" +
        "\u2022 *hey ken mood hype/chill/tired/focused* \u2014 lock mood for 2h\n" +
        "\u2022 *hey ken tag <name/number> as <type>* \u2014 tag a contact\n" +
        "\u2022 *hey ken post about <topic>* \u2014 tweet immediately\n" +
        "\u2022 *hey ken yt short about <topic>* \u2014 make + upload a yt short\n" +
        "\u2022 *hey ken inbox* \u2014 3h message summary\n" +
        "\u2022 *hey ken what did u learn* \u2014 show style profile\n" +
        "\u2022 *hey ken <anything>* \u2014 i'll answer as ken\n\n" +
        "*public commands (anyone can use):*\n" +
        "\u2022 hey ken trivia / roast me / debate [topic] / poll [topic]\n" +
        "\u2022 hey ken cricket update / what\u2019s trending / fun fact: ..."
      );
      return;
    }

    // ── hey ken inbox ─────────────────────────────────────────
    if (/^inbox/.test(cmd)) {
      await msg.reply("checking inbox...");
      const { data } = await axios.get(`${FLASK_BASE}/api/inbox/summary`, { timeout: 20_000 });
      await msg.reply(data?.summary || "inbox is empty rn");
      return;
    }

    // ── hey ken status <text> ─────────────────────────────────
    const statusMatch = instruction.match(/^status\s+(.+)/i);
    if (statusMatch) {
      const newStatus = statusMatch[1].trim();
      await axios.post(`${FLASK_BASE}/api/status`, { status: newStatus }, { timeout: 5_000 });
      await msg.reply(`status updated: "${newStatus}"`);
      return;
    }

    // ── hey ken mood <X> ──────────────────────────────────────
    const moodMatch = cmd.match(/^mood\s+(hype|chill|tired|focused|happy|sad|bored|busy)/);
    if (moodMatch) {
      const mood = moodMatch[1];
      await axios.post(`${FLASK_BASE}/api/mood/set`, { mood }, { timeout: 5_000 });
      await msg.reply(`mood locked to *${mood}* for 2h`);
      return;
    }

    // ── hey ken tag <name/number> as <type> ──────────────────
    const tagMatch = cmd.match(/^tag\s+(.+?)\s+as\s+(family|friend|inner_circle|acquaintance|colleague|adult|public)/);
    if (tagMatch) {
      const [, target, type] = tagMatch;
      const contactId = /^\+?\d[\d\s]+$/.test(target)
        ? target.replace(/\D/g, "") + "@c.us"
        : target;
      await axios.post(`${FLASK_BASE}/api/contact/type`, { contact_id: contactId, type }, { timeout: 5_000 });
      await msg.reply(`tagged *${target}* as *${type}*`);
      return;
    }

    // ── hey ken what did u learn ──────────────────────────────
    if (/^what\s+(did\s+)?u\s+learn|^what.{0,10}learn/i.test(cmd)) {
      await msg.reply("pulling style profile...");
      const { data } = await axios.post(
        `${FLASK_BASE}/api/command`,
        { instruction: "show me your current style profile: voice patterns, slang, topics, and what you've learned from recent conversations" },
        { timeout: 30_000 }
      );
      await msg.reply(data?.reply || "no style data yet");
      return;
    }

    // ── hey ken yt short about <topic> ───────────────────────
    const ytMatch = instruction.match(/^yt\s+short\s+(?:about\s+)?(.+)/i);
    if (ytMatch) {
      const topic = ytMatch[1].trim();
      await msg.reply(`generating yt short: "${topic}"\nthis takes ~2min, i'll dm u when it's live`);
      axios.post(`${FLASK_BASE}/api/command`, { instruction }, { timeout: 300_000 })
        .then(({ data }) => msg.reply(data?.reply || "yt short done"))
        .catch(err => msg.reply(`yt short failed: ${err.message.slice(0, 80)}`));
      return;
    }

    // ── hey ken post about <topic> ────────────────────────────
    if (/^post\s+(?:about\s+)?/i.test(cmd)) {
      await msg.reply("tweeting...");
      const { data } = await axios.post(`${FLASK_BASE}/api/command`, { instruction }, { timeout: 60_000 });
      await msg.reply(data?.reply || "posted");
      return;
    }

    // ── generic live news: "man city updates", "tenz news", "latest on arsenal" ──
    {
      let _topic = null;
      const _mA = instruction.match(/^(.+?)\s+(?:news|updates?|latest)\s*$/i);
      const _mB = instruction.match(/^(?:latest\s+(?:on|about)|update\s+on|what(?:'s|\s+is)\s+(?:the\s+latest\s+on|happening\s+(?:with|in)?|going\s+on\s+with))\s+(.+?)\s*$/i);
      if (_mA) _topic = _mA[1].trim();
      else if (_mB) _topic = _mB[1].trim();

      if (_topic && _topic.length > 1) {
        try {
          const { data } = await axios.get(`${FLASK_BASE}/api/news/search`, {
            params: { q: _topic, n: 5 },
            timeout: 20_000,
          });
          if (data?.result) {
            await msg.reply(data.result);
            return;
          }
        } catch (e) { /* fall through to Claude */ }
      }
    }

    // ── fallback: ask Claude directly ────────────────────────
    await msg.reply("on it...");
    const { data } = await axios.post(`${FLASK_BASE}/api/command`, { instruction }, { timeout: 60_000 });
    await msg.reply(data?.reply || "done");

  } catch (err) {
    console.error("[CMD error]", err.message);
    await msg.reply(`error: ${err.message.slice(0, 100)}`);
  }
}

// ── Away-mode gateway ────────────────────────────────────────────
// First contact intro + sho opt-out + inbox logging, then real AI reply.
async function gatewayAndReply(msg, text, senderName, groupName, isMentioned = false) {
  const chatId = msg.from;

  // Already opted out — stay silent
  if (optedOut.has(chatId)) return;

  // "sho" = opt-out
  if (/^s*shos*$/i.test(text)) {
    optedOut.add(chatId);
    await msg.reply("aight no worries, leaving u alone ✌ ill let kenneth know u messaged");
    logToInbox(senderName, groupName, "said sho (opted out)", chatId);
    return;
  }

  // Log every real message for the 3h summary
  logToInbox(senderName, groupName, text, chatId);

  // First contact — send intro with current status
  if (!greetedChats.has(chatId)) {
    greetedChats.add(chatId);
    const where = groupName ? " in *" + groupName + "*" : "";
    let statusLine = "caught up";
    try {
      const { data: sd } = await axios.get(`${FLASK_BASE}/api/status`, { timeout: 3_000 });
      if (sd?.status) statusLine = sd.status;
    } catch (_) {}
    await msg.reply(
      `hey${where}! kenneth's ${statusLine} rn, i'm his bot keeping things running what's up? (say sho if u want me to bounce)`
    );
    return;
  }

  // Normal AI reply
  await replyWithKen(msg, text, senderName, groupName, isMentioned);
}

// Post to Flask inbox log
function logToInbox(sender, group, message, chatId) {
  axios.post(FLASK_BASE + "/api/inbox/log", { sender, group, message, chat_id: chatId }).catch(() => {});
}

async function replyWithKen(msg, text, senderName, groupName, isMentioned = false) {
  try {
    // contact_id = individual sender JID (msg.author in groups, msg.from in DMs)
    const contactId = msg.author || msg.from;
    const { data } = await axios.post(
      `${FLASK_BASE}/api/whatsapp/reply`,
      {
        text,
        sender_name: senderName,
        group_name: groupName,
        chat_id: msg.from,
        contact_id: contactId,
        is_mentioned: isMentioned,
      },
      { timeout: 30_000 }
    );
    const reply = data?.reply || "";
    if (reply) {
      await msg.reply(reply);
      console.log(`[Ken â†’ ${groupName || senderName}]: ${reply.substring(0, 80)}â€¦`);
    }
  } catch (err) {
    console.error("Flask reply error:", err.message);
  }
}

// â”€â”€ Proactive shitposting cron â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Fires every 2 hours. Checks active hours (10amâ€“11pm IST).
// 50% random chance per trigger to feel natural/sporadic.
function startShitpostCron() {
  cron.schedule("0 */2 * * *", async () => {
    if (!isActiveHoursIST()) return;
    if (Math.random() > 0.5) return; // 50% chance â€” stay unpredictable

    const groups = Object.entries(realGroupChats);
    if (groups.length === 0) return;

    // Pick a random real group
    const [gKey, chat] = groups[Math.floor(Math.random() * groups.length)];

    try {
      const { data } = await axios.post(
        `${FLASK_BASE}/api/whatsapp/proactive`,
        { group_name: chat.name },
        { timeout: 30_000 }
      );
      const post = data?.post || "";
      if (post) {
        await chat.sendMessage(post);
        console.log(`[Ken shitpost â†’ ${chat.name}]: ${post.substring(0, 80)}â€¦`);
      }
    } catch (err) {
      console.error("Shitpost error:", err.message);
    }
  });
  console.log("ðŸ’¬ Shitpost cron armed (every 2h during active hours)");
}
// ── 3h inbox summary ─────────────────────────────────────────
function startSummaryCron() {
  // Every 3 hours fetch inbox log and DM it to Kenneth
  cron.schedule("0 */3 * * *", async () => {
    if (!MY_NUMBER) return;
    try {
      const { data } = await axios.get(`${FLASK_BASE}/api/inbox/summary`, { timeout: 10_000 });
      const summary = data?.summary || "";
      if (summary) {
        await client.sendMessage(`${MY_NUMBER}@c.us`, summary);
        console.log("📬 Inbox summary sent to Kenneth");
      }
    } catch (err) {
      console.error("Summary cron error:", err.message);
    }
  });
  console.log("📬 Inbox summary cron armed (every 3h)");
}
// â”€â”€ Reminder poller (every 1 min) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function startReminderPoller() {
  cron.schedule("* * * * *", async () => {
    try {
      const { data } = await axios.get(`${FLASK_BASE}/api/reminders/pending`, {
        timeout: 10_000,
      });
      const reminders = data?.reminders || [];
      for (const r of reminders) {
        if (MY_NUMBER) {
          await client.sendMessage(`${MY_NUMBER}@c.us`, r.message);
          await axios.post(`${FLASK_BASE}/api/reminders/mark_sent/${r.id}`);
          console.log(`â° Reminder: ${r.message.substring(0, 60)}`);
        }
      }
    } catch (_) {
      // Silent â€” Flask may not be ready yet
    }
  });
}


// ── Notify poller (every 1 min) ────────────────────────
function startNotifyPoller() {
  cron.schedule("* * * * *", async () => {
    if (!MY_NUMBER) return;
    try {
      const { data } = await axios.get(`${FLASK_BASE}/api/notify/pending`, { timeout: 10_000 });
      for (const msg of (data?.messages || [])) {
        await client.sendMessage(`${MY_NUMBER}@c.us`, msg);
        console.log(`📣 Notify sent: ${msg.slice(0, 60)}`);
      }
    } catch (_) {}
  });
  console.log("📣 Notify poller armed (every 1 min)");
}

// IST = UTC+5:30. Active window: 10:00am - 11:00pm IST (04:30 - 17:30 UTC)
function isActiveHoursIST() {
  const now = new Date();
  const utcH = now.getUTCHours();
  const utcM = now.getUTCMinutes();
  const totalUTCMin = utcH * 60 + utcM;
  // 10am IST = 04:30 UTC, 11pm IST = 17:30 UTC
  return totalUTCMin >= 270 && totalUTCMin <= 1050;
}

// Auto-clean stale Puppeteer Chrome + SingletonLock before every startup.
// Strategy: 1) read PID from lock file and kill that process
//            2) fallback: find chrome using our exact userDataDir via WMIC
//            3) delete the lock file
const _lockFile = path.join(__dirname, ".wwebjs_auth", "session", "SingletonLock");
const _userDataDir = path.join(__dirname, ".wwebjs_auth", "session");
try {
  if (fs.existsSync(_lockFile)) {
    // Attempt 1: kill the PID stored in the lock file (format: HOSTNAME-PID)
    let _killed = false;
    try {
      const _content = fs.readFileSync(_lockFile, "utf8").trim();
      const _pidMatch = _content.match(/-(\d+)$/);
      if (_pidMatch) {
        const _pid = parseInt(_pidMatch[1], 10);
        execSync(`taskkill /PID ${_pid} /F /T`, { stdio: "ignore" });
        console.log(`[startup] killed stale Chrome PID ${_pid}`);
        _killed = true;
      }
    } catch (_) {}

    // Attempt 2: find chrome processes using our specific userDataDir
    if (!_killed) {
      try {
        const _wmicOut = execSync(
          `wmic process where "name='chrome.exe'" get ProcessId,CommandLine /FORMAT:csv 2>nul`,
          { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }
        );
        const _dirFragment = _userDataDir.replace(/\\/g, "\\\\");
        for (const _line of _wmicOut.split("\n")) {
          if (_line.toLowerCase().includes(_userDataDir.toLowerCase())) {
            const _m = _line.match(/,(\d+)\s*$/);
            if (_m) {
              execSync(`taskkill /PID ${_m[1]} /F /T`, { stdio: "ignore" });
              console.log(`[startup] killed Chrome PID ${_m[1]} (matched userDataDir)`);
            }
          }
        }
      } catch (_) {}
    }

    try { fs.unlinkSync(_lockFile); } catch (_) {}
    console.log("[startup] cleared SingletonLock");
  }
} catch (_) {}

client.initialize();
