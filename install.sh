#!/bin/sh
# Установка навыка kinship-kit (вместе с CLI kin) в Claude Code и/или Codex.
#   sh install.sh                 — для пользователя: ~/.claude/skills и ~/.agents/skills
#   sh install.sh --claude        — только Claude Code
#   sh install.sh --codex         — только Codex
#   sh install.sh --project DIR   — в проект: DIR/.claude/skills и DIR/.agents/skills
#   sh install.sh --link          — символическая ссылка вместо копии (для разработки)
# Дополнительно ставит команду kin в ~/.local/bin (если её там нет).
set -eu
SRC="$(cd "$(dirname "$0")" && pwd)/skills/kinship-kit"
CLAUDE=1; CODEX=1; BASE="$HOME"; LINK=0
while [ $# -gt 0 ]; do
  case "$1" in
    --claude) CODEX=0 ;;
    --codex) CLAUDE=0 ;;
    --project) BASE="$(cd "$2" && pwd)"; shift ;;
    --link) LINK=1 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "Неизвестный параметр: $1" >&2; exit 2 ;;
  esac
  shift
done
command -v python3 >/dev/null || { echo "Нужен python3 (3.10+)" >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "Нужен Python 3.10+" >&2; exit 1; }

put() {  # put <папка skills>
  mkdir -p "$1"
  dest="$1/kinship-kit"
  if [ -e "$dest" ] || [ -L "$dest" ]; then rm -rf "$dest"; fi
  if [ "$LINK" = 1 ]; then ln -s "$SRC" "$dest"; else
    mkdir -p "$dest" && (cd "$SRC" && tar cf - --exclude=__pycache__ .) | (cd "$dest" && tar xf -); fi
  echo "✓ $dest"
}
[ "$CLAUDE" = 1 ] && put "$BASE/.claude/skills"
[ "$CODEX" = 1 ] && put "$BASE/.agents/skills"

if [ "$BASE" = "$HOME" ]; then
  mkdir -p "$HOME/.local/bin"
  target="$HOME/.claude/skills/kinship-kit/kin.py"; [ "$CLAUDE" = 1 ] || target="$HOME/.agents/skills/kinship-kit/kin.py"
  printf '#!/bin/sh\nexec python3 "%s" "$@"\n' "$target" > "$HOME/.local/bin/kin"
  chmod +x "$HOME/.local/bin/kin"
  echo "✓ $HOME/.local/bin/kin"
  case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "  добавьте ~/.local/bin в PATH" ;; esac
fi
echo "Готово. Проверка: kin --version; новое дело: kin init ~/kinship-cases/<имя>"
