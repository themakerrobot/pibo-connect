#!/usr/bin/env python3
"""파이썬 없는 윈도우 PC 용 '풀어서 쓰는' 묶음(portable zip) 을 만든다.

    python build/make_portable.py --out dist/pibo-connect-windows-portable.zip

왜 exe 말고 이것도 내는가
-------------------------
서명 없는 exe 는 Windows 11 '스마트 앱 컨트롤'(SAC) 에서 복불복이다.
SAC 는 파일 내용을 보지 않고 그 파일의 해시를 Microsoft 클라우드에 물어
'세상에서 본 적 있나' 로 판정한다. 서명이 없으면 빌드마다 해시가 새것이라
평판이 0 이고, 같은 코드로 만든 연속 릴리스끼리도 결과가 갈린다.
(0.4.1·0.4.2 는 통과했는데 0.4.3 릴리스판은 막힌 게 그래서다.)

이 묶음은 **판정 대상을 바꾼다.** 실행되는 바이너리가 우리 exe 가 아니라
python.org 가 배포하는 공식 embeddable 패키지의 `python.exe` 다. 그건
Python Software Foundation 이름으로 Authenticode 서명이 되어 있어서
SAC 가 '알 수 없는 파일' 로 볼 이유가 없다. 우리 코드는 `.py` 텍스트로만
들어가고, 시작 버튼은 `.bat` 이다 — 둘 다 SAC 가 막는 대상이 아니다.

그 전제가 진짜인지는 추측하지 않는다. 아래 `verify_signature()` 가 받아온
python.exe 의 PE 인증서 테이블을 직접 뜯어보고, 윈도우에서는
Get-AuthenticodeSignature 로 체인까지 확인한다. 서명이 없거나 PSF 가
아니면 빌드를 세운다. 서명이 없는 묶음은 exe 와 다를 게 없으니까.

묶음 구조 (zip 안)
------------------
    pibo-connect/
      시작하기.bat            ← 선생님이 두 번 누르는 것
      로봇 확인하기.bat        ← 안 찾아질 때 --check
      먼저-읽어보세요.txt
      python/                 ← 공식 embeddable (PSF 서명). 여기만 실행된다
        python.exe  python311.dll  python311.zip  *.pyd ...
        python311._pth          ← sys.path 를 ../app 과 ../app/lib 로 고정
      app/
        pibo_connector/       ← static/ 포함
        examples/
        lib/                  ← 의존성 (pip --target)

`.bat` 은 **ASCII 만 쓴다.** cmd.exe 는 배치 파일을 현재 코드페이지로 읽어서,
UTF-8 한글을 넣으면 chcp 65001 을 먼저 해도 깨진다. 한글 안내는 전부
파이썬이 찍는다 (`__main__.py` 의 `_utf8_console`).

경로 대응은 소스 실행(frozen=False) 과 같다:
    app/pibo_connector/static  = config.static_dir()
    app/examples               = config.examples_dir()
그래서 spec 의 datas 처럼 따로 맞출 게 없다. tests/smoke.py 가 확인한다.
"""

import argparse
import hashlib
import os
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pibo_connector import __version__  # noqa: E402

# CI 의 setup-python 과 같은 3.11 계열을 쓴다. ABI 태그(cp311)가 같아야
# pip 이 받아온 휠이 이 python.exe 에서 그대로 돌아간다.
PY_VER = "3.11.9"
PY_TAG = "".join(PY_VER.split(".")[:2])          # '311'
EMBED_URL = f"https://www.python.org/ftp/python/{PY_VER}/python-{PY_VER}-embed-amd64.zip"

BUNDLE = "pibo-connect"          # zip 안 최상위 폴더 이름
PY_DIR = "python"
APP_DIR = "app"
LIB_DIR = "lib"                  # app/lib

# python311._pth — python.exe 가 있는 폴더 기준 상대경로다.
# 'import site' 를 넣어야 lib 안의 .pth 처리와 importlib.metadata 가 정상이다.
PTH_LINES = [
    f"python{PY_TAG}.zip",
    ".",
    f"..\\{APP_DIR}",
    f"..\\{APP_DIR}\\{LIB_DIR}",
    "",
    "import site",
]

