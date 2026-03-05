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

// â”€â”€ Client init â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
const client = new Client({
  authStrategy: new LocalAuth({ dataPath: ".wwebjs_auth" }),
  puppeteer: {
    headless: true,
    executablePath: "C:\\Users\\Kenneth Oswin\\.cache\\puppeteer\\chrome\\win64-146.0.7680.31\\chrome-win64\\chrome.exe",
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

client.on("ready", async () => {
  console.log("ðŸš€ Ken WhatsApp bot is live!\n");
  await cacheRealGroups();
  startReminderPoller();
  startShitpostCron();
});

// â”€â”€ Cache real group chat objects for proactive use â”€â”€â”€â”€â”€â”€
async function cacheRealGroups() {
  try {
    const chats = await client.getChats();
    for (const chat of chats) {
      if (!chat.isGroup) continue;
      const nameLower = (chat.name || "").toLowerCase();
      for (const g of REAL_GROUP_NAMES) {
        if (nameLower.includes(g)) {
          realGroupChats[g] = chat;
          console.log(`ðŸ“Œ Cached real group: ${chat.name}`);
        }
      }
    }
    const found = Object.keys(realGroupChats).length;
    console.log(`ðŸ“Œ ${found}/${REAL_GROUP_NAMES.length} real groups found`);
  } catch (err) {
    console.error("Could not cache real groups:", err.message);
  }
}

// â”€â”€ Message handler â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
client.on("message", async (msg) => {
  try {
    await handleMessage(msg);
  } catch (err) {
    console.error("Message handler error:", err.message);
  }
});

async function handleMessage(msg) {
  // Learn from Kenneth's own typing in real groups
  if (msg.fromMe && !msg.isStatus) {
    try {
      const c = await msg.getChat();
      const rn = c.isGroup ? (c.name || "") : "";
      if (REAL_GROUP_NAMES.some(g => rn.toLowerCase().includes(g)) && msg.body && msg.body.length > 4) {
        axios.post(`${FLASK_BASE}/api/learn`, { message: msg.body }).catch(() => {});
      }
    } catch (_) {}
  }

  if (msg.isStatus || msg.fromMe) return;

  const chat    = await msg.getChat();
  const contact = await msg.getContact();
  const isGroup = chat.isGroup;
  const groupNameRaw  = isGroup ? (chat.name || "") : "";
  const groupNameLower = groupNameRaw.toLowerCase();
  const senderName    = contact.pushname || contact.name || "someone";
  const body          = (msg.body || "").trim();

  if (!body) return;

  if (!isGroup) {
    // DM â†’ always reply
    await replyWithKen(msg, body, senderName, "");
    return;
  }

  const isRealGroup = REAL_GROUP_NAMES.some((g) => groupNameLower.includes(g));

  if (isRealGroup) {
    // Real group: only reply if name is mentioned or @tagged
    const mentions = (await msg.getMentions?.()) || [];
    const taggedMe = mentions.some((c) => c.isMe);
    const namedMe  = /\bken(ny)?\b/i.test(body);

    if (taggedMe || namedMe) {
      await replyWithKen(msg, body, senderName, groupNameRaw, taggedMe || namedMe);
    }
  } else {
    // Other groups: only if Ken's contact is EXPLICITLY @mentioned
    // getMentions() returns individual contacts â€” isMe is true only for Ken
    // This correctly excludes @all/@everyone tags
    const mentions = (await msg.getMentions?.()) || [];
    const taggedMe = mentions.some((c) => c.isMe);

    if (taggedMe) {
      await replyWithKen(msg, body, senderName, groupNameRaw, true);
    }
    // else: Ken is silent. No butt-ins.
  }
}

// â”€â”€ AI reply via Flask â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async function replyWithKen(msg, text, senderName, groupName, isMentioned = false) {
  try {
    const { data } = await axios.post(
      `${FLASK_BASE}/api/whatsapp/reply`,
      { text, sender_name: senderName, group_name: groupName, chat_id: msg.from, is_mentioned: isMentioned },
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

client.initialize();
