---
name: kinship-kit
description: Генеалогическое исследование (бывший СССР, Российская империя) с приватной папкой дела и CLI kin — источники, утверждения, гипотезы, задачи, отрицательные поиски, аудит, сайт-схема рода. Для поиска предков и продолжения дела; не для слежки за живыми. EN — evidence-first genealogy case manager.
license: MIT (основано на ex-ussr-kinship-research © 2026 Denis Shiryaev)
compatibility: Python 3.10+ (только стандартная библиотека), shell. Claude Code, Codex и другие клиенты с поддержкой Agent Skills.
metadata:
  version: "0.3.1"
  language: "ru"
  reply_language: "user"
---

# Назначение

Вести генеалогическое исследование как управляемый процесс: каждый документ сохранён с происхождением,
каждый вывод прослеживается до источников, отрицательные результаты не теряются, состояние дела
восстанавливается из данных, а не из памяти чата.

Отвечать на языке пользователя. Поисковые запросы — на языке источника.
English: `references/guide.en.md` (методика и команды на английском; интерфейс — `kin --lang en`).

# Инструмент: `kin`

Вся работа с делом — через CLI этого навыка (только стандартная библиотека Python):

```bash
python3 <папка этого навыка>/kin.py <команда>      # далее для краткости: kin <команда>
```

Дело — **отдельная приватная папка** вне навыка и вне любого публичного репозитория, например `~/kinship-cases/<фамилия>`.
Команды находят дело по `--case DIR`, переменной `KIN_CASE` или по `case.json` в текущей папке и выше.

# Обновления набора

Один раз за сеанс (в начале, вместе с `kin status`) выполнить `kin upgrade check`. Если вышла новая версия — сообщить
пользователю, что в ней нового (вывод команды), и спросить: «Вышла новая версия kinship-kit X. Обновить?».
Только после согласия: `kin upgrade apply`, затем в деле `kin migrate --dry-run` и, если схема изменилась, `kin migrate`.
Нет ответа или отказ — продолжать работу на текущей версии, не предлагая снова в этом сеансе. Нет сети — не блокирует работу.

# Первый запуск (новый пользователь)

Если у пользователя ещё нет дела (`kin status` не находит `case.json`), **сначала одним сообщением спросить**:
1. основную фамилию исследования (линия поиска);
2. как назвать дело (и где хранить папку — по умолчанию `~/kinship-cases/<фамилия латиницей>`);
3. автора коммитов в истории дела — имя и e-mail или псевдоним («Исследователь»). **Не брать** имя и e-mail из
   глобальных настроек git без явного согласия: история дела видна всем, кому её передадут;
4. для каких клиентов разложить роли агентов (Claude Code, Codex, оба).

Затем: `kin setup --yes --surname "…" --title "…" [--dir …] --author-name "…" --author-email "…" --agents both`
(или `--anonymous-author`). Человек в терминале может просто запустить `kin setup` — он задаст те же вопросы.
`setup` создаёт дело с git-историей от выбранного автора, линию поиска, роли агентов и добавляет фамилию в личный
стоп-лист вне репозитория (защита публичного набора от случайной утечки).

