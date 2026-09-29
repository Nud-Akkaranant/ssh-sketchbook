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
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4


APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
DATA_PATH = Path(os.environ.get("APPDATA", Path.home())) / "SSH Sketchbook" / "connections.json"
HOST_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9_](?:[A-Za-z0-9_.-]*[A-Za-z0-9_])?$")
USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")


CLIPBOARD_LOCK = threading.RLock()


def write_clipboard(text):
    if not isinstance(text, str) or "\0" in text:
        raise ValueError("Clipboard text must be valid text.")
    if sys.platform != "win32":
        raise ValueError("The native clipboard is only available on Windows.")
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    with CLIPBOARD_LOCK:
        if not user32.OpenClipboard(None):
            raise OSError("Could not open the Windows clipboard.")
        handle = None
        try:
            payload = (text + "\0").encode("utf-16-le")
            handle = kernel32.GlobalAlloc(0x0042, len(payload))
            if not handle:
                raise OSError("Could not allocate clipboard memory.")
            address = kernel32.GlobalLock(handle)
            if not address:
                raise OSError("Could not lock clipboard memory.")
            try:
                ctypes.memmove(address, payload, len(payload))
            finally:
                kernel32.GlobalUnlock(handle)
            if not user32.EmptyClipboard() or not user32.SetClipboardData(13, handle):
                raise OSError("Could not write to the Windows clipboard.")
            handle = None
        finally:
            if handle:
                kernel32.GlobalFree(handle)
            user32.CloseClipboard()


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


def embedded_ssh_executable():
    # PATH may select an older SSH client than Windows Terminal uses.
    if sys.platform == "win32":
        native = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "OpenSSH" / "ssh.exe"
        if native.is_file():
            return str(native)
    return shutil.which("ssh")


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


class TerminalSession:
    """Collect PTY output on a daemon thread so bridge polls never block."""

    OUTPUT_LIMIT = 1024 * 1024

    def __init__(self, process, name):
        self.id = str(uuid4())
        self.name = name
        self.process = process
        self.lock = threading.Lock()
        self.io_lock = threading.Lock()
        self.output = deque()
        self.output_size = 0
        self.truncated = False
        self.running = True
        self.closed = False
        self.exit_code = None
        self.error = None
        self.stop_watcher = threading.Event()
        self.reader = threading.Thread(target=self._read, daemon=True, name=f"ssh-session-{self.id}")
        self.watcher = threading.Thread(target=self._watch, daemon=True, name=f"ssh-exit-{self.id}")
        self.reader.start()
        self.watcher.start()

    def _watch(self):
        # A PTY can leave read() blocked after the child exits. Allow its
        # remaining output to drain, then close the PTY to release the reader.
        while not self.stop_watcher.wait(0.1):
            with self.lock:
                if not self.running:
                    return
            try:
                alive = self.process.isalive()
            except (OSError, ValueError):
                alive = False
            if alive:
                continue
            try:
                exit_code = self.process.exitstatus
            except (OSError, ValueError):
                exit_code = None
            with self.lock:
                self.exit_code = exit_code
            self.reader.join(timeout=0.25)
            if self.reader.is_alive():
                with self.io_lock:
                    with self.lock:
                        if not self.closed:
                            self.closed = True
                            should_close = True
                        else:
                            should_close = False
                    if should_close:
                        try:
                            self.process.close(force=True)
                        except OSError:
                            pass
                self.reader.join(timeout=1)
            with self.lock:
                if self.exit_code is None:
                    self.exit_code = exit_code
                if self.reader.is_alive():
                    self.error = "Terminal output could not be fully drained."
                self.running = False
            return

    def _read(self):
        try:
            while True:
                chunk = self.process.read(4096)
                if not chunk:
                    continue
                with self.lock:
                    self.output.append(chunk)
                    self.output_size += len(chunk)
                    while self.output_size > self.OUTPUT_LIMIT:
                        removed = self.output.popleft()
                        excess = self.output_size - self.OUTPUT_LIMIT
                        if len(removed) > excess:
                            self.output.appendleft(removed[excess:])
                            self.output_size -= excess
                        else:
                            self.output_size -= len(removed)
                        self.truncated = True
        except EOFError:
            pass
        except (OSError, ValueError) as error:
            with self.lock:
                if not self.closed:
                    self.error = str(error)
        finally:
            try:
                exit_code = self.process.exitstatus
            except (OSError, ValueError):
                exit_code = None
            with self.lock:
                if self.exit_code is None:
                    self.exit_code = exit_code
                self.running = False

    def poll(self):
        with self.lock:
            result = {
                "output": "".join(self.output), "running": self.running,
                "truncated": self.truncated, "exit_code": self.exit_code,
            }
            if self.error is not None:
                result["error"] = self.error
            self.output.clear()
            self.output_size = 0
            self.truncated = False
            return result

    def write(self, data):
        if not isinstance(data, str) or not 1 <= len(data) <= 65536 or "\0" in data:
            raise ValueError("Terminal input must be 1 to 65536 characters without NUL.")
        with self.io_lock:
            with self.lock:
                if not self.running or self.closed:
                    raise ValueError("Session has ended.")
            self.process.write(data)

    def resize(self, cols, rows):
        validate_dimensions(cols, rows)
        with self.io_lock:
            with self.lock:
                if not self.running or self.closed:
                    raise ValueError("Session has ended.")
            self.process.setwinsize(rows, cols)

    def close(self):
        self.stop_watcher.set()
        try:
            with self.io_lock:
                with self.lock:
                    if self.closed:
                        return
                    self.closed = True
                self.process.close(force=True)
        finally:
            self.reader.join(timeout=1)
            if threading.current_thread() is not self.watcher:
                self.watcher.join(timeout=1)