START_BAT = r"""@echo off
rem pibo-connect launcher.  THIS FILE MUST STAY ASCII-ONLY.
rem cmd.exe reads a .bat in the console codepage, which differs per PC, so
rem Korean text here would be garbled even after chcp 65001.  Every Korean
rem message the teacher sees is printed by Python (see __main__._utf8_console).
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
rem Keep the robot list next to this folder so replacing python\ and app\ with
rem a newer version does not throw it away.
set "PIBO_CONNECT_DATA=%~dp0data"

if not exist "python\python.exe" goto noextract

"python\python.exe" -m pibo_connector %*
if errorlevel 1 (
  echo.
  echo  [!] Something went wrong. Please send the lines above.
  echo.
  pause
)
exit /b

:noextract
echo.
echo  [!] Extract the ZIP first, then run this again.
echo      Right-click the downloaded ZIP file and choose "Extract All".
echo.
pause
exit /b 1
"""

CHECK_BAT = r"""@echo off
rem Diagnose one robot.  ASCII-ONLY, same reason as the launcher.
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist "python\python.exe" goto noextract

set "ip="
set /p ip=robot IP address (ex. 192.168.0.51) : 
if "%ip%"=="" goto done
"python\python.exe" -m pibo_connector --check %ip%
goto done

:noextract
echo  [!] Extract the ZIP first, then run this again.

:done
echo.
pause
"""

README_TXT = """파이보 커넥터 — 풀어서 쓰는 묶음 (버전 {ver})

교실의 파이보·파이브레인을 브라우저 한 장으로 찾고, 같은 코드를 한 번에 실행해요.
노트북에 설치하는 것은 없어요. 이 폴더만 있으면 돼요.


■ 쓰는 방법

  1. 받은 zip 파일을 오른쪽 클릭 - [압축 풀기] 를 누르세요.
     (zip 안에서 바로 두 번 누르면 안 켜져요. 꼭 풀어서 쓰세요.)
  2. 풀린 폴더에서 [시작하기] 를 두 번 누르세요.
  3. 검은 창이 하나 뜨고, 잠시 뒤 브라우저가 열려요.
     검은 창은 닫지 마세요 — 닫으면 꺼져요.
  4. 로봇과 노트북이 같은 와이파이에 있는지 확인하고 [로봇 찾기] 를 누르세요.

  끝낼 때는 검은 창을 닫으면 돼요.


■ 로봇이 안 찾아질 때

  [로봇 확인하기] 를 두 번 누르고, 로봇의 IP 주소를 넣으세요.
  어디서 막혔는지 한 줄씩 알려줘요. 그 내용을 그대로 보내주시면 돼요.


■ 폴더 안에 있는 것

  시작하기.bat        켜는 버튼
  로봇 확인하기.bat    로봇 한 대를 짚어 보는 버튼
  python\\            파이썬 (python.org 공식 배포본, 그대로 넣었어요)
  app\\               커넥터 프로그램
  data\\              찾은 로봇 목록 (처음 켤 때 생겨요)

  다음 버전으로 바꿀 때는 python\\ 과 app\\ 만 덮어쓰면 돼요.
  data\\ 를 그대로 두면 로봇 목록이 남아요.


■ "이 앱이 차단되었습니다" 가 뜨나요

  이 묶음은 그 창이 뜨지 않도록 만든 거예요. 실행되는 프로그램이
  python.org 가 서명해서 배포하는 공식 파이썬이라서요.
  그래도 뜬다면 알려주세요.

만든 곳: Circulus
""".format(ver=__version__)


# ── 서명 확인 ──────────────────────────────────────────────

