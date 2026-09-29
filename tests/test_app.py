import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

import app


EXAMPLE = {
    "name": "Home VM", "description": "Test machine", "host": "192.0.2.10",
    "username": "vmuser", "port": 49152, "key_path": "", "jump_host": "",
    "timeout": 10,
}


class ValidationTests(unittest.TestCase):
    def test_embedded_ssh_prefers_windows_client_and_falls_back_to_path(self):
        with patch("app.sys.platform", "win32"), patch.dict("app.os.environ", {"SystemRoot": "C:/TestWindows"}):
            with patch("app.Path.is_file", return_value=True), patch("app.shutil.which") as which:
                self.assertEqual(app.embedded_ssh_executable(), str(Path("C:/TestWindows/System32/OpenSSH/ssh.exe")))
                which.assert_not_called()
            with patch("app.Path.is_file", return_value=False), patch("app.shutil.which", return_value="fallback-ssh"):
                self.assertEqual(app.embedded_ssh_executable(), "fallback-ssh")

    def test_valid_entry(self):
        self.assertEqual(app.validate_entry(EXAMPLE)["port"], 49152)
        self.assertTrue(app.valid_host("2001:db8::1"))
        self.assertTrue(app.valid_host("my-ssh-alias"))

    def test_rejects_unsafe_or_invalid_input(self):
        for replacement in ["-oProxyCommand=bad", "host;calc", "", "bad..host"]:
            with self.subTest(host=replacement):
                with self.assertRaises(ValueError):
                    app.validate_entry({**EXAMPLE, "host": replacement})
        for replacement in [0, 65536, "22", True]:
            with self.subTest(port=replacement):
                with self.assertRaises(ValueError):
                    app.validate_entry({**EXAMPLE, "port": replacement})
        with self.assertRaises(ValueError):
            app.validate_entry({**EXAMPLE, "jump_host": "-oProxyCommand=calc"})
        with self.assertRaises(ValueError):
            app.validate_entry({**EXAMPLE, "username": "user;calc"})

    def test_jump_host_format(self):
        self.assertEqual(app.validate_entry({**EXAMPLE, "jump_host": "admin@gateway:2222"})["jump_host"], "admin@gateway:2222")
        with self.assertRaises(ValueError):
            app.validate_entry({**EXAMPLE, "jump_host": "gateway:99999"})


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "connections.json"
        self.store = app.ConnectionStore(self.path)

    def test_add_edit_delete_persist(self):
        self.assertEqual(self.store.list(), [])
        first = self.store.save(EXAMPLE)
        self.assertEqual(self.store.list()[0]["id"], first["id"])
        updated = self.store.save({**EXAMPLE, "name": "Renamed"}, first["id"])
        self.assertEqual(updated["id"], first["id"])
        self.assertEqual(self.store.get(first["id"])["name"], "Renamed")
        self.assertNotIn("password", self.path.read_text(encoding="utf-8"))
        self.store.delete(first["id"])
        self.assertEqual(self.store.list(), [])

    def test_missing_entry_and_invalid_data(self):
        with self.assertRaises(ValueError):
            self.store.delete("unknown")
        with self.assertRaises(ValueError):
            self.store.save({**EXAMPLE, "port": 0})
        self.assertFalse(self.path.exists())
        self.path.write_text('{"wrong": "shape"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.list()


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.api = app.Api(app.ConnectionStore(Path(self.directory.name) / "connections.json"))
        self.entry = self.api.save_connection(EXAMPLE)["data"]

    def test_crud_and_errors(self):
        self.assertEqual(len(self.api.list_connections()["data"]), 1)
        self.assertFalse(self.api.save_connection({**EXAMPLE, "host": "bad host"})["ok"])
        self.assertTrue(self.api.delete_connection(self.entry["id"])["ok"])
        self.assertFalse(self.api.delete_connection(self.entry["id"])["ok"])

    @patch("app.subprocess.Popen")
    @patch("app.shutil.which", return_value="C:/Windows/System32/command.exe")
    def test_connect_uses_named_terminal_tab_without_shell(self, which, popen):
        result = self.api.connect(self.entry["id"])
        self.assertTrue(result["ok"])
        args, kwargs = popen.call_args
        self.assertEqual(args[0], [
            "wt", "-w", "ssh-sketchbook", "nt", "--title", "Home VM",
            "--suppressApplicationTitle", "ssh", "-p", "49152", "-o",
            "ConnectTimeout=10", "vmuser@192.0.2.10",
        ])
        self.assertIs(kwargs["shell"], False)

    @patch("app.subprocess.Popen")
    @patch("app.shutil.which", return_value="C:/Windows/System32/command.exe")
    def test_connect_all_opens_every_machine_in_one_window(self, which, popen):
        self.api.save_connection({**EXAMPLE, "name": "Gateway; admin", "host": "gateway.local", "port": 22})
        result = self.api.connect_all()
        self.assertEqual(result, {"ok": True, "data": 2})
        self.assertEqual(popen.call_count, 1)
        args = popen.call_args.args[0]
        self.assertEqual(args[:3], ["wt", "-w", "ssh-sketchbook"])
        self.assertEqual(args.count(";"), 1)
        self.assertIn("Gateway  admin", args)
        self.assertIn("vmuser@gateway.local", args)
        self.assertEqual(args.count("nt"), 2)
        self.assertIs(popen.call_args.kwargs["shell"], False)

    @patch("app.subprocess.Popen")
    @patch("app.shutil.which", side_effect=lambda name: None if name == "wt" else "ssh.exe")
    def test_missing_terminal_does_not_launch(self, which, popen):
        result = self.api.connect(self.entry["id"])
        self.assertFalse(result["ok"])
        self.assertIn("Windows Terminal", result["error"])
        popen.assert_not_called()

    @patch("app.subprocess.Popen")
    @patch("app.shutil.which", return_value="command.exe")
    def test_invalid_key_prevents_open_all_partial_launch(self, which, popen):
        self.api.save_connection({**EXAMPLE, "name": "Other", "key_path": "C:/missing/key"})
        result = self.api.connect_all()
        self.assertFalse(result["ok"])
        self.assertIn("Other", result["error"])
        popen.assert_not_called()

    @patch("app.subprocess.Popen")
    def test_open_all_empty_list(self, popen):
        self.api.delete_connection(self.entry["id"])
        result = self.api.connect_all()
        self.assertFalse(result["ok"])
        popen.assert_not_called()

    @patch("app.subprocess.Popen")
    @patch("app.shutil.which", return_value="command.exe")
    def test_semicolon_in_key_path_is_rejected(self, which, popen):
        with patch("app.Path.is_file", return_value=True):
            self.api.save_connection({**EXAMPLE, "key_path": "C:/keys/a;b"}, self.entry["id"])
            result = self.api.connect(self.entry["id"])
        self.assertFalse(result["ok"])
        popen.assert_not_called()

    @patch("app.probe", side_effect=lambda entry: {"id": entry["id"], "ping": False, "ssh_port": True})
    def test_refresh_returns_independent_ping_and_ssh_status(self, probe):
        result = self.api.refresh_status()
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], [{"id": self.entry["id"], "ping": False, "ssh_port": True}])


