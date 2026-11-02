---
title: Выгрузка сканов дела из онлайн-архива (скрипт в браузере)
assignee: Archive Researcher
evidential_value: 4
access: online
---
# {task_id}. {goal}

Гипотеза: {hypothesis} — {hypothesis_statement}
Люди: {persons}
Дело / сайт: {sources_to_check}
Ожидаемый результат: {expected_result}

## Порядок
1. Есть ли адаптер сайта: `kin downloader list`. Нет — новый адаптер по `references/downloaders.md`
   (попросить у пользователя сохранённую страницу просмотрщика).
2. `kin downloader build <адаптер> --out <файл>` → передать пользователю скрипт и инструкцию дословно.
   Платный доступ к делу — только решение пользователя (`kin task consent {task_id} --granted --by «Имя»`).
3. Пользователь присылает папку выгрузки → `kin source import-download <папка> --task {task_id}`.
4. Разбор сканов — отдельной задачей `kin task new metric-books --hypothesis {hypothesis} …`.
5. Не скачалось на сайте (ошибки в `_kinship-download.txt`) — повтор в ту же папку; стабильная ошибка — `kin search add … --result blocked`.
