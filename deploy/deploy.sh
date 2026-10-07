#!/usr/bin/env bash
# Деплой на сервер (Git Bash / Linux / macOS):
#   1) проверки локально: ruff + pytest brain, сборка и тесты мода;
#   2) git push;
#   3) новая версия мода (mod/gradle.properties) — GitHub Release v<версия> с jar (нужен gh, `gh auth login`);
#   4) mc-update на сервере: git pull, uv sync, jar из релиза, перезапуск только того, что поменялось.
#
#   deploy/deploy.sh [--now|--when-empty|--no-restart]    (флаги передаются в mc-update)
#
# Куда деплоить — deploy/deploy.env (не в git): DEPLOY_SSH=user@host
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f deploy/deploy.env ] && . deploy/deploy.env
: "${DEPLOY_SSH:?укажи DEPLOY_SSH=user@host в deploy/deploy.env}"
REMOTE_REPO="${REMOTE_REPO:-mc-modpack-assistant}"  # относительно домашней папки на сервере
REMOTE_SERVER="${REMOTE_SERVER:-server}"
remote() { ssh -o BatchMode=yes "$DEPLOY_SSH" "$@"; }
GH=$(command -v gh || echo "/c/Program Files/GitHub CLI/gh.exe")

step() { printf '\n== %s\n' "$*"; }

step "git"
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || { echo "деплой только из main" >&2; exit 1; }
git diff --quiet && git diff --cached --quiet || { echo "есть незакоммиченные изменения" >&2; exit 1; }
"$GH" auth status >/dev/null 2>&1 || { echo "gh не залогинен: gh auth login" >&2; exit 1; }

version=$(sed -n 's/^mod_version=//p' mod/gradle.properties | tr -d '\r')
jar="mod/build/libs/modpack-bridge-$version.jar"
deployed=$(remote "git -C $REMOTE_REPO rev-parse HEAD")
installed=$(remote "ls $REMOTE_SERVER/mods/ | sed -n 's/^modpack-bridge-\(.*\)\.jar$/\1/p'" | head -1)
echo "на сервере: код ${deployed:0:7}, мод ${installed:-нет}; локально: код $(git rev-parse --short HEAD), мод $version"

if ! git cat-file -e "$deployed" 2>/dev/null; then
  git fetch -q origin
fi
mod_changed=false
git diff --quiet "$deployed" HEAD -- mod/src mod/build.gradle mod/gradle.properties || mod_changed=true
released=false
"$GH" release view "v$version" >/dev/null 2>&1 && released=true
if [ "$mod_changed" = true ] && { [ "$version" = "$installed" ] || [ "$released" = true ]; }; then
  echo "мод изменился, а mod_version всё ещё $version — подними версию в mod/gradle.properties" >&2
  exit 1
fi

step "brain: ruff + pytest"
(cd brain && uv run ruff check . && uv run ruff format --check . && uv run pytest -q)

step "мод: сборка и тесты"
(cd mod && ./gradlew build -q)
[ -f "$jar" ] || { echo "не найден $jar" >&2; exit 1; }

step "git push"
git push -q origin main

if [ "$released" = false ]; then
  step "релиз v$version"
  "$GH" release create "v$version" "$jar" --target "$(git rev-parse HEAD)" \
    --title "Mod $version" --notes "modpack-bridge $version ($(git rev-parse --short HEAD))"
fi

step "скрипты на сервер"
remote "mkdir -p bin"
scp -q deploy/mc deploy/mc-update "$DEPLOY_SSH:bin/"
remote "chmod +x bin/mc bin/mc-update"

step "mc-update $*"
remote "bin/mc-update $*"
