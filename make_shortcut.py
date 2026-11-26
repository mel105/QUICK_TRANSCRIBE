"""
Create the quick_transcribe desktop shortcut (Windows) or the launcher in the
applications menu and on the desktop (Linux).

Run it with the Python that quick_transcribe should use, e.g.

    C:\\Users\\<name>\\Dev\\Env\\Personal\\Scripts\\python.exe make_shortcut.py
    python3 make_shortcut.py

Run it again after moving the folder.

Author: MEL
"""

import base64
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
LAUNCHER = os.path.join(BASE, "quick_transcribe.pyw")
NAME = "quick_transcribe"
COMMENT = "Offline transcription of recordings with a searchable archive"


def windows() -> int:
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        print(f"pythonw.exe not found next to {sys.executable}.")
        print("Run this script with python.exe of the environment quick_transcribe should use.")
        return 1
    icon = os.path.join(BASE, "quick_transcribe.ico")
    q = lambda s: s.replace("'", "''")  # noqa: E731  (PowerShell single-quoted string)
    ps = f"""
$d = [Environment]::GetFolderPath('Desktop')
$p = Join-Path $d '{NAME}.lnk'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($p)
$s.TargetPath = '{q(pythonw)}'
$s.Arguments = '"{q(LAUNCHER)}"'
$s.WorkingDirectory = '{q(BASE)}'
$s.IconLocation = '{q(icon)}'
$s.Description = '{COMMENT}'
$s.Save()
Write-Output $p
"""
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-EncodedCommand", enc], capture_output=True, text=True)
    if r.returncode != 0:
        print("The shortcut could not be created:\n", r.stderr)
        print(f'By hand: right-click the desktop > New > Shortcut > "{pythonw}" "{LAUNCHER}", icon {icon}')
        return 1
    print("Shortcut created:", r.stdout.strip())
    print("Python in the shortcut:", pythonw)
    return 0


def linux() -> int:
    py = sys.executable or "python3"
    entry = f"""[Desktop Entry]
Type=Application
Name={NAME}
Comment={COMMENT}
Exec="{py}" "{LAUNCHER}"
Icon={os.path.join(BASE, 'quick_transcribe.png')}
Path={BASE}
Terminal=false
Categories=AudioVideo;Utility;
"""
    apps = os.path.expanduser("~/.local/share/applications")
    os.makedirs(apps, exist_ok=True)
    targets = [os.path.join(apps, "quick_transcribe.desktop")]
    try:
        desk = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True).stdout.strip()
    except OSError:
        desk = ""
    if not desk or not os.path.isdir(desk):
        desk = next((p for p in (os.path.expanduser("~/Plocha"), os.path.expanduser("~/Desktop"))
                     if os.path.isdir(p)), "")
    if desk:
        targets.append(os.path.join(desk, "quick_transcribe.desktop"))
    for t in targets:
        with open(t, "w", encoding="utf-8") as f:
            f.write(entry)
        os.chmod(t, 0o755)
        try:
            subprocess.run(["gio", "set", t, "metadata::trusted", "true"], capture_output=True)
        except OSError:
            pass
        print("Created:", t)
    print("GNOME: if the desktop icon does not start, right-click it > Allow Launching.")
    return 0


if __name__ == "__main__":
    sys.exit(windows() if sys.platform.startswith("win") else linux())
