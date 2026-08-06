from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TextPart:
    text: str
    hit: bool


def load_banned_words(path: Path) -> list[str]:
    if not path.exists():
        return []
    words: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        word = raw.strip()
        if word and not word.startswith("#") and word not in words:
            words.append(word)
    return sorted(words, key=len, reverse=True)


def find_hits(text: str, words: list[str]) -> list[str]:
    folded = text.casefold()
    return [word for word in words if word.casefold() in folded]


def highlight_parts(text: str, words: list[str]) -> list[TextPart]:
    """按最长词优先切分文本，前端无需再次实现匹配规则。"""
    if not text:
        return []
    folded = text.casefold()
    parts: list[TextPart] = []
    cursor = 0
    plain_start = 0
    while cursor < len(text):
        matched = next((word for word in words if folded.startswith(word.casefold(), cursor)), None)
        if not matched:
            cursor += 1
            continue
        if cursor > plain_start:
            parts.append(TextPart(text[plain_start:cursor], False))
        parts.append(TextPart(text[cursor:cursor + len(matched)], True))
        cursor += len(matched)
        plain_start = cursor
    if plain_start < len(text):
        parts.append(TextPart(text[plain_start:], False))
    return parts


def check_text(text: str, banned_words_path: Path) -> tuple[list[str], list[TextPart]]:
    words = load_banned_words(banned_words_path)
    return find_hits(text, words), highlight_parts(text, words)

