---
title: Поиск в онлайн-базах (военные, репрессии, переселения, индексы)
assignee: Archive Researcher
evidential_value: 3
access: online
external_service: yes
---
# {task_id}. {goal}

Гипотеза: {hypothesis} — {hypothesis_statement}
Люди: {persons}
Базы: {sources_to_check}
Ожидаемый результат: {expected_result}

## Порядок
1. Минимум личных данных в запросах: фамилия, имя, год/место рождения умерших. **Сведения о живых не вводить.**
2. Варианты: написание фамилии (в т. ч. ошибки индексации), имя полное/краткое, отчество, место (старое/новое название).
3. Запись базы — это **индекс**: ищите образ документа; индекс и образ одного документа — одна группа независимости.
4. Сведения из базы проверяйте на однофамильцев: год, место, родственники, часть.

## Запись результата
- Каждый запрос — `kin search add --task {task_id} --source "<база>" --query … --variants … --result …`.
- Находка — `kin source add` (снимок/выгрузка, `--kind index-record`, `--url`, группа = документ, на который указывает индекс).
- Справочники: `references/ww1-search.md`, `references/source-strategy.md`, `references/seed-sources.md`.
