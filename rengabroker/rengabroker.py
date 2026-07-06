#!/usr/bin/env python3
"""RengaBroker — terminal-environment broker for Claude Code (and other agents).

Tracks tmux / WezTerm sessions, windows, panes and the processes inside
them, and exposes that state as JSON — either as one-shot CLI commands or
as a small resident HTTP daemon. The point: an AI agent running inside a
terminal can ask "where am I?" and "what else is running?", then send
keystrokes to or capture output from any pane, without a human relaying
that context by hand.

Design constraints (see CLAUDE.md):
  * Python 3.8+ standard library only — no pip installs, copy one file.
  * Cross-platform: Linux / macOS (tmux + WezTerm), Windows (WezTerm).
  * Error-tolerant: a missing binary or dead server degrades to
    {"available": false, "reason": ...}, never a traceback.
  * The HTTP daemon binds 127.0.0.1 only by default; optional bearer token.

Usage:
  rengabroker.py backends              # which multiplexers are reachable
  rengabroker.py snapshot              # full normalized state as JSON
  rengabroker.py panes                 # flat pane list
  rengabroker.py whereami [--pid N]    # locate the calling process
  rengabroker.py send --target tmux:%3 --text "ls" --enter
  rengabroker.py send --target tmux:%3 --keys C-c
  rengabroker.py capture --target wezterm:7 --lines 100
  rengabroker.py serve [--port 8787] [--token SECRET]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

__version__ = "0.1.0"

DEFAULT_PORT = 8787
DEFAULT_TIMEOUT = 5.0  # seconds per subprocess call
# Field delimiter for tmux -F output. Must be printable ASCII: tmux escapes
# control characters (\x1f becomes the text "\037") and replaces tab with
# "_", so classic unit-separator tricks do not survive. This token is long
# enough that a collision with a real session name / title / path is nil.
UNIT_SEP = "@@RB1F@@"


# ---------------------------------------------------------------------------
# Subprocess plumbing (injectable for tests)
# ---------------------------------------------------------------------------

class CommandError(Exception):
    """A backend command failed in a way the caller should see."""


def default_runner(argv, timeout=DEFAULT_TIMEOUT):
    """Run *argv*, return stdout as str. Raise CommandError on any failure."""
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        raise CommandError("binary not found: %s" % argv[0])
    except subprocess.TimeoutExpired:
        raise CommandError("timed out after %ss: %s" % (timeout, " ".join(argv)))
    except OSError as exc:
        raise CommandError("failed to run %s: %s" % (argv[0], exc))
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise CommandError(
            "%s exited %d: %s" % (argv[0], proc.returncode, detail[:500])
        )
    return proc.stdout


def process_tty(pid, runner=default_runner):
    """Return the controlling tty ("/dev/pts/3" style) of *pid*, or None."""
    if platform.system() == "Windows":
        return None
    try:
        out = runner(["ps", "-o", "tty=", "-p", str(pid)]).strip()
    except CommandError:
        return None
    if not out or out in ("?", "??", "-"):
        return None
    return out if out.startswith("/dev/") else "/dev/" + out


def process_ancestry(pid, runner=default_runner, limit=64):
    """Return [pid, parent, grandparent, ...] up to init, best effort."""
    chain = []
    current = pid
    for _ in range(limit):
        if current is None or current <= 0:
            break
        chain.append(current)
        parent = None
        # Fast path on Linux: /proc/<pid>/stat field 4.
        try:
            with open("/proc/%d/stat" % current, "r") as fh:
                stat = fh.read()
            parent = int(stat.rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            try:
                out = runner(["ps", "-o", "ppid=", "-p", str(current)]).strip()
                parent = int(out) if out else None
            except (CommandError, ValueError):
                parent = None
        if parent == current:
            break
        current = parent
    return chain


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------

class Backend:
    """One terminal multiplexer / emulator adapter.

    To support a new tool (e.g. herdr), subclass this, implement the four
    methods below, and add an instance in make_backends(). Every method
    must catch its own tool-specific failures and either degrade or raise
    CommandError — nothing else should escape.
    """

    name = "base"

    def __init__(self, runner=default_runner):
        self.runner = runner

    def available(self):
        raise NotImplementedError

    def snapshot(self):
        """Normalized state: {"available": bool, "sessions": [...]}.

        Pane schema: {backend, target, session, window_index, window_name,
        pane_id, title, command, pid, cwd, tty, active, width, height}.
        "target" is the canonical id accepted by send()/capture(),
        e.g. "tmux:%5" or "wezterm:7".
        """
        raise NotImplementedError

    def send(self, pane_ref, text=None, keys=None, enter=False):
        raise NotImplementedError

    def capture(self, pane_ref, lines=None):
        raise NotImplementedError

    # -- shared helpers ----------------------------------------------------

    def _unavailable(self, reason):
        return {"available": False, "reason": reason, "sessions": []}

    def iter_panes(self):
        snap = self.snapshot()
        for session in snap.get("sessions", []):
            for window in session.get("windows", []):
                for pane in window.get("panes", []):
                    yield pane


# ---------------------------------------------------------------------------
# tmux backend
# ---------------------------------------------------------------------------

# One line per pane; UNIT_SEP-delimited to survive names with spaces/colons.
TMUX_PANE_FORMAT = UNIT_SEP.join([
    "#{session_name}",
    "#{session_attached}",
    "#{window_index}",
    "#{window_name}",
    "#{window_active}",
    "#{pane_id}",
    "#{pane_index}",
    "#{pane_active}",
    "#{pane_pid}",
    "#{pane_current_command}",
    "#{pane_current_path}",
    "#{pane_title}",
    "#{pane_tty}",
    "#{pane_width}",
    "#{pane_height}",
])


class TmuxBackend(Backend):
    name = "tmux"

    def __init__(self, runner=default_runner, binary="tmux"):
        super().__init__(runner)
        self.binary = binary

    def _tmux(self, *args):
        return self.runner([self.binary] + list(args))

    def available(self):
        if shutil.which(self.binary) is None:
            return False
        try:
            self._tmux("list-sessions", "-F", "#{session_name}")
            return True
        except CommandError:
            return False  # no server running counts as unavailable

    def snapshot(self):
        if shutil.which(self.binary) is None:
            return self._unavailable("tmux binary not found")
        try:
            raw = self._tmux("list-panes", "-a", "-F", TMUX_PANE_FORMAT)
        except CommandError as exc:
            return self._unavailable(str(exc))

        sessions = {}
        for line in raw.splitlines():
            fields = line.split(UNIT_SEP)
            if len(fields) != 15:
                continue  # tolerate weird lines rather than crash
            (sess_name, sess_attached, win_index, win_name, win_active,
             pane_id, pane_index, pane_active, pane_pid, pane_cmd,
             pane_path, pane_title, pane_tty, width, height) = fields

            sess = sessions.setdefault(sess_name, {
                "name": sess_name,
                "attached": sess_attached not in ("", "0"),
                "windows": {},
            })
            win = sess["windows"].setdefault(win_index, {
                "index": _to_int(win_index),
                "name": win_name,
                "active": win_active == "1",
                "panes": [],
            })
            win["panes"].append({
                "backend": self.name,
                "target": "tmux:%s" % pane_id,
                "session": sess_name,
                "window_index": _to_int(win_index),
                "window_name": win_name,
                "pane_id": pane_id,
                "pane_index": _to_int(pane_index),
                "title": pane_title,
                "command": pane_cmd,
                "pid": _to_int(pane_pid),
                "cwd": pane_path,
                "tty": pane_tty,
                "active": pane_active == "1",
                "width": _to_int(width),
                "height": _to_int(height),
            })

        return {
            "available": True,
            "sessions": [
                {
                    "name": s["name"],
                    "attached": s["attached"],
                    "windows": [s["windows"][k] for k in sorted(
                        s["windows"], key=_sort_key)],
                }
                for s in sessions.values()
            ],
        }

    def send(self, pane_ref, text=None, keys=None, enter=False):
        if text is not None:
            # -l = literal: the text is typed as-is, not parsed as key names.
            self._tmux("send-keys", "-t", pane_ref, "-l", "--", text)
        if keys:
            self._tmux("send-keys", "-t", pane_ref, *keys.split())
        if enter:
            self._tmux("send-keys", "-t", pane_ref, "Enter")

    def capture(self, pane_ref, lines=None):
        args = ["capture-pane", "-p", "-t", pane_ref]
        if lines:
            args += ["-S", "-%d" % lines]
        return self._tmux(*args)

    def locate(self, env, pid=None):
        """Find the pane the caller lives in. Returns a pane dict or None."""
        panes = list(self.iter_panes())
        if not panes:
            return None
        # 1. $TMUX_PANE is authoritative when present.
        env_pane = env.get("TMUX_PANE")
        if env_pane:
            for pane in panes:
                if pane["pane_id"] == env_pane:
                    return pane
        if pid is None:
            return None
        # 2. Same controlling tty as some pane.
        tty = process_tty(pid, self.runner)
        if tty:
            for pane in panes:
                if pane["tty"] == tty:
                    return pane
        # 3. The pane's shell is an ancestor of the caller.
        ancestors = set(process_ancestry(pid, self.runner))
        for pane in panes:
            if pane["pid"] in ancestors:
                return pane
        return None


# ---------------------------------------------------------------------------
# WezTerm backend
# ---------------------------------------------------------------------------

class WeztermBackend(Backend):
    name = "wezterm"

    def __init__(self, runner=default_runner, binary="wezterm"):
        super().__init__(runner)
        self.binary = binary

    def _cli(self, *args):
        return self.runner([self.binary, "cli"] + list(args))

    def available(self):
        if shutil.which(self.binary) is None:
            return False
        try:
            self._cli("list", "--format", "json")
            return True
        except CommandError:
            return False

    def snapshot(self):
        if shutil.which(self.binary) is None:
            return self._unavailable("wezterm binary not found")
        try:
            raw = self._cli("list", "--format", "json")
            entries = json.loads(raw)
        except CommandError as exc:
            return self._unavailable(str(exc))
        except ValueError as exc:
            return self._unavailable("bad JSON from wezterm cli list: %s" % exc)

        # WezTerm's model: window > tab > pane. Map workspace to "session",
        # (window_id, tab_id) to a window, to line up with the tmux schema.
        sessions = {}
        for entry in entries:
            workspace = entry.get("workspace") or "default"
            sess = sessions.setdefault(workspace, {
                "name": workspace, "attached": True, "windows": {},
            })
            win_key = (entry.get("window_id"), entry.get("tab_id"))
            win = sess["windows"].setdefault(win_key, {
                "index": entry.get("tab_id"),
                "name": entry.get("tab_title") or entry.get("title") or "",
                "active": bool(entry.get("is_active")),
                "panes": [],
            })
            size = entry.get("size") or {}
            win["panes"].append({
                "backend": self.name,
                "target": "wezterm:%s" % entry.get("pane_id"),
                "session": workspace,
                "window_index": entry.get("tab_id"),
                "window_name": win["name"],
                "pane_id": str(entry.get("pane_id")),
                "pane_index": entry.get("pane_id"),
                "title": entry.get("title") or "",
                "command": None,  # wezterm cli list does not expose it
                "pid": None,
                "cwd": _file_url_to_path(entry.get("cwd")),
                "tty": entry.get("tty_name"),
                "active": bool(entry.get("is_active")),
                "width": size.get("cols"),
                "height": size.get("rows"),
            })

        return {
            "available": True,
            "sessions": [
                {
                    "name": s["name"],
                    "attached": s["attached"],
                    "windows": list(s["windows"].values()),
                }
                for s in sessions.values()
            ],
        }

    def send(self, pane_ref, text=None, keys=None, enter=False):
        if keys:
            raise CommandError(
                "wezterm backend does not support --keys; use --text")
        if text is not None:
            self._cli("send-text", "--no-paste", "--pane-id", pane_ref, text)
        if enter:
            self._cli("send-text", "--no-paste", "--pane-id", pane_ref, "\r")

    def capture(self, pane_ref, lines=None):
        args = ["get-text", "--pane-id", pane_ref]
        if lines:
            try:
                return self._cli(*args, "--start-line", "-%d" % lines)
            except CommandError:
                pass  # older wezterm: fall through to plain get-text
        return self._cli(*args)

    def locate(self, env, pid=None):
        env_pane = env.get("WEZTERM_PANE")
        tty = process_tty(pid, self.runner) if pid else None
        for pane in self.iter_panes():
            if env_pane is not None and pane["pane_id"] == str(env_pane):
                return pane
            if tty and pane["tty"] == tty:
                return pane
        return None


# ---------------------------------------------------------------------------
# Broker core: state aggregation + query handling
# ---------------------------------------------------------------------------

class Broker:
    """Aggregates backends behind one query surface (CLI and HTTP share it)."""

    def __init__(self, backends=None, cache_ttl=1.0):
        self.backends = backends if backends is not None else make_backends()
        self.cache_ttl = cache_ttl
        self._cache = None
        self._cache_at = 0.0
        self._lock = threading.Lock()

    def backends_info(self):
        info = {}
        for backend in self.backends:
            try:
                info[backend.name] = {"available": backend.available()}
            except Exception as exc:  # a broken adapter must not sink the rest
                info[backend.name] = {"available": False, "reason": str(exc)}
        return info

    def snapshot(self, fresh=False):
        with self._lock:
            now = time.monotonic()
            if (not fresh and self._cache is not None
                    and now - self._cache_at < self.cache_ttl):
                return self._cache
            result = {
                "broker": "rengabroker",
                "version": __version__,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "host": socket.gethostname(),
                "platform": platform.system(),
                "backends": {},
            }
            for backend in self.backends:
                try:
                    result["backends"][backend.name] = backend.snapshot()
                except Exception as exc:
                    result["backends"][backend.name] = {
                        "available": False, "reason": str(exc), "sessions": [],
                    }
            self._cache = result
            self._cache_at = now
            return result

    def panes(self):
        flat = []
        for state in self.snapshot()["backends"].values():
            for session in state.get("sessions", []):
                for window in session.get("windows", []):
                    flat.extend(window.get("panes", []))
        return flat

    def whereami(self, pid=None, env=None):
        env = env if env is not None else os.environ
        pid = pid if pid is not None else os.getpid()
        for backend in self.backends:
            locate = getattr(backend, "locate", None)
            if locate is None:
                continue
            try:
                pane = locate(env, pid)
            except Exception:
                continue
            if pane:
                return {"found": True, "pid": pid, "pane": pane}
        return {"found": False, "pid": pid, "pane": None}

    def _resolve(self, target):
        """Split "tmux:%5" into (backend, "%5"). Bare tmux targets pass through."""
        if ":" in target:
            prefix, _, ref = target.partition(":")
            for backend in self.backends:
                if backend.name == prefix:
                    return backend, ref
        # No known prefix: assume a native tmux target like "mysess:1.2".
        for backend in self.backends:
            if backend.name == "tmux":
                return backend, target
        raise CommandError("cannot resolve target %r" % target)

    def send(self, target, text=None, keys=None, enter=False):
        backend, ref = self._resolve(target)
        backend.send(ref, text=text, keys=keys, enter=enter)
        return {"ok": True, "target": target}

    def capture(self, target, lines=None):
        backend, ref = self._resolve(target)
        return {"target": target, "content": backend.capture(ref, lines=lines)}


def make_backends(runner=default_runner):
    return [TmuxBackend(runner), WeztermBackend(runner)]


# ---------------------------------------------------------------------------
# HTTP daemon
# ---------------------------------------------------------------------------

class BrokerHTTPHandler(BaseHTTPRequestHandler):
    server_version = "RengaBroker/" + __version__
    broker = None   # set by serve()
    token = None

    # -- helpers -----------------------------------------------------------

    def _reply(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        if not self.token:
            return True
        header = self.headers.get("Authorization", "")
        return header == "Bearer %s" % self.token

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise CommandError("request body is not valid JSON")
        if not isinstance(data, dict):
            raise CommandError("request body must be a JSON object")
        return data

    def log_message(self, fmt, *args):  # quiet by default
        if os.environ.get("RENGABROKER_DEBUG"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # -- routes ------------------------------------------------------------

    def do_GET(self):
        if not self._authorized():
            return self._reply(401, {"error": "unauthorized"})
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/health":
                return self._reply(200, {"ok": True, "version": __version__})
            if parsed.path == "/backends":
                return self._reply(200, self.broker.backends_info())
            if parsed.path == "/snapshot":
                fresh = query.get("fresh", ["0"])[0] in ("1", "true")
                return self._reply(200, self.broker.snapshot(fresh=fresh))
            if parsed.path == "/panes":
                return self._reply(200, {"panes": self.broker.panes()})
            if parsed.path == "/whereami":
                pid = query.get("pid", [None])[0]
                pid = int(pid) if pid else None
                return self._reply(200, self.broker.whereami(pid=pid))
            return self._reply(404, {"error": "no such endpoint",
                                     "endpoints": HTTP_ENDPOINTS})
        except CommandError as exc:
            return self._reply(502, {"error": str(exc)})
        except Exception as exc:
            return self._reply(500, {"error": "internal: %s" % exc})

    def do_POST(self):
        if not self._authorized():
            return self._reply(401, {"error": "unauthorized"})
        parsed = urllib.parse.urlparse(self.path)
        try:
            body = self._read_json_body()
            if parsed.path == "/send":
                target = body.get("target")
                if not target:
                    raise CommandError("'target' is required")
                if body.get("text") is None and not body.get("keys") \
                        and not body.get("enter"):
                    raise CommandError("one of 'text', 'keys', 'enter' is required")
                return self._reply(200, self.broker.send(
                    target,
                    text=body.get("text"),
                    keys=body.get("keys"),
                    enter=bool(body.get("enter")),
                ))
            if parsed.path == "/capture":
                target = body.get("target")
                if not target:
                    raise CommandError("'target' is required")
                lines = body.get("lines")
                lines = int(lines) if lines else None
                return self._reply(200, self.broker.capture(target, lines=lines))
            return self._reply(404, {"error": "no such endpoint",
                                     "endpoints": HTTP_ENDPOINTS})
        except CommandError as exc:
            return self._reply(400, {"error": str(exc)})
        except Exception as exc:
            return self._reply(500, {"error": "internal: %s" % exc})


HTTP_ENDPOINTS = [
    "GET  /health",
    "GET  /backends",
    "GET  /snapshot[?fresh=1]",
    "GET  /panes",
    "GET  /whereami?pid=<pid>",
    "POST /send     {target, text?, keys?, enter?}",
    "POST /capture  {target, lines?}",
]


def serve(broker, host, port, token=None):
    handler = type("BoundHandler", (BrokerHTTPHandler,), {
        "broker": broker, "token": token,
    })
    httpd = ThreadingHTTPServer((host, port), handler)
    print("rengabroker %s listening on http://%s:%d  (token %s)" % (
        __version__, host, port, "required" if token else "disabled"))
    print("endpoints: " + ", ".join(e.split()[1] for e in HTTP_ENDPOINTS))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        httpd.server_close()


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sort_key(value):
    number = _to_int(value)
    return (0, number) if number is not None else (1, str(value))


def _file_url_to_path(url):
    if not url:
        return None
    if url.startswith("file://"):
        parsed = urllib.parse.urlparse(url)
        return urllib.parse.unquote(parsed.path) or None
    return url


def _print_json(payload):
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="rengabroker",
        description="Terminal-environment broker for Claude Code: "
                    "query and drive tmux / WezTerm panes as JSON.",
    )
    parser.add_argument("--version", action="version",
                        version="rengabroker " + __version__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("backends", help="show which backends are reachable")

    snap = sub.add_parser("snapshot", help="full normalized state as JSON")
    snap.add_argument("--fresh", action="store_true",
                      help="bypass the snapshot cache")

    sub.add_parser("panes", help="flat list of every pane")

    where = sub.add_parser("whereami",
                           help="locate a process inside the multiplexers")
    where.add_argument("--pid", type=int, default=None,
                       help="process to locate (default: this CLI's parent)")

    send = sub.add_parser("send", help="send text or keys to a pane")
    send.add_argument("--target", required=True,
                      help='pane target, e.g. "tmux:%%3", "wezterm:7", '
                           'or a native tmux target like "main:1.2"')
    send.add_argument("--text", help="literal text to type into the pane")
    send.add_argument("--keys", help='tmux key names, e.g. "C-c" or "Up Enter"')
    send.add_argument("--enter", action="store_true",
                      help="press Enter after sending")

    cap = sub.add_parser("capture", help="capture a pane's visible text")
    cap.add_argument("--target", required=True)
    cap.add_argument("--lines", type=int, default=None,
                     help="include N lines of scrollback")
    cap.add_argument("--raw", action="store_true",
                     help="print plain text instead of JSON")

    srv = sub.add_parser("serve", help="run the resident HTTP daemon")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=DEFAULT_PORT)
    srv.add_argument("--token", default=os.environ.get("RENGABROKER_TOKEN"),
                     help="bearer token (default: $RENGABROKER_TOKEN)")
    srv.add_argument("--cache-ttl", type=float, default=1.0,
                     help="snapshot cache lifetime in seconds")

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    broker = Broker()

    try:
        if args.command == "backends":
            _print_json(broker.backends_info())
        elif args.command == "snapshot":
            _print_json(broker.snapshot(fresh=args.fresh))
        elif args.command == "panes":
            _print_json({"panes": broker.panes()})
        elif args.command == "whereami":
            pid = args.pid if args.pid is not None else os.getppid()
            result = broker.whereami(pid=pid)
            _print_json(result)
            return 0 if result["found"] else 3
        elif args.command == "send":
            if args.text is None and not args.keys and not args.enter:
                raise CommandError("provide --text, --keys, and/or --enter")
            _print_json(broker.send(args.target, text=args.text,
                                    keys=args.keys, enter=args.enter))
        elif args.command == "capture":
            result = broker.capture(args.target, lines=args.lines)
            if args.raw:
                sys.stdout.write(result["content"])
            else:
                _print_json(result)
        elif args.command == "serve":
            broker.cache_ttl = args.cache_ttl
            serve(broker, args.host, args.port, token=args.token)
    except CommandError as exc:
        print("rengabroker: error: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
