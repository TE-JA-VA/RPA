# -*- mode: python ; coding: utf-8 -*-
# 프리페어 RPA - 메일에서 '>>>' 로 시작하는 건의 첨부파일을 내려받는다.
# 루틴 RPA(ERPia_RPA.exe) 보다 먼저 실행되어야 한다.
#   .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean Prepare_RPA.spec
#
# 주의: Chromium(약 700MB)은 exe 안에 넣을 수 없다.
#       exe 옆에 ms-playwright 폴더를 두면 web_runner 가 알아서 그걸 쓴다.
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ['win32timezone']
for pkg in ('comtypes', 'pywinauto', 'playwright'):
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['web_runner.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='Prepare_RPA',
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