| Задача | Команда |
|---|---|
| Новое дело | `kin setup` (вопросы) или `kin init ~/kinship-cases/<имя> --title "…"` |
| **Начало каждого сеанса** | `kin status` → `kin next` → `kin audit` |
| Поля и словари реестров | `kin schema [persons]` |
| Документ, скан, страница сайта | `kin source add <файл> --title … --kind … --repository … --ref "ф. …, оп. …, д. …, л. …" --group <группа независимости> --provenance "…"` (или `--url` без файла) |
| Человек так, как записан в источнике | `kin mention add --artifact A-… --name "…как написано…" --role child [--person P-… --link-status probable --rationale …]` |
| Личность | `kin person add --label "Фамилия Имя Отчество" --living deceased --status candidate` |
| Утверждение (факт из источников) | `kin claim add --type birth --subject P-… --statement "…" --date 1885-03-02 --sources A-… --status single-source` |
| Связь (родство названо в источнике) | `kin rel add P-A parent-of P-B --claims C-… --status single-source` |
| Гипотеза, место | `kin add hypotheses|places --set поле=значение …` |
| Задача по шаблону | `kin task new metric-books|archive-catalog|online-database|library|archive-request|family-interview --goal "…" [--hypothesis H-…] [--value 1-5] [--cost free|paid] [--access online|request|onsite]` → `tasks/T-….md` |
| Ход задачи | `kin task start|block|review|done|close T-… [--reason …] [--evidence A-…]`; согласие пользователя — `kin task consent T-… --granted --by «Имя»` (только человек) |
| Следующее действие | `kin next` — ранжирование с причинами; недоступное (платно без согласия, лимит попыток) — отдельно |
| Поиск (и пустой) | `kin search add --task T-… --source … --query … --variants … --period 1880/1890 --result not-found --limits … --allowed … --disallowed … --repeat-when …`; проверить до поиска — `kin search check --source … --query …` |
| Решение по гипотезе | `kin hypothesis status H-… supported|weakened|parked|rejected|accepted --reason "…" [--reopen "…"]` |
| Независимое ревью | `kin review request <ID> --for accepted|rejected|strongly-corroborated|merge` → другая роль: `kin review checklist <ID>`, `kin review submit V-… --verdict … --checked A-… --findings …` → при необходимости человек: `kin review decide V-… --by «Имя»` |
| Запросы в архивы | `kin request add --recipient … --subject … --channel gov-portal --text requests/….md`, `kin request sent Q-… --date … --number …`, `kin request answer Q-… --artifacts A-…` |
| История решений | `kin history <ID>` |
| Изменить запись | `kin update C-0003 status=corroborated rationale="…"`, добавить ID в список: `--append artifact_ids=A-0009` |
| Посмотреть запись и ссылки на неё | `kin show P-0002`, `kin list claims --where status=hypothesis` |
| Слить дубликат / разделить | `kin person merge P-дубль P-основной` (нужно identity-утверждение ≥ corroborated и пройденное ревью), `kin person unmerge P-… --reason …` |
| Корень схемы, линии поиска | `kin case set root_person=P-…`, `kin case line add <id> title=… state="ищем сейчас" color=#b5651d` |
| Сайт-схема | `kin site build [--profile public]`, `kin site serve` → http://127.0.0.1:8080, выкладка — `kin site publish --to <папка>` (только с согласия пользователя); своё оформление — `kin site theme init [--full]` |
| Публикация живых (решает только автор дела) | человек: `kin update P-… publication=allow|deny`; всё дело: `kin case set privacy.public_living=allow --by «Имя»`; закрывать скрытое вместо остановки сборки: `kin case set privacy.on_leak=redact` |
| Роли агентов | `kin agents install` → `.claude/agents/*.md`, `.codex/agents/*.toml` в папке дела |
| Поиск по делу | `kin find <слова>` (имена в любом падеже, ё/е) |
| Сканы дела из онлайн-архива | `kin downloader list` → `kin downloader build <адаптер> --out f.js` (скрипт для консоли браузера пользователя + инструкция) → `kin source import-download <папка> --task T-…`; нового сайта нет — адаптер по `references/downloaders.md` (пользователь присылает сохранённую страницу просмотрщика) |
| Сведения семьи (форма на приватном сайте) | `kin case set feedback.enabled=true`, `kin feedback serve`, `kin feedback list|show`, решение — `kin feedback accept|reject FR-… --by «Имя»` |
| Обмен и сохранность | `kin export --out f.json` / `kin import f.json` (без дублей), `kin gedcom export|import`, `kin backup` / `kin restore` |
| MCP для клиентов без shell | `kin mcp config --client claude-code|claude-desktop|codex` |
| Окружение, схема | `kin doctor`, `kin migrate [--dry-run]` |

Указывайте исполнителя: `--as "Archive Researcher"` (или `KIN_ACTOR`) — попадает в журнал `journal.jsonl`.
Реестры не правьте вручную: `kin` проверяет схему и ссылки, блокирует одновременную запись и ведёт журнал.

# Неподлежащие нарушению правила

1. Новый материал — **артефакт, а не факт**. Сначала `kin source add`, потом утверждение с оценкой.
2. Копии, индексы, зеркала и пересказы одной записи — **одна группа независимости** (`--group`). Индекс сайта и скан той же метрики — одна группа.
3. `corroborated` — только при **двух независимых группах** источников и с `rationale`. `kin audit` считает это ошибкой.
4. Документ ≠ человек. Запись в источнике — `mention`; отождествление с `person` — отдельное решение с `link_rationale`.
   Одноимённых людей не сливать по ФИО, возрасту или деревне: два `person` + утверждение `identity` со статусом `hypothesis`.
