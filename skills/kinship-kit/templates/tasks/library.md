---
title: Поиск в библиотеках и изданиях (книги памяти, справочники, периодика)
assignee: Archive Researcher
evidential_value: 2
access: online
---
# {task_id}. {goal}

Гипотеза: {hypothesis} — {hypothesis_statement}
Люди: {persons}
Где смотреть: {sources_to_check}
Ожидаемый результат: {expected_result}

## Порядок
1. Электронные каталоги и полнотекстовые коллекции; краеведческие издания, книги памяти, адрес-календари, памятные книжки губерний.
2. Издание — производный источник: указывайте, на чём оно основано; ищите первоисточник.
3. Заказ копий — подготовить запрос (`kin request add`), отправляет пользователь; платное — после `kin task consent`.

## Запись результата
`kin search add --task {task_id} …` на каждое издание/каталог; находка — `kin source add --kind book --originality derivative`.
