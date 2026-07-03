from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from darkweb_collector.runtime import default_db_path


SETTINGS_PATH_ENV = "DARKWEB_TOR_BRIDGE_SETTINGS_PATH"
SETTINGS_FILE = "tor_bridge_settings.json"
RUNTIME_DIR_NAME = "tor_bridge_runtime"
DEFAULT_SOCKS_HOST = "127.0.0.1"
DEFAULT_SOCKS_PORT = 9050
BRIDGE_MODES = {"snowflake", "obfs4", "webtunnel", "meek_lite", "vanilla", "custom"}
TRANSPORT_MODES = {"snowflake", "obfs4", "webtunnel", "meek_lite"}
DEFAULT_SNOWFLAKE_BRIDGES = [
    (
        "Bridge snowflake 192.0.2.3:80 2B280B23E1107BB62ABFC40DDCC8824814F80A72 "
        "fingerprint=2B280B23E1107BB62ABFC40DDCC8824814F80A72 "
        "url=https://1098762253.rsc.cdn77.org/ fronts=app.datapacket.com,www.datapacket.com "
        "ice=stun:stun.epygi.com:3478,stun:stun.uls.co.za:3478,stun:stun.voipgate.com:3478,"
        "stun:stun.mixvoip.com:3478,stun:stun.telnyx.com:3478,stun:stun.hot-chilli.net:3478,"
        "stun:stun.fitauto.ru:3478,stun:stun.m-online.net:3478 utls-imitate=hellorandomizedalpn"
    ),
    (
        "Bridge snowflake 192.0.2.4:80 8838024498816A039FCBBAB14E6F40A0843051FA "
        "fingerprint=8838024498816A039FCBBAB14E6F40A0843051FA "
        "url=https://1098762253.rsc.cdn77.org/ fronts=app.datapacket.com,www.datapacket.com "
        "ice=stun:stun.epygi.com:3478,stun:stun.uls.co.za:3478,stun:stun.voipgate.com:3478,"
        "stun:stun.mixvoip.com:3478,stun:stun.telnyx.com:3478,stun:stun.hot-chilli.net:3478,"
        "stun:stun.fitauto.ru:3478,stun:stun.m-online.net:3478 utls-imitate=hellorandomizedalpn"
    ),
]
DEFAULT_SNOWFLAKE_BRIDGE = DEFAULT_SNOWFLAKE_BRIDGES[0]
DEFAULT_OBFS4_BRIDGES = [
    "Bridge obfs4 37.218.245.14:38224 D9A82D2F9C2F65A18407B1D2B764F130847F8B5D "
    "cert=bjRaMrr1BRiAW8IE9U5z27fQaYgOhX1UCmOpg2pFpoMvo6ZgQMzLsaTzzQNTlm7hNcb+Sg iat-mode=0",
    "Bridge obfs4 209.148.46.65:443 74FAD13168806246602538555B5521A0383A1875 "
    "cert=ssH+9rP8dG2NLDN2XuFw63hIO/9MNNinLmxQDpVa+7kTOa9/m+tGWT1SmSYpQ9uTBGa6Hw iat-mode=0",
    "Bridge obfs4 146.57.248.225:22 10A6CD36A537FCE513A322361547444B393989F0 "
    "cert=K1gDtDAIcUfeLqbstggjIw2rtgIKqdIhUlHp82XRqNSq/mtAjp1BIC9vHKJ2FAEpGssTPw iat-mode=0",
    "Bridge obfs4 45.145.95.6:27015 C5B7CD6946FF10C5B3E89691A7D3F2C122D2117C "
    "cert=TD7PbUO0/0k6xYHMPW3vJxICfkMZNdkRrb63Zhl5j9dW3iRGiCx0A7mPhe5T2EDzQ35+Zw iat-mode=0",
    "Bridge obfs4 51.222.13.177:80 5EDAC3B810E12B01F6FD8050D2FD3E277B289A08 "
    "cert=2uplIpLQ0q9+0qMFrK5pkaYRDOe460LL9WHBvatgkuRr/SL31wBOEupaMMJ6koRE6Ld0ew iat-mode=0",
    "Bridge obfs4 212.83.43.95:443 BFE712113A72899AD685764B211FACD30FF52C31 "
    "cert=ayq0XzCwhpdysn5o0EyDUbmSOx3X/oTEbzDMvczHOdBJKlvIdHHLJGkZARtT4dcBFArPPg iat-mode=1",
    "Bridge obfs4 212.83.43.74:443 39562501228A4D5E27FCA4C0C81A01EE23AE3EE4 "
    "cert=PBwr+S8JTVZo6MPdHnkTwXJPILWADLqfMGoVvhZClMq/Urndyd42BwX9YFJHZnBB3H0XCw iat-mode=1",
]
DEFAULT_OBFS4_BRIDGE = DEFAULT_OBFS4_BRIDGES[0]
DEFAULT_MEEK_LITE_BRIDGES = [
    "Bridge meek_lite 192.0.2.20:80 url=https://1603026938.rsc.cdn77.org "
    "front=www.phpmyadmin.net utls=HelloRandomizedALPN",
]
DEFAULT_MEEK_LITE_BRIDGE = DEFAULT_MEEK_LITE_BRIDGES[0]
DEFAULT_BUILTIN_BRIDGES = {
    "snowflake": DEFAULT_SNOWFLAKE_BRIDGES,
    "obfs4": DEFAULT_OBFS4_BRIDGES,
    "meek_lite": DEFAULT_MEEK_LITE_BRIDGES,
}
SNOWFLAKE_ARGS = [
    "-url",
    "https://snowflake-broker.torproject.net/",
    "-fronts",
    "www.google.com",
]

