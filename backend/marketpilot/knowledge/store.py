"""Trading knowledge library: loading, persistence and BM25 retrieval (RAG).

Retrieval is local and deterministic (Okapi BM25), so it works offline and needs
no embedding API. The AI analyst receives retrieved passages *with their sources*
and is instructed to cite them.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import KnowledgeDoc

LIB_DIR = Path(__file__).parent / "library"
_HEADER = re.compile(r"^---json\s*\n(.*?)\n---\s*\n", re.S | re.M)
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = set("a an and are as at be by for from has have in is it its of on or that the to was were will with this "
            "these those can not no but if then than so such into over under more most less very".split())


def parse_library_file(text: str) -> list[dict[str, Any]]:
    docs = []
    matches = list(_HEADER.finditer(text))
    for i, m in enumerate(matches):
        meta = json.loads(m.group(1))
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end() : end].strip()
        meta["body"] = body
        first_para = body.split("\n\n", 1)[0]
        meta.setdefault("summary", re.sub(r"[*_`]", "", first_para)[:400])
        docs.append(meta)
    return docs


def load_curated() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in sorted(LIB_DIR.glob("*.md")):
        out.extend(parse_library_file(p.read_text(encoding="utf-8")))
    slugs = [d["slug"] for d in out]
    dupes = {s for s in slugs if slugs.count(s) > 1}
    if dupes:
        raise ValueError(f"Duplicate knowledge slugs: {dupes}")
    return out


def seed_knowledge(s: Session) -> int:
    n = 0
    for d in load_curated():
        row = s.execute(select(KnowledgeDoc).where(KnowledgeDoc.slug == d["slug"])).scalar_one_or_none()
        fields = dict(title=d["title"], category=d["category"], summary=d["summary"], body=d["body"],
                      sources=d.get("sources", []), tags=d.get("tags", []), updated_at=d.get("updated", ""), origin="curated")
        if row is None:
            s.add(KnowledgeDoc(slug=d["slug"], **fields))
            n += 1
        elif row.origin == "curated":
            for k, v in fields.items():
                setattr(row, k, v)
    return n


def doc_to_dict(d: KnowledgeDoc, with_body: bool = True) -> dict[str, Any]:
    out = {"id": d.id, "slug": d.slug, "title": d.title, "category": d.category, "summary": d.summary,
           "sources": d.sources, "tags": d.tags, "updated_at": d.updated_at, "origin": d.origin}
    if with_body:
        out["body"] = d.body
    return out


def tokenize(text: str) -> list[str]:
    toks = [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]
    # light stemming: plural / -ing / -ed
    out = []
    for t in toks:
        for suf in ("ings", "ing", "ed", "es", "s"):
            if len(t) > 4 and t.endswith(suf):
                t = t[: -len(suf)]
                break
        out.append(t)
    return out


@dataclass
class _Indexed:
    doc: dict[str, Any]
    tf: Counter[str]
    length: int


class BM25Index:
    def __init__(self, docs: list[dict[str, Any]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.items: list[_Indexed] = []
        for d in docs:
            text = " ".join([d["title"]] * 3 + [" ".join(d.get("tags", []))] * 2 + [d.get("category", ""), d.get("body", "")])
            toks = tokenize(text)
            self.items.append(_Indexed(d, Counter(toks), len(toks)))
        self.N = len(self.items)
        self.avgdl = sum(i.length for i in self.items) / self.N if self.N else 0
        df: Counter[str] = Counter()
        for i in self.items:
            df.update(i.tf.keys())
        self.idf = {t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def search(self, query: str, k: int = 5, category: str | None = None) -> list[dict[str, Any]]:
        q = tokenize(query)
        scored = []
        for it in self.items:
            if category and it.doc.get("category") != category:
                continue
            score = 0.0
            for t in q:
                f = it.tf.get(t)
                if not f:
                    continue
                score += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * it.length / self.avgdl))
            if score > 0:
                scored.append((score, it.doc))
        scored.sort(key=lambda x: -x[0])
        return [{**d, "score": round(sc, 3)} for sc, d in scored[:k]]


def build_index(s: Session) -> BM25Index:
    docs = [doc_to_dict(d) for d in s.execute(select(KnowledgeDoc)).scalars()]
    return BM25Index(docs)


def retrieve(s: Session, query: str, k: int = 4) -> list[dict[str, Any]]:
    """Top-k passages formatted for an LLM prompt: body excerpt + sources."""
    out = []
    for d in build_index(s).search(query, k):
        out.append({"slug": d["slug"], "title": d["title"], "category": d["category"], "excerpt": d["body"][:1800],
                    "sources": [f"{x.get('authors', '')} ({x.get('year', '')}). {x.get('title', '')}. {x.get('publisher', '')}"
                                f" [{x.get('type', '')}]" for x in d.get("sources", [])]})
    return out
