"""Small dependency-free BM25 implementation with Chinese bigram tokenization."""
from __future__ import annotations

import math
import re
from collections import Counter


def tokenize(text: str) -> list[str]:
    text = text.lower()
    latin = re.findall(r"[a-z0-9][a-z0-9_.+/-]*", text)
    chinese_runs = re.findall(r"[\u4e00-\u9fff]+", text)
    chinese: list[str] = []
    for run in chinese_runs:
        chinese.extend(list(run))
        chinese.extend(run[i:i + 2] for i in range(len(run) - 1))
    return latin + chinese


def score(query: str, documents: list[str], *, k1: float = 1.5, b: float = 0.75) -> list[float]:
    if not documents:
        return []
    q_tokens = list(dict.fromkeys(tokenize(query)))
    tokenized = [tokenize(d) for d in documents]
    avg_len = sum(map(len, tokenized)) / max(len(tokenized), 1)
    dfs: Counter[str] = Counter()
    for tokens in tokenized:
        dfs.update(set(tokens))
    n = len(documents)
    results: list[float] = []
    for tokens in tokenized:
        tf = Counter(tokens)
        dl = len(tokens)
        total = 0.0
        for term in q_tokens:
            freq = tf.get(term, 0)
            if not freq:
                continue
            idf = math.log(1 + (n - dfs[term] + 0.5) / (dfs[term] + 0.5))
            denom = freq + k1 * (1 - b + b * dl / max(avg_len, 1))
            total += idf * freq * (k1 + 1) / denom
        results.append(total)
    return results
