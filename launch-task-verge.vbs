Set fso = CreateObject("Scripting.FileSystemObject")
Set ws = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
ws.CurrentDirectory = root
ws.Run """" & root & "\.ui-venv\Scripts\pythonw.exe"" """ & root & "\task-panel.pyw""", 0, False
