#!/usr/bin/env bash
# Деплой на сервер (Git Bash / Linux / macOS):
#   1) проверки локально: ruff + pytest brain, сборка и тесты мода;
#   2) git push;
#   3) если версия мода (mod/gradle.properties) новее установленной — jar на сервер;
#   4) mc-update на сервере: git pull, uv sync, перезапуск только того, что поменялось.
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

step() { printf '\n== %s\n' "$*"; }

step "git"
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || { echo "деплой только из main" >&2; exit 1; }
git diff --quiet && git diff --cached --quiet || { echo "есть незакоммиченные изменения" >&2; exit 1; }

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
if [ "$mod_changed" = true ] && [ "$version" = "$installed" ]; then
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

step "на сервер"
remote "mkdir -p bin deploy"
scp -q deploy/mc deploy/mc-update "$DEPLOY_SSH:bin/"
remote "chmod +x bin/mc bin/mc-update"
if [ "$version" != "$installed" ]; then
  scp -q "$jar" "$DEPLOY_SSH:deploy/"
  echo "мод $version загружен"
fi

step "mc-update $*"
remote "bin/mc-update $*"
