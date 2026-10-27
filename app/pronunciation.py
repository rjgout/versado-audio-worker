"""Deterministic, non-recursive pronunciation substitution."""
from dataclasses import dataclass
import re
import unicodedata

LANGUAGES = frozenset({'nl', 'en', 'de', 'fr', 'es'})

@dataclass(frozen=True)
class Rule:
    id: int
    version: int
    language: str
    source: str
    original: str
    replacement: str
    status: str = 'approved'
    engine: str | None = None
    voice: str | None = None


def prepare(text: str, rules: list[Rule], language: str, source: str, engine: str, voice: str):
    """Return prepared text and rule snapshots. Exact language and source isolation.

    Prefer voice-specific, then engine-specific, then general rules. Match on
    original text only, never on replacement output. A word boundary includes
    Unicode combining marks to avoid matching inside decomposed characters.
    """
    if language.split('-')[0] not in LANGUAGES:
        raise ValueError('unsupported language')
    eligible = [r for r in rules if r.status == 'approved' and r.language == language
                and r.source == source and (r.engine is None or r.engine == engine)
                and (r.voice is None or (r.engine == engine and r.voice == voice))
                and r.original and r.replacement]
    eligible.sort(key=lambda r: (-(bool(r.voice) * 2 + bool(r.engine)), -r.version, r.id))
    selected = {}
    for rule in eligible:
        selected.setdefault(unicodedata.normalize('NFC', rule.original).casefold(), rule)
    normalized = unicodedata.normalize('NFC', text)
    # Candidate matches are collected on the original string and resolved by
    # leftmost-longest match; replacements are never reprocessed.
    matches = []
    def word(c):
        return c == '_' or c.isalnum() or unicodedata.category(c).startswith('M')
    for rule in selected.values():
        for m in re.finditer(re.escape(unicodedata.normalize('NFC', rule.original)), normalized, re.IGNORECASE):
            if (m.start() and word(normalized[m.start()-1])) or (m.end() < len(normalized) and word(normalized[m.end()])):
                continue
            matches.append((m.start(), m.end(), rule))
    matches.sort(key=lambda x: (x[0], -(x[1]-x[0]), x[2].id))
    out, used, pos = [], [], 0
    for start, end, rule in matches:
        if start < pos:
            continue
        out.extend((normalized[pos:start], rule.replacement))
        used.append({'id': rule.id, 'version': rule.version, 'original': rule.original, 'replacement': rule.replacement})
        pos = end
    out.append(normalized[pos:])
    return ''.join(out), used
