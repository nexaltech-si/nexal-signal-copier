"""MT5 session manager.

Holds the credentials of the currently logged-in MT5 account in memory so that:
  1. The /mt5/login endpoint can switch accounts at runtime.
  2. The equity-protection heartbeat can transparently reconnect after a drop.
  3. App startup can auto-login from MT5_LOGIN / MT5_PASSWORD / MT5_SERVER env vars.

Security model:
  - Credentials never leave process memory and are never logged.
  - Password is wiped from the credential dict in error/log paths.
  - If MT5_PERSIST_LOGIN=1, credentials are persisted to /protection_config/mt5_session.json
    (chmod 0600). Off by default — env vars are the recommended path.
"""
import json
import logging
import os
import threading
from typing import Optional, Dict, Any

import MetaTrader5 as mt5

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_state: Dict[str, Any] = {
    "login": None,        # int
    "server": None,       # str
    "path": None,         # str (optional terminal64.exe path)
    "password": None,     # str (kept in memory only)
    "timeout": 60000,     # ms
    "last_error": None,
    "connected": False,
}

PERSIST_PATH = "/protection_config/mt5_session.json"
PERSIST_ENABLED = os.environ.get("MT5_PERSIST_LOGIN", "0") == "1"


def _redact(d: Dict[str, Any]) -> Dict[str, Any]:
    """Strip password from a credentials dict for logging/return."""
    return {k: ("***" if k == "password" else v) for k, v in d.items()}