5. Связь (`rel`) — только если родство **прямо названо в источнике**. Общее отчество или деревня — гипотеза
   (`claim` `parentage`/`sibling` со статусом `hypothesis`; в `parentage` первый subject — родитель).
6. Разные даты в разных документах — **два утверждения** со ссылкой `competing_claim_ids` и статусом `contradicted`/`unresolved`.
   Не выбирать «правильную» дату молча и не писать «1880/1882» в одно утверждение.
7. Исходное написание имён, дат, мест сохранять в `mention` и `name_variants`; нормализованное — в `preferred_label`.
8. Отсутствие результата — не доказательство отсутствия. Каждый пустой поиск — запись в `searches`:
   где, что, варианты написания, период, ограничения источника, `allowed_conclusions`, `disallowed_conclusions`, `repeat_when`.
   Перед поиском смотреть `kin status` → «Проверено без результата» и не повторять без нового основания.
9. Гипотезу не закрывать одной задачей. `rejected` — только с источниками «против» и `reopen_conditions`;
   `closed-without-finding` у задачи не означает опровержение гипотезы.
10. Не выдумывать недостающее, не повышать семейную память до документального факта (`family-reported`).

# Цикл работы

1. `kin status` и `kin next` — активные гипотезы, задачи, заблокированное, пустые поиски, **следующее действие с причинами**.
2. Взять задачу: `kin task start T-… --as "<роль>"` (откажет, если нужно согласие пользователя или исчерпан лимит попыток),
   прочитать задание `tasks/T-….md` и источник.
3. Каждый просмотренный ресурс — `kin search add --task T-…` (и при находке, и без неё); находку — `source add` + `mention`.
   Повтор безрезультатного поиска `kin` отклонит без `--new-basis`.
4. Обновить утверждения, связи и гипотезу (источники «за» и «против», противоречия); решение по гипотезе — `kin hypothesis status … --reason`.
5. Завершить задачу: `kin task done T-… --reason … --evidence A-…` или `kin task close T-… --reason …`; новую — `kin task new …`.
6. Значимый вывод (принять/опровергнуть гипотезу, strongly-corroborated, слияние) — `kin review request <ID> --for <решение>`; проверяет
   **другая роль** (Evidence Reviewer) по первичным источникам; правила — `docs/REVIEW.md` репозитория набора.
7. `kin audit` — 0 ошибок. Коммит в git-репозитории дела (короткое сообщение).
8. Повторять, пока `kin next` предлагает доступные шаги в пределах ограничений дела (`case.json` → `limits`).

# Роли агентов

`kin agents install` раскладывает роли в папку дела: Orchestrator, Genealogy Researcher, Archive Researcher,
Evidence Reviewer, Data Curator, Security & Privacy Reviewer (Claude Code — `.claude/agents/`, Codex — `.codex/agents/`).
Не нужно запускать все роли для каждой задачи. Одну запись реестра в один момент меняет одна роль; все записи — через `kin`.
Исполнитель и проверяющий — разные роли (`--as`), это проверяется по журналу.

Ограничения инициативы: не больше `max_attempts_per_task` попыток на задачу без нового основания;
**платные действия и передача сведений сторонним сервисам — только с согласия пользователя**
(задача со статусом `blocked` и причиной в `constraints`). CAPTCHA и вход — по `references/browser-and-captcha.md`.

# Приватность

Различать три вида передачи: (1) обработка материалов дела моделью ИИ, которую выбрал пользователь;
(2) передача сведений сторонним сайтам и архивам (поисковые запросы, формы) — минимум личных данных, живых не искать;
(3) публикация (GitHub, сайт) — только через `kin site build --profile public`: живые и «возможно живые»
скрыты, служебные поля не попадают, сборка падает при утечке имени скрытого человека, e-mail, телефона или локального пути.
Сомнительное — исключить из публикации (`kin update P-… publication=deny`) до отдельного решения пользователя.
Не обещать полностью локальную обработку, если используется внешняя модель. Подробно — `references/privacy-and-safety.md`.

# Справочники

`references/README.md` — указатель: доказательность (`evidence-protocol.md`), источники бывшего СССР
(`source-strategy.md`, `seed-sources.md`), имена и административное деление (`ex-ussr-locale-guide.md`),
переписка с архивами (`correspondence.md`), специальные направления.
