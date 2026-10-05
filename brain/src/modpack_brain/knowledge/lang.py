"""Русские названия предметов: ключ перевода → текст.

На сервере есть только английский, поэтому русский собираем сами, по приоритету (последний побеждает):
ваниль (с серверов Mojang, кэшируется) < файлы ru_ru.json модов (включая вложенные jar) < ресурспаки сборки.
"""

from __future__ import annotations

import io
import json
import logging
import re
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

LANG = "ru_ru"
_LANG_FILE = re.compile(rf"^assets/[^/]+/lang/{LANG}\.json$")
_NESTED_JAR = re.compile(r"^META-INF/jars/[^/]+\.jar$")
CACHE_DIR = Path("modpack-bridge") / "lang"
RESOURCE_PACK_DIRS = (Path("config") / "paxi" / "resourcepacks", Path("resourcepacks"))
VERSION_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
ASSETS_URL = "https://resources.download.minecraft.net/{prefix}/{hash}"


def load_names(server_dir: Path, minecraft_version: str | None) -> dict[str, str]:
    names: dict[str, str] = {}
    if minecraft_version:
        names.update(_vanilla(server_dir, minecraft_version))
    for jar in sorted((server_dir / "mods").glob("*.jar")):
        try:
            with zipfile.ZipFile(jar) as archive:
                _scan(archive, names)
        except (OSError, zipfile.BadZipFile):
            log.warning("язык: не прочитать %s", jar.name)
    for pack_dir in RESOURCE_PACK_DIRS:
        for pack in sorted((server_dir / pack_dir).glob("*.zip")):
            try:
                with zipfile.ZipFile(pack) as archive:
                    _scan(archive, names, nested=False)
            except (OSError, zipfile.BadZipFile):
                log.warning("язык: не прочитать %s", pack.name)
    return names


def _scan(archive: zipfile.ZipFile, out: dict[str, str], *, nested: bool = True, depth: int = 0) -> None:
    for name in archive.namelist():
        if _LANG_FILE.match(name):
            out.update(_strings(archive.read(name)))
        elif nested and depth < 2 and _NESTED_JAR.match(name):
            try:
                with zipfile.ZipFile(io.BytesIO(archive.read(name))) as inner:
                    _scan(inner, out, depth=depth + 1)
            except zipfile.BadZipFile:
                pass


def _strings(raw: bytes) -> dict[str, str]:
    try:
        data: Any = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return {}
    return (
        {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(data, dict) else {}
    )


def _vanilla(server_dir: Path, version: str) -> dict[str, str]:
    cache = server_dir / CACHE_DIR / f"minecraft-{version}-{LANG}.json"
    if cache.exists():
        return _strings(cache.read_bytes())
    try:
        raw = _download_vanilla(version)
    except Exception as error:  # сеть, формат манифеста — без ванильного русского переживём
        log.warning("язык: не удалось скачать ванильный %s: %s", LANG, error)
        return {}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(raw)
    return _strings(raw)


def _download_vanilla(version: str) -> bytes:
    manifest = _get_json(VERSION_MANIFEST)
    entry = next(v for v in manifest["versions"] if v["id"] == version)
    asset_index = _get_json(_get_json(entry["url"])["assetIndex"]["url"])
    file_hash = asset_index["objects"][f"minecraft/lang/{LANG}.json"]["hash"]
    return _get(ASSETS_URL.format(prefix=file_hash[:2], hash=file_hash))


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=20) as response:
        return response.read()


def _get_json(url: str) -> Any:
    return json.loads(_get(url))
