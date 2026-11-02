"""Small, deterministic retrieval for the local Markdown knowledge base."""

from pathlib import Path
import re

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge_base"
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a", "about", "an", "and", "are", "as", "at", "can", "could", "do",
    "does", "for", "from", "give", "has", "have", "how", "i", "in", "is",
    "it", "me", "of", "on", "or", "please", "tell", "that", "the", "this",
    "to", "what", "when", "where", "which", "who", "why", "with", "would",
    "you", "your",
}
TERM_ALIASES = {
    "bookings": "booking",
    "films": "movie",
    "film": "movie",
    "movies": "movie",
    "reservations": "booking",
    "reservation": "booking",
    "tickets": "ticket",
    "cancellation": "cancel",
    "cancellations": "cancel",
    "cancelled": "cancel",
    "cancelling": "cancel",
    "refunds": "refund",
    "refunded": "refund",
    "policies": "policy",
}


def _normalize_terms(text: str) -> set[str]:
    terms = set(TOKEN_PATTERN.findall(text.casefold()))
    return {
        TERM_ALIASES.get(term) or term
        for term in terms
        if term not in STOP_WORDS
    }


def _load_chunks(path: Path) -> list[tuple[str, str]]:
    chunks = []
    section = "General"
    paragraph: list[str] = []

    def add_paragraph() -> None:
        body = " ".join(line.strip() for line in paragraph).strip()
        if body:
            chunks.append((section, body))
        paragraph.clear()

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            add_paragraph()
            section = stripped.lstrip("#").strip() or "General"
        elif stripped:
            paragraph.append(stripped)
        else:
            add_paragraph()

    add_paragraph()
    return chunks


def retrieve_knowledge(question: str, max_chunks: int = 3) -> str:
    """Return only the highest-scoring FAQ passages relevant to a question."""
    query_terms = _normalize_terms(question)
    if not query_terms or max_chunks < 1:
        return ""

    scored: list[tuple[float, int, str]] = []
    order = 0
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        for section, body in _load_chunks(path):
            passage_terms = _normalize_terms(f"{section} {body}")
            overlap = query_terms & passage_terms
            if overlap:
                # Prefer passages that cover a larger share of the question.
                score = len(overlap) * 2 + len(overlap) / len(query_terms)
                text = f"Source: {path.name} | {section}\n{body}"
                scored.append((score, order, text))
            order += 1

    scored.sort(key=lambda item: (-item[0], item[1]))
    return "\n\n".join(text for _, _, text in scored[:max_chunks])
