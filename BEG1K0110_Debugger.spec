# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['run_beg1k0110_debugger.py'],
    pathex=[],
    binaries=[],
    datas=[('tools/beg1k0110_debugger', 'tools/beg1k0110_debugger')],
    hiddenimports=['can.interfaces.pcan'],
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
    [],
    exclude_binaries=True,
    name='BEG1K0110_Debugger',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BEG1K0110_Debugger',
)
