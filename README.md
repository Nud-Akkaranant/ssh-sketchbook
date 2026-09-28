# SSH Sketchbook

A small Windows desktop app for keeping SSH connections in one place. The interface has a hand-drawn, notebook-style theme. Connections open as tabs in one shared Windows Terminal window.

## Set up

1. Install Python 3, the Windows OpenSSH Client, and Windows Terminal. Check with `py -3 --version`, `ssh -V`, and `where wt` in a terminal.
2. In this folder, run `py -3 -m pip install -r requirements.txt`. The desktop window uses pywebview and the Windows WebView2 runtime.
3. Double-click **Open SSH Sketchbook.vbs** to open the app without a terminal window. If it does not launch, run **Launch SSH Sketchbook.cmd** instead to see the error. You can also start it with `py -3 app.py`.

### Pin to the Windows taskbar

Double-click **Create taskbar shortcut.vbs**. It creates `ssh-sketchbook.lnk` in this folder with the app logo and the right Python launch command. Right-click `ssh-sketchbook.lnk` and select **Pin to taskbar**. On Windows 11, you may need **Show more options** first. Keep this project folder in place after pinning it; the shortcut points to `app.py` and `static/icon.ico` here. If Windows does not offer Pin to taskbar, launch the `.lnk`, right-click the running app icon on the taskbar, and choose **Pin to taskbar** there.

## Use it

- **My machines** lists saved connections. Connect opens a tab in a Windows Terminal window named `ssh-sketchbook`. Later connections reuse that window. **Open all machines** starts every saved machine in a separate tab of that same window with one click. Refresh status checks ping and the configured SSH TCP port independently. Some hosts block ping even when SSH is available.
- **Configure** lets you add, edit, or delete connections. For example: name `Home VM`, username `operator`, host `192.0.2.10`, port `49152`.
- Optional connection details are a private key path, a jump host in `user@host:port` format, and a connection timeout. Standard `~/.ssh/config` settings still apply. The SSH client handles its normal password prompts and first-connection host-key confirmation.

Connection details are stored in `%APPDATA%\SSH Sketchbook\connections.json`. Passwords are **never stored**. The app does not connect to the internet for its interface or perform background status checks. Status checks happen only when you press Refresh. To stop the app, close its window.

If the app window does not open, check that WebView2 Runtime is installed and run `py -3 app.py` from a terminal to see the error. If tabs do not open, check that `wt.exe` and `ssh.exe` are on PATH. The per-machine connection timeout defaults to 10 seconds; it is a maximum wait to reach an unavailable SSH server, not a deliberate pause before opening a terminal. If a terminal appears immediately but login is slow, run `ssh -vvv -p 49152 operator@192.0.2.10` with your own address and port to see whether the delay is DNS, network, a jump host, or authentication. The verbose output may contain hostnames and account information; review it before sharing.

## Tests

Run `py -3 -m unittest discover -s tests -v` from this folder. Tests mock network checks and process creation; they never connect to your VMs.
