# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


ROOT_DIR = Path('/Users/wangshuang/PycharmProjects/obs/obs')
ENV_DATAS = []
ENV_FILE = ROOT_DIR / '.env'
if ENV_FILE.exists():
    ENV_DATAS.append((str(ENV_FILE), '.'))


a = Analysis(
    ['/Users/wangshuang/PycharmProjects/obs/obs/src/omni_agent/desktop_app.py'],
    pathex=['/Users/wangshuang/PycharmProjects/obs/obs/src', '/Users/wangshuang/PycharmProjects/obs/obs/.claude/skills'],
    binaries=[],
    datas=[('/Users/wangshuang/PycharmProjects/obs/obs/.claude/skills', '.claude/skills'), ('/Users/wangshuang/PycharmProjects/obs/obs/frontend', 'frontend'), ('/Users/wangshuang/PycharmProjects/obs/obs/skills', 'skills'), *ENV_DATAS],
    hiddenimports=['omni_agent.api', 'skill_manager', 'skill_loader', 'base_skill'],
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
    name='OBS Agent',
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
    name='OBS Agent',
)
app = BUNDLE(
    coll,
    name='OBS Agent.app',
    icon=None,
    bundle_identifier=None,
)
