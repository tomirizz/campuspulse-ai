"""Source-grounded, extractive study notes and portable document exports.

This module never follows instructions in a document and never calls a model.
Every study paragraph and answer is copied from selected source evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from io import BytesIO
import os
from pathlib import Path
import re
import uuid


METHOD_NOTE = ("Экстрактивная выжимка по цитатам: приложение выбирает фрагменты загруженных материалов, "
               "выделяет определения и предлагает вопросы для самопроверки. Это не генерация Gemini "
               "и не проверка истинности источника. У каждого фрагмента есть ссылка на файл и страницу.")
_STOP = {"это", "для", "или", "как", "при", "что", "его", "она", "они", "the", "and", "for", "with", "that", "this", "from", "are", "has", "was", "will"}
_STYLE_NAMES = {"summary": "Краткий конспект", "exam": "Подготовка к экзамену", "flashcards": "Карточки для повторения"}
_METADATA_LABEL = re.compile(
    r"^(?:(?:этот|данный)\s+(?:текст|документ|пример)|учебный\s+пример|пример|example|sample|заметка|note|"
    r"примечание|источник|source|дата|date|автор|author|copyright|license|лицензия|дисклеймер|disclaimer|"
    r"инструкция|instructions?|system|assistant|developer|user|role|prompt)(?:\b|$)", re.I)


def _is_metadata(text):
    value = text.strip()
    if _METADATA_LABEL.search(value):
        return True
    return bool(re.search(
        r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions|disregard\s+.*instructions|"
        r"system\s+prompt|(?:reveal|send|print)\s+.*(?:api.?key|password|secret)|"
        r"(?:игнорируй|забудь)\s+.*(?:инструкци|правил)|(?:раскрой|отправь|покажи)\s+.*(?:парол|секрет|api.?ключ)|"
        r"(?:delete|удали)\s+.*(?:files?|файл)|<\s*script\b|javascript:|\bonerror\s*=", value, re.I))


def _terms(text):
    return {word.casefold().replace("ё", "е")[:6] for word in re.findall(r"[A-Za-zА-Яа-яЁё]{3,}", text)
            if word.casefold() not in _STOP}


def _pieces(text):
    """Exact, bounded substrings with original line/start offsets."""
    for line_number, line in enumerate(text.splitlines(), 1):
        if not re.search(r"[A-Za-zА-Яа-яЁё]", line):
            continue
        # Sentence ends before a capitalized next sentence, not inside 0.01.
        for match in re.finditer(r".+?(?:[.!?](?=\s+[A-ZА-ЯЁ])|$)", line):
            raw = match.group()
            offset = match.start()
            while raw.strip():
                leading = len(raw) - len(raw.lstrip())
                raw, offset = raw[leading:], offset + leading
                if len(raw) > 700:
                    stop = raw.rfind(" ", 200, 700)
                    stop = stop if stop > 0 else 700
                else:
                    stop = len(raw)
                quote = raw[:stop].rstrip()
                if quote and (len(_terms(quote)) >= 3 or re.search(r"\w\s*[:=—]\s*\w", quote)):
                    yield quote, line_number, offset
                raw, offset = raw[stop:], offset + stop


def _definition(quote):
    if _is_metadata(quote):
        return None
    match = re.fullmatch(r"\s*([^:—=\n]{2,70})\s*[:—=]\s*(.{3,500})\s*", quote)
    if not match:
        return None
    term, definition = match[1].strip(), match[2].strip()
    if len(term.split()) > 9 or "<" in term or ">" in term or not re.search(r"[A-Za-zА-Яа-яЁё]", term):
        return None
    return term, definition


def build_notebook(materials: list[dict], title: str = "", focus: str = "", style: str = "summary",
                   now: datetime | None = None) -> dict:
    if style not in _STYLE_NAMES:
        raise ValueError("Выберите краткий конспект, подготовку к экзамену или карточки")
    if not 1 <= len(materials) <= 10:
        raise ValueError("Выберите от одного до десяти своих материалов")
    wanted = _terms(focus[:300])
    candidates = []
    seen = set()
    input_chars = 0
    for material_index, material in enumerate(materials):
        for page in material.get("pages", [])[:20]:
            text = str(page.get("text", ""))[:30_000]
            if input_chars >= 200_000:
                break
            text = text[:200_000 - input_chars]
            input_chars += len(text)
            for quote, line, start in _pieces(text):
                identity = (str(material.get("id")), int(page.get("page", 1)), quote)
                if identity in seen:
                    continue
                seen.add(identity)
                overlap = len(wanted & _terms(quote))
                definition = _definition(quote)
                score = overlap * 12 + (4 if definition else 0) + min(3, len(_terms(quote)) // 8)
                if len(quote) < 25:
                    score -= 2
                candidates.append({"material_id": str(material["id"]), "file": str(material.get("name", "Материал"))[:160],
                    "page": int(page.get("page", 1)), "line": line, "start": start, "quote": quote,
                    "_score": score, "_overlap": overlap, "_definition": definition, "_order": len(candidates),
                    "_material_index": material_index})
                if len(candidates) >= 3000:
                    break
            if len(candidates) >= 3000:
                break
        if len(candidates) >= 3000:
            break
    if not candidates:
        raise ValueError("В выбранных материалах не найден читаемый учебный текст. Загрузите PDF с текстом или конспект TXT/MD")
    focused = [item for item in candidates if item["_overlap"]]
    pool = focused if wanted and focused else candidates
    ranked = sorted(pool, key=lambda item: (-item["_score"], item["_order"]))
    # Reserve representation for every selected source with matching evidence.
    selected = []
    for material in materials:
        selected.extend([item for item in ranked if item["material_id"] == str(material["id"])][:3])
    selected_keys = {item["_order"] for item in selected}
    selected.extend(item for item in ranked if item["_order"] not in selected_keys)
    selected = selected[:36 if style != "flashcards" else 28]
    selected.sort(key=lambda item: (item["_material_index"], item["_order"]))
    sources = []
    for index, item in enumerate(selected, 1):
        item["_id"] = f"S{index}"
        sources.append({key: item[key] for key in ("material_id", "file", "page", "line", "start", "quote")} | {"id": item["_id"]})
    sections = []
    for material in materials:
        rows = [item for item in selected if item["material_id"] == str(material["id"])]
        if not rows:
            continue
        name = str(material.get("name", "Материал"))[:160]
        prefix = "Опорные факты" if style == "exam" else "Фрагменты для повторения" if style == "flashcards" else "Главное из материала"
        sections.append({"title": f"{prefix}: {name}", "paragraphs": [
            {"text": item["quote"], "source_ids": [item["_id"]]} for item in rows]})
    key_terms, questions = [], []
    known_terms = set()
    for item in selected:
        if not item["_definition"]:
            continue
        term, definition = item["_definition"]
        if term.casefold() in known_terms:
            continue
        known_terms.add(term.casefold())
        key_terms.append({"term": term, "definition": definition, "source_ids": [item["_id"]]})
        questions.append({"question": f"Что означает «{term}» согласно материалу?", "answer": definition,
                          "source_ids": [item["_id"]]})
        if len(key_terms) >= 12:
            break
    used_questions = {q["source_ids"][0] for q in questions}
    # Three genuine definitions already make a useful quiz. Do not pad it
    # with arbitrary verbs or metadata simply to reach a question count.
    for item in ([] if len(questions) >= 3 else sorted(selected, key=lambda row: (-row["_score"], row["_order"]))):
        if len(questions) >= (16 if style == "flashcards" else 10):
            break
        if item["_id"] in used_questions or _is_metadata(item["quote"]):
            continue
        match = re.search(r"\b\d+(?:[.,]\d+)?(?:\s*%)?", item["quote"])
        if not match:
            match = re.search(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b|\b[A-Z]{2,8}\b", item["quote"])
        if not match:
            for known in key_terms:
                match = re.search(r"(?<!\w)" + re.escape(known["term"]) + r"(?!\w)", item["quote"], re.I)
                if match:
                    break
        if not match:
            continue
        masked = item["quote"][:match.start()] + "_____" + item["quote"][match.end():]
        questions.append({"question": f"Восстановите пропущенный фрагмент из источника: «{masked}»",
                          "answer": match.group(), "source_ids": [item["_id"]]})
        used_questions.add(item["_id"])
    note = METHOD_NOTE
    if wanted and not focused:
        note += " По указанному фокусу буквальных совпадений не найдено; показана общая выжимка."
    if input_chars >= 200_000 or len(candidates) >= 3000:
        note += " Большие материалы ограничены по объёму обработки; проверьте полноту."
    name = title.strip()[:160] or (f"Конспект: {focus.strip()}"[:160] if focus.strip() else f"{_STYLE_NAMES[style]}: {materials[0].get('name', 'Материалы')}"[:160])
    created = now or datetime.now(timezone.utc)
    return {"id": uuid.uuid4().hex, "title": name, "created_at": created.isoformat(),
            "material_ids": [str(item["id"]) for item in materials], "focus": focus.strip()[:300], "style": style,
            "sources": sources, "sections": sections, "key_terms": key_terms, "questions": questions,
            "mode": "extractive", "method_note": note}


def notebook_metadata(note: dict) -> dict:
    return {key: note.get(key) for key in ("id", "title", "created_at", "material_ids", "focus", "style", "mode")} | {
        "source_count": len(note.get("sources", [])), "question_count": len(note.get("questions", []))}


def _markdown(value):
    return re.sub(r"([\\`*_{}\[\]<>#])", r"\\\1", str(value))


def render_markdown(note: dict) -> str:
    lines = ["# " + _markdown(note["title"]).replace("\n", " "), "", note["method_note"], ""]
    for section in note["sections"]:
        lines.extend(["## " + _markdown(section["title"]).replace("\n", " "), ""])
        for paragraph in section["paragraphs"]:
            lines.extend([_markdown(paragraph["text"]) + " " + " ".join(f"[{sid}]" for sid in paragraph["source_ids"]), ""])
    if note["key_terms"]:
        lines.extend(["## Ключевые понятия", ""])
        for item in note["key_terms"]:
            lines.extend([f"- {_markdown(item['term'])}: {_markdown(item['definition'])} " + " ".join(f"[{sid}]" for sid in item["source_ids"]), ""])
    lines.extend(["## Самопроверка", ""])
    for index, item in enumerate(note["questions"], 1):
        lines.extend([f"{index}. {_markdown(item['question'])}", "", f"   Ответ: {_markdown(item['answer'])} " + " ".join(f"[{sid}]" for sid in item["source_ids"]), ""])
    lines.extend(["## Источники", ""])
    for source in note["sources"]:
        lines.extend([f"[{source['id']}] {_markdown(source['file'])}, стр. {source['page']}, строка {source.get('line', 1)}", "", "> " + _markdown(source["quote"]).replace("\n", "\n> "), ""])
    return "\n".join(lines)


def render_text(note: dict) -> str:
    lines = [note["title"], "", note["method_note"], ""]
    for section in note["sections"]:
        lines.extend([section["title"], ""])
        for paragraph in section["paragraphs"]:
            lines.extend([paragraph["text"] + " " + " ".join(f"[{sid}]" for sid in paragraph["source_ids"]), ""])
    if note["key_terms"]:
        lines.extend(["КЛЮЧЕВЫЕ ПОНЯТИЯ", ""])
        for item in note["key_terms"]:
            lines.append(f"{item['term']}: {item['definition']} " + " ".join(f"[{sid}]" for sid in item["source_ids"]))
    lines.extend(["", "САМОПРОВЕРКА", ""])
    for index, item in enumerate(note["questions"], 1):
        lines.extend([f"{index}. {item['question']}", "Ответ: " + item["answer"] + " " + " ".join(f"[{sid}]" for sid in item["source_ids"]), ""])
    lines.extend(["ИСТОЧНИКИ", ""])
    for source in note["sources"]:
        lines.extend([f"[{source['id']}] {source['file']}, стр. {source['page']}, строка {source.get('line', 1)}", source["quote"], ""])
    return "\n".join(lines)


def render_html(note: dict) -> str:
    def refs(ids):
        return " ".join(f'<a class="ref" href="#source-{escape(sid, quote=True)}">[{escape(sid)}]</a>' for sid in ids)
    parts = ['<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>' + escape(note["title"]) + '</title><style>body{font:16px/1.65 system-ui,sans-serif;color:#213047;max-width:860px;margin:45px auto;padding:0 25px}h1{font-size:32px;line-height:1.2}h2{margin-top:34px;font-size:22px;color:#17656c}.method{padding:18px;background:#eef5f5;border-radius:12px;color:#526476;font-size:14px}.ref{font-size:12px;color:#207078;text-decoration:none}blockquote{border-left:3px solid #bfd7d8;margin:14px 0;padding:5px 18px;color:#526476;white-space:pre-wrap}.source{font-size:13px}.answer{color:#526476}@media print{body{margin:0;max-width:none}h2{break-after:avoid}a{color:inherit}}</style></head><body>',
        '<p>CampusPulse · Учебные материалы</p><h1>' + escape(note["title"]) + '</h1><p class="method">' + escape(note["method_note"]) + '</p>']
    for section in note["sections"]:
        parts.append('<h2>' + escape(section["title"]) + '</h2>')
        for paragraph in section["paragraphs"]:
            parts.append('<p>' + escape(paragraph["text"]).replace("\n", "<br>") + ' ' + refs(paragraph["source_ids"]) + '</p>')
    if note["key_terms"]:
        parts.append('<h2>Ключевые понятия</h2><dl>')
        for item in note["key_terms"]:
            parts.append('<dt><strong>' + escape(item["term"]) + '</strong></dt><dd>' + escape(item["definition"]) + ' ' + refs(item["source_ids"]) + '</dd>')
        parts.append('</dl>')
    parts.append('<h2>Самопроверка</h2><ol>')
    for item in note["questions"]:
        parts.append('<li><p>' + escape(item["question"]) + '</p><p class="answer">Ответ: ' + escape(item["answer"]) + ' ' + refs(item["source_ids"]) + '</p></li>')
    parts.append('</ol><h2>Источники</h2>')
    for source in note["sources"]:
        parts.append('<div class="source" id="source-' + escape(source["id"], quote=True) + '"><strong>[' + escape(source["id"]) + '] ' + escape(source["file"]) + ', стр. ' + str(source["page"]) + ', строка ' + str(source.get("line", 1)) + '</strong><blockquote>' + escape(source["quote"]) + '</blockquote></div>')
    parts.append('</body></html>')
    return "\n".join(parts)


def _pdf_fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    root = Path(__file__).resolve().parent.parent
    regular_candidates = [os.getenv("CAMPUSPULSE_PDF_FONT"), root / "assets/fonts/DejaVuSans.ttf",
        root / "assets/fonts/LiberationSans-Regular.ttf", Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf")]
    regular = next((Path(path) for path in regular_candidates if path and Path(path).is_file()), None)
    if regular is None:
        raise ValueError("Для PDF нужен шрифт с кириллицей. Установите DejaVu Sans или задайте CAMPUSPULSE_PDF_FONT; TXT, Markdown и HTML доступны без него")
    bold_candidates = [regular.parent / "DejaVuSans-Bold.ttf", regular.parent / "LiberationSans-Bold.ttf", regular.parent / "arialbd.ttf"]
    bold = next((path for path in bold_candidates if path.is_file()), regular)
    # Safe to repeat across concurrent exports: ReportLab keeps a process registry.
    if "CampusPulseNotes" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("CampusPulseNotes", str(regular)))
    if "CampusPulseNotesBold" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("CampusPulseNotesBold", str(bold)))
    return "CampusPulseNotes", "CampusPulseNotesBold"


def render_pdf(note: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph
    font, bold = _pdf_fonts()
    buffer = BytesIO()
    styles = {
        "title": ParagraphStyle("NotesTitle", fontName=bold, fontSize=22, leading=28, spaceAfter=17, textColor=colors.HexColor("#15364A")),
        "section": ParagraphStyle("NotesSection", fontName=bold, fontSize=14, leading=19, spaceBefore=18, spaceAfter=9, keepWithNext=True, textColor=colors.HexColor("#17656C")),
        "body": ParagraphStyle("NotesBody", fontName=font, fontSize=10.2, leading=15.3, spaceAfter=10, alignment=TA_LEFT, textColor=colors.HexColor("#243549")),
        "small": ParagraphStyle("NotesSmall", fontName=font, fontSize=8.5, leading=12, spaceAfter=10, textColor=colors.HexColor("#5B6D7A")),
        "source": ParagraphStyle("NotesSource", fontName=font, fontSize=8.5, leading=12.5, spaceAfter=10, textColor=colors.HexColor("#4B5B6A")),
    }

    def clean(value):
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value))
        text = text.replace("—", "-").replace("–", "-").replace("‑", "-")
        return escape(text).replace("\n", "<br/>")

    story = [Paragraph("CAMPUSPULSE / УЧЕБНЫЙ КОНСПЕКТ", styles["small"]),
             Paragraph(clean(note["title"]), styles["title"]), Paragraph(clean(note["method_note"]), styles["small"])]
    for section in note["sections"]:
        story.append(Paragraph(clean(section["title"]), styles["section"]))
        for paragraph in section["paragraphs"]:
            refs = " ".join(f"[{sid}]" for sid in paragraph["source_ids"])
            story.append(Paragraph(clean(paragraph["text"]) + " <font color='#17656C'>" + clean(refs) + "</font>", styles["body"]))
    if note["key_terms"]:
        story.append(Paragraph("Ключевые понятия", styles["section"]))
        for item in note["key_terms"]:
            story.append(Paragraph("<font name='" + bold + "'>" + clean(item["term"]) + "</font>: " + clean(item["definition"]) + " " + clean(" ".join(f"[{sid}]" for sid in item["source_ids"])), styles["body"]))
    story.append(Paragraph("Самопроверка", styles["section"]))
    for index, item in enumerate(note["questions"], 1):
        story.append(Paragraph(f"{index}. " + clean(item["question"]), styles["body"]))
        story.append(Paragraph("Ответ: " + clean(item["answer"]) + " " + clean(" ".join(f"[{sid}]" for sid in item["source_ids"])), styles["small"]))
    story.append(Paragraph("Источники и точные цитаты", styles["section"]))
    for source in note["sources"]:
        location = f"[{source['id']}] {source['file']}, стр. {source['page']}, строка {source.get('line', 1)}"
        story.append(Paragraph("<font name='" + bold + "'>" + clean(location) + "</font><br/>" + clean(source["quote"]), styles["source"]))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#DBE5EA"))
        canvas.line(44, 37, A4[0] - 44, 37)
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#667988"))
        canvas.drawString(44, 24, "CampusPulse - выжимка по загруженным источникам")
        canvas.drawRightString(A4[0] - 44, 24, str(document.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=44, leftMargin=44, topMargin=39, bottomMargin=51,
                            title=note["title"], author="CampusPulse AI")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def export_notebook(note: dict, format: str = "md") -> tuple[bytes, str]:
    if format == "pdf":
        return render_pdf(note), "application/pdf"
    renderers = {"md": (render_markdown, "text/markdown"), "txt": (render_text, "text/plain"), "html": (render_html, "text/html")}
    if format not in renderers:
        raise ValueError("Выберите PDF, Markdown, TXT или HTML")
    renderer, media_type = renderers[format]
    return renderer(note).encode("utf-8"), media_type + "; charset=utf-8"
