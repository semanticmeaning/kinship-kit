"""Язык интерфейса CLI: ru (основной) или en.

Выбор: --lang, затем KIN_LANG, затем language дела (case.json), иначе ru.
Переводятся подписи выводов status/next/audit, вопросы setup и итоговые сообщения команд (функция t —
только для подписей интерфейса, данные дела не переводятся и не изменяются).
Остальные сообщения об ошибках пока только на русском (docs/ACCEPTANCE.md, сценарий 10).
"""
from __future__ import annotations

import os

LANG = "ru"

# Подпись интерфейса по-русски → по-английски. Только точное совпадение в t(); к готовому выводу и данным дела
# словарь не применяется. Тест TestTranslations проверяет, что у каждой подписи из t() есть перевод.
PHRASES = {
    "СЛЕДУЮЩИЙ ШАГ": "NEXT STEP",
    "Дело": "Case",
    "Записей": "Records",
    "Аудит: ошибок": "Audit: errors",
    "предупреждений": "warnings",
    "Активные гипотезы": "Active hypotheses",
    "→ задачи": "→ tasks",
    "→ задач нет": "→ no tasks",
    "В работе": "In progress",
    "На ревью": "In review",
    "Заблокировано": "Blocked",
    "Готово к старту": "Ready",
    "Запланировано": "Planned",
    "Проверено без результата": "Checked with no result",
    "не повторять без нового основания": "do not repeat without a new basis",
    "повторить, если": "repeat when",
    "Ревью ждут": "Reviews pending",
    "нужно решение человека": "a human decision is needed",
    "Запросы в архивы": "Archive requests",
    "срок": "due",
    "ПРОСРОЧЕН": "OVERDUE",
    "Сведения семьи ждут решения": "Family reports awaiting a decision",
    "Нерешённые противоречия": "Unresolved contradictions",
    "Последние изменения": "Recent changes",
    "Начать": "Start",
    "Продолжить": "Continue",
    "Независимое ревью": "Independent review",
    "роль": "role",
    "оценка": "score",
    "ценность": "value",
    "приоритет": "priority",
    "активная гипотеза": "active hypothesis",
    "снимает противоречие": "resolves a contradiction",
    "стоимость": "cost",
    "доступ": "access",
    "попыток": "attempts",
    "уже начата": "already started",
    "ещё не готова": "not ready yet",
    "Исправить ошибки аудита": "Fix audit errors",
    "Очередь (оценка — ценность, приоритет, гипотеза, стоимость, доступ, попытки)":
        "Queue (score — value, priority, hypothesis, cost, access, attempts)",
    "Недоступно сейчас": "Not available now",
    "платно — нужно согласие пользователя": "paid — the user's consent is required",
    "передача сведений стороннему сервису — нужно согласие": "data goes to a third-party service — consent required",
    "исчерпан лимит попыток": "attempt limit reached",
    "нужен пересмотр задачи": "the task needs revision",
    "пользователь отказал": "the user declined",
    "Нет доступных задач: поставьте новую (kin task new …) или разберите гипотезы.":
        "No available tasks: create one (kin task new …) or work on hypotheses.",
    "Утверждения": "Claims",
    "Связи": "Relationships",
    "ОШИБКИ": "ERRORS",
    "ПРЕДУПРЕЖДЕНИЯ": "WARNINGS",
    "Ошибок и предупреждений нет.": "No errors or warnings.",
    "нет": "none",
    "добавлено": "added",
    "обновлено": "updated",
    "Ошибка": "Error",
    "Дело создано": "Case created",
    "Дальше": "Next",
    "Ничего не найдено": "Nothing found",
    "(пусто)": "(empty)",
}

SETUP = {
    "ru": {
        "intro": "Первый запуск kinship-kit. Ответьте на вопросы (Enter — значение в скобках).\n"
                 "Сведения сохраняются только у вас: в папке дела и в личном стоп-листе вне репозитория.",
        "surname": "1. Основная фамилия исследования (линия поиска)",
        "title": "2. Название дела",
        "title_default": "{surname} — родословная",
        "dir": "3. Папка дела (приватная, вне репозитория набора)",
        "author": "4. Автор коммитов в git-истории дела. Виден всем, кому вы дадите копию дела.\n   Можно псевдоним. ",
        "author_global": "Глобальные настройки git: {name} <{email}> — используются, только если вы их введёте.",
        "author_name": "   Имя автора",
        "author_email": "   E-mail автора",
        "lang": "5. Язык дела (ru/en)",
        "agents": "6. Роли агентов для (claude, codex, both, none)",
        "deny": "7. Добавить «{surname}» в личный стоп-лист ({path}), чтобы фамилия не попала в публичный репозиторий набора? (да/нет)",
        "yes": "да",
        "pseudonym": "Исследователь",
        "need": "  Нужен ответ.",
    },
    "en": {
        "intro": "First run of kinship-kit. Answer the questions (Enter — the value in brackets).\n"
                 "Everything stays with you: in the case folder and in a personal deny-list outside the repository.",
        "surname": "1. Main surname of the research (search line)",
        "title": "2. Case title",
        "title_default": "{surname} family history",
        "dir": "3. Case folder (private, outside the kit repository)",
        "author": "4. Commit author in the case's git history. Visible to anyone you give a copy of the case.\n   A pseudonym is fine. ",
        "author_global": "Global git settings: {name} <{email}> — used only if you type them.",
        "author_name": "   Author name",
        "author_email": "   Author e-mail",
        "lang": "5. Case language (ru/en)",
        "agents": "6. Agent roles for (claude, codex, both, none)",
        "deny": "7. Add “{surname}” to your personal deny-list ({path}) so it never reaches the public kit repository? (yes/no)",
        "yes": "yes",
        "pseudonym": "Researcher",
        "need": "  An answer is required.",
    },
}

def set_lang(lang: str | None) -> None:
    global LANG
    LANG = "en" if (lang or "").lower().startswith("en") else "ru"


def init(cli_lang: str | None, case_lang: str | None = None) -> None:
    set_lang(cli_lang or os.environ.get("KIN_LANG") or case_lang or "ru")


def t(phrase: str) -> str:
    """Перевод подписи интерфейса (точное совпадение). Данные дела сюда не передаются."""
    return PHRASES.get(phrase, phrase) if LANG == "en" else phrase


def setup_text(key: str, **kw) -> str:
    return SETUP[LANG][key].format(**kw)
