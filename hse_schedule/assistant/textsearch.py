"""Shared word search: tokenisation (stem = first 6 letters) and BM25.

Used by the old 15-rule index in engine.py and by the knowledge base
retriever, so both treat words the same way.
"""

from __future__ import annotations

import math
import re
from collections import Counter

_WORD = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
STOP = set("и в во на по к ко с со о об от до за из у а но или ли же бы не ни что как где когда мне меня мой моя мои мою "
           "я ты вы вас вам это этот эта то та там тут ещё еще уже для при про над под без очень можно нужно надо "
           "хочу какой какая какие каких сколько есть будет был была".split())


def stem(word: str) -> str:
    word = word.lower().replace("ё", "е")
    return word[:6] if len(word) > 6 else word


def tokens(text: str) -> list[str]:
    return [stem(w) for w in _WORD.findall(text.lower()) if w.lower() not in STOP and len(w) > 1]


class BM25:
    """Okapi BM25 over plain texts (k1 = 1.2, b = 0.75)."""

    def __init__(self, texts: list[str]) -> None:
        self.bags = [Counter(tokens(text)) for text in texts]
        self.lengths = [sum(bag.values()) for bag in self.bags]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        df: Counter = Counter()
        for bag in self.bags:
            df.update(bag.keys())
        n = len(texts)
        self.idf = {term: math.log(1 + (n - count + 0.5) / (count + 0.5)) for term, count in df.items()}

    def scores(self, query: str) -> list[float]:
        terms = tokens(query)
        result = []
        for bag, length in zip(self.bags, self.lengths):
            score = 0.0
            for term in terms:
                tf = bag.get(term, 0)
                if tf:
                    score += self.idf[term] * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / (self.avg or 1)))
            result.append(score)
        return result
