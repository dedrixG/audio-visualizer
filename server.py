#!/usr/bin/env python3
"""Local HTTP + WebSocket server for the audio visualizer.

Streams the PipeWire/Pulse default-sink monitor (what's playing) to the
page this process serves. Listens on 127.0.0.1 unless --bind is wider.
--bind 0.0.0.0 reaches a phone on Wi-Fi or Tailscale. Anyone who can open
that URL can hear playback. Other websites cannot.
"""

from __future__ import annotations

import argparse
import array
import hashlib
import ipaddress
import base64
import json
import os
import random
import socket
import struct
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


def bundle_root() -> Path:
    """Directory that holds web/ when running from source or a frozen build."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


WEB_ROOT = bundle_root() / "web"
# Bumps the launch URL so an already-installed cache-first page fetches this build.
PAGE_REV = "5"
# This computer only. Pass --bind 0.0.0.0 for the phone on Wi-Fi or Tailscale.
DEFAULT_BIND = "127.0.0.1"
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
SAMPLE_RATE = 44100
CHUNK_FRAMES = 1024  # stereo frames per read
PALETTES = ("ion", "magma", "aurora", "mono")
MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webmanifest": "application/manifest+json",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


def local_ips() -> list[str]:
    ips: list[str] = []
    seen: set[str] = set()

    def add(ip: str) -> None:
        if not ip or ip in seen:
            return
        if ":" in ip or ip.startswith("127.") or ip.startswith("172.17."):
            return
        seen.add(ip)
        ips.append(ip)

    try:
        out = subprocess.check_output(
            ["hostname", "-I"], text=True, stderr=subprocess.DEVNULL
        )
        for tok in out.split():
            add(tok)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 80))
        add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    preferred = [ip for ip in ips if ip.startswith("192.168.") or ip.startswith("10.")]
    tailscale = [ip for ip in ips if ip.startswith("100.")]
    rest = [ip for ip in ips if ip not in preferred and ip not in tailscale]
    return preferred + tailscale + rest


def _dbus_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", "replace")
    try:
        parts = list(value)  # type: ignore[arg-type]
    except TypeError:
        return str(value)
    if parts and not isinstance(parts[0], str):
        return str(value)
    return ", ".join(str(part) for part in parts)


def read_now_playing(skip_until: dict[str, float]) -> dict | None:
    """Current MPRIS track, preferring a player that is actually playing."""
    try:
        import dbus
    except ImportError:
        return None
    try:
        bus = dbus.SessionBus()
        raw_names = bus.get_object(
            "org.freedesktop.DBus", "/org/freedesktop/DBus"
        ).ListNames(dbus_interface="org.freedesktop.DBus", timeout=0.4)
    except Exception:
        return None
    names = [str(name) for name in raw_names if str(name).startswith("org.mpris.MediaPlayer2.")]
    now = time.time()
    playing = None
    paused = None
    for name in names:
        if skip_until.get(name, 0) > now:
            continue
        try:
            player = bus.get_object(name, "/org/mpris/MediaPlayer2", introspect=False)
            status = str(player.Get(
                "org.mpris.MediaPlayer2.Player",
                "PlaybackStatus",
                dbus_interface="org.freedesktop.DBus.Properties",
                timeout=0.4,
            ))
            meta = player.Get(
                "org.mpris.MediaPlayer2.Player",
                "Metadata",
                dbus_interface="org.freedesktop.DBus.Properties",
                timeout=0.4,
            )
        except Exception:
            skip_until[name] = now + 30
            continue
        artist = _dbus_text(meta.get("xesam:artist"))
        title = _dbus_text(meta.get("xesam:title"))
        track_id = _dbus_text(meta.get("mpris:trackid"))
        if not track_id:
            track_id = f"{artist}\n{title}" if (artist or title) else ""
        if not track_id:
            continue
        rec = {"id": track_id, "title": title, "artist": artist, "status": status}
        if status == "Playing" and playing is None:
            playing = rec
        elif status == "Paused" and paused is None:
            paused = rec
    return playing or paused


def port_in_use(exc: OSError) -> bool:
    if exc.errno in {98, 48, 10048}:
        return True
    return getattr(exc, "winerror", None) == 10048


def now_playing_script() -> Path | None:
    candidates = [
        bundle_root() / "windows" / "now_playing.ps1",
        Path(sys.executable).resolve().parent / "windows" / "now_playing.ps1",
        Path(__file__).resolve().parent / "windows" / "now_playing.ps1",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def _to_stereo_f32(raw: bytes, channels: int) -> bytes:
    """Downmix interleaved float32 frames to stereo float32."""
    width = 4 * max(channels, 1)
    usable = len(raw) - (len(raw) % width)
    if usable <= 0:
        return b""
    if channels == 2:
        return raw[:usable]
    src = array.array("f")
    src.frombytes(raw[:usable])
    frames = len(src) // channels
    out = array.array("f")
    if channels == 1:
        for sample in src:
            out.append(sample)
            out.append(sample)
    else:
        for i in range(frames):
            base = i * channels
            out.append(src[base])
            out.append(src[base + 1])
    return out.tobytes()


class WasapiCapture:
    """What-you-hear capture through the default Windows output device."""

    def __init__(self) -> None:
        try:
            import pyaudiowpatch as pyaudio
        except ImportError as exc:
            raise ImportError(
                "Windows audio needs pyaudiowpatch. Run install.bat in this folder."
            ) from exc
        self._pyaudio = pyaudio
        self.pa = pyaudio.PyAudio()
        self.stream = None
        self.device = ""
        self.channels = 2
        self.pending = bytearray()
        self.dead = False
        try:
            self._open()
        except Exception:
            self.close()
            raise

    def _open(self) -> None:
        try:
            info = self.pa.get_default_wasapi_loopback()
        except Exception as exc:
            raise RuntimeError(f"No WASAPI loopback device ({exc})") from exc
        self.device = str(info.get("name") or "WASAPI loopback")
        self.channels = max(1, int(info.get("maxInputChannels") or 2))
        rate = int(info.get("defaultSampleRate") or 48000)
        self.stream = self.pa.open(
            format=self._pyaudio.paFloat32,
            channels=self.channels,
            rate=rate,
            input=True,
            frames_per_buffer=CHUNK_FRAMES,
            input_device_index=int(info["index"]),
        )

    def read(self, nbytes: int) -> bytes:
        if self.dead or self.stream is None:
            return b""
        try:
            while len(self.pending) < nbytes:
                frames = max(1, (nbytes // 8))
                raw = self.stream.read(frames, exception_on_overflow=False)
                self.pending.extend(_to_stereo_f32(raw, self.channels))
        except Exception:
            self.dead = True
            return b""
        out = bytes(self.pending[:nbytes])
        del self.pending[:nbytes]
        return out

    def close(self) -> None:
        self.dead = True
        stream, self.stream = self.stream, None
        if stream is not None:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        try:
            self.pa.terminate()
        except Exception:
            pass


def default_monitor() -> str | None:
    if sys.platform == "win32":
        return None
    try:
        sink = subprocess.check_output(
            ["pactl", "get-default-sink"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    if not sink:
        return None
    return sink + ".monitor"


class Hub:
    """Broadcasts mono float32 PCM from the system monitor to WebSocket clients."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.clients: list[WebSocketClient] = []
        self.device: str | None = None
        self.error: str | None = None
        self.track_id = ""
        self.track_title = ""
        self.track_artist = ""
        self.track_status = ""
        self.palette = ""
        self._mpris_skip: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        threading.Thread(target=self._watch_tracks, name="mpris-watch", daemon=True).start()

    def add(self, client: WebSocketClient) -> None:
        with self.lock:
            self.clients.append(client)
            should_start = len(self.clients) == 1
        if should_start:
            self._start_capture()

    def remove(self, client: WebSocketClient) -> None:
        with self.lock:
            if client in self.clients:
                self.clients.remove(client)
            empty = not self.clients
        if empty:
            self._stop_capture()

    def snapshot(self) -> dict:
        with self.lock:
            n = len(self.clients)
            device = self.device
            error = self.error
            track = {
                "id": self.track_id,
                "title": self.track_title,
                "artist": self.track_artist,
                "status": self.track_status,
                "palette": self.palette,
            }
        return {
            "clients": n,
            "device": device or default_monitor(),
            "error": error,
            "rate": SAMPLE_RATE,
            "frames": CHUNK_FRAMES,
            "track": track,
        }

    def _apply_track(self, track: dict | None) -> None:
        if not track or not track.get("id"):
            return
        with self.lock:
            if track["id"] != self.track_id:
                self.track_id = str(track["id"])
                choices = [name for name in PALETTES if name != self.palette]
                self.palette = random.choice(choices or PALETTES)
            self.track_title = str(track.get("title") or "")
            self.track_artist = str(track.get("artist") or "")
            self.track_status = str(track.get("status") or "")

    def _watch_tracks(self) -> None:
        if sys.platform == "win32":
            self._watch_windows()
            return
        while True:
            self._apply_track(read_now_playing(self._mpris_skip))
            time.sleep(1.0)

    def _watch_windows(self) -> None:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        while True:
            script = now_playing_script()
            if script is None:
                time.sleep(5)
                continue
            try:
                proc = subprocess.Popen(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(script),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=flags,
                )
            except (OSError, FileNotFoundError):
                time.sleep(5)
                continue
            if proc.stdout is not None:
                for line in proc.stdout:
                    line = line.strip().lstrip("\ufeff")
                    if not line.startswith("{"):
                        continue
                    try:
                        track = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    status = str(track.get("status") or "")
                    if status in {"4", "Playing"} or status.endswith("Playing"):
                        track["status"] = "Playing"
                    elif status in {"5", "Paused"} or status.endswith("Paused"):
                        track["status"] = "Paused"
                    self._apply_track(track)
            if proc.poll() is None:
                proc.kill()
            time.sleep(2)

    def _start_capture(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="pcm-capture", daemon=True)
        self._thread.start()

    def _stop_capture(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        if sys.platform == "win32":
            self._run_wasapi()
            return
        proc: subprocess.Popen | None = None
        current = None
        while not self._stop.is_set():
            monitor = default_monitor()
            if monitor != current:
                if proc:
                    proc.kill()
                    proc = None
                current = monitor
                with self.lock:
                    self.device = monitor
                if not monitor:
                    with self.lock:
                        self.error = "No default audio sink found."
                    time.sleep(1.0)
                    continue
                proc = self._spawn(monitor)
                if proc is None:
                    time.sleep(1.0)
                    continue
            if proc is None or proc.poll() is not None:
                with self.lock:
                    self.error = "Audio capture exited; retrying."
                if proc:
                    proc.kill()
                proc = None
                current = None
                time.sleep(0.5)
                continue
            nbytes = CHUNK_FRAMES * 2 * 4  # stereo float32
            raw = proc.stdout.read(nbytes) if proc.stdout else b""
            if len(raw) != nbytes:
                with self.lock:
                    self.error = "Short read from audio capture."
                if proc:
                    proc.kill()
                proc = None
                current = None
                time.sleep(0.2)
                continue
            with self.lock:
                self.error = None
                clients = list(self.clients)
            mono = _stereo_to_mono(raw)
            dead: list[WebSocketClient] = []
            for c in clients:
                try:
                    c.send_binary(mono)
                except OSError:
                    dead.append(c)
            for c in dead:
                self.remove(c)
        if proc:
            proc.kill()

    def _run_wasapi(self) -> None:
        cap: WasapiCapture | None = None
        nbytes = CHUNK_FRAMES * 2 * 4
        while not self._stop.is_set():
            if cap is None:
                try:
                    cap = WasapiCapture()
                except ImportError as exc:
                    with self.lock:
                        self.error = str(exc)
                    time.sleep(2.0)
                    continue
                except Exception as exc:
                    with self.lock:
                        self.error = str(exc)
                    time.sleep(1.0)
                    continue
                with self.lock:
                    self.device = cap.device
                    self.error = None
            raw = cap.read(nbytes)
            if len(raw) != nbytes:
                with self.lock:
                    self.error = "Audio capture stopped; retrying."
                cap.close()
                cap = None
                time.sleep(0.5)
                continue
            with self.lock:
                self.error = None
                clients = list(self.clients)
            mono = _stereo_to_mono(raw)
            dead: list[WebSocketClient] = []
            for client in clients:
                try:
                    client.send_binary(mono)
                except OSError:
                    dead.append(client)
            for client in dead:
                self.remove(client)
        if cap:
            cap.close()

    def _spawn(self, device: str) -> subprocess.Popen | None:
        cmd = [
            "parec",
            "--format=float32le",
            "--channels=2",
            f"--rate={SAMPLE_RATE}",
            f"--device={device}",
            "--latency-msec=40",
        ]
        try:
            return subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            with self.lock:
                self.error = "parec not found (pulseaudio-utils)."
            return None
        except OSError as exc:
            with self.lock:
                self.error = str(exc)
            return None


HUB = Hub()


class WebSocketClient:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.lock = threading.Lock()

    def send_binary(self, payload: bytes) -> None:
        self._send(0x2, payload)

    def send_text(self, text: str) -> None:
        self._send(0x1, text.encode("utf-8"))

    def send_close(self) -> None:
        try:
            self._send(0x8, b"")
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def _send(self, opcode: int, payload: bytes) -> None:
        n = len(payload)
        header = bytearray()
        header.append(0x80 | opcode)
        if n < 126:
            header.append(n)
        elif n < 65536:
            header.append(126)
            header.extend(struct.pack("!H", n))
        else:
            header.append(127)
            header.extend(struct.pack("!Q", n))
        with self.lock:
            self.sock.sendall(header + payload)


def listens_on_network(bind: str) -> bool:
    """True when ``bind`` is not a loopback address."""
    host = bind.strip().lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host not in {"127.0.0.1", "localhost", "::1"}


def _normalized_host(hostname: str) -> str:
    return hostname.strip().lower().rstrip(".")


def _ip_address(hostname: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(hostname)
    except ValueError:
        return None


def _origin_port(parsed) -> int | None:
    """Port of a path-less http origin, or None when it is not one."""
    if (parsed.scheme or "").lower() != "http":
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if parsed.path or parsed.params or parsed.query or parsed.fragment:
        return None
    try:
        port = parsed.port
        hostname = parsed.hostname
    except ValueError:
        return None
    if not hostname:
        return None
    if port is None:
        port = 80
    if not 1 <= port <= 65535:
        return None
    return port


def _request_ip(host_header: str | None, server_port: int) -> str | None:
    """IP literal from a Host header whose port is ``server_port``.

    A missing port is port 80. DNS names are ignored so a name that merely
    resolves to this machine cannot satisfy the check.
    """
    if not host_header:
        return None
    raw = host_header.strip()
    if not raw or any(ch in raw for ch in " @/?#"):
        return None
    if raw.startswith("["):
        end = raw.find("]")
        if end <= 1:
            return None
        hostname = raw[1:end]
        rest = raw[end + 1 :]
        if rest == "":
            port = 80
        elif rest.startswith(":") and rest[1:].isdigit():
            port = int(rest[1:])
        else:
            return None
    else:
        if raw.count(":") > 1:
            return None
        if ":" in raw:
            hostname, _, port_text = raw.rpartition(":")
            if not port_text.isdigit():
                return None
            port = int(port_text)
        else:
            hostname = raw
            port = 80
    if port != server_port:
        return None
    address = _ip_address(_normalized_host(hostname))
    if address is None:
        return None
    return address.compressed


def origin_allowed(origin: str | None, host_header: str | None, port: int) -> bool:
    """True when ``origin`` is the page this server is serving on ``port``.

    Loopback (localhost, 127.0.0.1, ::1) is the desktop page. A phone is
    allowed only for the http://<ip>:<port> the request came in on.
    """
    if origin is None or not isinstance(port, int) or not 1 <= port <= 65535:
        return False
    parsed = urlparse(origin.strip())
    origin_port = _origin_port(parsed)
    if origin_port != port:
        return False
    try:
        hostname = parsed.hostname or ""
    except ValueError:
        return False
    hostname = _normalized_host(hostname)
    if hostname == "localhost":
        return True
    address = _ip_address(hostname)
    if address is None:
        return False
    if address.is_loopback:
        return True
    return _request_ip(host_header, port) == address.compressed


class VizHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AudioVisualizer/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/ws/pcm":
            self._ws_upgrade()
            return
        if parsed.path == "/api/status":
            self._json(
                {
                    **HUB.snapshot(),
                    "urls": self._urls(),
                }
            )
            return
        self._static(parsed.path)

    def _urls(self) -> dict:
        port = self.server.server_address[1]
        urls = {
            "local": f"http://127.0.0.1:{port}/?v={PAGE_REV}",
            "lan": [],
        }
        bind_host = str(self.server.server_address[0])
        if listens_on_network(bind_host):
            for ip in local_ips():
                urls["lan"].append(f"http://{ip}:{port}/?v={PAGE_REV}")
        return urls

    def _json(self, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: str) -> None:
        rel = unquote(path)
        if rel == "/":
            rel = "/index.html"
        rel = rel.lstrip("/")
        target = (WEB_ROOT / rel).resolve()
        try:
            target.relative_to(WEB_ROOT.resolve())
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = target.read_bytes()
        ctype = MIME.get(target.suffix.lower(), "application/octet-stream")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if target.suffix.lower() in {".html", ".js", ".css", ".json"}:
            self.send_header("Cache-Control", "no-cache")
        else:
            self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def _ws_upgrade(self) -> None:
        key = self.headers.get("Sec-WebSocket-Key")
        if not key or self.headers.get("Upgrade", "").lower() != "websocket":
            self.send_error(HTTPStatus.BAD_REQUEST, "Expected WebSocket upgrade")
            return
        port = int(self.server.server_address[1])
        if not origin_allowed(self.headers.get("Origin"), self.headers.get("Host"), port):
            self.send_error(HTTPStatus.FORBIDDEN, "Origin not allowed")
            return
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        self.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        self.close_connection = True

        client = WebSocketClient(self.connection)
        HUB.add(client)
        try:
            client.send_text(
                json.dumps({"type": "hello", **HUB.snapshot()})
            )
            self._ws_read_loop(client)
        finally:
            HUB.remove(client)
            try:
                self.connection.close()
            except OSError:
                pass

    def _ws_read_loop(self, client: WebSocketClient) -> None:
        sock = self.connection
        sock.settimeout(60.0)
        buf = b""
        while True:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                try:
                    client._send(0x9, b"")
                except OSError:
                    return
                continue
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while True:
                frame, buf = _decode_ws_frame(buf)
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == 0x8:
                    return
                if opcode == 0x9:
                    try:
                        client._send(0xA, payload)
                    except OSError:
                        return
                # text/binary from client ignored


def _decode_ws_frame(buf: bytes) -> tuple[tuple[int, bytes] | None, bytes]:
    if len(buf) < 2:
        return None, buf
    b0, b1 = buf[0], buf[1]
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    n = b1 & 0x7F
    idx = 2
    if n == 126:
        if len(buf) < 4:
            return None, buf
        n = struct.unpack("!H", buf[2:4])[0]
        idx = 4
    elif n == 127:
        if len(buf) < 10:
            return None, buf
        n = struct.unpack("!Q", buf[2:10])[0]
        idx = 10
    if masked:
        if len(buf) < idx + 4:
            return None, buf
        mask = buf[idx : idx + 4]
        idx += 4
    else:
        mask = None
    if len(buf) < idx + n:
        return None, buf
    payload = buf[idx : idx + n]
    rest = buf[idx + n :]
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return (opcode, payload), rest


def _stereo_to_mono(raw: bytes) -> bytes:
    stereo = array.array("f")
    stereo.frombytes(raw)
    mono = array.array("f")
    it = iter(stereo)
    for left in it:
        right = next(it, left)
        mono.append((left + right) * 0.5)
    return mono.tobytes()


def open_browser(url: str) -> None:
    if sys.platform == "win32":
        _open_browser_windows(url)
        return
    for cmd in (
        ["google-chrome", f"--app={url}", "--new-window"],
        ["chromium-browser", f"--app={url}"],
        ["firefox", url],
        ["xdg-open", url],
    ):
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return
        except FileNotFoundError:
            continue


def _open_browser_windows(url: str) -> None:
    local = os.environ.get("LOCALAPPDATA", "")
    prog = os.environ.get("ProgramFiles", "")
    prog86 = os.environ.get("ProgramFiles(x86)", "")
    candidates = [
        Path(prog) / "Google/Chrome/Application/chrome.exe",
        Path(prog86) / "Google/Chrome/Application/chrome.exe",
        Path(local) / "Google/Chrome/Application/chrome.exe",
        Path(prog) / "Microsoft/Edge/Application/msedge.exe",
        Path(prog86) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for exe in candidates:
        if exe.is_file():
            subprocess.Popen(
                [str(exe), f"--app={url}", "--new-window"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
    os.startfile(url)  # type: ignore[attr-defined]


def main() -> int:
    parser = argparse.ArgumentParser(description="Audio visualizer server")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--bind",
        default=DEFAULT_BIND,
        help="Listen address (default %(default)s). Use 0.0.0.0 for a phone on Wi-Fi or Tailscale.",
    )
    parser.add_argument("--open", action="store_true", help="Open desktop app window")
    args = parser.parse_args()

    if not WEB_ROOT.is_dir():
        print(f"Missing web root: {WEB_ROOT}", file=sys.stderr)
        return 1

    try:
        httpd = ThreadingHTTPServer((args.bind, args.port), VizHandler)
    except OSError as exc:
        if port_in_use(exc):
            url = f"http://127.0.0.1:{args.port}/?v={PAGE_REV}"
            print(f"Already running at {url}")
            if args.open:
                open_browser(url)
            return 0
        raise

    port = httpd.server_address[1]
    print("Audio Visualizer", flush=True)
    print(f"  This PC:     http://127.0.0.1:{port}/?v={PAGE_REV}", flush=True)
    if listens_on_network(args.bind):
        for ip in local_ips():
            kind = "Tailscale" if ip.startswith("100.") else "Phone Wi-Fi"
            print(f"  {kind:12} http://{ip}:{port}/?v={PAGE_REV}", flush=True)
        print("  Warning:     anyone on that network who opens the URL can hear playback.", flush=True)
    else:
        print("  Phone:       off. Start with --bind 0.0.0.0 to share it.", flush=True)
    print("  Source:      default sink monitor (system playback)", flush=True)
    print("  Ctrl+C to stop.", flush=True)

    if args.open:
        open_browser(f"http://127.0.0.1:{port}/?v={PAGE_REV}")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        HUB._stop_capture()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
