# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('/Users/wangshuang/PycharmProjects/obs/obs/.env', '.'), ('/Users/wangshuang/PycharmProjects/obs/obs/.claude/skills', '.claude/skills'), ('/Users/wangshuang/PycharmProjects/obs/obs/frontend', 'frontend'), ('/Users/wangshuang/PycharmProjects/obs/obs/skills', 'skills')]
binaries = []
hiddenimports = ['omni_agent.api', 'skill_manager', 'skill_loader', 'base_skill', 'webview', 'objc', 'AppKit', 'Foundation', 'WebKit', 'PyObjCTools', 'PyObjCTools.AppHelper', 'webview.platforms.cocoa']
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['/Users/wangshuang/PycharmProjects/obs/obs/src/omni_agent/desktop_app.py'],
    pathex=['/Users/wangshuang/PycharmProjects/obs/obs/src', '/Users/wangshuang/PycharmProjects/obs/obs/.claude/skills'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'IPython', 'jupyter_client', 'jupyter_core', 'ipykernel', 'pandas', 'scipy'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OBS Code',
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
    icon=['/Users/wangshuang/PycharmProjects/obs/obs/build/obs-code-logo.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='OBS Code',
)
app = BUNDLE(
    coll,
    name='OBS Code.app',
    icon='/Users/wangshuang/PycharmProjects/obs/obs/build/obs-code-logo.icns',
    bundle_identifier=None,
)
