"""Spelling correction of a question against the regulations' own vocabulary (SP1, 27 Oct 2026).

Users misspell: "carmin", "anatto", "dihydroxyacetne", "chlorophylin". The color matcher reads exact names and the
lexical search exact lexemes, so a misspelled color name sends the question to the picker with the wrong candidates.
Search engines answer this with a "did you mean" correction against their own index's vocabulary (Elasticsearch fuzzy
queries, SymSpell); this module does the same against the words of the live Title 21 text and the FD&C Act store.

How: every word of the regulation text (with its frequency) and each of its one-letter deletions are indexed
(SymSpell's delete neighbourhood); a question word the regulations never use is replaced by the regulation word
nearest to it - Damerau-Levenshtein distance 1 for words of 5-7 letters, 2 from 8 letters - when exactly one nearest
word is clearly the most frequent. Words of an ordinary English dictionary (when the system has one) are never
changed, nor are words under 5 letters, words with digits, or quoted text. Deterministic; no model.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

MIN_LEN = 5
MIN_FREQ = 2
_WORD = re.compile(r"[A-Za-z][a-z]+(?:['’][a-z]+)?(?:-[a-z]+)*")   # "doesn't" is one word, never "doesn"
MIN_TARGET_LEN = 6   # "indie" is not "india"
_ENGLISH = Path("/usr/share/dict/words")
_VOCAB: dict[int, "Vocabulary"] = {}


def _deletes(w: str) -> set[str]:
    return {w[:i] + w[i + 1:] for i in range(len(w))}


def distance(a: str, b: str) -> int:
    """Damerau-Levenshtein distance (optimal string alignment)."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def _base_forms(w: str) -> set[str]:
    out = {w}
    for suf, add in (("ies", "y"), ("ied", "y"), ("ing", ""), ("ing", "e"), ("ed", ""), ("ed", "e"), ("es", ""), ("s", ""),
                     ("ly", ""), ("er", ""), ("ers", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            b = w[: -len(suf)] + add
            out.add(b)
            if len(b) > 3 and b[-1] == b[-2] and not add:   # "shipping" -> "ship"
                out.add(b[:-1])
    return out


def _substitution(a: str, b: str) -> bool:
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1


def _vowel_swap(a: str, b: str) -> bool:
    return _substitution(a, b) and all(x in "aeiouy" and y in "aeiouy" for x, y in zip(a, b) if x != y)


def _same_word(a: str, b: str) -> bool:
    return bool(_base_forms(a) & _base_forms(b))


class Vocabulary:
    def __init__(self, freq: Counter, english: set[str] | None = None) -> None:
        self.freq = freq
        self.english = english or set()
        self.index: dict[str, set[str]] = {}
        for w in freq:
            if len(w) >= MIN_LEN - 1:
                for key in {w} | _deletes(w):
                    self.index.setdefault(key, set()).add(w)

    @classmethod
    def from_texts(cls, texts, english: set[str] | None = None) -> "Vocabulary":
        freq: Counter = Counter()
        for t in texts:
            freq.update(w.lower() for w in _WORD.findall(t or ""))
        return cls(freq, english)

    def known(self, w: str) -> bool:
        """In the regulations or the dictionary, as written or as an inflection of a word that is ("launching": the
        dictionary lists "launch" only)."""
        return any(f in self.freq or f in self.english for f in _base_forms(w))

    def suggest(self, word: str) -> str | None:
        """The regulation word `word` most likely misspells, or None."""
        w = word.lower()
        if len(w) < MIN_LEN or not w.isalpha() or self.known(w):
            return None
        limit = 1 if len(w) < 8 else 2
        cands: set[str] = set(self.index.get(w, ()))
        for d in _deletes(w):
            cands |= self.index.get(d, set())
        scored = [(distance(w, c), -self.freq[c], c) for c in cands if self.freq[c] >= MIN_FREQ]
        scored = sorted(x for x in scored if x[0] <= limit)
        if not scored:
            return None
        # "eyeshadow" is not a misspelling of "eyeshadows"; "withdrew" / "substrata" are word forms, not typos (one vowel
        # for another); a short word is corrected only for a dropped, doubled or swapped letter ("refile" is a word)
        scored = [x for x in scored if not _same_word(w, x[2]) and len(x[2]) >= MIN_TARGET_LEN
                  and not _vowel_swap(w, x[2]) and not (len(w) <= 6 and _substitution(w, x[2]))]
        if not scored:
            return None
        best = scored[0]
        rivals = [x for x in scored[1:] if x[0] == best[0]]
        if rivals and -rivals[0][1] * 3 > -best[1]:
            return None   # two regulation words as near and about as common: no safe guess
        return best[2]

    def correct(self, text: str) -> tuple[str, list[tuple[str, str]]]:
        """`text` with its misspelled words replaced (case kept for a capitalized word), and the (from, to) pairs.
        Quoted text is left as the user wrote it."""
        quoted = [(m.start(), m.end()) for m in re.finditer(r"(?<![A-Za-z])['\"‘“][^'\"’”]{1,80}['\"’”]", text or "")]
        fixes: list[tuple[str, str]] = []

        def repl(m):
            if any(a <= m.start() < b for a, b in quoted):
                return m.group(0)
            parts = m.group(0).split("-")
            out = []
            for p in parts:
                s = self.suggest(p)
                if s is None:
                    out.append(p)
                    continue
                fixes.append((p, s))
                out.append(s.capitalize() if p[:1].isupper() else s)
            return "-".join(out)

        return _WORD.sub(repl, text or ""), fixes


def vocabulary(db) -> Vocabulary:
    """The vocabulary of the live regulation text and the FD&C Act store (built once per database object)."""
    key = id(db)
    if key not in _VOCAB:
        texts = [r["t"] for r in db.query("SELECT body_text AS t FROM cfr_records WHERE removed_on IS NULL")]
        texts += [r["t"] for r in db.query("SELECT DISTINCT section_heading AS t FROM cfr_records WHERE removed_on IS NULL AND section_heading IS NOT NULL")]
        try:
            from regulus.retrieval.statute import statute_index

            st = statute_index(db)
            texts += [r.get("body_text") or r.get("text") or "" for r in getattr(st, "rows", [])]
        except Exception:  # noqa: BLE001 - the regulations alone are enough
            pass
        english = set()
        if _ENGLISH.exists():
            english = {w.strip().lower() for w in _ENGLISH.read_text(errors="ignore").splitlines() if w.strip()}
        _VOCAB[key] = Vocabulary.from_texts(texts, english)
    return _VOCAB[key]
