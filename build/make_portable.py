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
Python Software Foundation 이름으로 Authenticode 서명이 되어 있다.

켜는 버튼은 왜 .exe 인가 (.bat 이 아니라)
-----------------------------------------
처음엔 시작하기.bat 으로 냈는데 **실기에서 SAC 가 그것도 막았다.** SAC 는
서명 없는 프로그램만이 아니라 출처 불명 스크립트(.bat 포함)도 막는다.
그래서 스크립트를 쓰지 않는다. 켜는 버튼은 **python.exe 를 복사해 이름만
바꾼 것**이다 — Authenticode 서명은 파일 내용에 붙고 파일 이름과 무관하므로
복사·개명해도 PSF 서명이 그대로 유효하다. 두 번 누르면 파이썬이 대화형으로
뜨고, app/sitecustomize.py 가 site 초기화 때 자동으로 import 되어 커넥터를
띄운다. 무엇을 할지는 실행 파일 이름으로 가른다 ('확인' 이 들어 있으면
--check). 결과적으로 묶음 안에서 실행되는 PE 는 전부 PSF 가 서명한 것이고,
우리 것은 .py 텍스트뿐이다.

그 전제가 진짜인지는 추측하지 않는다. `verify_signature()` 가 세 번 본다.
  1. PE 의 Certificate Table 에 PKCS#7 서명 blob 이 있나  (어디서든)
  2. 그 blob 안의 인증서가 Python Software Foundation 을 담고 있나  (어디서든)
  3. Get-AuthenticodeSignature 로 체인과 Subject 까지  (윈도우, 되는 경우)
1·2 는 못 넘어가면 빌드를 세운다. 3 은 러너에 따라 cmdlet 이 안 붙어서
(windows-latest 의 Windows PowerShell 5.1 에서 Microsoft.PowerShell.Security
로드가 실패한다) pwsh → powershell 순으로 해보고 둘 다 안 되면 못 했다고만
말한다 — 돌기만 하면 Valid 가 아닐 때 세운다. 복사한 런처도 같이 확인한다.

묶음 구조 (zip 안)
------------------
    pibo-connect/
      1. 파이보 커넥터 시작.exe   ← python.exe 복사본 (PSF 서명). 이걸 누른다
      2. 로봇 확인하기.exe        ← 같은 복사본. 안 찾아질 때 --check
      먼저-읽어보세요.txt
      python.exe  python311.dll  python311.zip  *.pyd ...  ← 공식 배포본 그대로
      python311._pth              ← sys.path 를 app 과 app/lib 로 고정
      app/
        sitecustomize.py          ← 두 번 눌렀을 때 커넥터를 띄우는 곳
        pibo_connector/           ← static/ 포함
        examples/
        lib/                      ← 의존성 (pip --target)

embeddable 은 **한 폴더에 펼친 그대로** 둔다. python311.dll 은 exe 옆에
있어야 하고, 확장 모듈(.pyd) 이 딸린 DLL(libssl 등) 도 같은 폴더에서 찾는다.
보기엔 파일이 많아도, 옮겨서 얻는 건 없고 잃을 건 많다.

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
APP_DIR = "app"
LIB_DIR = "lib"                  # app/lib

# 켜는 버튼. python.exe 를 복사해 이 이름으로 둔다 (서명은 이름과 무관하다).
# 앞에 번호를 붙이는 건 탐색기에서 맨 위에 오게 하려는 것이다.
# sitecustomize.CHECK_MARK('확인') 가 두 번째를 --check 로 가른다.
LAUNCH_RUN = "1. 파이보 커넥터 시작.exe"
LAUNCH_CHECK = "2. 로봇 확인하기.exe"
LAUNCHERS = (LAUNCH_RUN, LAUNCH_CHECK)

# ._pth — 실행 파일이 있는 폴더(= 묶음 루트) 기준 상대경로다.
# 'import site' 를 넣어야 app/sitecustomize.py 가 불리고, lib 의 .pth 처리와
# importlib.metadata 도 정상이 된다. 이 줄이 없으면 두 번 눌러도 안 켜진다.
PTH_LINES = [
    f"python{PY_TAG}.zip",
    ".",
    APP_DIR,
    f"{APP_DIR}\\{LIB_DIR}",
    "",
    "import site",
]

