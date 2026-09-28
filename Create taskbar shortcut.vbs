Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
Set lookup = shell.Exec("py -3 -c ""import sys; from pathlib import Path; print(Path(sys.executable).with_name('pythonw.exe'))""")
If lookup.StdOut.AtEndOfStream Then
  MsgBox "Python 3 was not found. Install Python first, then try again.", vbExclamation, "ssh-sketchbook"
  WScript.Quit 1
End If
pythonw = Trim(lookup.StdOut.ReadLine())
If Not files.FileExists(pythonw) Then
  MsgBox "pythonw.exe was not found at " & pythonw, vbExclamation, "ssh-sketchbook"
  WScript.Quit 1
End If
Set shortcut = shell.CreateShortcut(folder & "\ssh-sketchbook.lnk")
shortcut.TargetPath = pythonw
shortcut.Arguments = Chr(34) & folder & "\app.py" & Chr(34)
shortcut.WorkingDirectory = folder
shortcut.IconLocation = folder & "\static\icon.ico,0"
shortcut.Description = "ssh-sketchbook"
shortcut.Save
WScript.Echo "Shortcut created: ssh-sketchbook.lnk" & vbCrLf & "Right-click it and choose Pin to taskbar. On Windows 11, check Show more options if needed."
