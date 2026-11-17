"""Retrieval evaluation on rag_test_data/questions.json (kb-eval).

Per mode (BM25 only, vectors only, hybrid):
- hit@1 / hit@3 / hit@5 — a fragment of gold_doc_id and gold_section in the top N;
- MRR of the first such fragment;
- must_contain@5 — every must_contain substring occurs in the top-5 texts;
- correct refusals — unanswerable questions that is_confident rejects;
- accepted — answerable questions that is_confident lets through.

Vector modes need embeddings in the base; without them they are reported as
«не измерено», never as numbers. 15 questions are a small sample: the numbers
are indicative and say nothing about real documents.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

from ..textsearch import tokens
from .chunker import matches_section
from .retriever import Retriever, SearchResult, is_confident

MODES = (("bm25", "Только BM25"), ("vector", "Только векторы"), ("hybrid", "Гибрид (RRF)"))


def load_questions(path: str | Path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["questions"]


def _rank(result: SearchResult, q: dict) -> int | None:
    for place, hit in enumerate(result.hits, start=1):
        if hit.fragment.doc_id == q["gold_doc_id"] and matches_section(hit.fragment.section_path, q["gold_section"]):
            return place
    return None


async def run_mode(retriever: Retriever, questions: list[dict], mode: str) -> list[dict]:
    rows = []
    for q in questions:
        result = await retriever.search(q["question"], k=5, mode=mode)
        rows.append({"q": q, "result": result, "rank": _rank(result, q) if q["answerable"] else None})
    return rows


def metrics(rows: list[dict], thresholds: dict) -> dict:
    answerable = [r for r in rows if r["q"]["answerable"]]
    refusals = [r for r in rows if not r["q"]["answerable"]]
    n = len(answerable) or 1

    def hit(k: int) -> float:
        return sum(1 for r in answerable if r["rank"] and r["rank"] <= k) / n

    must = sum(1 for r in answerable
               if all(m in "\n".join(h.fragment.text for h in r["result"].hits[:5]) for m in r["q"]["must_contain"])) / n
    return {
        "hit@1": hit(1), "hit@3": hit(3), "hit@5": hit(5),
        "mrr": sum(1 / r["rank"] for r in answerable if r["rank"]) / n,
        "must@5": must,
        "refused": sum(1 for r in refusals if not is_confident(r["result"], thresholds)),
        "refusals_total": len(refusals),
        "accepted": sum(1 for r in answerable if is_confident(r["result"], thresholds)),
        "answerable_total": len(answerable),
        "mode_used": sorted({r["result"].mode for r in rows}),
    }


def calibrate(rows: list[dict], key: str) -> dict:
    """Grid search: every unanswerable question refused, as many answerable ones accepted as possible.

    Among equally good pairs the one in the middle of the feasible range is taken,
    so the threshold is not glued to a single question.
    """
    if key == "bm25_only":
        grid_a = [x / 2 for x in range(0, 41)]  # min_bm25 0 … 20
        signal = lambda r: r["result"].top_bm25  # noqa: E731
        name_a = "min_bm25"
    else:
        grid_a = [x / 100 for x in range(0, 101, 2)]  # min_cosine 0 … 1
        signal = lambda r: r["result"].top_cosine if r["result"].top_cosine is not None else -1.0  # noqa: E731
        name_a = "min_cosine"
    grid_c = [x / 10 for x in range(0, 11)]
    best, best_pairs = -1, []
    for a, cov in itertools.product(grid_a, grid_c):
        accept = lambda r: bool(r["result"].hits) and signal(r) >= a and r["result"].term_coverage >= cov  # noqa: E731
        if any(accept(r) for r in rows if not r["q"]["answerable"]):
            continue
        good = sum(1 for r in rows if r["q"]["answerable"] and accept(r))
        if good > best:
            best, best_pairs = good, [(a, cov)]
        elif good == best:
            best_pairs.append((a, cov))
    if not best_pairs:
        return {"found": False}
    # Middle of the gap on each signal between «no answer» and the accepted questions:
    # the largest margin on both sides, instead of a threshold glued to one question.
    a0, c0 = best_pairs[len(best_pairs) // 2]
    accepted = [r for r in rows if r["q"]["answerable"] and r["result"].hits and signal(r) >= a0 and r["result"].term_coverage >= c0]
    refused = [r for r in rows if not r["q"]["answerable"] and r["result"].hits]
    a, cov = a0, c0
    if accepted and refused:
        snap = lambda value, grid: min(grid, key=lambda g: abs(g - value))  # noqa: E731
        a = snap((max(signal(r) for r in refused) + min(signal(r) for r in accepted)) / 2, grid_a)
        cov = snap((max(r["result"].term_coverage for r in refused) + min(r["result"].term_coverage for r in accepted)) / 2, grid_c)
        if (a, cov) not in best_pairs:
            a, cov = a0, c0
    return {"found": True, name_a: a, "min_term_coverage": cov, "accepted": best, "pairs": len(best_pairs)}


def hypothesis(row: dict) -> str:
    q, result = row["q"], row["result"]
    docs = [h.fragment.doc_id for h in result.hits]
    query_terms = set(tokens(q["question"]))
    gold_terms = set().union(*(tokens(m) for m in q["must_contain"])) if q["must_contain"] else set()
    if q["gold_doc_id"] in docs:
        return "нужный документ найден, но не тот пункт — нарезка или соседний пункт с теми же словами"
    if q["gold_section"] and q["gold_section"].startswith("table"):
        return "ответ в таблице: слова вопроса не совпадают с подписью и шапкой таблицы"
    if query_terms and not (query_terms & gold_terms):
        return "синонимы: в вопросе другие слова, чем в правиле (BM25 их не связывает)"
    return "вопрос делит слова с другими документами — выше оказался чужой документ"


def report(results: dict[str, list[dict] | None], thresholds: dict) -> tuple[str, dict]:
    lines = ["| Режим | hit@1 | hit@3 | hit@5 | MRR | must_contain@5 | Отклонено без ответа | Пропущено с ответом |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    table = {}
    for mode, label in MODES:
        rows = results.get(mode)
        if rows is None:
            lines.append(f"| {label} | не измерено | не измерено | не измерено | не измерено | не измерено | не измерено | не измерено |")
            continue
        m = metrics(rows, thresholds)
        table[mode] = m
        lines.append(f"| {label} | {m['hit@1']:.2f} | {m['hit@3']:.2f} | {m['hit@5']:.2f} | {m['mrr']:.2f} | {m['must@5']:.2f} | "
                     f"{m['refused']} из {m['refusals_total']} | {m['accepted']} из {m['answerable_total']} |")
    return "\n".join(lines), table


def failures(rows: list[dict]) -> list[str]:
    out = []
    for r in rows:
        q = r["q"]
        if not q["answerable"] or (r["rank"] == 1):
            continue
        top = "; ".join(f"{h.fragment.doc_id} {h.fragment.section_path}" for h in r["result"].hits[:3]) or "—"
        place = f"место {r['rank']}" if r["rank"] else "нет в топ-5"
        out.append(f"- **{q['id']}** «{q['question']}» — эталон {q['gold_doc_id']} / {q['gold_section']}, {place}. "
                   f"Топ-3: {top}. Гипотеза: {hypothesis(r)}.")
    return out