_process_lock = Lock()
_process: subprocess.Popen | None = None
_last_error = ""


def settings_path() -> Path:
    raw_path = str(os.environ.get(SETTINGS_PATH_ENV) or "").strip()
    if raw_path:
        return Path(raw_path).expanduser().resolve()
    return default_db_path().with_name(SETTINGS_FILE).resolve()


def _default_runtime_dir() -> Path:
    return default_db_path().with_name(RUNTIME_DIR_NAME).resolve()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _string(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_lines(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_lines = value.splitlines()
    elif isinstance(value, list):
        raw_lines = value
    else:
        raw_lines = []
    lines: list[str] = []
    for item in raw_lines:
        line = _string(item)
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def _normalize_bridge_lines(value: Any) -> list[str]:
    lines = []
    for line in _normalize_lines(value):
        if line.lower().startswith("bridge "):
            lines.append(line)
        else:
            lines.append(f"Bridge {line}")
    return lines


def _normalize_settings(payload: dict[str, Any]) -> dict[str, Any]:
    mode = _string(payload.get("bridge_mode")) or "snowflake"
    if mode not in BRIDGE_MODES:
        raise ValueError(f"bridge_mode must be one of {', '.join(sorted(BRIDGE_MODES))}")

    socks_port = _int(payload.get("socks_port"), DEFAULT_SOCKS_PORT)
    if socks_port < 1 or socks_port > 65535:
        raise ValueError("socks_port must be between 1 and 65535")

    data_directory = _string(payload.get("data_directory"))
    return {
        "enabled": bool(payload.get("enabled", False)),
        "bridge_mode": mode,
        "tor_executable": _string(payload.get("tor_executable")),
        "transport_executable": _string(payload.get("transport_executable")),
        "socks_host": _string(payload.get("socks_host")) or DEFAULT_SOCKS_HOST,
        "socks_port": socks_port,
        "bridge_lines": _normalize_bridge_lines(payload.get("bridge_lines")),
        "extra_torrc_lines": _normalize_lines(payload.get("extra_torrc_lines")),
        "data_directory": data_directory,
        "updated_at": _string(payload.get("updated_at")),
        "last_started_at": _string(payload.get("last_started_at")),
    }


def _load_raw_settings() -> dict[str, Any]:
    path = settings_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_tor_bridge_settings() -> dict[str, Any]:
    defaults = {
        "enabled": False,
        "bridge_mode": "snowflake",
        "tor_executable": "",
        "transport_executable": "",
        "socks_host": DEFAULT_SOCKS_HOST,
        "socks_port": DEFAULT_SOCKS_PORT,
        "bridge_lines": [],
        "extra_torrc_lines": [],
        "data_directory": "",
        "updated_at": "",
        "last_started_at": "",
    }
    settings = _normalize_settings({**defaults, **_load_raw_settings()})
    if not settings["tor_executable"]:
        settings["tor_executable"] = detect_tor_executable()
    if not settings["transport_executable"]:
        settings["transport_executable"] = detect_transport_executable(settings["tor_executable"], settings["bridge_mode"])
    return settings


def save_tor_bridge_settings(payload: dict[str, Any]) -> dict[str, Any]:
    settings = _normalize_settings({**load_tor_bridge_settings(), **payload, "updated_at": _now_iso()})
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    apply_collector_proxy_env(settings)
    return get_tor_bridge_status()


def apply_collector_proxy_env(settings: dict[str, Any] | None = None) -> None:
    current = settings or load_tor_bridge_settings()
    if not current.get("enabled"):
        return
    os.environ["TOR_SOCKS_HOST"] = _string(current.get("socks_host")) or DEFAULT_SOCKS_HOST
    os.environ["TOR_SOCKS_PORT"] = str(_int(current.get("socks_port"), DEFAULT_SOCKS_PORT))


def active_socks_settings() -> tuple[str, int] | None:
    settings = load_tor_bridge_settings()
    if not settings.get("enabled"):
        return None
    return _string(settings.get("socks_host")) or DEFAULT_SOCKS_HOST, _int(settings.get("socks_port"), DEFAULT_SOCKS_PORT)


def _home_candidates() -> list[Path]:
    try:
        home = Path.home()
    except RuntimeError:
        return []
    return [
        home / "tor-browser" / "Browser" / "TorBrowser" / "Tor" / "tor",
        home / "Desktop" / "tor-browser" / "Browser" / "TorBrowser" / "Tor" / "tor",
        home / "Downloads" / "tor-browser" / "Browser" / "TorBrowser" / "Tor" / "tor",
    ]


def detect_tor_executable() -> str:
    candidates = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    user_profile = os.environ.get("USERPROFILE")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "Tor Browser" / "Browser" / "TorBrowser" / "Tor" / "tor.exe")
    if user_profile:
        for parent in ("Desktop", "Downloads", "Documents"):
            candidates.append(Path(user_profile) / parent / "Tor Browser" / "Browser" / "TorBrowser" / "Tor" / "tor.exe")
    candidates.extend(
        [
            Path("/usr/bin/tor"),
            Path("/usr/local/bin/tor"),
        ]
    )
    candidates.extend(_home_candidates())
    for candidate in candidates:
        if candidate.exists():
            return str(candidate.resolve())
    return ""


def detect_transport_executable(tor_executable: str = "", bridge_mode: str = "snowflake") -> str:
    names = (
        ["snowflake-client.exe", "snowflake-client", "lyrebird.exe", "lyrebird"]
        if bridge_mode == "snowflake"
        else ["lyrebird.exe", "lyrebird", "obfs4proxy.exe", "obfs4proxy"]
    )
    tor_path = Path(tor_executable).expanduser() if tor_executable else None
    candidates: list[Path] = []
    if tor_path:
        transport_dir = tor_path.parent / "PluggableTransports"
        candidates.extend(transport_dir / name for name in names)
    candidates.extend(Path("/usr/bin") / name for name in names)
    candidates.extend(Path("/usr/local/bin") / name for name in names)
    for candidate in candidates:
        if candidate.exists():
            return str(candidate.resolve())
    return ""


def _runtime_paths(settings: dict[str, Any]) -> dict[str, str]:
    runtime_dir = Path(settings.get("data_directory") or _default_runtime_dir()).expanduser().resolve()
    return {
        "data_directory": str(runtime_dir),
        "torrc_path": str(runtime_dir / "torrc"),
        "log_path": str(runtime_dir / "tor.log"),
        "snowflake_log_path": str(runtime_dir / "snowflake.log"),
    }


def _looks_like_posix_absolute_path(value: str) -> bool:
    return value.startswith("/") and not value.startswith("//")


def _torrc_token(value: str | Path) -> str:
    if isinstance(value, Path):
        text = str(value.expanduser().resolve())
    else:
        raw = _string(value)
        text = raw if _looks_like_posix_absolute_path(raw) else str(Path(raw).expanduser().resolve())
    if any(char.isspace() for char in text):
        return f'"{text}"'
    return text


def _transport_exec_token(settings: dict[str, Any]) -> str:
    raw_transport = _string(settings.get("transport_executable"))
    if _looks_like_posix_absolute_path(raw_transport):
        return _torrc_token(raw_transport)
    transport = Path(_string(settings.get("transport_executable"))).expanduser().resolve()
    tor_executable = Path(_string(settings.get("tor_executable"))).expanduser().resolve()
    token = _torrc_token(transport)
    if not any(char.isspace() for char in token.strip('"')):
        return token
    try:
        relative = transport.relative_to(tor_executable.parent)
    except ValueError:
        return token
    relative_text = str(relative)
    if any(char.isspace() for char in relative_text):
        return token
    return relative_text


def _effective_bridge_lines(settings: dict[str, Any]) -> list[str]:
    lines = list(settings.get("bridge_lines") or [])
    mode = _string(settings.get("bridge_mode"))
    if not lines and mode in DEFAULT_BUILTIN_BRIDGES:
        return list(DEFAULT_BUILTIN_BRIDGES[mode])
    return lines


def _client_transport_plugin(settings: dict[str, Any], paths: dict[str, str]) -> str:
    mode = _string(settings.get("bridge_mode")) or "snowflake"
    if mode not in TRANSPORT_MODES:
        return ""
    transport = _string(settings.get("transport_executable"))
    if not transport:
        return ""
    base = f"ClientTransportPlugin {mode} exec {_transport_exec_token(settings)}"
    if mode == "snowflake":
        if Path(transport).name.lower() in {"lyrebird.exe", "lyrebird"}:
            return base
        args = " ".join(SNOWFLAKE_ARGS + ["-log", _torrc_token(paths["snowflake_log_path"])])
        return f"{base} {args}"
    return base


def build_torrc(settings: dict[str, Any] | None = None) -> str:
    current = settings or load_tor_bridge_settings()
    paths = _runtime_paths(current)
    lines = [
        "ClientOnly 1",
        f"SocksPort {_string(current.get('socks_host')) or DEFAULT_SOCKS_HOST}:{_int(current.get('socks_port'), DEFAULT_SOCKS_PORT)}",
        f"DataDirectory {_torrc_token(paths['data_directory'])}",
        "AvoidDiskWrites 1",
    ]
    if current.get("enabled"):
        lines.append("UseBridges 1")
        plugin = _client_transport_plugin(current, paths)
        if plugin:
            lines.append(plugin)
        lines.extend(current.get("extra_torrc_lines") or [])
        lines.extend(_effective_bridge_lines(current))
    else:
        lines.append("UseBridges 0")
    return "\n".join(lines) + "\n"


def write_torrc(settings: dict[str, Any] | None = None) -> Path:
    current = settings or load_tor_bridge_settings()
    paths = _runtime_paths(current)
    runtime_dir = Path(paths["data_directory"])
    runtime_dir.mkdir(parents=True, exist_ok=True)
    torrc_path = Path(paths["torrc_path"])
    torrc_path.write_text(build_torrc(current), encoding="utf-8")
    return torrc_path


def _validate_start_inputs(settings: dict[str, Any]) -> None:
    tor_executable = Path(_string(settings.get("tor_executable"))).expanduser()
    if not tor_executable.exists():
        raise RuntimeError("未自动检测到 Tor 可执行文件，请先安装 Tor Browser 或 tor")
    mode = _string(settings.get("bridge_mode"))
    if mode in TRANSPORT_MODES:
        transport_executable = Path(_string(settings.get("transport_executable"))).expanduser()
        if not transport_executable.exists():
            raise RuntimeError("未自动检测到网桥传输插件，请确认 Tor Browser 的 lyrebird/snowflake-client 可用")
    if settings.get("enabled") and not _effective_bridge_lines(settings):
        raise RuntimeError("当前网桥类型没有可用的内置网桥")


def _process_running() -> bool:
    return _process is not None and _process.poll() is None


def start_tor_bridge() -> dict[str, Any]:
    global _last_error, _process
    settings = load_tor_bridge_settings()
    if not settings.get("enabled"):
        raise RuntimeError("Tor bridge is disabled")
    _validate_start_inputs(settings)
    paths = _runtime_paths(settings)
    with _process_lock:
        if _process_running():
            return get_tor_bridge_status()
        torrc_path = write_torrc(settings)
        Path(paths["data_directory"]).mkdir(parents=True, exist_ok=True)
        log_handle = Path(paths["log_path"]).open("a", encoding="utf-8")
        try:
            _process = subprocess.Popen(
                [_string(settings["tor_executable"]), "-f", str(torrc_path)],
                cwd=str(Path(_string(settings["tor_executable"])).expanduser().resolve().parent),
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                close_fds=True,
            )
        finally:
            log_handle.close()
        time.sleep(0.4)
        if _process.poll() is not None:
            _last_error = f"tor exited early with code {_process.returncode}"
            _process = None
            raise RuntimeError(_last_error)
    save_tor_bridge_settings({"last_started_at": _now_iso()})
    return get_tor_bridge_status()


def stop_tor_bridge() -> dict[str, Any]:
    global _last_error, _process
    with _process_lock:
        if _process_running():
            _process.terminate()
            try:
                _process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _process.kill()
                _process.wait(timeout=5)
        _process = None
        _last_error = ""
    return get_tor_bridge_status()


def get_tor_bridge_status() -> dict[str, Any]:
    settings = load_tor_bridge_settings()
    paths = _runtime_paths(settings)
    process_running = _process_running()
    pid = _process.pid if process_running and _process is not None else None
    return {
        **settings,
        **paths,
        "settings_path": str(settings_path()),
        "bridge_count": len(_effective_bridge_lines(settings)),
        "process_running": process_running,
        "process_pid": pid,
        "collector_proxy": f"socks5h://{settings['socks_host']}:{settings['socks_port']}",
        "last_error": _last_error,
    }
