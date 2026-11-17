"""Generate the RAG test bench: 11 PDF regulations, 3 portal pages, manifest and questions.

Offline and deterministic: texts come from content.py, reportlab runs in
invariant mode (fixed creation date and document id), so the same input always
gives byte-identical files and identical content hashes.

    python tools/rag_dataset/generate.py [--out rag_test_data]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from html import escape
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from content import DOCUMENTS, PAGES, QUESTIONS, RECTOR, REFERENCE_ANSWERS, UNIVERSITY  # noqa: E402

FONTS = ROOT / "hse_schedule" / "assets" / "fonts"
SIGNOFF = [["Проректор по учебной работе", "Б. Г. Примерова", "согласовано"],
           ["Начальник правового управления", "В. Д. Образцов", "согласовано"],
           ["Председатель студенческого совета", "Г. Е. Тестовая", "согласовано"]]


def _pdf(doc: dict, path: Path) -> int:
    from reportlab import rl_config
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    rl_config.invariant = 1  # fixed timestamps and ids: byte-identical output
    for name, file in (("Onest", "Onest_400Regular.ttf"), ("Onest-Bold", "Onest_700Bold.ttf")):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(FONTS / file)))

    body = ParagraphStyle("body", fontName="Onest", fontSize=11.5, leading=16.5, alignment=TA_JUSTIFY, spaceAfter=5)
    cell = ParagraphStyle("cell", fontName="Onest", fontSize=10.5, leading=13.5)
    head_cell = ParagraphStyle("headcell", parent=cell, fontName="Onest-Bold")
    right = ParagraphStyle("right", parent=body, alignment=TA_RIGHT, spaceAfter=0, leading=15)
    center = ParagraphStyle("center", parent=body, alignment=TA_CENTER)
    title = ParagraphStyle("title", parent=center, fontName="Onest-Bold", fontSize=15, leading=20, spaceBefore=14, spaceAfter=10)
    heading = ParagraphStyle("heading", parent=body, fontName="Onest-Bold", fontSize=12.5, spaceBefore=10, spaceAfter=6, alignment=0)
    caption = ParagraphStyle("caption", parent=body, fontName="Onest-Bold", fontSize=10.5, spaceBefore=4, spaceAfter=4, alignment=0)

    def p(text: str, style) -> Paragraph:
        return Paragraph(xml_escape(text), style)

    def table(head: list[str], rows: list[list[str]], widths: list[float]) -> Table:
        data = [[p(h, head_cell) for h in head]] + [[p(c, cell) for c in row] for row in rows]
        t = Table(data, colWidths=widths, repeatRows=1)  # the header repeats when the table breaks
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#7a8699")),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf7")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        return t

    width = A4[0] - 4.5 * cm
    story = [p("УТВЕРЖДАЮ", right), p(RECTOR, right), p(doc["order"], right), Spacer(1, 6),
             p(UNIVERSITY, center), p(doc["title"], title)]
    for section in doc["sections"]:
        story.append(p(section["title"], heading))
        for number, text in section["items"]:
            story.append(p(f"{number} {text}", body))
        if section.get("table"):
            t = section["table"]
            widths = [width * 0.46, width * 0.30, width * 0.24]
            block = [p(t["caption"], caption), table(t["head"], t["rows"], widths), Spacer(1, 6)]
            story.extend(block if len(t["rows"]) > 8 else [KeepTogether(block)])
    story += [PageBreak(), p("Лист согласования", heading),
              table(["Должность", "ФИО", "Отметка"], SIGNOFF, [width * 0.5, width * 0.28, width * 0.22])]

    pages = [0]
    running = f"НИУ СТ · {doc['short']} · редакция {doc['version']}"

    def decorate(canvas, document) -> None:
        pages[0] = max(pages[0], document.page)
        canvas.saveState()
        canvas.setFont("Onest", 8.5)
        canvas.setFillColor(colors.HexColor("#5b6577"))
        canvas.drawString(2.5 * cm, A4[1] - 1.3 * cm, running)
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Страница {document.page}")
        canvas.restoreState()

    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=2.5 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
                      title=doc["title"], author="НИУ СТ (вымышленный)", subject="RAG test bench",
                      creator="tools/rag_dataset/generate.py").build(story, onFirstPage=decorate, onLaterPages=decorate)
    return pages[0]


CSS = """body{font-family:Arial,sans-serif;margin:0;color:#1d2433;background:#f4f6fb}
header,nav,footer{background:#1f4fbf;color:#fff;padding:10px 24px}nav a{color:#fff;margin-right:16px}
main{max-width:860px;margin:24px auto;background:#fff;padding:24px;border-radius:12px}
.important{border-left:4px solid #d97706;background:#fff7e6;padding:12px 16px;margin:16px 0}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #c9d1e0;padding:6px 8px;text-align:left}
details{border:1px solid #c9d1e0;border-radius:8px;padding:8px 12px;margin:8px 0}summary{font-weight:bold;cursor:pointer}"""


def _html(page: dict) -> str:
    t = page["table"]
    rows = "".join("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in row) + "</tr>" for row in t["rows"])
    faq = "".join(f"<details><summary>{escape(q)}</summary><p>{escape(a)}</p></details>" for q, a in page["faq"])
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>{escape(page['title'])} — НИУ СТ</title><style>{CSS}</style>
<script>document.addEventListener('DOMContentLoaded',()=>console.log('portal'));</script></head>
<body>
<header>НИУ СТ · студенческий портал (вымышленный университет, концепт для конкурса)</header>
<nav><a href="#">Главная</a><a href="#">Учёба</a><a href="#">Общежития</a><a href="#">Библиотека</a><a href="#">Контакты</a></nav>
<main>
<h1>{escape(page['title'])}</h1>
<p>{escape(page['intro'])}</p>
<div class="important">{escape(page['important'])}</div>
<h2>{escape(t['caption'])}</h2>
<table><thead><tr>{''.join(f'<th>{escape(h)}</th>' for h in t['head'])}</tr></thead><tbody>{rows}</tbody></table>
<h2>Частые вопросы</h2>
{faq}
</main>
<footer>© НИУ СТ, вымышленная организация. Телефоны и адреса не существуют. Обновлено: {escape(page['version'])}</footer>
</body></html>
"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(out: Path) -> dict:
    (out / "pdfs").mkdir(parents=True, exist_ok=True)
    (out / "web").mkdir(parents=True, exist_ok=True)
    manifest = []
    for doc in DOCUMENTS:
        path = out / "pdfs" / doc["file"]
        pages = _pdf(doc, path)
        manifest.append({"doc_id": doc["doc_id"], "title": doc["title"], "kind": "regulation", "version": doc["version"],
                         "status": doc["status"], "effective_from": doc["effective_from"], "priority": doc["priority"],
                         "audience": doc["audience"], "source_path": f"pdfs/{doc['file']}", "pages": pages,
                         "sha256": _sha256(path)})
    for page in PAGES:
        path = out / "web" / page["file"]
        path.write_text(_html(page), encoding="utf-8", newline="\n")
        manifest.append({"doc_id": page["doc_id"], "title": page["title"], "kind": "portal", "version": page["version"],
                         "status": page["status"], "effective_from": page["effective_from"], "priority": page["priority"],
                         "audience": page["audience"], "source_path": f"web/{page['file']}", "pages": 1,
                         "sha256": _sha256(path)})
    (out / "manifest.json").write_text(json.dumps({"documents": manifest}, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8", newline="\n")
    (out / "questions.json").write_text(json.dumps({"questions": QUESTIONS}, ensure_ascii=False, indent=2) + "\n",
                                        encoding="utf-8", newline="\n")
    (out / "README.md").write_text(_readme(manifest), encoding="utf-8", newline="\n")
    return {"documents": manifest}


def _readme(manifest: list[dict]) -> str:
    lines = ["# Тестовый стенд RAG (НИУ СТ — вымышленный университет)", "",
             "Сгенерировано `python tools/rag_dataset/generate.py`, проверяется `python tools/rag_dataset/verify.py`. "
             "Все документы, числа, адреса и телефоны выдуманы для конкурсного концепта; это не документы реального вуза.", "",
             "## Файлы", "", "| doc_id | Файл | Статус | Приоритет | Аудитория | Страниц |", "| --- | --- | --- | --- | --- | --- |"]
    for d in manifest:
        lines.append(f"| {d['doc_id']} | `{d['source_path']}` | {d['status']} | {d['priority']} | {d['audience']} | {d['pages']} |")
    lines += ["", "Приоритет: 1 — выше. Ловушки:", "",
              "1. **Устаревшая редакция.** `04_old_…_red1.pdf` (superseded) с другими суммами и сроками; верный ответ — только из редакции 2.",
              "2. **Конфликт документов.** Срок апелляции: Этический кодекс (док. 09, п. 4.2) — 5 рабочих дней, Положение об учебном процессе (док. 01, п. 5.1) — 3; док. 09 сам отдаёт приоритет док. 01.",
              "3. **Таблица через страницы.** Таблица 1 в док. 10 переходит со страницы 1 на страницу 2 с повтором шапки.",
              "4. **Перекрёстные ссылки.** Док. 06 п. 2.4 → док. 04 п. 3.4; док. 03 п. 3.3 → док. 07 п. 5.2; док. 09 п. 1.1 → док. 07 п. 5.2.",
              "", "Шум, который должен отбрасывать разбор: строка «УТВЕРЖДАЮ», колонтитул «НИУ СТ · … · редакция N» и «Страница N» на каждой странице, лист согласования; в HTML — шапка, меню, подвал и скрипт.",
              "", "## Вопросы и эталонные ответы", "", "| id | Тип | Вопрос | Эталон | Источник | must_contain |", "| --- | --- | --- | --- | --- | --- |"]
    for q in QUESTIONS:
        must = ", ".join(f"«{m}»" for m in q["must_contain"]) or "—"
        source = f"{q['gold_doc_id']} / {q['gold_section']}" if q["gold_doc_id"] else "нет в базе"
        lines.append(f"| {q['id']} | {q['type']} | {q['question']} | {REFERENCE_ANSWERS[q['id']]} | {source} | {must} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "rag_test_data")
    result = generate(parser.parse_args().out)
    for d in result["documents"]:
        print(f"{d['doc_id']:<13} {d['pages']} стр.  {d['source_path']}")
    print(f"Готово: {len(result['documents'])} файлов, {len(QUESTIONS)} вопросов")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
