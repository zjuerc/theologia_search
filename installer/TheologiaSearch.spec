from pathlib import Path
import sys

PROJECT_ROOT = Path(SPECPATH).parent
sqlite_dll = Path(sys.prefix) / "Library" / "bin" / "sqlite3.dll"
binaries = [
    (str(path), ".")
    for path in (
        sqlite_dll,
        Path(sys.prefix) / "Library" / "bin" / "tcl86t.dll",
        Path(sys.prefix) / "Library" / "bin" / "tk86t.dll",
    )
    if path.exists()
]
datas = [
    (str(PROJECT_ROOT / "assets"), "assets"),
    (str(PROJECT_ROOT / "generated" / "semantic_index.sqlite"), "generated"),
    (str(PROJECT_ROOT / "generated" / "index_manifest.json"), "generated"),
    (str(PROJECT_ROOT / "installer" / "README.txt"), "."),
    (str(PROJECT_ROOT / "CATALOG.txt"), "."),
    (str(PROJECT_ROOT / "license"), "license"),
]

hiddenimports = [
    "common",
    "gui",
    "periods",
    "search",
]

a = Analysis(
    [str(PROJECT_ROOT / "qt_gui.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    name="TheologiaSearch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    exclude_binaries=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TheologiaSearch",
)
