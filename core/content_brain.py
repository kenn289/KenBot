"""
KenBot OS — Content Brain
Generates viral-optimized content ideas for Kenneth's persona.
Uses trend data, humor patterns, and personality to produce memes,
hot takes, sports debates, gaming humor, and relatable tweets.
"""
from __future__ import annotations

import random
from typing import Optional

from utils.logger import logger

# Format: (template, category, tags)
_HOT_TAKE_TEMPLATES = [
    ("{sport} fans are the most emotionally unstable people on the internet and i mean that with love", "sports", ["Cricket", "Sports"]),
    ("anyone who says they're 'not a gamer' in 2026 is just lying to themselves at this point", "gaming", ["Gaming"]),
    ("bangalore traffic doesn't teach patience. it teaches acceptance of suffering.", "bangalore", ["Bangalore"]),
    ("valorant ranked is just a personality test that tells u exactly how mentally fragile u are", "gaming", ["Valorant", "Gaming"]),
    ("the people who post 'no excuses' at 5am are statistically the most annoying people alive", "lifestyle", ["Life"]),
    ("AI is not replacing programmers. it's replacing programmers who refuse to use AI.", "tech", ["AI", "Tech"]),
    ("ngl {team} might actually be cooked this season", "cricket", ["Cricket", "IPL"]),
    ("we need to stop pretending {game} is not a dead game", "gaming", ["Gaming"]),
    ("the internet would be 40% better if people were only allowed to tweet after 8am", "lifestyle", ["Life"]),
    ("nobody is working as hard as they say they are on linkedin", "tech", ["LinkedIn", "Tech"]),
]

_RELATABLE_TEMPLATES = [
    ("me explaining to my parents why i stayed up till 3am: it was important. (it was not important.)", "relatable", []),
    ("the wifi cutting out exactly when i'm about to win is not a coincidence. it's targeted.", "relatable", []),
    ("studying for hours and then forgetting everything in the exam has to be a superpower", "relatable", ["Exams"]),
    ("my sleep schedule is in shambles and i have never felt more myself", "relatable", []),
    ("i will start fresh on monday. this is my 47th monday promise.", "relatable", ["Productivity"]),
    ("me at 11pm: i should sleep. me at 3am: anyway here's my entire life plan", "relatable", []),
]

_DEBATE_STARTERS = [
    "settle this once and for all: {option_a} or {option_b}?",
    "unpopular opinion: {opinion}",
    "honest question — is {topic} overrated or am i missing something",
    "can we all agree that {statement}",
    "the {topic} discourse needs to end. here's my final take:",
]

_GAMING_TOPICS = [
    "TenZ's aim feels scripted at this point",
    "Valorant ranks haven't meant anything since they added Ascendant",
    "the pro scene ignoring {agent} is wild when you watch ranked",
    "cloud9 era Valorant was peak esports content",
    "every time they 'fix' the meta they just break something else",
    "solo queue with randoms is actually skill testing in a different way",
]

_CRICKET_TOPICS = [
    "Virat Kohli coming back in form every time someone writes him off",
    "T20 cricket has changed batting forever and Test purists are just coping",
    "IPL auction drama is better content than most movies",
    "India's bowling depth right now is actually terrifying for everyone else",
    "whoever selected the squad for {series} needs to explain themselves",
    "DRS technology improving doesn't stop umpires from making strange calls",
]

_BANGALORE_TOPICS = [
    "Bangalore traffic is a personality test and most people are failing",
    "the weather here is the only reliable thing in this city",
    "paying 40k rent to sit in a 2BHK and order Swiggy is the Bangalore experience",
    "auto drivers here have a sixth sense for when you're running late",
    "Koramangala vs Indiranagar debate is the most Bangalore thing ever",
    "the startup culture here makes everyone think they're one pitch deck away from a billion dollars",
]


