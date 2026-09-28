import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app


EXAMPLE = {
    "name": "Home VM", "description": "Test machine", "host": "192.0.2.10",
    "username": "vmuser", "port": 49152, "key_path": "", "jump_host": "",
    "timeout": 10,
}


class ValidationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
