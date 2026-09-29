# SSH Sketchbook

A small Windows desktop app for keeping SSH connections in one place. The interface has a hand-drawn, notebook-style theme. Open interactive SSH tabs inside the app, or use one shared Windows Terminal window.

## Install on Windows

Open the [Build Windows installer workflow](https://github.com/Nud-Akkaranant/ssh-sketchbook/actions/workflows/build-windows.yml), select the latest successful run on `main`, and download the `ssh-sketchbook-installer-*` artifact. Unzip it and run `ssh-sketchbook-setup.exe`. The installer puts the app in your user profile, adds a Start menu shortcut, and offers a desktop shortcut. Python is not required on the installed computer. Artifacts are retained for 30 days; each push to `main` creates a fresh installer.

The Windows OpenSSH Client (`ssh.exe`) and Microsoft Edge WebView2 Runtime must be installed on that computer. Windows Terminal (`wt.exe`) is required only for the external **Windows Terminal** and **Open all machines** buttons, not for **Connect via app**. The installer does not bundle these system components. This installer is not code-signed, so Windows may show an unknown publisher warning; verify the download came from this repository before running it. Upgrades and uninstalls do not remove saved connections in `%APPDATA%`.

### Run from source instead

1. Install Python 3 and run `py -3 -m pip install -r requirements.txt` in this folder.
2. Double-click **Open SSH Sketchbook.vbs** to open the app without a terminal window. If it does not launch, run **Launch SSH Sketchbook.cmd** to see the error. You can also start it with `py -3 app.py`.
3. For a local installer build, install Inno Setup 6 and run `py -3 -m pip install -r requirements-build.txt`, then `pwsh -File scripts/build.ps1`. The installer appears in `dist/installer/`.

### Pin a source checkout to the Windows taskbar

For the installed app, pin the **ssh-sketchbook** Start menu entry instead. For a source checkout, double-click **Create taskbar shortcut.vbs**. It creates `ssh-sketchbook.lnk` in this folder with the app logo and the right Python launch command. Right-click `ssh-sketchbook.lnk` and select **Pin to taskbar**. On Windows 11, you may need **Show more options** first. Keep this project folder in place after pinning it; the shortcut points to `app.py` and `static/icon.ico` here. If Windows does not offer Pin to taskbar, launch the `.lnk`, right-click the running app icon on the taskbar, and choose **Pin to taskbar** there.

## Use it

- **My machines** lists saved connections. **Connect via app** opens an interactive shell on the app's **Terminal** page; open several machines to switch between their tabs. Closing a tab ends that SSH session. The **Windows Terminal** button opens a tab in an external Windows Terminal window named `ssh-sketchbook`; later connections reuse that window. **Open all machines** starts every saved machine in separate external Windows Terminal tabs with one click. Refresh status checks ping and the configured SSH TCP port independently. Some hosts block ping even when SSH is available.
- **Terminal** also lets you choose a saved machine and start a new in-app tab. Drag the terminal's bottom-right corner to resize it; terminal rows and columns follow the new size. Use **Full screen** at the top right to fill the display where supported (or the app window otherwise), and **Exit full screen** or Esc to return. Sessions end when you close the app; terminal contents and passwords are never saved. The built-in terminal assets are bundled locally, so the interface works offline; SSH still needs network access to the machine.
- **Configure** lets you add, edit, or delete connections. For example: name `Home VM`, username `operator`, host `192.0.2.10`, port `49152`.
- Optional connection details are a private key path, a jump host in `user@host:port` format, and a connection timeout. Standard `~/.ssh/config` settings still apply. The SSH client handles its normal password prompts and first-connection host-key confirmation.

Connection details are stored in `%APPDATA%\SSH Sketchbook\connections.json`. Passwords are **never stored**. The app does not connect to the internet for its interface or perform background status checks. Status checks happen only when you press Refresh. To stop the app, close its window.

If the app window does not open, check that WebView2 Runtime is installed and run `py -3 app.py` from a terminal to see the error. If external tabs do not open, check that `wt.exe` and `ssh.exe` are on PATH. If in-app sessions do not open, check `ssh.exe` and that `pywinpty` was installed from `requirements.txt` (or included in the installer). The per-machine connection timeout defaults to 10 seconds; it is a maximum wait to reach an unavailable SSH server, not a deliberate pause before opening a terminal. If a terminal appears immediately but login is slow, run `ssh -vvv -p 49152 operator@192.0.2.10` with your own address and port to see whether the delay is DNS, network, a jump host, or authentication. The verbose output may contain hostnames and account information; review it before sharing.

## Tests

Run `py -3 -m unittest discover -s tests -v` from this folder. Tests mock network checks and process creation; they never connect to your VMs.
