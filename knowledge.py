"""Deterministic, relevance-gated retrieval for the Markdown knowledge base.

The public ``retrieve_knowledge`` function intentionally keeps returning a string
so the existing LangGraph agent can use it without changes.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import log
from pathlib import Path
import re

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge_base"
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a", "about", "an", "and", "are", "as", "at", "can", "could", "do",
    "does", "for", "from", "give", "has", "have", "how", "i", "in", "is",
    "it", "me", "of", "on", "or", "please", "tell", "that", "the", "this",
    "to", "what", "when", "where", "which", "who", "why", "with", "would",
    "you", "your", "my", "we", "our", "there", "much", "many",
}
TERM_ALIASES = {
    "bookings": "booking", "films": "movie", "film": "movie",
    "movies": "movie", "reservations": "booking", "reservation": "booking",
    "tickets": "ticket", "cancellation": "cancel", "cancellations": "cancel",
    "cancelled": "cancel", "cancelling": "cancel", "refunds": "refund",
    "refunded": "refund", "policies": "policy", "hours": "hour",
    "times": "time", "prices": "price", "costs": "cost",
}

@dataclass(frozen=True)
class KnowledgePassage:
    source: str
    section: str
    content: str
    score: float
    matched_terms: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "section": self.section,
            "content": self.content,
            "score": round(self.score, 4),
            "matched_terms": list(self.matched_terms),
        }

def _normalize_terms(text: str) -> list[str]:
    terms = []
    for term in TOKEN_PATTERN.findall(text.casefold()):
        if term in STOP_WORDS:
            continue
        terms.append(TERM_ALIASES.get(term, term))
    return terms

def _load_chunks(path: Path) -> list[tuple[str, str]]:
    """Split Markdown into paragraph passages while retaining heading metadata."""
    chunks: list[tuple[str, str]] = []
    heading_stack: list[str] = []
    paragraph: list[str] = []

    def add_paragraph() -> None:
        body = " ".join(line.strip() for line in paragraph).strip()
        if body:
            section = " > ".join(heading_stack) if heading_stack else "General"
            chunks.append((section, body))
        paragraph.clear()

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            add_paragraph()
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped.lstrip("#").strip() or "General"
            heading_stack[:] = heading_stack[: max(0, level - 1)]
            heading_stack.append(title)
        elif stripped:
            paragraph.append(stripped)
        else:
            add_paragraph()
    add_paragraph()
    return chunks

def retrieve_knowledge_results(
    question: str,
    max_chunks: int = 3,
    min_query_coverage: float = 0.34,
) -> list[KnowledgePassage]:
    """Return ranked passages only when enough of the query is supported.

    This is a lightweight lexical ranker with inverse-document-frequency weighting
    and a small heading boost. It is intentionally dependency-free.
    """
    query_terms = list(dict.fromkeys(_normalize_terms(question)))
    if not query_terms or max_chunks < 1:
        return []

    documents: list[tuple[str, str, str, list[str], list[str]]] = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        for section, body in _load_chunks(path):
            section_terms = _normalize_terms(section)
            body_terms = _normalize_terms(body)
            documents.append((path.name, section, body, section_terms, body_terms))

    if not documents:
        return []

    document_frequency = Counter()
    for _, _, _, section_terms, body_terms in documents:
        document_frequency.update(set(section_terms + body_terms))

    query_set = set(query_terms)
    ranked: list[KnowledgePassage] = []
    for source, section, body, section_terms, body_terms in documents:
        body_counts = Counter(body_terms)
        section_set = set(section_terms)
        matched = query_set.intersection(set(body_terms) | section_set)
        if not matched:
            continue

        coverage = len(matched) / len(query_set)
        if coverage < min_query_coverage:
            continue
        # Avoid a one-word coincidence for longer queries.
        if len(query_set) >= 4 and len(matched) < 2:
            continue

        score = 0.0
        total_docs = len(documents)
        for term in matched:
            idf = log(1 + (total_docs + 1) / (document_frequency[term] + 0.5))
            frequency = body_counts[term]
            term_score = idf * (1.0 + min(frequency, 3) * 0.15)
            if term in section_set:
                term_score *= 1.8
            score += term_score

        # Reward coverage so a passage matching most of the user's actual
        # question beats one matching only a common fragment.
        score *= 0.5 + coverage
        ranked.append(KnowledgePassage(
            source=source,
            section=section,
            content=body,
            score=score,
            matched_terms=tuple(sorted(matched)),
        ))

    ranked.sort(key=lambda item: (-item.score, item.source, item.section))
    return ranked[:max_chunks]

def retrieve_knowledge(question: str, max_chunks: int = 3) -> str:
    """Return formatted evidence, preserving the existing agent interface."""
    passages = retrieve_knowledge_results(question, max_chunks=max_chunks)
    return "\n\n".join(
        f"Source: {item.source} | Section: {item.section}\n{item.content}"
        for item in passages
    )
