# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

import sys

a = Analysis(
    ['transcribe.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'vlc',
        'ffmpeg',
        'platformdirs',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # reduce size by excluding large unused Qt modules
        'PySide6.Qt3D*',
        'PySide6.QtBluetooth',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.QtLocation',
        'PySide6.QtPdf',
        'PySide6.QtPositioning',
        'PySide6.QtQuick3D',
        'PySide6.QtRemoteObjects',
        'PySide6.QtSensors',
        'PySide6.QtSerialPort',
        'PySide6.QtWeb*',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Sermon Transcriber',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if sys.platform == 'darwin':
    app = BUNDLE(
        exe,  # pass exe directly; PyInstaller handles internal COLLECT for BUNDLE on mac
        name='Sermon Transcriber.app',
        icon='res/transcribe.icns',
        bundle_identifier='com.tedcarnahan.sermon-transcribe',
        info_plist={
            'CFBundleDisplayName': 'Sermon Transcriber',
            'CFBundleName': 'Sermon Transcriber',
            'CFBundleVersion': '0.1.0',
            'CFBundleShortVersionString': '0.1.0',
        }
    )
else:
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name='SermonTranscriber'
    )