# 개발자·고급 사용자용. 선생님 눈에 안 띄게 app/ 안에 둔다. 켜는 버튼이 아니다.
# (SAC 가 막을 수 있는 건 이 파일이고, 아무도 이걸 누르지 않아도 묶음은 돈다.)
OPTIONS_BAT = r"""@echo off
rem Run the connector with extra options. ASCII-ONLY: cmd.exe reads a .bat in
rem the console codepage, which differs per PC, so Korean here would garble.
rem Normal use does not need this file - double-click the .exe in the folder
rem above instead. Smart App Control may block this script; the .exe is not
rem a script and is signed by the Python Software Foundation.
rem   example:  run-with-options.bat --host 0.0.0.0
setlocal
cd /d "%~dp0.."
set "PIBO_CONNECT_DATA=%~dp0..\data"
"python.exe" -m pibo_connector %*
pause
"""

README_TXT = """파이보 커넥터 — 풀어서 쓰는 묶음 (버전 {ver})

교실의 파이보·파이브레인을 브라우저 한 장으로 찾고, 같은 코드를 한 번에 실행해요.
노트북에 설치하는 것은 없어요. 이 폴더만 있으면 돼요.


■ 쓰는 방법

  1. 받은 zip 파일을 오른쪽 클릭 - [압축 풀기] 를 누르세요.
     (zip 안에서 바로 두 번 누르면 안 켜져요. 꼭 풀어서 쓰세요.)
  2. 풀린 폴더에서 [{run}] 를 두 번 누르세요. 맨 위에 있어요.
  3. 검은 창이 하나 뜨고, 잠시 뒤 브라우저가 열려요.
     검은 창은 닫지 마세요 - 닫으면 꺼져요.
  4. 로봇과 노트북이 같은 와이파이에 있는지 확인하고 [로봇 찾기] 를 누르세요.

  끝낼 때는 검은 창을 닫으면 돼요.


■ 로봇이 안 찾아질 때

  [{check}] 를 두 번 누르고, 로봇의 IP 주소를 넣으세요.
  어디서 막혔는지 한 줄씩 알려줘요. 그 내용을 그대로 보내주시면 돼요.


■ 폴더 안에 있는 것

  {run}
      켜는 버튼이에요. 이것만 누르면 돼요.
  {check}
      로봇 한 대를 짚어 보는 버튼이에요.
  app\\
      커넥터 프로그램이 들어 있어요.
  data\\
      찾은 로봇 목록이에요 (처음 켤 때 생겨요).
  그 밖의 파일들
      python.org 가 배포하는 공식 파이썬이에요. 그대로 넣었어요.
      건드리지 않아도 되고, 지우면 안 켜져요.

  다음 버전으로 바꿀 때는 data\\ 만 남겨 두고 나머지를 덮어쓰면
  찾아둔 로봇 목록이 그대로예요.


■ "이 앱이 차단되었습니다" 가 뜨나요

  이 묶음은 그 창이 뜨지 않도록 만든 거예요. 누르는 파일이 python.org 가
  서명해서 배포하는 공식 파이썬이고, 이름만 알아보기 쉽게 바꾼 거예요.
  (서명은 파일 이름이 아니라 내용에 붙어 있어서 그대로 살아 있어요.)

  그래도 뜬다면, 압축을 풀기 전에 zip 파일을 오른쪽 클릭 - [속성] -
  맨 아래 [차단 해제] 를 체크하고 확인을 누른 다음에 압축을 푸세요.
  그리고 어떤 파일 이름이 창에 나왔는지 알려주세요.

만든 곳: Circulus
""".format(ver=__version__, run=LAUNCH_RUN, check=LAUNCH_CHECK)


# ── 서명 확인 ──────────────────────────────────────────────

# 서명 주체. 이 이름이 인증서 안에 없으면 python.org 배포본이 아니다.
SIGNER = "Python Software Foundation"


