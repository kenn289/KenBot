"""
KenBot OS — Personal Knowledge Graph
Links people, topics, events, and memories in a lightweight
graph structure stored in KV. No external graph DB required.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from memory.store import memory
from utils.logger import logger

_KV_KEY = "knowledge_graph"


class KnowledgeGraph:
    """
    Nodes: people, topics, events, facts
    Edges: person—topic, person—event, topic—topic (related)
    All stored as JSON in KV store.
    """

    # ── Nodes ─────────────────────────────────────────────────────────────

    def add_person(self, name: str, **attrs) -> None:
        g = self._load()
        n_id = f"person:{name.lower()}"
        g["nodes"][n_id] = {"type": "person", "name": name, **attrs,
                             "updated_at": datetime.utcnow().isoformat()}
        self._save(g)

    def add_topic(self, topic: str, category: str = "general") -> None:
        g = self._load()
        n_id = f"topic:{topic.lower()}"
        if n_id not in g["nodes"]:
            g["nodes"][n_id] = {"type": "topic", "name": topic, "category": category,
                                 "mention_count": 0}
        g["nodes"][n_id]["mention_count"] = g["nodes"][n_id].get("mention_count", 0) + 1
        self._save(g)

    def add_event(self, event: str, date: Optional[str] = None) -> None:
        g = self._load()
        n_id = f"event:{event.lower()}"
        g["nodes"][n_id] = {"type": "event", "name": event,
                             "date": date or datetime.utcnow().isoformat()[:10]}
        self._save(g)

    # ── Edges ─────────────────────────────────────────────────────────────

    def link(self, id_a: str, id_b: str, relation: str = "related") -> None:
        g = self._load()
        edge = {"a": id_a, "b": id_b, "rel": relation, "ts": datetime.utcnow().isoformat()}
        # Deduplicate
        existing = [(e["a"], e["b"], e["rel"]) for e in g["edges"]]
        if (id_a, id_b, relation) not in existing:
            g["edges"].append(edge)
            g["edges"] = g["edges"][-500:]  # cap
        self._save(g)

    def link_person_topic(self, person_name: str, topic: str) -> None:
        self.add_topic(topic)
        self.link(f"person:{person_name.lower()}", f"topic:{topic.lower()}", "discusses")

    # ── Query ──────────────────────────────────────────────────────────────

    def related_topics(self, person_name: str, limit: int = 5) -> list[str]:
        g = self._load()
        pid = f"person:{person_name.lower()}"
        related = [
            e["b"].replace("topic:", "") for e in g["edges"]
            if e["a"] == pid and e["b"].startswith("topic:")
        ]
        # Also reverse links
        related += [
            e["a"].replace("topic:", "") for e in g["edges"]
            if e["b"] == pid and e["a"].startswith("topic:")
        ]
        # Sort by topic mention count
        counts = {
            n_id.replace("topic:", ""): g["nodes"].get(n_id, {}).get("mention_count", 0)
            for n_id in g["nodes"]
        }
        return sorted(set(related), key=lambda t: counts.get(t, 0), reverse=True)[:limit]

    def summary(self) -> dict:
        g = self._load()
        return {
            "total_nodes": len(g["nodes"]),
            "total_edges": len(g["edges"]),
            "people":  sum(1 for n in g["nodes"].values() if n.get("type") == "person"),
            "topics":  sum(1 for n in g["nodes"].values() if n.get("type") == "topic"),
            "events":  sum(1 for n in g["nodes"].values() if n.get("type") == "event"),
        }

    # ── Internal ──────────────────────────────────────────────────────────

    def _load(self) -> dict:
        try:
            return json.loads(memory.get(_KV_KEY, '{"nodes":{},"edges":[]}'))
        except Exception:
            return {"nodes": {}, "edges": []}

    def _save(self, g: dict) -> None:
        memory.set(_KV_KEY, json.dumps(g))


knowledge_graph = KnowledgeGraph()
