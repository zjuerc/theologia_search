# Building the Windows Installer

This document is for the build machine only. End users do not need Python,
PySide6, pip, PyInstaller, or Inno Setup.

## One-time build-machine setup

Use Windows 10 or Windows 11 with a supported Python installation. From the
repository root:

```powershell
python -m pip install -r .\requirements-gui.txt
python -m pip install -r .\requirements-build.txt
```

Install Inno Setup 6 separately. The build script searches the standard
Program Files locations, or you can provide an explicit `-IsccPath`.

## Create the installer

```powershell
Set-Location .\theologia_search
.\installer\build_installer.ps1 -PythonExe python
```

The final file is created at:

```text
theologia_search\release\Theologia Search Setup.exe
```

The script validates the source index, creates the PyInstaller onedir payload,
checks its manifest and SQLite counts, runs `TheologiaSearch.exe --self-test`,
and only then invokes Inno Setup.

The current semantic index is approximately 1.9 GB before installer
compression. The final installer will therefore be substantially larger than
a typical small desktop utility.
