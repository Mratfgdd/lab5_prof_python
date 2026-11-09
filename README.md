# Reliable Student Importer

Лабораторна робота №5 з дисципліни «Професійний Python»:
«Обробка помилок, файли та серіалізація».
Варіант 1: імпорт та експорт даних системи обліку студентів (продовження ЛР1-ЛР4).

## Опис

Надійний модуль імпорту/експорту студентів. Поля: `student_id`, `first_name`, `last_name`,
`group`, `average_grade`.

- CSV streaming import; додатково JSON, JSON Lines і YAML через єдиний інтерфейс `Importer`
  (формат за розширенням файла);
- перевірка ID, ПІБ, коду групи та `average_grade` у межах 0-100, кожна причина відхилення має
  власний код;
- strict (fail-fast) і tolerant (пропуск + error CSV) режими, `skip_invalid` у YAML;
- мінімальний середній бал у YAML: студенти нижче порогу не експортуються;
- JSON і JSON Lines export, атомарний запис (тимчасовий файл + `os.replace`), резервна копія;
- статистика valid/invalid, помилки за кодами, експорт за групами, `summary.json`;
- власна ієрархія винятків, exception chaining, context managers, logging із ротацією;
- змінні середовища `STUDENTIO_*` перевизначають параметри конфігурації.

## Requirements

Python 3.11+, PyYAML. Для перевірок: `pip install -e ".[dev]"` (mypy, ruff).

## Installation

```
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
```

## Run

```
python -m reliable_importer.main --config config.yaml
python experiments/run_experiments.py
```

або console command `student-import`. Результати: `output/students.json`, `output/errors.csv`,
`output/summary.json`, журнал `logs/application.log`. Strict режим:
`$env:STUDENTIO_SKIP_INVALID = "false"`. Коди завершення: 0 - успіх, 1 - очікувана помилка
(конфігурація, дані, експорт), 2 - непередбачена помилка.

## Tests

```
python -m unittest discover -s tests -v
mypy
ruff check src tests
```

## Project structure

```
config.yaml                         конфігурація (YAML)
data/students.csv                   приклад: 20 записів, 7 некоректних, 2 нижче мінімуму
data/students.jsonl, students.yaml  ті самі поля в інших форматах
src/reliable_importer/exceptions.py ієрархія винятків
src/reliable_importer/config.py     завантаження та перевірка конфігурації
src/reliable_importer/readers.py    Importer (CSV, JSON Lines, JSON, YAML)
src/reliable_importer/validators.py перевірка записів
src/reliable_importer/services.py   політики strict/tolerant, фільтр, конвеєр
src/reliable_importer/exporters.py  JSON, JSON Lines, AtomicWriter, error CSV
src/reliable_importer/logging_config.py, utils.py, models.py, main.py
experiments/                        п'ять експериментів, results/
tests/                              unittest
```

## Author

Student: Левандівський Назар