def pe_has_signature(exe: Path) -> tuple:
    """PE 의 Certificate Table(데이터 디렉토리 4번) 을 직접 읽는다.

    (signed, detail). 윈도우가 아닌 데서도 '서명이 붙어 있나' 는 확인된다.
    """
    b = exe.read_bytes()
    if b[:2] != b"MZ":
        return False, "MZ 가 아니다"
    e_lfanew = struct.unpack_from("<I", b, 0x3C)[0]
    if b[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        return False, "PE 서명이 없다"
    magic = struct.unpack_from("<H", b, e_lfanew + 24)[0]
    if magic == 0x20B:            # PE32+
        dd = e_lfanew + 24 + 112
    elif magic == 0x10B:          # PE32
        dd = e_lfanew + 24 + 96
    else:
        return False, f"알 수 없는 optional header magic 0x{magic:X}"
    off, size = struct.unpack_from("<II", b, dd + 4 * 8)
    if not off or not size:
        return False, "Certificate Table 이 비어 있다 (서명 없음)"
    # WIN_CERTIFICATE: dwLength, wRevision, wCertificateType
    _len, _rev, ctype = struct.unpack_from("<IHH", b, off)
    if ctype != 0x0002:           # WIN_CERT_TYPE_PKCS_SIGNED_DATA
        return False, f"PKCS#7 이 아니다 (type 0x{ctype:04X})"
    return True, f"Authenticode {size} bytes @ 0x{off:X}"


def authenticode_subject(exe: Path):
    """윈도우에서만: 체인까지 확인하고 서명 주체를 돌려준다. 못 하면 None."""
    if sys.platform != "win32":
        return None
    ps = (f"$s = Get-AuthenticodeSignature -LiteralPath '{exe}'; "
          "Write-Output $s.Status; "
          "Write-Output $s.SignerCertificate.Subject")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                              "-Command", ps],
                             capture_output=True, text=True, timeout=120)
    except Exception as ex:
        raise SystemExit(f"!! 서명 확인을 못 했다: {ex}")
    lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
    if len(lines) < 2:
        raise SystemExit(f"!! 서명 확인 출력이 이상하다: {out.stdout!r} {out.stderr!r}")
    return lines[0], " ".join(lines[1:])


def verify_signature(exe: Path) -> None:
    """서명이 없으면 빌드를 세운다. 이 묶음의 존재 이유가 서명이다."""
    signed, detail = pe_has_signature(exe)
    print(f"  서명(PE)  : {'있다' if signed else '없다'} — {detail}")
    if not signed:
        raise SystemExit(
            "!! 받아온 python.exe 에 Authenticode 서명이 없다.\n"
            "   서명된 python.exe 가 SAC 를 넘는 유일한 근거다. 묶음을 내지 않는다.")
    got = authenticode_subject(exe)
    if got is None:
        print("  서명(체인): 확인 생략 (윈도우가 아니다)")
        return
    status, subject = got
    print(f"  서명(체인): {status} — {subject}")
    if status != "Valid":
        raise SystemExit(f"!! 서명 상태가 Valid 가 아니다: {status}")
    if "Python Software Foundation" not in subject:
        raise SystemExit(
            f"!! 서명 주체가 PSF 가 아니다: {subject}\n"
            "   python.org 가 아닌 데서 받아왔을 수 있다.")


# ── 묶기 ───────────────────────────────────────────────────

