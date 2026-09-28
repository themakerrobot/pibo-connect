# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 스펙. 파이썬이 없는 노트북에서 그대로 도는 한 덩어리 실행 파일.

    pip install -r requirements.txt pyinstaller
    pyinstaller build/pibo-connect.spec --noconfirm

번들에 들어가는 데이터는 config.py 가 보는 자리에 정확히 풀어야 한다.
frozen 일 때 그 자리는 sys._MEIPASS 바로 아래다:
    static/    ← config.static_dir()
    examples/  ← config.examples_dir()
'pibo_connector/static' 처럼 한 단계 더 넣으면 실행 파일이
StaticFiles 에서 'Directory does not exist' 로 죽는다. 실제로 한 번 그랬다.
tests/smoke.py 가 이 대응이 맞는지 매번 확인한다.

윈도우에서는 console=True 로 둔다. 주소와 토큰이 콘솔에 찍혀야 하고,
스캔이 도는 동안 멈춘 것처럼 보이지 않는다.
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(os.path.abspath(SPECPATH)).parent
sys.path.insert(0, str(ROOT))
from pibo_connector import __version__   # noqa: E402  — 태그 가드와 같은 값
STATIC = ROOT / "pibo_connector" / "static"
EXAMPLES = ROOT / "examples"
ICON = ROOT / "build" / "pibo-connect.ico"    # sense-lab 의 파이보 얼굴 (tools/portable/icon.ico) 그대로

for d in (STATIC, EXAMPLES):
    if not d.is_dir():
        raise SystemExit(f"번들할 디렉토리가 없다: {d}")

# uvicorn 과 engineio 는 런타임에 이름으로 모듈을 찾는다. 통째로 넣는다.
hidden = []
for pkg in ("uvicorn", "engineio", "socketio", "aiohttp", "anyio"):
    try:
        hidden += collect_submodules(pkg)
    except Exception:
        pass
hidden += [
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto", "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on", "uvicorn.lifespan.off",
    "engineio.async_drivers.aiohttp",
    "engineio.async_drivers.asgi",
]

def win_version_info():
    """exe 속성 창의 '자세히' 탭. 서명은 아니지만 정체를 밝힌다 —
    SmartScreen 의 '알 수 없는 게시자' 판정을 없애지는 못한다."""
    if sys.platform != "win32":
        return None
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo,
        VarStruct, VSVersionInfo)
    nums = [int(x) for x in __version__.split(".")[:3]] + [0]
    nums = tuple(nums[:4])
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums, mask=0x3F, flags=0x0,
                          OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", "Circulus"),
                StringStruct("ProductName", "파이보 커넥터 (pibo-connect)"),
                StringStruct("FileDescription", "파이보 커넥터 — 파이보/파이브레인 여러 대를 브라우저로 찾고 실행"),
                StringStruct("FileVersion", __version__),
                StringStruct("ProductVersion", __version__),
                StringStruct("OriginalFilename", "pibo-connect.exe"),
                StringStruct("InternalName", "pibo-connect"),
                StringStruct("LegalCopyright", "© Circulus"),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ])


a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(STATIC), "static"), (str(EXAMPLES), "examples")],
    hiddenimports=sorted(set(hidden)),
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "PIL", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="pibo-connect",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    # .ico 는 윈도우용이다. 맥은 .icns 를 원하고 리눅스는 무시한다.
    icon=str(ICON) if (sys.platform == "win32" and ICON.exists()) else None,
    version=win_version_info(),
)
