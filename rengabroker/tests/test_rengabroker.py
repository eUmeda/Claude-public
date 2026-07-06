"""Tests for rengabroker.

Two layers:
  * Unit tests — backends fed by a FakeRunner with canned tmux / wezterm
    output. Run anywhere, no multiplexer needed.
  * Live smoke tests — skipped automatically unless a usable tmux binary
    is present. They create a throwaway detached session, exercise
    snapshot / send / capture / whereami against it, and kill it.

Run with:  python3 -m unittest discover -s rengabroker/tests -v
"""

import json
import os
import shutil
import subprocess
import sys
import time
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import rengabroker as rb  # noqa: E402

US = rb.UNIT_SEP


def tmux_line(session="work", attached="1", win_index="0", win_name="edit",
              win_active="1", pane_id="%0", pane_index="0", pane_active="1",
              pid="100", command="vim", path="/home/u/proj", title="vim",
              tty="/dev/pts/1", width="80", height="24"):
    return US.join([session, attached, win_index, win_name, win_active,
                    pane_id, pane_index, pane_active, pid, command, path,
                    title, tty, width, height])


WEZTERM_LIST = json.dumps([
    {
        "window_id": 0, "tab_id": 0, "pane_id": 7, "workspace": "default",
        "title": "zsh", "tab_title": "shell", "is_active": True,
        "cwd": "file://host/Users/u/proj",
        "tty_name": "/dev/ttys003",
        "size": {"rows": 24, "cols": 80},
    },
])


class FakeRunner:
    """Callable standing in for default_runner; records calls."""

    def __init__(self, responses):
        # responses: list of (predicate(argv) -> bool, result str | Exception)
        self.responses = responses
        self.calls = []

    def __call__(self, argv, timeout=None):
        self.calls.append(list(argv))
        for predicate, result in self.responses:
            if predicate(argv):
                if isinstance(result, Exception):
                    raise result
                return result
        raise rb.CommandError("FakeRunner: unexpected command %r" % (argv,))


def has(*words):
    return lambda argv: all(w in argv for w in words)


class TmuxBackendTest(unittest.TestCase):
    def make_backend(self, panes_output):
        runner = FakeRunner([
            (has("list-panes"), panes_output),
        ])
        backend = rb.TmuxBackend(runner)
        backend.binary = sys.executable  # something which(...) can find
        return backend, runner

    def test_snapshot_normalizes_sessions_windows_panes(self):
        output = "\n".join([
            tmux_line(pane_id="%0", pane_index="0"),
            tmux_line(pane_id="%1", pane_index="1", pane_active="0",
                      command="python", title="repl"),
            tmux_line(session="logs", attached="0", win_index="0",
                      win_name="tail", pane_id="%2", pid="200",
                      command="tail", tty="/dev/pts/2"),
        ])
        backend, _ = self.make_backend(output)
        snap = backend.snapshot()

        self.assertTrue(snap["available"])
        self.assertEqual(len(snap["sessions"]), 2)
        work = next(s for s in snap["sessions"] if s["name"] == "work")
        self.assertTrue(work["attached"])
        self.assertEqual(len(work["windows"][0]["panes"]), 2)
        pane = work["windows"][0]["panes"][0]
        self.assertEqual(pane["target"], "tmux:%0")
        self.assertEqual(pane["cwd"], "/home/u/proj")
        self.assertEqual(pane["pid"], 100)

    def test_snapshot_degrades_when_server_down(self):
        runner = FakeRunner([
            (has("list-panes"), rb.CommandError("no server running")),
        ])
        backend = rb.TmuxBackend(runner)
        backend.binary = sys.executable
        snap = backend.snapshot()
        self.assertFalse(snap["available"])
        self.assertIn("no server", snap["reason"])
        self.assertEqual(snap["sessions"], [])

    def test_snapshot_degrades_when_binary_missing(self):
        backend = rb.TmuxBackend(FakeRunner([]))
        backend.binary = "definitely-not-a-real-binary-xyz"
        snap = backend.snapshot()
        self.assertFalse(snap["available"])

    def test_send_literal_text_then_enter(self):
        backend, runner = self.make_backend("")
        runner.responses.append((has("send-keys"), ""))
        backend.send("%3", text="echo hi", enter=True)
        sends = [c for c in runner.calls if "send-keys" in c]
        self.assertEqual(sends[0][-4:], ["%3", "-l", "--", "echo hi"])
        self.assertEqual(sends[1][-1], "Enter")

    def test_locate_by_env_pane(self):
        backend, _ = self.make_backend(tmux_line(pane_id="%9"))
        pane = backend.locate({"TMUX_PANE": "%9"}, pid=None)
        self.assertIsNotNone(pane)
        self.assertEqual(pane["target"], "tmux:%9")

    def test_locate_by_tty(self):
        output = tmux_line(pane_id="%4", tty="/dev/pts/7")
        runner = FakeRunner([
            (has("list-panes"), output),
            (has("-o", "tty="), "pts/7\n"),
        ])
        backend = rb.TmuxBackend(runner)
        backend.binary = sys.executable
        pane = backend.locate({}, pid=12345)
        self.assertIsNotNone(pane)
        self.assertEqual(pane["pane_id"], "%4")