class FakePty:
    def __init__(self):
        self.incoming = queue.Queue()
        self.read_started = threading.Event()
        self.ended = threading.Event()
        self.writes = []
        self.resizes = []
        self.closed = False
        self.alive = True
        self.exitstatus = 0

    def isalive(self):
        return self.alive

    def read(self, size=1024):
        self.read_started.set()
        item = self.incoming.get(timeout=3)
        if item is None:
            self.ended.set()
            raise EOFError()
        if isinstance(item, Exception):
            raise item
        return item

    def write(self, data):
        self.writes.append(data)

    def setwinsize(self, rows, cols):
        self.resizes.append((rows, cols))

    def close(self, force=False):
        self.closed = True
        self.alive = False
        self.incoming.put(None)


class TerminalSessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.api = app.Api(app.ConnectionStore(Path(self.directory.name) / "connections.json"))
        self.addCleanup(self.api.shutdown)
        self.entry = self.api.save_connection(EXAMPLE)["data"]
        self.ptys = []
        self.spawns = []

        def spawn(argv, **kwargs):
            self.spawns.append((argv, kwargs))
            pty = FakePty()
            self.ptys.append(pty)
            return pty

        fake_winpty = types.SimpleNamespace(
            Backend=types.SimpleNamespace(WinPTY=1),
            PtyProcess=types.SimpleNamespace(spawn=spawn),
        )
        patcher = patch.dict(sys.modules, {"winpty": fake_winpty})
        patcher.start()
        self.addCleanup(patcher.stop)
        ssh_patcher = patch("app.embedded_ssh_executable", return_value="C:/Windows/System32/OpenSSH/ssh.exe")
        ssh_patcher.start()
        self.addCleanup(ssh_patcher.stop)

    def start(self):
        result = self.api.start_session(self.entry["id"], 100, 30)
        self.assertTrue(result["ok"], result)
        return result["data"]["id"]

    def test_lifecycle_nonblocking_poll_and_final_output(self):
        session_id = self.start()
        pty = self.ptys[0]
        self.assertEqual(self.spawns[0], (
            ["C:/Windows/System32/OpenSSH/ssh.exe", *app.ssh_args(self.entry)[1:]],
            {"dimensions": (30, 100), "backend": 1},
        ))
        self.assertTrue(pty.read_started.wait(1))
        self.assertEqual(self.api.read_session(session_id)["data"]["running"], True)
        self.assertTrue(self.api.write_session(session_id, "ls\r")["ok"])
        self.assertEqual(pty.writes, ["ls\r"])
        self.assertTrue(self.api.resize_session(session_id, 120, 40)["ok"])
        self.assertEqual(pty.resizes, [(40, 120)])
        pty.exitstatus = 23
        pty.incoming.put("hello")
        pty.incoming.put(" world")
        pty.incoming.put(None)
        self.assertTrue(pty.ended.wait(1))
        self.api.sessions.get(session_id).reader.join(1)
        result = self.api.read_session(session_id)["data"]
        self.assertEqual(result["output"], "hello world")
        self.assertFalse(result["running"])
        self.assertEqual(result["exit_code"], 23)
        self.assertEqual(self.api.read_session(session_id)["data"]["output"], "")
        self.assertFalse(self.api.write_session(session_id, "after")["ok"])
        self.assertTrue(self.api.close_session(session_id)["ok"])
        self.assertTrue(pty.closed)
        self.assertFalse(self.api.read_session(session_id)["ok"])

    def test_dead_child_with_blocked_reader_drains_final_output(self):
        session_id = self.start()
        pty = self.ptys[-1]
        self.assertTrue(pty.read_started.wait(1))
        pty.exitstatus = 255
        pty.incoming.put("ssh: connection refused\r\n")
        # The PTY keeps read() blocked even though the child is already gone.
        pty.alive = False
        session = self.api.sessions.get(session_id)
        session.watcher.join(timeout=2)
        self.assertFalse(session.watcher.is_alive())
        self.assertFalse(session.reader.is_alive())
        self.assertTrue(pty.closed)
        result = self.api.read_session(session_id)["data"]
        self.assertEqual(result["output"], "ssh: connection refused\r\n")
        self.assertFalse(result["running"])
        self.assertEqual(result["exit_code"], 255)
        self.assertEqual(self.api.read_session(session_id)["data"]["output"], "")

    def test_bounded_output_reports_truncation_once(self):
        session_id = self.start()
        pty = self.ptys[0]
        pty.incoming.put("X" * (app.TerminalSession.OUTPUT_LIMIT + 30))
        pty.incoming.put(None)
        self.api.sessions.get(session_id).reader.join(1)
        result = self.api.read_session(session_id)["data"]
        self.assertEqual(len(result["output"]), app.TerminalSession.OUTPUT_LIMIT)
        self.assertTrue(result["truncated"])
        self.assertFalse(self.api.read_session(session_id)["data"]["truncated"])

    def test_validation_limits_and_missing_dependencies(self):
        self.assertFalse(self.api.start_session("missing", 80, 24)["ok"])
        for cols, rows in [(0, 24), (501, 24), (80, 0), (80, 201), (True, 24), (80, "24")]:
            with self.subTest(cols=cols, rows=rows):
                self.assertFalse(self.api.start_session(self.entry["id"], cols, rows)["ok"])
        self.assertEqual(self.spawns, [])
        with patch.dict(sys.modules, {"winpty": None}):
            result = self.api.start_session(self.entry["id"], 80, 24)
        self.assertFalse(result["ok"])
        self.assertIn("pywinpty", result["error"])
        with patch("app.embedded_ssh_executable", return_value=None):
            self.assertIn("OpenSSH", self.api.start_session(self.entry["id"], 80, 24)["error"])
        session_id = self.start()
        for data in [None, "", "a\0b", "x" * 65537]:
            self.assertFalse(self.api.write_session(session_id, data)["ok"])
        self.assertFalse(self.api.resize_session(session_id, -1, 24)["ok"])
        self.assertFalse(self.api.write_session(123, "x")["ok"])
        self.assertEqual(self.ptys[0].writes, [])
        for _ in range(app.SessionManager.MAX_SESSIONS - 1):
            self.start()
        self.assertIn("Too many", self.api.start_session(self.entry["id"], 80, 24)["error"])
        self.assertTrue(self.api.close_session(session_id)["ok"])
        self.start()

    def test_saved_entry_revalidated_and_no_shell_interpolation(self):
        self.api.save_connection({**EXAMPLE, "key_path": "C:/keys/private key; safe"}, self.entry["id"])
        with patch("app.Path.is_file", return_value=True):
            session_id = self.start()
        argv, _ = self.spawns[-1]
        self.assertEqual(argv[-3:], ["-i", "C:/keys/private key; safe", "vmuser@192.0.2.10"])
        self.api.close_session(session_id)
        self.api.store._write([{**self.entry, "host": "host;calc"}])
        self.assertFalse(self.api.start_session(self.entry["id"], 80, 24)["ok"])
        self.assertEqual(len(self.spawns), 1)

    def test_spawn_and_reader_failures_are_reported(self):
        with patch.dict(sys.modules, {"winpty": types.SimpleNamespace(
                Backend=types.SimpleNamespace(WinPTY=1),
                PtyProcess=types.SimpleNamespace(spawn=lambda *a, **kw: (_ for _ in ()).throw(OSError("spawn failed"))),
        )}):
            result = self.api.start_session(self.entry["id"], 80, 24)
        self.assertFalse(result["ok"])
        self.assertIn("spawn failed", result["error"])
        self.assertEqual(self.api.sessions.sessions, {})
        session_id = self.start()
        self.ptys[-1].incoming.put(OSError("read failed"))
        self.api.sessions.get(session_id).reader.join(1)
        result = self.api.read_session(session_id)["data"]
        self.assertFalse(result["running"])
        self.assertEqual(result["error"], "read failed")

    def test_shutdown_closes_all_sessions(self):
        ids = [self.start(), self.start()]
        self.api.shutdown()
        self.assertTrue(all(pty.closed for pty in self.ptys))
        self.assertTrue(all(not self.api.read_session(session_id)["ok"] for session_id in ids))


if __name__ == "__main__":
    unittest.main()