def validate_dimensions(cols, rows):
    if (isinstance(cols, bool) or not isinstance(cols, int) or not 2 <= cols <= 500
            or isinstance(rows, bool) or not isinstance(rows, int) or not 1 <= rows <= 200):
        raise ValueError("Terminal dimensions must be 2-500 columns and 1-200 rows.")


class SessionManager:
    MAX_SESSIONS = 8

    def __init__(self):
        self.lock = threading.RLock()
        self.sessions = {}

    def start(self, entry, cols, rows):
        validate_dimensions(cols, rows)
        clean = validate_entry(entry)
        if clean["key_path"] and not Path(clean["key_path"]).is_file():
            raise ValueError("Private key file not found. Update its path in Configure.")
        ssh_exe = embedded_ssh_executable()
        if not ssh_exe:
            raise ValueError("OpenSSH is not installed or ssh.exe is not on PATH.")
        try:
            from winpty import Backend, PtyProcess
        except ImportError as error:
            raise ValueError("In-app terminals require pywinpty 3.0.5. Install it to use SSH sessions.") from error
        with self.lock:
            if len(self.sessions) >= self.MAX_SESSIONS:
                raise ValueError("Too many terminal sessions. Close a session first.")
            process = PtyProcess.spawn([ssh_exe, *ssh_args(clean)[1:]], dimensions=(rows, cols), backend=Backend.WinPTY)
            try:
                session = TerminalSession(process, clean["name"])
            except Exception:
                process.close(force=True)
                raise
            self.sessions[session.id] = session
            return {"id": session.id, "name": session.name}

    def get(self, session_id):
        if not isinstance(session_id, str):
            raise ValueError("Session not found.")
        with self.lock:
            session = self.sessions.get(session_id)
        if session is None:
            raise ValueError("Session not found.")
        return session

    def close(self, session_id):
        with self.lock:
            session = self.get(session_id)
            del self.sessions[session_id]
        session.close()

    def shutdown(self):
        with self.lock:
            sessions = list(self.sessions.values())
            self.sessions.clear()
        for session in sessions:
            try:
                session.close()
            except OSError:
                pass


class Api:
    def __init__(self, store=None):
        self.store = store or ConnectionStore()
        self.sessions = SessionManager()

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

    def start_session(self, entry_id, cols=80, rows=24):
        def start():
            entry = self.store.get(entry_id)
            if entry is None:
                raise ValueError("Connection not found.")
            return self.sessions.start(entry, cols, rows)
        return self._result(start)

    def read_session(self, session_id):
        return self._result(lambda: self.sessions.get(session_id).poll())

    def write_session(self, session_id, data):
        return self._result(lambda: self.sessions.get(session_id).write(data))

    def resize_session(self, session_id, cols, rows):
        return self._result(lambda: self.sessions.get(session_id).resize(cols, rows))

    def close_session(self, session_id):
        return self._result(lambda: self.sessions.close(session_id))

    def clipboard_set(self, text):
        return self._result(lambda: write_clipboard(text))

    def shutdown(self):
        self.sessions.shutdown()


def main():
    try:
        import webview
    except ImportError:
        print("pywebview is missing. Install it with: py -m pip install -r requirements.txt")
        sys.exit(1)
    api = Api()
    webview.create_window(
        "ssh-sketchbook", (APP_DIR / "static" / "index.html").as_uri(),
        js_api=api, width=1180, height=780, min_size=(800, 600),
        background_color="#f7f2e8",
    )
    try:
        webview.start(gui="edgechromium", debug=False, icon=str(APP_DIR / "static" / "icon.ico"))
    finally:
        api.shutdown()


if __name__ == "__main__":
    main()
