"""
KenBot OS — Thread Generator
Produces multi-tweet thread content in Kenneth's voice.
Returns a list of tweet strings ready to post sequentially.
"""
from __future__ import annotations

import json
import random
from typing import Optional

from config.settings import settings
from utils.logger import logger

# Thread templates — expandable seed structures
_THREAD_TEMPLATES: dict[str, list[str]] = {
    "bangalore": [
        "10 things only Bangalore people understand (a thread) 🧵",
        "1/ the weather here is the only reliable thing. everything else is a mystery.",
        "2/ your commute is not a commute. it is a spiritual journey.",
        "3/ every area has its own personality. Koramangala thinks it's NYC. Jayanagar is that friend who refuses to leave their neighbourhood.",
        "4/ the food scene is genuinely unreal. but finding parking near that restaurant? that's the challenge.",
        "5/ everyone here is either building a startup or knows three people who are.",
        "6/ the rent is not real. paying 35k to live in a place where the power cuts at 7pm is peak Bangalore.",
        "7/ but the pubs. dear god the pubs. Saturday nights here hit different.",
        "8/ and somehow this city keeps pulling you back. left twice. back both times. it does something to you.",
        "9/ Bangalore doesn't belong to anyone. it belongs to everyone who got dragged here for a job and accidentally fell in love with it.",
        "10/ if u grew up here or moved here and stayed — u know. nobody explains Bangalore. u just get it. 🧡",
    ],
    "valorant_ranked": [
        "why valorant ranked destroys your mental health — a scientific breakdown 🧵",
        "1/ it starts optimistically. 'i'm going to hard carry today.' this is your first mistake.",
        "2/ first match. interesting teammate comp. one person is playing a completely different game.",
        "3/ you win anyway somehow. false confidence enters the chat.",
        "4/ second match. 3 instalocks. the Reyna doesn't know what a lineup is and is personally offended by the concept.",
        "5/ you lose. that's fine. variance.",
        "6/ third match. you go up 10-2. comfortable lead. 'this is it. this is the carry.'",
        "7/ 10-2 becomes 12-12. then 12-13. then you're watching the post-match screen wondering what happened.",
        "8/ the thing about ranked is it teaches you that you're never as good as you think you are in the wins and never as bad as you feel in the losses.",
        "9/ and for some reason you queue up again. every. single. time.",
        "10/ valorant ranked is not a game. it's a long-running psychological experiment and we're all participants. play accordingly.",
    ],
    "ai_work": [
        "AI is not replacing programmers. it's replacing programmers who won't adapt. here's what that actually means 🧵",
        "1/ the programmers panicking about AI are usually the ones who spent years mastering syntax and shortcuts. valid concern.",
        "2/ the programmers not worried are usually the ones who spent those years learning how to solve problems. different skill entirely.",
        "3/ what AI does really well: boilerplate, documentation, debugging known patterns, first-draft code.",
        "4/ what AI does badly: understanding your specific codebase's quirks, making judgment calls on architecture, knowing what NOT to build.",
        "5/ the shift is from 'can you write code' to 'can you direct code'. same destination, different vehicle.",
        "6/ also — most 'AI will replace programmers' discourse comes from people who have never shipped production code.",
        "7/ the real skill now is prompt architecture. knowing how to break down a problem so AI can help with the right pieces.",
        "8/ this is not sad. this is how every technological shift in programming has worked. from assembly to C to Python to this.",
        "9/ adapt or get left behind. but also — the adapting part isn't that hard if you're genuinely curious.",
        "10/ the developers thriving in 2-3 years will be the ones who learned to think with AI, not just ask it to write things.",
    ],
}

# Fallback generic thread structure
_GENERIC_OPENER = "here's the full breakdown of {topic} — nobody else is saying this 🧵"


class ThreadGenerator:
    """
    Generates tweet threads. Returns list of tweet strings.
    AI-powered expansion handled in ai_engine — this provides
    seed structures and templates.
    """

    def get_template(self, topic: Optional[str] = None) -> list[str]:
        """Return a complete ready-to-post thread as list of tweet strings."""
        if not topic:
            key = random.choice(list(_THREAD_TEMPLATES.keys()))
            return _THREAD_TEMPLATES[key]

        t = topic.lower()
        if "bangalore" in t or "blr" in t:
            return _THREAD_TEMPLATES["bangalore"]
        if "valorant" in t or "ranked" in t or "val" in t:
            return _THREAD_TEMPLATES["valorant_ranked"]
        if "ai" in t or "programming" in t or "developer" in t:
            return _THREAD_TEMPLATES["ai_work"]

        # Generic fallback
        return [_GENERIC_OPENER.format(topic=topic)] + [
            f"{i}/ thought {i} goes here — expand with AI" for i in range(1, 6)
        ]

    def seed_for_ai(self, topic: str) -> dict:
        """
        Return a seed structure for AI to expand into a full thread.
        Used by ai_engine.generate_tweet_thread().
        """
        return {
            "topic":    topic,
            "template": self.get_template(topic),
            "style":    "numbered 🧵 thread, each tweet standalone, ends with a punchy closer",
        }

    def format_thread_ideas(self) -> str:
        return "\n".join(f"• {k.replace('_',' ')}" for k in _THREAD_TEMPLATES.keys())


thread_generator = ThreadGenerator()