def pe_cert_blob(exe: Path):
    """PE 의 Certificate Table(데이터 디렉토리 4번) 을 직접 읽는다.

    (있나, PKCS#7 바이트, 설명). 윈도우가 아닌 데서도 확인된다.
    """
    b = exe.read_bytes()
    if b[:2] != b"MZ":
        return False, b"", "MZ 가 아니다"
    e_lfanew = struct.unpack_from("<I", b, 0x3C)[0]
    if b[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        return False, b"", "PE 서명이 없다"
    magic = struct.unpack_from("<H", b, e_lfanew + 24)[0]
    if magic == 0x20B:            # PE32+
        dd = e_lfanew + 24 + 112
    elif magic == 0x10B:          # PE32
        dd = e_lfanew + 24 + 96
    else:
        return False, b"", f"알 수 없는 optional header magic 0x{magic:X}"
    off, size = struct.unpack_from("<II", b, dd + 4 * 8)
    if not off or not size:
        return False, b"", "Certificate Table 이 비어 있다 (서명 없음)"
    # WIN_CERTIFICATE: dwLength, wRevision, wCertificateType, 그 뒤가 PKCS#7
    _len, _rev, ctype = struct.unpack_from("<IHH", b, off)
    if ctype != 0x0002:           # WIN_CERT_TYPE_PKCS_SIGNED_DATA
        return False, b"", f"PKCS#7 이 아니다 (type 0x{ctype:04X})"
    return True, b[off + 8:off + size], f"Authenticode {size} bytes @ 0x{off:X}"


def pe_has_signature(exe: Path):
    ok, _blob, detail = pe_cert_blob(exe)
    return ok, detail


def blob_names_signer(blob: bytes, who: str = SIGNER) -> bool:
    """PKCS#7 안의 인증서가 이 이름을 담고 있나.

    체인 검증은 아니다. 인증서의 Subject 문자열은 DER 의 PrintableString /
    UTF8String 이라 바이트로 그대로 들어 있고, 그걸 찾는다. 파이썬만으로
    어디서든 되기 때문에 이게 1차 관문이다.
    """
    return who.encode("utf-8") in blob or who.encode("utf-16-le") in blob


def authenticode_subject(exe: Path):
    """윈도우에서 체인까지 확인한다. (status, subject) 또는 None.

    None 은 '확인을 못 했다' 다 — 러너에 따라 Get-AuthenticodeSignature 가
    안 붙는다 (windows-latest 의 Windows PowerShell 5.1 에서
    Microsoft.PowerShell.Security 모듈 로드가 실패한 적이 있다).
    그래서 pwsh 를 먼저 쓰고, 안 되면 못 했다고만 말한다 — 1차 관문은
    이미 통과한 상태다.
    """
    if sys.platform != "win32":
        return None
    ps = ("Import-Module Microsoft.PowerShell.Security -ErrorAction SilentlyContinue; "
          f"$s = Get-AuthenticodeSignature -LiteralPath '{exe}'; "
          "Write-Output ('STATUS=' + $s.Status); "
          "Write-Output ('SUBJECT=' + $s.SignerCertificate.Subject)")
    for shell in ("pwsh", "powershell"):
        try:
            out = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", ps],
                                 capture_output=True, text=True, timeout=180)
        except Exception:
            continue
        status = subject = ""
        for line in out.stdout.splitlines():
            line = line.strip()
            if line.startswith("STATUS="):
                status = line[7:].strip()
            elif line.startswith("SUBJECT="):
                subject = line[8:].strip()
        if status:
            return status, subject
        print(f"  (참고) {shell} 로 체인 확인 실패: "
              f"{(out.stderr or out.stdout).strip().splitlines()[:1]}")
    return None