class ContentBrain:
    """
    Generates viral content ideas and full posts for Ken's voice.
    Standalone — does NOT call AI. Used as a prompt-seed layer.
    For AI-powered generation, pass the output to ai_engine.
    """

    def hot_take(self, topic: Optional[str] = None) -> dict:
        """Return a hot take template + context for AI to expand."""
        if topic:
            t_lower = topic.lower()
            if any(k in t_lower for k in ["cricket", "ipl", "kohli", "rohit"]):
                seed = random.choice(_CRICKET_TOPICS)
            elif any(k in t_lower for k in ["valorant", "game", "gaming", "fps"]):
                seed = random.choice(_GAMING_TOPICS)
            elif "bangalore" in t_lower or "blr" in t_lower:
                seed = random.choice(_BANGALORE_TOPICS)
            else:
                tmpl, _, tags = random.choice(_HOT_TAKE_TEMPLATES)
                seed = tmpl.format(sport="cricket", team="India", game="PUBG", agent="breach", series="WTC")
        else:
            tmpl, cat, tags = random.choice(_HOT_TAKE_TEMPLATES + _RELATABLE_TEMPLATES)
            seed = tmpl.format(sport="cricket", team="India", game="PUBG", agent="breach", series="WTC",
                               topic="remote work", statement="the office sitcom is overrated")
        return {"seed": seed, "topic": topic or "general", "type": "hot_take"}

    def debate_starter(self, option_a: str = "Kohli", option_b: str = "Rohit") -> str:
        tmpl = random.choice(_DEBATE_STARTERS)
        return tmpl.format(
            option_a=option_a,
            option_b=option_b,
            opinion=f"{option_a} is the better choice and everyone knows it",
            topic=option_a,
            statement=f"{option_a} would destroy {option_b} in their prime",
        )

    def poll_options(self, topic: str) -> dict:
        """Generate a Twitter/WhatsApp-style would-you-rather poll."""
        polls = [
            {"q": "would you rather", "a": "1 year no internet", "b": "1 year no music"},
            {"q": "would you rather", "a": "always be 10 mins late", "b": "always be 20 mins early"},
            {"q": "would you rather", "a": "give up coffee forever", "b": "give up sleep for 3 days"},
            {"q": "settle it:", "a": "Virat", "b": "Rohit — who do you trust in a final?"},
            {"q": "settle it:", "a": "Mouse + Keyboard", "b": "Controller — which is actually harder"},
        ]
        return random.choice(polls)

    def thread_ideas(self, topic: Optional[str] = None) -> list[str]:
        """Return list of thread seed ideas."""
        bangalore_threads = [
            "10 things only Bangalore people understand (a thread)",
            "the Bangalore startup bubble is getting out of control and here's why (thread)",
            "growing up in Bangalore vs working in Bangalore — two completely different cities (thread)",
        ]
        gaming_threads = [
            "why valorant ranked destroys your mental health — a scientific breakdown (thread)",
            "TenZ's career arc is the most interesting story in esports right now (thread)",
            "every Valorant player type you meet in ranked (thread)",
        ]
        general_threads = [
            "the internet made everyone an expert and it's actually a disaster (thread)",
            "things i learned the hard way about working on side projects (thread)",
            "why most people are sleeping on what AI is actually doing to creative work (thread)",
        ]
        if topic:
            t = topic.lower()
            if "bangalore" in t or "blr" in t:
                return bangalore_threads
            if any(k in t for k in ["valorant", "game", "gaming"]):
                return gaming_threads
        return general_threads + bangalore_threads[:1]

    def meme_idea(self, situation: str = "") -> dict:
        """Return a meme format + text layers for the meme generator."""
        formats = [
            {
                "format":  "drake",
                "top":     situation or "using 'it works on my machine' as a valid excuse",
                "bottom":  "writing actual tests",
            },
            {
                "format":  "two_buttons",
                "left":    "sleeping on time",
                "right":   situation or "watching 3 more YouTube videos",
                "caption": "me at 1am",
            },
            {
                "format":  "expanding_brain",
                "panels":  [
                    "going to sleep early",
                    situation or "scrolling twitter till 3am",
                    "blaming the algorithm",
                    "creating the exact content you just wasted 4 hours watching",
                ],
            },
        ]
        return random.choice(formats)


content_brain = ContentBrain()
