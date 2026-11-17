"""Check the RAG test bench; exits non-zero on any problem.

- every PDF opens, prints its first 200 characters, has 2–4 pages and no
  replacement characters (U+FFFD, «(cid:…)», empty glyph boxes);
- every must_contain substring really occurs in the text of its gold document;
- the traps are in place: the cross-page table, the superseded edition with
  other numbers, the conflict and the cross-references.

    python tools/rag_dataset/verify.py [--data rag_test_data]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BAD = re.compile(r"�|\(cid:\d+\)|[□▯]")


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def pdf_text(path: Path) -> tuple[str, int, list]:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
        tables = [page.extract_tables() for page in pdf.pages]
    return "\n".join(pages), len(pages), tables


def html_text(path: Path) -> str:
    from bs4 import BeautifulSoup

    return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser").get_text(" ")


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка тестового стенда RAG")
    parser.add_argument("--data", type=Path, default=ROOT / "rag_test_data")
    data = parser.parse_args().data
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))["documents"]
    questions = json.loads((data / "questions.json").read_text(encoding="utf-8"))["questions"]
    errors: list[str] = []
    texts: dict[str, str] = {}

    for doc in manifest:
        path = data / doc["source_path"]
        if not path.is_file():
            errors.append(f"{doc['doc_id']}: нет файла {path}")
            continue
        if path.suffix == ".pdf":
            text, pages, tables = pdf_text(path)
            print(f"[{doc['doc_id']}] {pages} стр. {squash(text)[:200]}")
            if not 2 <= pages <= 4:
                errors.append(f"{doc['doc_id']}: {pages} страниц, нужно 2–4")
            if pages != doc["pages"]:
                errors.append(f"{doc['doc_id']}: в manifest {doc['pages']} страниц, в файле {pages}")
            if not any(tables):
                errors.append(f"{doc['doc_id']}: нет ни одной таблицы")
            if doc["doc_id"] == "10":
                spans = [i for i, page in enumerate(tables) if any(t and t[0][0] == "Документ" and len(t) > 3 for t in page)]
                if len(spans) < 2:
                    errors.append("10: таблица-ловушка не переходит на следующую страницу с повтором шапки")
        else:
            text = html_text(path)
            print(f"[{doc['doc_id']}] html {squash(text)[:200]}")
        bad = BAD.findall(text)
        if bad:
            errors.append(f"{doc['doc_id']}: символы-замены {sorted(set(bad))[:5]}")
        if len(squash(text)) < 300:
            errors.append(f"{doc['doc_id']}: слишком мало текста")
        texts[doc["doc_id"]] = squash(text)

    if len(questions) != 15:
        errors.append(f"вопросов {len(questions)}, нужно 15")
    counts: dict[str, int] = {}
    for q in questions:
        counts[q["type"]] = counts.get(q["type"], 0) + 1
        if q["answerable"]:
            gold = texts.get(q["gold_doc_id"])
            if gold is None:
                errors.append(f"{q['id']}: нет gold-документа {q['gold_doc_id']}")
                continue
            for needle in q["must_contain"]:
                if squash(needle) not in gold:
                    errors.append(f"{q['id']}: «{needle}» не найдено в документе {q['gold_doc_id']}")
        elif q["must_contain"]:
            errors.append(f"{q['id']}: у вопроса без ответа must_contain должен быть пустым")
    expected = {"direct": 5, "table": 3, "cross_doc": 2, "html": 2, "unanswerable": 3}
    if counts != expected:
        errors.append(f"типы вопросов {counts}, нужно {expected}")

    status = {d["doc_id"]: d["status"] for d in manifest}
    if status.get("04_old") != "superseded" or "5400 руб." in texts.get("04_old", "") or "4650 руб." not in texts.get("04_old", ""):
        errors.append("ловушка 1: старая редакция 04 должна быть superseded и с другими суммами")
    if "5 рабочих дней" not in texts.get("09", "") or "п. 5.1" not in texts.get("09", ""):
        errors.append("ловушка 2: нет конфликта сроков апелляции в док. 09")
    if "п. 3.4 Положения о стипендиальном обеспечении (док. 04)" not in texts.get("06", ""):
        errors.append("ловушка 4: нет перекрёстной ссылки 06 → 04 п. 3.4")

    print(f"\nДокументов: {len(manifest)} (PDF: {sum(d['source_path'].endswith('.pdf') for d in manifest)}, "
          f"HTML: {sum(d['source_path'].endswith('.html') for d in manifest)}); вопросов: {len(questions)} {counts}")
    if errors:
        print("\nОШИБКИ:")
        for error in errors:
            print(" -", error)
        return 1
    print("Проверка пройдена: все must_contain найдены в gold-документах, ловушки на месте.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