def verify_signature(exe: Path) -> None:
    """서명이 없거나 PSF 것이 아니면 빌드를 세운다.

    이 묶음의 존재 이유가 '실행되는 PE 는 PSF 가 서명한 것' 이다.
    그게 아니면 exe 를 내는 것과 다를 게 없으니 묶음을 만들지 않는다.
    """
    signed, blob, detail = pe_cert_blob(exe)
    print(f"  서명(PE)  : {'있다' if signed else '없다'} — {detail}")
    if not signed:
        raise SystemExit(
            "!! 받아온 python.exe 에 Authenticode 서명이 없다.\n"
            "   서명된 python.exe 가 SAC 를 넘는 유일한 근거다. 묶음을 내지 않는다.")

    named = blob_names_signer(blob)
    print(f"  서명(주체): {'PSF 다' if named else 'PSF 가 아니다'} "
          f"— 인증서에서 '{SIGNER}' 찾기")
    if not named:
        raise SystemExit(
            f"!! 인증서에 '{SIGNER}' 가 없다. python.org 배포본이 아닐 수 있다.\n"
            f"   {EMBED_URL}")

    got = authenticode_subject(exe)
    if got is None:
        print("  서명(체인): 확인 못 함 (윈도우가 아니거나 cmdlet 이 없다). "
              "위 두 관문은 통과했다")
        return
    status, subject = got
    print(f"  서명(체인): {status} — {subject}")
    if status != "Valid":
        raise SystemExit(f"!! 서명 상태가 Valid 가 아니다: {status}")
    if SIGNER not in subject:
        raise SystemExit(f"!! 서명 주체가 PSF 가 아니다: {subject}")


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
    # 두 번 눌렀을 때 커넥터를 띄우는 곳. app/ 이 sys.path 에 있으므로
    # site 초기화가 자동으로 import 한다. 이게 빠지면 대화형 파이썬만 뜬다.
    shutil.copy2(ROOT / "build" / "sitecustomize.py", app / "sitecustomize.py")
    # 소스 실행과 같은 자리여야 한다. 아니면 static 이 404 다.
    for need in (app / "pibo_connector" / "static" / "app.js", app / "examples",
                 app / "sitecustomize.py"):
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
    root.mkdir(parents=True)

    # embeddable 은 루트에 그대로 펼친다. python311.dll 은 실행 파일 옆에
    # 있어야 하고, .pyd 가 딸린 DLL(libssl-3, libffi-8, sqlite3) 도 같은
    # 폴더에서 찾는다. 나누면 얻는 것 없이 깨질 구멍만 생긴다.
    with zipfile.ZipFile(fetch_embed(cache)) as z:
        z.extractall(root)
    exe = root / "python.exe"
    if not exe.exists():
        raise SystemExit("!! embeddable 안에 python.exe 가 없다")
    verify_signature(exe)

    # 기본 ._pth 를 우리 것으로 바꾼다. sys.path 가 여기서 정해진다.
    # 이름은 셋 다 쓴다 — CPython 은 실행 파일 이름 기준과 DLL 이름 기준을
    # 모두 보는데, 런처 이름을 바꿔 두었으므로 어느 쪽이 먼저든 맞게 한다.
    # 없으면 두 번 눌러도 app/sitecustomize.py 를 못 찾아 안 켜진다.
    for old_pth in root.glob("python*._pth"):
        old_pth.unlink()
    body = "\n".join(PTH_LINES) + "\n"
    for name in (f"python{PY_TAG}._pth",
                 *(Path(x).stem + "._pth" for x in LAUNCHERS)):
        write_text(root / name, body, crlf=False)

    app = root / APP_DIR
    app.mkdir(parents=True)
    copy_app(app)
    install_deps(app / LIB_DIR)

    # 켜는 버튼. python.exe 를 복사해 이름만 바꾼다 — Authenticode 서명은
    # 파일 내용에 붙으므로 이름을 바꿔도 PSF 서명이 그대로 유효하다.
    # 복사본도 다시 확인한다. 복사 과정에서 잘리면 서명이 깨진다.
    for name in LAUNCHERS:
        shutil.copy2(exe, root / name)
        ok, blob, detail = pe_cert_blob(root / name)
        if not (ok and blob_names_signer(blob)):
            raise SystemExit(f"!! 복사한 런처의 서명이 깨졌다: {name} — {detail}")
    print(f"  런처      : {', '.join(LAUNCHERS)}  (서명 그대로)")

    write_text(root / "먼저-읽어보세요.txt", README_TXT, bom=True)
    write_text(app / "run-with-options.bat", OPTIONS_BAT)
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
