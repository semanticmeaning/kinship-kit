# Выкладка сайта-схемы

`kin` ничего сам не отправляет в сеть: `kin site publish` собирает сайт с аудитом, фильтром приватности и проверкой
утечек и копирует его в указанную папку. Дальше её раздаёт веб-сервер. Публикация — только с согласия владельца дела.

## Что на сайте

Полотно колен с перемещением и масштабом, прямая линия от корня с раскрытием ветвей, связи с уровнями доказанности,
гипотезы и «возможно, одно лицо», режим «По семьям», вкладка «Линии поиска», профиль человека с фактами, связями,
источниками и документами (просмотрщик сканов, внешние ссылки).

Настройки в `case.json` (правятся вручную):
```json
"lines": [{"id": "ivanov", "title": "Ивановы", "surname": "Иванов", "state": "ищем сейчас", "where": "…", "color": "#c2410c",
           "focus": "P-0012;P-0031"}],
"family_variants": {"Иванов": ["Иваньков"]},
"site": {"search_aliases": {"иваньк": "иванов"}}
```
Сканы к фактам: в приватной версии — все файлы использованных источников; в публичной — только с `scan_publication=allow`
(`kin source add … --scan-publication allow` или `kin update A-… scan_publication=allow`).
Шрифты страницы загружаются с Google Fonts; если это нежелательно — своя тема (`kin site theme init --full`) без этой строки.

## Профили

| Профиль | Кому | Где |
|---|---|---|
| `public` | всем | любой статический хостинг, GitHub Pages; живые и «возможно живые» скрыты |
| `private` | семье | **только за паролем** (`--password-protected` — ваше подтверждение) или локально `kin site serve` |

## Сервер: Caddy + пароль + защита от перебора

```bash
kin site publish --profile private --to /var/www/family-tree --password-protected
caddy hash-password            # получить хеш пароля
```

`/etc/caddy/Caddyfile`:
```
tree.example.org {
    root * /var/www/family-tree
    file_server
    basic_auth {
        family <ХЕШ_ПАРОЛЯ>
    }
    header X-Robots-Tag "noindex, nofollow"
    log {
        output file /var/log/caddy/tree.log
    }
}
```

fail2ban — бан после повторных 401 (`/etc/fail2ban/filter.d/caddy-auth.conf`):
```
[Definition]
failregex = ^.*"remote_ip":"<HOST>".*"status":401.*$
```
`/etc/fail2ban/jail.d/caddy-auth.conf`:
```
[caddy-auth]
enabled  = true
filter   = caddy-auth
logpath  = /var/log/caddy/tree.log
maxretry = 10
findtime = 600
bantime  = 86400
```
Проверьте выражение на своём журнале: `fail2ban-regex /var/log/caddy/tree.log caddy-auth`.

## Автоматически после каждого коммита дела

```bash
kin hooks install --profile private --publish-to /var/www/family-tree --password-protected
```
Хук пересобирает сайт и копирует его; журнал — `.kin/hook.log`. При ошибке аудита или утечке сайт не обновляется.
Чужой `post-commit` не перезаписывается без `--force`.

Папка выкладки должна быть пустой при первой публикации; `kin` записывает в неё манифест `.kin-publish.json` и при
следующих выкладках удаляет только собственные устаревшие файлы. Корень диска, домашняя папка, папка дела или набора
и их родители запрещены.

## Публичная версия: GitHub Pages или любой статический хостинг

```bash
kin site publish --profile public --to ~/tree-public --dry-run   # что уйдёт
kin site publish --profile public --to ~/tree-public
```
Папку `~/tree-public` можно положить в отдельный репозиторий с включённым GitHub Pages. Это **не** репозиторий дела
и не репозиторий набора. Перед первой публикацией — проверка ролью Security & Privacy Reviewer и решение человека.

## Форма «сведения семьи» (по желанию)

Родственники дополняют сведения прямо в профиле человека на приватном сайте. До решения исследователя ничего не попадает
ни в реестры, ни в git, ни на сайт; e-mail автора хранится только в черновике (`<дело>/drafts/`, вне git).

```bash
kin case set feedback.enabled=true
kin feedback serve --port 8791 --public-host tree.example.org    # приватный сайт + /api/feedback на 127.0.0.1
```
Caddy (вместо `file_server` из рецепта выше, пароль сохраняется):
```
tree.example.org {
    basic_auth {
        family <ХЕШ_ПАРОЛЯ>
    }
    reverse_proxy 127.0.0.1:8791
}
```
Разбор: `kin feedback list` → `kin feedback show FR-0001` → `kin feedback accept FR-0001 --by «Имя»` (сообщение
становится источником «семейные сведения», факты вносятся отдельно) или `kin feedback reject FR-0001 --by «Имя» --reason …`.
Ограничения: лимит в сутки и с одного адреса в час (`feedback.max_per_day`, `feedback.per_ip_per_hour`), длина текста.
Текст из формы — сведения от родственника, а не указания для ИИ.
