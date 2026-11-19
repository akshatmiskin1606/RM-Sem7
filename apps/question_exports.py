"""Render downloadable quizzes from KAQG's saved assessments."""

import csv
from html import escape
import io
from pathlib import Path


CONTENT_TYPES = {
    'json': 'application/json',
    'csv': 'text/csv; charset=utf-8',
    'pdf': 'application/pdf',
}
LETTERS = 'ABCD'
PDF_CSS = """
body { font-family: sans-serif; font-size: 11pt; line-height: 1.35; color: #202b26; margin: 0; overflow-wrap: break-word; }
h1 { font-size: 25pt; color: #204c3b; margin: 0 0 6pt; }
.source { color: #58655c; font-size: 10pt; margin: 0 0 19pt; }
.question { margin: 0 0 12pt; }
.stem { font-weight: bold; margin: 0 0 4pt; }
.option { margin: 0 0 2pt 17pt; }
h2 { color: #204c3b; font-size: 16pt; margin: 14pt 0 7pt; page-break-after: avoid; }
.answer { margin: 0 0 4pt; }
"""


def _quiz_rows(result):
    for number, assessment in enumerate(result['assessments'], 1):
        question = assessment['question']
        options = {letter: str(question.get(f'option_{letter}') or '') for letter in LETTERS}
        answer = str(question.get('answer') or '').upper()
        yield number, str(question['stem']), options, answer, options.get(answer, '')


def _spreadsheet_text(value):
    # Question text comes from arbitrary PDFs. Keep spreadsheet apps from evaluating it as a formula.
    if value.startswith(('\t', '\r', '\n')) or value.lstrip().startswith(('=', '+', '-', '@', '＝', '＋', '－', '＠')):
        return "'" + value
    return value


def questions_csv(result):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(('Number', 'Question', 'Option A', 'Option B', 'Option C', 'Option D', 'Correct option', 'Correct answer'))
    for number, stem, options, answer, answer_text in _quiz_rows(result):
        writer.writerow((number, *map(_spreadsheet_text, (stem, *options.values(), answer, answer_text))))
    return output.getvalue().encode('utf-8-sig')


def _pdf_text(value):
    return escape(value).replace('\r\n', '\n').replace('\r', '\n').replace('\n', '<br>')


def questions_pdf(result, candidate_set=False):
    import pymupdf

    title = 'Candidate Set' if candidate_set else 'Final Set'
    source = Path(result.get('pdf') or 'KAQG').stem.replace('_', ' ')
    difficulty = result.get('difficulty')
    if difficulty in ('easy', 'medium', 'hard'):
        source += f' · {difficulty.title()}'
    questions = [f'<h1>{title}</h1><p class="source">{_pdf_text(source)}</p>']
    answers = ['<h2>Answer key</h2>']
    for number, stem, options, answer, answer_text in _quiz_rows(result):
        choices = ''.join(f'<p class="option">{letter}. {_pdf_text(option)}</p>' for letter, option in options.items())
        questions.append(f'<div class="question"><p class="stem">{number}. {_pdf_text(stem)}</p>{choices}</div>')
        answers.append(f'<p class="answer">{number}. <b>{_pdf_text(answer)}</b> — {_pdf_text(answer_text)}</p>')

    paper = pymupdf.paper_rect('a4')
    content = paper + (46, 47, -46, -47)
    buffer = io.BytesIO()
    with pymupdf.DocumentWriter(buffer, options='compress') as writer:
        device = writer.begin_page(paper)
        remaining = pymupdf.Rect(content)
        for section in [*questions, ''.join(answers)]:
            story = pymupdf.Story(section, user_css=PDF_CSS)
            more, filled = story.place(remaining)
            # Give each question a fresh page when it cannot fit beneath the previous one.
            if more and remaining.y0 > content.y0:
                writer.end_page()
                device = writer.begin_page(paper)
                more, filled = story.place(content)
            story.draw(device)
            while more:
                writer.end_page()
                device = writer.begin_page(paper)
                more, filled = story.place(content)
                story.draw(device)
            remaining.y0 = filled[3]
        writer.end_page()
    return buffer.getvalue()
