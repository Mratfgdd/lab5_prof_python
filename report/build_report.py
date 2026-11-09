import argparse
import ast
import csv
import html
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "report"
PDF_PATH = ROOT / "Звіт_ЛР5_Левандівський.pdf"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
PROMPT = r"PS C:\Github\prof_python\Lab_05>"

sys.path.insert(0, str(ROOT / "src"))

ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(ROOT / "src")}

EXCEPTION_TREE = """ApplicationError
├── ConfigurationError
└── DataError
    ├── DataImportError
    │   └── UnsupportedFormatError
    ├── RecordValidationError
    └── DataExportError"""


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def code(source: str, keep: bool | None = None) -> str:
    text = source.strip("\n")
    if keep is None:
        keep = text.count("\n") < 16
    return f'<pre class="code{" keep" if keep else ""}">{esc(text)}</pre>'


def strip_docstrings(source: str) -> str:
    source = textwrap.dedent(source)
    tree = ast.parse(source)
    drop: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.ClassDef) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                if isinstance(first.value.value, str) and first.end_lineno is not None:
                    drop.update(range(first.lineno, first.end_lineno + 1))
    kept = [line for n, line in enumerate(source.splitlines(), 1) if n not in drop]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip("\n")


def src(*objects: object, keep: bool | None = None) -> str:
    return code("\n\n".join(strip_docstrings(inspect.getsource(o)) for o in objects), keep)


def terminal(command: str, output: str) -> str:
    return (
        f'<div class="term"><span class="ps">{esc(PROMPT)}</span> {esc(command)}\n'
        f"{esc(output.rstrip())}</div>"
    )


def table(headers: list[str], rows: list[list[str]], cls: str = "") -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def num(value: float, digits: int) -> str:
    return f"{value:,.{digits}f}".replace(",", " ")


def plural(number: int, one: str, few: str, many: str) -> str:
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


def speed_word(ratio: float) -> str:
    if ratio < 0.95:
        return "швидший"
    if ratio > 1.05:
        return "повільніший"
    return "практично однаковий за часом"


def short(text: str) -> str:
    return text.replace(str(ROOT) + "\\", "").replace(str(ROOT), ".")


