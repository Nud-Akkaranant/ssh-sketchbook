"""Local desktop SSH connection manager."""

import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4


APP_DIR = Path(__file__).resolve().parent
DATA_PATH = Path(os.environ.get("APPDATA", Path.home())) / "SSH Sketchbook" / "connections.json"
HOST_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9_](?:[A-Za-z0-9_.-]*[A-Za-z0-9_])?$")
USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")


def valid_host(value):
    if not isinstance(value, str) or not value or len(value) > 253:
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return bool(HOST_RE.fullmatch(value)) and ".." not in value


def validate_entry(data):
    if not isinstance(data, dict):
        raise ValueError("Connection details must be an object.")
    name = data.get("name", "")
    description = data.get("description", "")
    host = data.get("host", "")
    username = data.get("username", "")
    key_path = data.get("key_path", "")
    jump_host = data.get("jump_host", "")
    port = data.get("port", 22)
    timeout = data.get("timeout", 10)

    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError("Name must be 1 to 80 characters.")
    if not isinstance(description, str) or len(description) > 500:
        raise ValueError("Description must be 500 characters or fewer.")
    if not valid_host(host):
        raise ValueError("Enter a valid IP address, hostname, or SSH host alias.")
    if not isinstance(username, str) or not USER_RE.fullmatch(username):
        raise ValueError("Enter a valid SSH username.")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535.")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 60:
        raise ValueError("Timeout must be between 1 and 60 seconds.")
    if not isinstance(key_path, str) or len(key_path) > 1024 or "\0" in key_path:
        raise ValueError("Enter a valid private key path.")
    if not isinstance(jump_host, str) or len(jump_host) > 320:
        raise ValueError("Enter a valid jump host.")
    if jump_host:
        # OpenSSH accepts [user@]host[:port] for -J. Bracket IPv6 addresses.
        match = re.fullmatch(r"(?:(?P<user>[A-Za-z_][A-Za-z0-9_.-]{0,63})@)?(?P<host>\[[0-9a-fA-F:]+\]|[A-Za-z0-9_.-]+)(?::(?P<port>[0-9]{1,5}))?", jump_host)
        if not match:
            raise ValueError("Jump host must look like user@host:port.")
        jump_name = match.group("host")
        if not valid_host(jump_name[1:-1] if jump_name.startswith("[") else jump_name):
            raise ValueError("Enter a valid jump host address.")
        if match.group("port") and not 1 <= int(match.group("port")) <= 65535:
            raise ValueError("Jump host port must be between 1 and 65535.")

    return {
        "name": name.strip(), "description": description.strip(), "host": host,
        "username": username, "port": port, "key_path": key_path.strip(),
        "jump_host": jump_host, "timeout": timeout,
    }


class ConnectionStore:
    def __init__(self, path=DATA_PATH):
        self.path = Path(path)
        self.lock = threading.RLock()

    def list(self):
        with self.lock:
            if not self.path.exists():
                return []
            with self.path.open("r", encoding="utf-8") as file:
                entries = json.load(file)
            if not isinstance(entries, list):
                raise ValueError("Saved connection data is not a list.")
            return entries

    def save(self, entry, entry_id=None):
        clean = validate_entry(entry)
        with self.lock:
            entries = self.list()
            if entry_id is None:
                clean["id"] = str(uuid4())
                entries.append(clean)
            else:
                index = next((i for i, item in enumerate(entries) if item["id"] == entry_id), None)
                if index is None:
                    raise ValueError("Connection not found.")
                clean["id"] = entry_id
                entries[index] = clean
            self._write(entries)
            return clean

    def delete(self, entry_id):
        with self.lock:
            entries = self.list()
            remaining = [item for item in entries if item["id"] != entry_id]
            if len(remaining) == len(entries):
                raise ValueError("Connection not found.")
            self._write(remaining)

    def get(self, entry_id):
        return next((entry for entry in self.list() if entry["id"] == entry_id), None)

    def _write(self, entries):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".connections-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(entries, file, indent=2, ensure_ascii=False)
                file.write("\n")
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def ssh_args(entry):
    args = ["ssh", "-p", str(entry["port"]), "-o", f"ConnectTimeout={entry['timeout']}"]
    if entry["key_path"]:
        args.extend(["-i", entry["key_path"]])
    if entry["jump_host"]:
        args.extend(["-J", entry["jump_host"]])
    args.append(f"{entry['username']}@{entry['host']}")
    return args