class WeztermBackendTest(unittest.TestCase):
    def make_backend(self):
        runner = FakeRunner([
            (has("cli", "list"), WEZTERM_LIST),
            (has("cli", "send-text"), ""),
        ])
        backend = rb.WeztermBackend(runner)
        backend.binary = sys.executable
        return backend, runner

    def test_snapshot_maps_workspace_to_session(self):
        backend, _ = self.make_backend()
        snap = backend.snapshot()
        self.assertTrue(snap["available"])
        sess = snap["sessions"][0]
        self.assertEqual(sess["name"], "default")
        pane = sess["windows"][0]["panes"][0]
        self.assertEqual(pane["target"], "wezterm:7")
        self.assertEqual(pane["cwd"], "/Users/u/proj")
        self.assertEqual(pane["width"], 80)

    def test_send_rejects_keys(self):
        backend, _ = self.make_backend()
        with self.assertRaises(rb.CommandError):
            backend.send("7", keys="C-c")

    def test_locate_by_env(self):
        backend, _ = self.make_backend()
        pane = backend.locate({"WEZTERM_PANE": "7"}, pid=None)
        self.assertIsNotNone(pane)
        self.assertEqual(pane["backend"], "wezterm")


class BrokerTest(unittest.TestCase):
    def make_broker(self):
        tmux_runner = FakeRunner([
            (has("list-panes"), tmux_line(pane_id="%0")),
            (has("send-keys"), ""),
            (has("capture-pane"), "captured!\n"),
        ])
        tmux = rb.TmuxBackend(tmux_runner)
        tmux.binary = sys.executable
        wez = rb.WeztermBackend(FakeRunner([(has("cli", "list"), WEZTERM_LIST)]))
        wez.binary = sys.executable
        return rb.Broker(backends=[tmux, wez], cache_ttl=60)

    def test_panes_flattens_across_backends(self):
        broker = self.make_broker()
        targets = {p["target"] for p in broker.panes()}
        self.assertEqual(targets, {"tmux:%0", "wezterm:7"})

    def test_snapshot_is_cached(self):
        broker = self.make_broker()
        first = broker.snapshot()
        second = broker.snapshot()
        self.assertIs(first, second)
        self.assertIsNot(first, broker.snapshot(fresh=True))

    def test_target_resolution(self):
        broker = self.make_broker()
        result = broker.capture("tmux:%0", lines=10)
        self.assertEqual(result["content"], "captured!\n")
        # A native tmux target (no known prefix) routes to tmux too.
        self.assertTrue(broker.send("work:0.0", text="x")["ok"])

    def test_whereami_not_found_is_graceful(self):
        broker = self.make_broker()
        result = broker.whereami(pid=999999, env={})
        self.assertFalse(result["found"])

    def test_one_broken_backend_does_not_sink_snapshot(self):
        class ExplodingBackend(rb.Backend):
            name = "boom"

            def available(self):
                raise RuntimeError("kaboom")

            def snapshot(self):
                raise RuntimeError("kaboom")

        broker = rb.Broker(backends=[ExplodingBackend()], cache_ttl=0)
        snap = broker.snapshot()
        self.assertFalse(snap["backends"]["boom"]["available"])
        info = broker.backends_info()
        self.assertFalse(info["boom"]["available"])


class HelperTest(unittest.TestCase):
    def test_file_url_to_path(self):
        self.assertEqual(rb._file_url_to_path("file://h/a%20b/c"), "/a b/c")
        self.assertEqual(rb._file_url_to_path("/plain/path"), "/plain/path")
        self.assertIsNone(rb._file_url_to_path(None))

    def test_to_int(self):
        self.assertEqual(rb._to_int("42"), 42)
        self.assertIsNone(rb._to_int("x"))


def _tmux_usable():
    if shutil.which("tmux") is None:
        return False
    probe = subprocess.run(["tmux", "start-server", ";", "kill-server"],
                           capture_output=True)
    return probe.returncode == 0


@unittest.skipUnless(_tmux_usable(), "tmux not available")
class LiveTmuxSmokeTest(unittest.TestCase):
    """End-to-end against a real, throwaway tmux session."""

    @classmethod
    def setUpClass(cls):
        cls.session = "rengabroker-test-" + uuid.uuid4().hex[:8]
        subprocess.run(["tmux", "new-session", "-d", "-s", cls.session,
                        "-x", "80", "-y", "24"], check=True)
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["tmux", "kill-session", "-t", cls.session],
                       capture_output=True)

    def broker(self):
        return rb.Broker(cache_ttl=0)

    def test_snapshot_sees_test_session(self):
        snap = self.broker().snapshot()
        self.assertTrue(snap["backends"]["tmux"]["available"])
        names = [s["name"] for s in snap["backends"]["tmux"]["sessions"]]
        self.assertIn(self.session, names)

    def test_send_and_capture_roundtrip(self):
        broker = self.broker()
        pane = next(p for p in broker.panes() if p["session"] == self.session)
        marker = "renga-" + uuid.uuid4().hex[:8]
        broker.send(pane["target"], text="echo %s" % marker, enter=True)
        deadline = time.time() + 5
        content = ""
        while time.time() < deadline:
            content = broker.capture(pane["target"], lines=50)["content"]
            # Expect the marker on an output line, not just the echoed command.
            if content.count(marker) >= 2:
                break
            time.sleep(0.2)
        self.assertIn(marker, content)

    def test_whereami_via_env_pane(self):
        broker = self.broker()
        pane = next(p for p in broker.panes() if p["session"] == self.session)
        result = broker.whereami(pid=0, env={"TMUX_PANE": pane["pane_id"]})
        self.assertTrue(result["found"])
        self.assertEqual(result["pane"]["session"], self.session)


if __name__ == "__main__":
    unittest.main()