def run_python(venv: Path, *args: str, cwd: Path = ROOT, env: dict[str, str] | None = None):
    return subprocess.run(
        [str(venv / "Scripts" / "python.exe"), *args],
        cwd=cwd,
        env=ENV | (env or {}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def chaining_demo(venv: Path) -> str:
    done = run_python(venv, "experiments/chaining_demo.py")
    assert done.returncode == 1 and "direct cause" in done.stderr, done.stderr
    return short(done.stderr)


def keep_numbers_together(markup: str) -> str:
    pieces = re.split(r"(<pre.*?</pre>|<div class=\"term\">.*?</div>)", markup, flags=re.S)
    return "".join(
        piece
        if piece.startswith(("<pre", '<div class="term"'))
        else re.sub(r"(?<=\d) (?=\d{3}\b)", "\u00a0", piece)
        for piece in pieces
    )


class Numbering:
    def __init__(self) -> None:
        self.table = 0
        self.figure = 0

    def tcap(self, text: str) -> str:
        self.table += 1
        return f'<p class="tcap">Таблиця {self.table} – {text}</p>'

    def fcap(self, text: str) -> str:
        self.figure += 1
        return f'<p class="fcap">Рисунок {self.figure} – {text}</p>'


def run_demo(venv: Path) -> dict[str, str]:
    work = Path(tempfile.mkdtemp(prefix="lab5_demo_"))
    try:
        shutil.copy2(ROOT / "config.yaml", work / "config.yaml")
        shutil.copytree(ROOT / "data", work / "data", ignore=shutil.ignore_patterns("generated"))
        base = {key: value for key, value in ENV.items() if not key.startswith("STUDENTIO_")}
        first = subprocess.run(
            [str(venv / "Scripts" / "python.exe"), "-m", "reliable_importer.main"],
            cwd=work,
            env=base,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert first.returncode == 0, first.stderr
        strict = subprocess.run(
            [str(venv / "Scripts" / "python.exe"), "-m", "reliable_importer.main"],
            cwd=work,
            env=base | {"STUDENTIO_SKIP_INVALID": "false"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert strict.returncode == 1, strict.stderr
        log = (work / "logs" / "application.log").read_text(encoding="utf-8")
        personal = ("Шевченко", "Бойко", "Гриценко", "Ткаченко", "Петренко", "Кравець", "Лисак")
        for value in (*personal, "Анна", "Коваль", "wrong", "105"):
            assert value not in log, value
        output = (work / "output" / "students.json").read_text(encoding="utf-8")
        return {
            "tolerant": first.stderr,
            "strict": strict.stderr,
            "errors_csv": (work / "output" / "errors.csv").read_text(encoding="utf-8"),
            "json_head": "\n".join(output.splitlines()[:3]) + "\n  ...",
            "summary": json.dumps(
                json.loads((work / "output" / "summary.json").read_text(encoding="utf-8")),
                ensure_ascii=False,
            ),
            "exported": str(len(json.loads(output))),
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def checks(venv: Path) -> list[tuple[str, str]]:
    scripts = venv / "Scripts"
    commands = [
        (
            "python -m unittest discover -s tests",
            [str(scripts / "python.exe"), "-m", "unittest", "discover", "-s", "tests"],
        ),
        (
            "mypy  (strict, src + tests)",
            [str(scripts / "mypy.exe"), "--no-incremental", "--cache-dir=nul"],
        ),
        (
            "ruff check src tests",
            [str(scripts / "ruff.exe"), "check", "--no-cache", "src", "tests"],
        ),
    ]
    results = []
    for title, command in commands:
        done = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            env=ENV,
        )
        assert done.returncode == 0, done.stdout + done.stderr
        text = (done.stdout + done.stderr).strip().splitlines()
        ran = [ln for ln in text if ln.startswith("Ran ")]
        results.append((title, f"{ran[0]} — OK" if ran else text[-1]))
    return results


CSS = """
@page { size: A4; margin: 20mm 15mm 20mm 30mm;
  @bottom-center { content: counter(page); font: 12pt "Times New Roman", serif; } }
@page :first { @bottom-center { content: none; } }
html { background: #fff; }
body { margin: 0; color: #000; background: #fff; font-family: "Times New Roman", serif;
  font-size: 14pt; line-height: 1.2; }
p { margin: 0 0 2pt; text-indent: 1.25cm; text-align: justify; }
h1 { font-size: 14pt; text-align: center; margin: 9pt 0 4pt; break-after: avoid; }
code { font-family: Consolas, "Courier New", monospace; font-size: 0.8em; }
pre.code { font-family: Consolas, "Courier New", monospace; font-size: 8pt;
  line-height: 1.12; margin: 2pt 0 5pt; padding: 3pt 8pt; white-space: pre-wrap;
  background: #f6f6f4; border-left: 3px solid #c3c2b7; orphans: 4; widows: 4; }
pre.keep { break-inside: avoid; }
.term { font-family: Consolas, "Courier New", monospace; font-size: 7.4pt; line-height: 1.15;
  white-space: pre-wrap; background: #0c0c0c; color: #d4d4d4; padding: 4pt 8pt;
  border-radius: 4px; margin: 2pt 0 3pt; orphans: 4; widows: 4; }
.term .ps { color: #f9f1a5; }
table { width: 100%; border-collapse: collapse; font-size: 10.5pt; line-height: 1.13;
  margin: 2pt 0 5pt; }
th, td { border: 1px solid #000; padding: 1.5pt 4pt; vertical-align: top; text-align: left; }
th { background: #f0efec; }
table.num td { text-align: right; white-space: nowrap; }
table.num td:first-child { text-align: left; }
tr { break-inside: avoid; }
.tcap { text-indent: 0; text-align: left; margin: 4pt 0 2pt; break-after: avoid; }
.fcap { text-indent: 0; text-align: center; margin: 1pt 0 5pt; }
.title { height: 255mm; display: flex; flex-direction: column; justify-content: space-between;
  text-align: center; break-after: page; line-height: 1.5; }
.title .main { margin-top: 30mm; }
.title .main .big { font-size: 20pt; font-weight: bold; letter-spacing: 2pt; }
.title .main .theme { font-size: 16pt; font-weight: bold; margin-top: 10pt; }
.title .sign { align-self: flex-end; text-align: left; width: 85mm; margin-top: 30mm; }
.title .city { margin-top: auto; }
"""


def build_html(venv: Path) -> str:
    from reliable_importer import (
        config,
        exceptions,
        exporters,
        logging_config,
        readers,
        services,
        utils,
        validators,
    )

    n = Numbering()
    demo = run_demo(venv)
    test_results = checks(venv)
    experiments = json.loads((ROOT / "results" / "experiments.json").read_text(encoding="utf-8"))
    with (ROOT / "results" / "streaming.csv").open(encoding="utf-8") as file:
        streaming = [{k: float(v) for k, v in row.items()} for row in csv.DictReader(file)]
    st = experiments["strict_vs_tolerant"]
    atomic = experiments["atomic_output"]
    csv_lines = (ROOT / "data" / "students.csv").read_text(encoding="utf-8").splitlines()
    summary = json.loads(demo["summary"])
    assert (summary["total"], summary["valid"], summary["invalid"]) == (20, 13, 7)
    assert (summary["below_minimum"], summary["exported"]) == (2, 11)
    assert demo["exported"] == "11" and len(csv_lines) == 21
    total_tests = int(re.search(r"Ran (\d+) tests?", test_results[0][1]).group(1))

    chaining = chaining_demo(venv)
    checker = validators.RecordValidator(
        config.ProcessingConfig(False, Decimal(60), re.compile(r"PI-\d{2}"), 1000)
    )
    try:
        checker.validate(2, {"student_id": "abc"})
    except exceptions.RecordValidationError as error:
        assert isinstance(error.__cause__, ValueError)
    else:
        raise AssertionError("очікувалась помилка")

    parts: list[str] = []
    add = parts.append
    add("""
<section class="title">
  <div>МІНІСТЕРСТВО ОСВІТИ І НАУКИ УКРАЇНИ<br>
  Львівський національний університет імені Івана Франка</div>
  <div class="main">
    <div class="big">ЗВІТ</div>
    <div>до лабораторної роботи №5</div>
    <div>з дисципліни «Професійний Python»</div>
    <div class="theme">Тема: «Обробка помилок, файли та серіалізація»</div>
  </div>
  <div class="sign">Виконав:<br>студент Левандівський Назар<br><br>
  Перевірив:<br>Куньо Іван Михайлович</div>
  <div class="city">Львів – 2026</div>
</section>""")

    add("<h1>Мета роботи</h1>")
    add(
        "<p>Навчитися створювати надійні програми, що передбачувано поводяться з помилками, "
        "файлами, конфігурацією та структурованими форматами: власна ієрархія винятків, "
        "exception chaining, context managers, logging, pathlib, CSV/JSON/YAML, streaming I/O, "
        "атомарний запис і валідація зовнішніх даних.</p>"
    )

    add("<h1>1. Постановка задачі</h1>")
    add(
        "<p><b>Варіант 1. Імпорт та експорт даних системи обліку студентів</b> (продовження "
        "ЛР1–ЛР4). Поля: <code>student_id, first_name, last_name, group, average_grade</code>. "
        "Перевіряти ID, ПІБ і групу, <code>average_grade</code> у межах 0–100. Реалізувати "
        "CSV streaming import, strict/tolerant mode, JSON export, YAML configuration з "
        "мінімальним середнім балом, статистику valid/invalid і logging некоректних "
        "записів.</p>"
    )
    add(n.tcap("Схема вхідних даних і правила перевірки"))
    add(
        table(
            ["Поле", "Тип", "Правило", "Код помилки"],
            [
                ["student_id", "int", "ціле число ≥ 1", "bad_id, missing_field"],
                [
                    "first_name, last_name",
                    "str",
                    "непорожні; літери, дефіс, апостроф, пробіл",
                    "missing_field, bad_name",
                ],
                [
                    "group",
                    "str",
                    "відповідає <code>group_pattern</code> із config (PI-21)",
                    "bad_group",
                ],
                [
                    "average_grade",
                    "Decimal",
                    "число від 0 до 100, округлення до сотих",
                    "bad_number, grade_out_of_range",
                ],
            ],
        )
    )
    add(
        "<p>Приклад <code>data/students.csv</code>: 20 записів, із них 7 некоректних і 2 "
        "коректні, але нижчі за мінімальний бал 60 (перші 9 рядків):</p>"
    )
    add(code("\n".join(csv_lines[:9])))

    add("<h1>2. Структура проєкту та ієрархія винятків</h1>")
    add(
        code(
            "Lab_05/  config.yaml, pyproject.toml, README.md\n"
            "├── data/          students.csv | .jsonl | .yaml\n"
            "├── output/  logs/ (створюються програмою)\n"
            "├── src/reliable_importer/  exceptions, config, logging_config, readers,\n"
            "│                           validators, exporters, services, utils, models, main\n"
            f"├── tests/         {total_tests} тестів (unittest)\n"
            "└── experiments/   run_experiments.py -> results/",
            keep=True,
        )
    )
    add(
        "<p>Усі очікувані помилки успадковують <code>ApplicationError</code>, тому "
        "<code>main()</code> відрізняє їх від непередбачених (код 1 проти 2). "
        "<code>RecordValidationError</code> несе номер рядка, поле й код, але не значення "
        "полів: повідомлення безпечно писати в log.</p>"
    )
    add(code(EXCEPTION_TREE, keep=True))
    add(src(exceptions.RecordValidationError, keep=True))
    add(
        "<p><b>Exception chaining.</b> Технічна помилка розбору числа перетворюється на "
        "доменну через <code>raise ... from error</code>, і оригінальна причина зберігається в "
        "<code>__cause__</code>. Для оцінки <code>wrong</code> причиною є "
        "<code>decimal.InvalidOperation</code>, для ідентифікатора <code>abc</code> – "
        "<code>ValueError</code> (обидва випадки перевіряють тести). Traceback експерименту 3 "
        "показує обидві ланки:</p>"
    )
    add(src(validators.RecordValidator._grade))
    add(terminal("python experiments/chaining_demo.py", chaining))

    add("<h1>3. Конфігурація</h1>")
    add(code((ROOT / "config.yaml").read_text(encoding="utf-8")))
    add(
        "<p><code>load_config</code> читає YAML через <code>safe_load</code>, застосовує "
        "змінні середовища (<code>STUDENTIO_SKIP_INVALID</code>, "
        "<code>STUDENTIO_MINIMUM_GRADE</code> тощо), будує frozen dataclass і перетворює всі "
        "технічні помилки на <code>ConfigurationError</code> із chaining. "
        "<code>validate_config</code> (fail-fast) перевіряє версію схеми, "
        "<code>minimum_grade</code> у межах 0–100, формати, рівень логування, наявність "
        "вхідного файла й те, що вхід і вихід не збігаються. Параметр "
        "<code>minimum_grade</code> керує експортом: студенти з нижчим балом вважаються "
        "коректними, але до JSON не потрапляють.</p>"
    )
    add(src(config.load_config))

    add("<h1>4. Logging</h1>")
    add(
        "<p>Лог пишеться у файл із ротацією (<code>RotatingFileHandler</code>) і в консоль. "
        "Повідомлення про некоректні записи містять лише номер рядка, поле, причину й код "
        "помилки, але не значення полів: імена студентів у log не потрапляють (це перевірено "
        "на справжньому файлі log під час генерації звіту й тестом). Приклад log – у розділі "
        "7.</p>"
    )
    add(src(logging_config.configure_logging, utils.logged_operation))

    add("<h1>5. Streaming reader, validation, strict / tolerant</h1>")
    add(
        "<p>Єдиний інтерфейс <code>Importer</code> (Protocol) має реалізації для CSV, JSON "
        "Lines (потокові), JSON і YAML (читаються цілком); формат обирається за розширенням. "
        "CSV читається рядок за рядком, а технічні помилки файлової системи, кодування та "
        "синтаксису перетворюються на <code>DataImportError</code>:</p>"
    )
    add(src(readers.CsvImporter.read))
    add("<p>Валідатор перевіряє поля у фіксованому порядку, правила беруться з конфігурації:</p>")
    add(src(validators.RecordValidator.validate, validators.RecordValidator._student_id))
    add(
        "<p>Поведінку з некоректним записом визначає об'єкт-політика: strict піднімає "
        "виняток (fail-fast), tolerant пише warning у log і рядок в <code>errors.csv</code>. "
        "Генератори <code>import_records</code> і <code>filter_by_grade</code> ведуть "
        "статистику й віддають записи по одному:</p>"
    )
    add(
        src(
            services.StrictPolicy,
            services.TolerantPolicy,
            services.import_records,
            services.filter_by_grade,
        )
    )

    add("<h1>6. JSON serialization, atomic export, context managers</h1>")
    add(
        "<p><code>JsonExporter</code> пише JSON-масив потоково, а Decimal серіалізується "
        "числом (custom encoder): оцінка має не більше двох знаків, тому <code>float</code> її "
        "не спотворює. <code>AtomicWriter</code> – власний class-based context manager: дані "
        "пишуться у тимчасовий файл у тому ж каталозі; лише після успішного блоку with "
        "виконуються <code>fsync</code>, резервна копія <code>.bak</code> і атомарний "
        "<code>os.replace</code> (з <code>retry</code> на випадок тимчасового блокування "
        "файла у Windows); при винятку тимчасовий файл видаляється. Generator-based "
        "<code>logged_operation</code> журналює тривалість операції.</p>"
    )
    add(src(exporters.DecimalJSONEncoder, exporters.JsonExporter))
    add(src(exporters.AtomicWriter.__exit__))
    add(
        "<p>У <code>run_import_export</code> писачі й генератори реєструються в "
        "<code>ExitStack</code>, причому генератори – через <code>contextlib.closing</code>: "
        "при зупинці strict-режиму посередині файла вхідний CSV закривається одразу, а не "
        "після збирання сміття (у Windows відкритий файл не можна видалити; це перевіряє тест "
        "<code>test_strict_abort_releases_input_file</code>).</p>"
    )

    add("<h1>7. Виконання програми</h1>")
    add(terminal("python -m reliable_importer.main", demo["tolerant"]))
    add(n.fcap("Tolerant mode: 20 записів, 11 експортовано, 7 некоректних, 2 нижче мінімуму"))
    add(
        terminal(
            '$env:STUDENTIO_SKIP_INVALID = "false"; python -m reliable_importer.main',
            demo["strict"],
        )
    )
    add(
        n.fcap(
            "Strict mode через змінну середовища: зупинка на рядку 5, вихідні файли не змінено, "
            "exit code 1"
        )
    )
    add(
        "<p>Ті самі рядки записано у <code>logs/application.log</code>. Нижче – "
        "<code>output/errors.csv</code>, початок <code>output/students.json</code> і "
        "<code>summary.json</code> після tolerant-запуску:</p>"
    )
    add(code(demo["errors_csv"]))
    add(code(demo["json_head"] + "\n\n" + demo["summary"], keep=True))

    add("<h1>8. Експерименти</h1>")
    add(n.tcap("Експеримент 1: 1000 валідних + 10 некоректних записів"))
    s, t = st["strict"], st["tolerant"]
    add(
        table(
            ["Параметр", "Strict", "Tolerant"],
            [
                ["Оброблено записів", str(s["total"]), str(t["total"])],
                ["Valid", str(s["valid"]), str(t["valid"])],
                ["Invalid", str(s["invalid"]), str(t["invalid"])],
                ["Exported", str(s["exported"]), str(t["exported"])],
                [
                    "Завершення application",
                    f"exit {s['exit_code']}: {esc(s['outcome'])}; output не створено",
                    f"exit {t['exit_code']}: успішно",
                ],
            ],
        )
    )
    assert not s["output_exists"] and t["output_exists"] and t["exported"] == 1000
    add(
        "<p>Strict доцільний там, де частковий імпорт неприпустимий (наприклад, нарахування за "
        "оцінками): краще не імпортувати нічого, ніж половину. Tolerant – для масових даних, де "
        "некоректні рядки виправляють окремо за <code>errors.csv</code>.</p>"
    )
    mb = 1024 * 1024
    add(
        n.tcap(
            "Експеримент 2: streaming vs eager (час – найкращий із 3 почергових запусків, "
            "пам'ять – пік tracemalloc)"
        )
    )
    add(
        table(
            [
                "Records",
                "Eager time, с",
                "Streaming time, с",
                "Streaming / eager",
                "Eager peak RAM, МБ",
                "Streaming peak RAM, МБ",
            ],
            [
                [
                    num(r["records"], 0),
                    num(r["eager_time"], 3),
                    num(r["streaming_time"], 3),
                    num(r["streaming_time"] / r["eager_time"], 2),
                    num(r["eager_peak"] / mb, 1),
                    num(r["streaming_peak"] / mb, 2),
                ]
                for r in streaming
            ],
            cls="num",
        )
    )
    big, small = streaming[-1], streaming[0]
    ratio = big["eager_peak"] / big["streaming_peak"]
    time_ratio = big["streaming_time"] / big["eager_time"]
    small_ratio = small["streaming_time"] / small["eager_time"]
    assert big["streaming_peak"] < 2 * mb and ratio > 20
    add(
        f"<p>Пам'ять eager росте лінійно ({num(small['eager_peak'] / mb, 1)} → "
        f"{num(big['eager_peak'] / mb, 1)} МБ), streaming залишається "
        f"≈{num(big['streaming_peak'] / mb, 2)} МБ – у {num(ratio, 0)} "
        f"{plural(round(ratio), 'раз', 'рази', 'разів')} менше на "
        f"{num(big['records'], 0)} записів. За часом на {num(small['records'], 0)} записів "
        f"streaming {speed_word(small_ratio)} (streaming/eager = {num(small_ratio, 2)}), на "
        f"{num(big['records'], 0)} записів – {speed_word(time_ratio)} "
        f"(streaming/eager = {num(time_ratio, 2)}): парсинг, перевірка й серіалізація в обох "
        "варіантах однакові, тому виграш у часі не гарантований, а в пам'яті – гарантований. "
        "Заміри часу робилися почергово (A, B, A, B), щоб зміна частоти процесора впливала на "
        "обидва варіанти однаково.</p>"
    )
    add(
        f"<p><b>Експеримент 4 (atomic output).</b> Після успішного експорту запущено експорт "
        f"із exporter, що падає з <code>OSError</code> на 6-му записі. Результат: "
        f"<code>{esc(atomic['error'])}</code>; попередній файл "
        f"{'не змінено (SHA-256 збігається)' if atomic['output_unchanged'] else 'ЗМІНЕНО'}; "
        f"тимчасових файлів: {len(atomic['tmp_files'])}; у log – "
        f"«{esc(atomic['log'][0].split(': ', 1)[1])}». <code>DataExportError</code> – "
        "нащадок <code>ApplicationError</code>, тому <code>main()</code> перехоплює його й "
        "повертає код 1.</p>"
    )
    assert atomic["output_unchanged"] and not atomic["tmp_files"]
    add(n.tcap("Експеримент 5: помилки конфігурації"))
    add(
        table(
            ["Випадок", "Exit", "Повідомлення в log"],
            [
                [esc(c["case"]), str(c["exit_code"]), esc(c["message"])]
                for c in experiments["configuration_errors"]
            ],
        )
    )

    add("<h1>9. Перевірка правильності</h1>")
    add(
        f"<p>{total_tests} тестів перевіряють завантаження й семантичну перевірку конфігурації "
        "(13 некоректних випадків, змінні середовища, межі minimum_grade), кожен код "
        "помилки валідатора та граничні значення, chaining, відсутність значень у "
        "повідомленнях, усі формати й зламані файли, strict/tolerant, фільтр за мінімальним "
        "балом, атомарність, backup, retry, відсутність імен у log і коди завершення "
        "<code>main</code>.</p>"
    )
    add(
        table(
            ["Перевірка", "Результат"],
            [[f"<code>{esc(t)}</code>", esc(r)] for t, r in test_results],
        )
    )

    add("<h1>Висновки</h1>")
    add(
        "<p>Створено надійний модуль імпорту/експорту студентів: дані перевіряються на межі "
        "системи, кожна очікувана помилка має свій тип і код, причина зберігається через "
        "chaining, ресурси звільняють context managers, а атомарний запис, як показав "
        "експеримент, не пошкоджує попередній output. Поведінка (strict/tolerant, мінімальний "
        "бал, формати) змінюється через YAML або змінні середовища без редагування коду, log "
        "не містить персональних даних, а streaming тримає пам'ять сталою незалежно від "
        "розміру файла.</p>"
    )

    body = keep_numbers_together("\n".join(parts))
    return (
        "<!doctype html><html lang='uk'><head><meta charset='utf-8'>"
        f"<title>Звіт ЛР5</title><style>{CSS}</style></head><body>{body}</body></html>"
    )


def print_pdf(html_path: Path, pdf_path: Path, profile: Path) -> None:
    args = [
        str(EDGE),
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--print-to-pdf-no-header",
        f"--user-data-dir={profile}",
        f"--print-to-pdf={pdf_path}",
        html_path.as_uri(),
    ]
    subprocess.run(args, check=True, capture_output=True, timeout=120)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--venv", type=Path, required=True)
    parser.add_argument(
        "--profile", type=Path, default=Path(tempfile.gettempdir()) / "lab5_report_edge_profile"
    )
    args = parser.parse_args()
    html_path = REPORT_DIR / "report.html"
    html_path.write_text(build_html(args.venv), encoding="utf-8")
    if PDF_PATH.exists():
        PDF_PATH.unlink()
    print_pdf(html_path, PDF_PATH, args.profile)

    import pymupdf

    with pymupdf.open(PDF_PATH) as document:
        print(f"PDF: {PDF_PATH} — {document.page_count} сторінок")


if __name__ == "__main__":
    main()
