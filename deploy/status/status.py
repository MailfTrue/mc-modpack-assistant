#!/usr/bin/env python3
"""Публичная страница статуса сервера: / — страница, /api/status — JSON. Только stdlib.

Ничего не зашито: название и описание — MOTD из server.properties (первая и вторая строка), адрес —
telegram.status.address из config/modpack-bridge.json (иначе хост из заголовка запроса), сборка —
llm.packName, число модов и загрузчик — из выгрузки мода. Снаружи — за обратным прокси (Traefik).

Переменные окружения: SERVER_DIR (по умолчанию ~/server), STATUS_LISTEN (по умолчанию 127.0.0.1:8080).
"""

import html
import json
import os
import re
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SERVER_DIR = Path(os.environ.get("SERVER_DIR", Path.home() / "server"))
LISTEN = os.environ.get("STATUS_LISTEN", "127.0.0.1:8080")
CACHE_SECONDS = 10
TEMPLATE = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")
PROTOCOL_1_20_1 = 763


# ---------- Server List Ping ----------


def varint(n: int) -> bytes:
    out = b""
    while True:
        b, n = n & 0x7F, n >> 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def read_varint(sock: socket.socket) -> int:
    n = shift = 0
    while True:
        b = sock.recv(1)
        if not b:
            raise ConnectionError("соединение закрыто")
        n |= (b[0] & 0x7F) << shift
        shift += 7
        if not b[0] & 0x80:
            return n


def read_exact(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("соединение закрыто")
        data += chunk
    return data


def ping(port: int) -> dict:
    host = "127.0.0.1"
    with socket.create_connection((host, port), timeout=5) as sock:
        handshake = b"\x00" + varint(PROTOCOL_1_20_1) + varint(len(host)) + host.encode()
        handshake += struct.pack(">H", port) + varint(1)
        sock.sendall(varint(len(handshake)) + handshake + b"\x01\x00")
        read_varint(sock)  # длина пакета
        read_varint(sock)  # id пакета
        status = json.loads(read_exact(sock, read_varint(sock)))
        # Завершаем обмен как настоящий клиент (ping/pong) и закрываем аккуратно: обрыв с RST сервер считает
        # «malformed traffic» и после нескольких таких перестаёт отвечать этому IP.
        sock.sendall(varint(9) + b"\x01" + struct.pack(">q", 1))
        read_exact(sock, read_varint(sock))
        sock.shutdown(socket.SHUT_WR)
        while sock.recv(1024):
            pass
    players = status.get("players") or {}
    return {
        "online": True,
        "version": (status.get("version") or {}).get("name", ""),
        "players": players.get("online", 0),
        "max": players.get("max", 0),
        "names": sorted((p.get("name", "") for p in players.get("sample") or []), key=str.lower),
    }


# ---------- что показывать ----------


def read_properties() -> dict[str, str]:
    """server.properties в формате Java Properties (нужны только motd и server-port)."""
    out = {}
    try:
        text = (SERVER_DIR / "server.properties").read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            out[key.strip()] = value
    return out


def unescape_motd(value: str) -> list[str]:
    value = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), value)
    value = value.replace("\\n", "\n").replace("\\\\", "\\")
    value = re.sub("§.", "", value)  # цветовые коды
    return [line.strip() for line in value.split("\n") if line.strip()]


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def describe() -> dict:
    props = read_properties()
    motd = unescape_motd(props.get("motd", "")) or ["Сервер Minecraft"]
    bridge = read_json(SERVER_DIR / "config/modpack-bridge.json") or {}
    telegram = bridge.get("telegram") or {}
    mods = read_json(SERVER_DIR / "modpack-bridge/export/mods.json") or []
    ids = {m.get("id") for m in mods if isinstance(m, dict)}
    builtin = {"minecraft", "java", "fabricloader", "quilt_loader", "fabric-api"}
    return {
        "title": motd[0],
        "subtitle": motd[1] if len(motd) > 1 else "",
        "address": (telegram.get("status") or {}).get("address") or "",
        "pack": (bridge.get("llm") or {}).get("packName") or "",
        "loader": "Fabric" if "fabricloader" in ids else ("Quilt" if "quilt_loader" in ids else ""),
        "mods": sum(1 for i in ids if i and i not in builtin and not str(i).startswith("fabric-")) or None,
        "port": int(props.get("server-port") or 25565),
    }


_lock = threading.Lock()
_cache: dict = {"at": 0.0, "data": None}


def status() -> dict:
    with _lock:
        if _cache["data"] is None or time.monotonic() - _cache["at"] > CACHE_SECONDS:
            info = describe()
            try:
                data = ping(info.pop("port"))
            except (OSError, ValueError, ConnectionError):
                info.pop("port", None)
                data = {"online": False}
            data.update(info, checked_at=int(time.time()))
            _cache.update(at=time.monotonic(), data=data)
        return _cache["data"]


def page(host: str) -> bytes:
    data = status()
    address = data["address"] or host.split(":")[0]
    description = data["subtitle"] or f"Статус сервера {data['title']}"
    values = {
        "__TITLE__": data["title"],
        "__SUBTITLE__": data["subtitle"],
        "__DESCRIPTION__": description,
        "__ADDRESS__": address,
    }
    text = TEMPLATE
    for key, value in values.items():
        text = text.replace(key, html.escape(value))
    return text.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "status"

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/api/status":
            body, kind = json.dumps(status(), ensure_ascii=False).encode(), "application/json; charset=utf-8"
        elif path in ("/", "/index.html"):
            body, kind = page(self.headers.get("Host", "")), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


if __name__ == "__main__":
    host, _, port = LISTEN.rpartition(":")
    ThreadingHTTPServer((host or "127.0.0.1", int(port)), Handler).serve_forever()
