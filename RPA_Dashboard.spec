# -*- mode: python ; coding: utf-8 -*-
# RPA 현황 대시보드 - 사내 PC/휴대폰 브라우저로 프리페어/루틴 RPA 진행 상황을 본다.
#   .venv\Scripts\python.exe -m PyInstaller --noconfirm RPA_Dashboard.spec
#
# 표준 라이브러리만 쓰므로 가볍다. 화면(dashboard.html)은 exe 안에 함께 넣는다.

a = Analysis(
    ['rpa_dashboard.py'],
    pathex=[],
    binaries=[],
    datas=[('dashboard.html', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'pywinauto', 'comtypes', 'playwright', 'win32com', 'pythoncom', 'pywintypes'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='RPA_Dashboard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
