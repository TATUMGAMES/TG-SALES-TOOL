# PyInstaller build of tg_sales.exe (one-folder). Run through scripts/build_windows.ps1.
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH)
SRC = ROOT / "src" / "tg_sales"

datas = [
    # Alembic loads migration scripts from folders at runtime.
    (str(SRC / "db" / "migrations_pg"), "tg_sales/db/migrations_pg"),
    (str(SRC / "legacy" / "sqlite_migrations"), "tg_sales/legacy/sqlite_migrations"),
    (str(SRC / "resources"), "tg_sales/resources"),
]
datas += collect_data_files("reportlab")
hiddenimports = (
    collect_submodules("tg_sales")
    + collect_submodules("uvicorn")
    + ["psycopg_binary", "psycopg_binary.pq", "psycopg_binary._psycopg"]
)

a = Analysis(
    [str(SRC / "__main__.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "PySide6", "pandas", "numpy", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="tg_sales",
    console=True,  # the window shows status and closing it stops tg_sales
    icon=str(ROOT / "build" / "tg_sales.ico"),
    version=str(ROOT / "build" / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="tg_sales")