def fetch_embed(cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    dst = cache / EMBED_URL.rsplit("/", 1)[-1]
    if dst.exists() and dst.stat().st_size > 1_000_000:
        print(f"  받기      : 이미 있다 ({dst.name})")
        return dst
    print(f"  받기      : {EMBED_URL}")
    with urllib.request.urlopen(EMBED_URL, timeout=180) as r, dst.open("wb") as f:
        shutil.copyfileobj(r, f)
    print(f"              {dst.stat().st_size / 1e6:.1f} MB  "
          f"sha256 {hashlib.sha256(dst.read_bytes()).hexdigest()[:16]}…")
    return dst


def copy_app(app: Path) -> None:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
    shutil.copytree(ROOT / "pibo_connector", app / "pibo_connector", ignore=ignore)
    shutil.copytree(ROOT / "examples", app / "examples", ignore=ignore)
    for f in ("README.md", "CHANGELOG.md"):
        shutil.copy2(ROOT / f, app / f)
    # 소스 실행과 같은 자리여야 한다. 아니면 static 이 404 다.
    for need in (app / "pibo_connector" / "static" / "app.js", app / "examples"):
        if not need.exists():
            raise SystemExit(f"!! 묶음에 빠진 것이 있다: {need}")


def install_deps(lib: Path) -> None:
    req = ROOT / "requirements.txt"
    cmd = [sys.executable, "-m", "pip", "install", "-r", str(req),
           "--target", str(lib), "--no-warn-script-location", "--no-compile"]
    if sys.platform != "win32":
        # 리눅스/맥에서 만들 때도 윈도우 휠을 받아야 쓸 수 있다.
        cmd += ["--platform", "win_amd64", "--python-version", PY_VER,
                "--only-binary=:all:"]
    print("  의존성    : " + " ".join(cmd[-6:]))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        raise SystemExit("!! 의존성 설치 실패")
    # pip 이 만든 실행 스크립트는 이 묶음에서 안 쓴다. 지워서 혼란을 줄인다.
    for junk in ("bin", "Scripts"):
        shutil.rmtree(lib / junk, ignore_errors=True)


def write_text(path: Path, text: str, bom: bool = False, crlf: bool = True) -> None:
    """윈도우에서 열 파일이니 줄끝은 CRLF 로 쓴다.

    ._pth 는 LF 로 쓴다. CPython 의 읽는 쪽은 \r 도 떼어내지만, 줄 끝에 \r 이
    남으면 sys.path 에 '..\app\r' 같은 게 들어가 조용히 import 가 깨진다.
    확실한 쪽을 고른다.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    body = text.replace("\r\n", "\n")
    if crlf:
        body = body.replace("\n", "\r\n")
    # 메모장이 한글을 제대로 열게 BOM 을 붙인다 (.txt 만. .bat 과 ._pth 에 BOM 은 금물).
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body.encode("utf-8"))


def build_tree(dest: Path, cache: Path) -> Path:
    """dest 아래에 pibo-connect/ 를 만들고 그 경로를 돌려준다."""
    root = dest / BUNDLE
    if root.exists():
        shutil.rmtree(root)
    py = root / PY_DIR
    py.mkdir(parents=True)

    with zipfile.ZipFile(fetch_embed(cache)) as z:
        z.extractall(py)
    exe = py / "python.exe"
    if not exe.exists():
        raise SystemExit("!! embeddable 안에 python.exe 가 없다")
    verify_signature(exe)

    # 기본 ._pth 를 우리 것으로 바꾼다. sys.path 가 여기서 정해진다.
    for old in py.glob("python*._pth"):
        old.unlink()
    write_text(py / f"python{PY_TAG}._pth", "\n".join(PTH_LINES) + "\n", crlf=False)

    app = root / APP_DIR
    app.mkdir(parents=True)
    copy_app(app)
    install_deps(app / LIB_DIR)

    write_text(root / "시작하기.bat", START_BAT)
    write_text(root / "로봇 확인하기.bat", CHECK_BAT)
    write_text(root / "먼저-읽어보세요.txt", README_TXT, bom=True)
    return root


def make_zip(tree: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    base = tree.parent
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(tree.rglob("*")):
            if p.is_file():
                z.write(p, str(p.relative_to(base)).replace(os.sep, "/"))
    print(f"\n{out}  ({out.stat().st_size / 1e6:.1f} MB)")


def main() -> int:
    ap = argparse.ArgumentParser(description="윈도우용 풀어서 쓰는 묶음을 만든다")
    ap.add_argument("--out", default="dist/pibo-connect-windows-portable.zip")
    ap.add_argument("--work", default="build/_portable",
                    help="묶기 전 폴더를 펼칠 곳")
    ap.add_argument("--cache", default="build/_cache",
                    help="embeddable zip 을 받아 둘 곳")
    ap.add_argument("--no-zip", action="store_true",
                    help="폴더만 만든다 (시험용)")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print(f"pibo-connect {__version__} — 풀어서 쓰는 묶음")
    tree = build_tree(Path(args.work).resolve(), Path(args.cache).resolve())
    print(f"  폴더      : {tree}")
    if not args.no_zip:
        make_zip(tree, Path(args.out).resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