def terminal_args(entries):
    args = ["wt", "-w", "ssh-sketchbook"]
    for index, entry in enumerate(entries):
        if index:
            args.append(";")
        title = re.sub(r'[;"\r\n\t]', " ", entry["name"]).strip() or "SSH machine"
        args.extend(["nt", "--title", title, "--suppressApplicationTitle", *ssh_args(entry)])
    return args


def launch_terminal(entries):
    if not entries:
        raise ValueError("Add a machine before opening SSH tabs.")
    if not shutil.which("wt"):
        raise ValueError("Windows Terminal is not installed or wt.exe is not on PATH.")
    if not shutil.which("ssh"):
        raise ValueError("OpenSSH is not installed or ssh.exe is not on PATH.")
    for entry in entries:
        if entry["key_path"] and not Path(entry["key_path"]).is_file():
            raise ValueError(f"Private key file not found for {entry['name']}. Update its path in Configure.")
        if ";" in entry["key_path"]:
            raise ValueError(f"Private key path for {entry['name']} cannot contain a semicolon with Windows Terminal.")
    subprocess.Popen(terminal_args(entries), shell=False)


def probe(entry):
    host = entry["host"]
    try:
        command = ["ping", "-n", "1", "-w", "1200", host] if sys.platform == "win32" else ["ping", "-c", "1", "-W", "1", host]
        ping = subprocess.run(command, capture_output=True, timeout=2.5, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ping = False
    try:
        with socket.create_connection((host, entry["port"]), timeout=1.5):
            ssh_port = True
    except (OSError, ValueError):
        ssh_port = False
    return {"id": entry["id"], "ping": ping, "ssh_port": ssh_port}


class Api:
    def __init__(self, store=None):
        self.store = store or ConnectionStore()

    def _result(self, action):
        try:
            return {"ok": True, "data": action()}
        except (ValueError, OSError, json.JSONDecodeError, KeyError) as error:
            return {"ok": False, "error": str(error)}

    def list_connections(self):
        return self._result(self.store.list)

    def save_connection(self, entry, entry_id=None):
        return self._result(lambda: self.store.save(entry, entry_id))

    def delete_connection(self, entry_id):
        def delete():
            self.store.delete(entry_id)
            return None
        return self._result(delete)

    def connect(self, entry_id):
        def launch():
            entry = self.store.get(entry_id)
            if entry is None:
                raise ValueError("Connection not found.")
            launch_terminal([entry])
            return None
        return self._result(launch)

    def connect_all(self):
        def launch():
            entries = self.store.list()
            launch_terminal(entries)
            return len(entries)
        return self._result(launch)

    def refresh_status(self):
        def refresh():
            entries = self.store.list()
            with ThreadPoolExecutor(max_workers=8) as pool:
                return list(pool.map(probe, entries))
        return self._result(refresh)


def main():
    try:
        import webview
    except ImportError:
        print("pywebview is missing. Install it with: py -m pip install -r requirements.txt")
        sys.exit(1)
    webview.create_window(
        "ssh-sketchbook", (APP_DIR / "static" / "index.html").as_uri(),
        js_api=Api(), width=1180, height=780, min_size=(800, 600),
        background_color="#f7f2e8",
    )
    webview.start(gui="edgechromium", debug=False, icon=str(APP_DIR / "static" / "icon.ico"))


if __name__ == "__main__":
    main()