def _persist():
    """Optionally persist credentials to disk so the container can self-recover after restart."""
    if not PERSIST_ENABLED:
        return
    try:
        os.makedirs(os.path.dirname(PERSIST_PATH), exist_ok=True)
        # Create with 0600 from the start: write-then-chmod left the password world-readable for a moment
        fd = os.open(PERSIST_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({
                "login": _state["login"],
                "server": _state["server"],
                "path": _state["path"],
                "password": _state["password"],
                "timeout": _state["timeout"],
            }, f)
        os.chmod(PERSIST_PATH, 0o600)  # also tightens a file that already existed with looser permissions
    except Exception as e:
        logger.error("Failed to persist MT5 session: %s", e)


def _load_persisted() -> Optional[Dict[str, Any]]:
    if not PERSIST_ENABLED or not os.path.exists(PERSIST_PATH):
        return None
    try:
        with open(PERSIST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to read persisted MT5 session: %s", e)
        return None


def _do_initialize(login: Optional[int], password: Optional[str], server: Optional[str],
                   path: Optional[str], timeout: int) -> bool:
    """Call mt5.initialize() with whatever credentials we have."""
    kwargs = {"timeout": timeout}
    if path:
        kwargs["path"] = path
    if login is not None:
        kwargs["login"] = int(login)
    if password is not None:
        kwargs["password"] = password
    if server is not None:
        kwargs["server"] = server

    try:
        # Always tear down any previous connection first to make switching accounts deterministic.
        try:
            mt5.shutdown()
        except Exception:
            pass
        ok = mt5.initialize(**kwargs)
        if not ok:
            ec, es = mt5.last_error()
            _state["last_error"] = f"({ec}) {es}"
            logger.warning("MT5 initialize failed: %s with %s", _state["last_error"], _redact(kwargs))
        else:
            _state["last_error"] = None
        return bool(ok)
    except Exception as e:
        _state["last_error"] = str(e)
        logger.error("MT5 initialize raised: %s", e)
        return False


def login(login_id: int, password: str, server: str,
          path: Optional[str] = None, timeout: int = 60000) -> Dict[str, Any]:
    """Log into a broker account. Returns a status dict.

    Stores credentials in memory (and on disk if MT5_PERSIST_LOGIN=1) so the
    heartbeat can reconnect transparently after a network drop.
    """
    with _lock:
        ok = _do_initialize(int(login_id), password, server, path, timeout)
        if ok:
            _state["login"] = int(login_id)
            _state["password"] = password
            _state["server"] = server
            _state["path"] = path
            _state["timeout"] = timeout
            _state["connected"] = True
            _persist()
            info = mt5.account_info()
            logger.info("MT5 login OK: account=%s server=%s", login_id, server)
            return {
                "ok": True,
                "login": int(login_id),
                "server": server,
                "account": info._asdict() if info else None,
            }
        _state["connected"] = False
        return {"ok": False, "error": _state["last_error"] or "initialize failed"}


def logout() -> Dict[str, Any]:
    """Disconnect from MT5 and forget credentials."""
    with _lock:
        try:
            mt5.shutdown()
        except Exception as e:
            logger.error("mt5.shutdown raised during logout: %s", e)
        _state["login"] = None
        _state["password"] = None
        _state["server"] = None
        _state["path"] = None
        _state["connected"] = False
        if PERSIST_ENABLED and os.path.exists(PERSIST_PATH):
            try:
                os.remove(PERSIST_PATH)
            except Exception:
                pass
        logger.info("MT5 logout complete")
        return {"ok": True}


def status() -> Dict[str, Any]:
    """Current session status (no password)."""
    with _lock:
        term = None
        try:
            term = mt5.terminal_info()
        except Exception:
            pass
        info = None
        try:
            info = mt5.account_info()
        except Exception:
            pass

        connected = bool(term and term.connected)
        # _state["login"]/["server"] are only set by our own login() call. When we attached to
        # an already-running terminal instead (bootstrap's "attach-existing" path, or a terminal
        # opened manually), they stay None even though the terminal has a real account loaded.
        # Report the live values in that case so this can't say logged_in=false while returning
        # a populated account block.
        login_val = _state["login"] if _state["login"] is not None else (info.login if info else None)
        server_val = _state["server"] or (info.server if info else None)

        return {
            "logged_in": connected and info is not None,
            "login": login_val,
            "server": server_val,
            "path": _state["path"],
            "connected": connected,
            "account": info._asdict() if info else None,
            "last_error": _state["last_error"],
        }


def reconnect() -> bool:
    """Re-attempt initialize() with the stored credentials (used by heartbeat)."""
    with _lock:
        if _state["login"] is None and _state["password"] is None and _state["server"] is None:
            # No credentials known — fall back to plain initialize() which connects to the
            # currently-running terminal, if any.
            return _do_initialize(None, None, None, _state["path"], _state["timeout"])
        return _do_initialize(_state["login"], _state["password"], _state["server"],
                              _state["path"], _state["timeout"])


def bootstrap_from_env_or_disk() -> Dict[str, Any]:
    """At app startup: try env vars, then disk-persisted creds, then bare initialize().

    Returns the first successful result, or the failure of the last attempt.
    """
    env_login = os.environ.get("MT5_LOGIN")
    env_password = os.environ.get("MT5_PASSWORD")
    env_server = os.environ.get("MT5_SERVER")
    env_path = os.environ.get("MT5_PATH")
    env_timeout = int(os.environ.get("MT5_TIMEOUT", 60000))

    # 1. Env vars
    if env_login and env_password and env_server:
        logger.info("MT5 bootstrap: trying env-var credentials (login=%s, server=%s)", env_login, env_server)
        result = login(int(env_login), env_password, env_server, env_path, env_timeout)
        if result.get("ok"):
            return result

    # 2. Persisted file (only if MT5_PERSIST_LOGIN=1)
    persisted = _load_persisted()
    if persisted and persisted.get("login") and persisted.get("password") and persisted.get("server"):
        logger.info("MT5 bootstrap: trying persisted credentials (login=%s)", persisted["login"])
        result = login(int(persisted["login"]), persisted["password"], persisted["server"],
                       persisted.get("path"), persisted.get("timeout", 60000))
        if result.get("ok"):
            return result

    # 3. Bare initialize — connects to whichever terminal is already running & logged in
    logger.info("MT5 bootstrap: falling back to bare initialize()")
    with _lock:
        ok = _do_initialize(None, None, None, env_path, env_timeout)
        _state["connected"] = ok
        if ok:
            _state["path"] = env_path
            return {"ok": True, "mode": "attach-existing"}
        return {"ok": False, "error": _state["last_error"] or "initialize failed"}
