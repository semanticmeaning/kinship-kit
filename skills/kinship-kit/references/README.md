# Справочники навыка kinship-kit

Методические справочники взяты из навыка [ex-ussr-kinship-research](https://github.com/DenisSergeevitch/ex-ussr-kinship-research)
v1.11.0 (MIT, © 2026 Denis Shiryaev) и адаптированы. Лицензия исходника — `../../../LICENSE`, атрибуция — `../../../NOTICE.md`.

## Соответствие исходному навыку

| В исходнике | В kinship-kit |
|---|---|
| `artifact-register.csv` | `registry/artifacts.csv` (`kin source add`) |
| `person-register.csv` | `registry/persons.csv` (`kin person add`) + `registry/mentions.csv` — запись о человеке в источнике отдельно от личности |
| `claims-register.csv` | `registry/claims.csv` (`kin claim add`); конкурирующие версии — `competing_claim_ids` |
| `relationship-register.csv` | `registry/relationships.csv` (`kin rel add`) |
| `search-log.csv` | `registry/searches.csv` (`kin add searches`) — с полями для отрицательных результатов |
| `research-state.md` (очередь) | `registry/hypotheses.csv`, `registry/tasks.csv`; состояние — `kin status` |
| `audit_evidence.py` | `kin audit` |
| `init_case.py` | `kin init` |
| `hash_artifact.py` | `kin source add` (sha256 автоматически) |
| `register_search.py`, `gwar.py`, `familysearch*.py`, `build_pdf.py` | **ещё не перенесены** — упоминания `scripts/…` в справочниках относятся к исходному навыку |

## Что где читать

| Файл | Когда |
|---|---|
| `evidence-protocol.md` | Оценка источника, независимость, статусы утверждений |
| `source-strategy.md`, `seed-sources.md` | Выбор источников по периоду и региону |
| `ex-ussr-locale-guide.md` | Имена, отчества, старая орфография, административное деление |
| `privacy-and-safety.md` | Живые люди, согласие, передача данных |
| `correspondence.md` | Запросы в архивы и библиотеки |
| `search-result-validation.md` | Проверка найденной записи |
| `ww1-search.md`, `chechnya-deportation.md`, `bessarabia-moldova.md`, `habsburg-galicia-bukovina.md` | Специальные направления |
| `photo-search.md`, `familysearch-indexes.md`, `browser-and-captcha.md` | Инструменты и сайты |
| `field-lessons.md`, `research-coordination.md` | Практика и работа нескольких исполнителей |
