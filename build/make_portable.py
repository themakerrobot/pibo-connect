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
띄운다. 결과적으로 묶음 안에서 실행되는 PE 는 PSF 가 서명한 것이고, 우리
것은 .py 텍스트뿐이다. 이 묶음은 실기에서 차단 없이 켜졌다.

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
      pibo-connect.exe            ← python.exe 복사본 (PSF 서명). 이걸 누른다
      python311.dll  python3.dll  vcruntime140*.dll   ← 옮길 수 없는 것들
      python311._pth              ← sys.path 를 app 아래로 고정
      app/
        README.txt                ← 선생님용 안내
        runtime/                  ← python311.zip, *.pyd, libssl-3 …
        sitecustomize.py          ← 두 번 눌렀을 때 커넥터를 띄우는 곳
        pibo_connector/           ← static/ 포함
        examples/
        lib/                      ← 의존성 (pip --target)
      data/                       ← 찾은 로봇 목록 (처음 켤 때)

풀었을 때 눌러야 할 것이 하나만 보여야 한다. 그래서 embeddable 을 app/runtime
으로 넣고, 옮길 수 없는 것만 루트에 남긴다 — python3*.dll 은 실행 파일의 import
table 이 이름으로 옆에서 찾고, vcruntime*.dll 은 그 DLL 이 쓴다. python311.zip 과
.pyd 는 ._pth 로 자리를 알려주면 되고, .pyd 에 딸린 DLL(libssl-3, libcrypto-3,
libffi-8, sqlite3)은 확장 모듈이 LOAD_WITH_ALTERED_SEARCH_PATH 로 불리는 덕에
그 .pyd 와 같은 폴더에서 찾아진다. tests/portable_smoke.py 가 실제로 켜 본다.

**파일 이름은 전부 ASCII 다.** 탐색기의 zip 풀기가 한글 이름을 제대로 못 살리는
경우가 있다 (실기에서 이상하게 보였다). 한글은 파일 안에만 있다.

.bat 은 묶음에 하나도 없다. SAC 가 막는 종류를 아예 두지 않는다. 옵션이나
--check 가 필요하면 검은 창에서
    pibo-connect.exe -m pibo_connector --check 192.168.0.51
    pibo-connect.exe -m pibo_connector --host 0.0.0.0
처럼 쓴다. 인자를 주면 sitecustomize 의 자동 시작은 빠진다.

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
RUNTIME_DIR = "runtime"          # app/runtime — embeddable 중 루트에 안 남는 것들
LIB_DIR = "lib"                  # app/lib — 의존성

# 루트에 남겨야 하는 것. 여기 있는 것만 밖에 나온다.
#   python3*.dll   : 실행 파일의 import table 이 이름으로 찾는다. 옆에 없으면
#                    "python311.dll 을 찾을 수 없습니다" 로 안 켜진다.
#                    python3.dll(stable ABI forwarder)도 같이 둔다 — abi3 휠이
#                    이걸 링크하는 경우가 있고, 66KB 아끼자고 걸 이유가 없다.
#   vcruntime*.dll : python311.dll 이 쓰는 C 런타임. 탐색이 실행 파일 폴더에서
#                    시작하므로 이것도 옆에 있어야 한다.
# 나머지(python311.zip, *.pyd, libssl-3, libcrypto-3, libffi-8, sqlite3, 카탈로그)
# 는 app/runtime 으로 들어간다. .pyd 에 딸린 DLL 은 그 .pyd 와 같은 폴더에서
# 찾으므로(확장 모듈은 LOAD_WITH_ALTERED_SEARCH_PATH 로 불린다) 같이 옮기면 된다.
ROOT_KEEP = ("python3*.dll", "vcruntime*.dll")

# 켜는 버튼. python.exe 를 복사해 이 이름으로 둔다 (서명은 이름과 무관하다).
# 묶음 안의 파일 이름은 전부 ASCII 로 맞춘다 — 탐색기의 zip 풀기가 한글 이름을
# 제대로 못 살리는 경우가 있고, 실기에서 실제로 이상하게 보였다.
LAUNCHER = "pibo-connect.exe"
README_NAME = "README.txt"

# ._pth — 실행 파일이 있는 폴더(= 묶음 루트) 기준 상대경로다.
# 'import site' 를 넣어야 app/sitecustomize.py 가 불리고, lib 의 .pth 처리와
# importlib.metadata 도 정상이 된다. 이 줄이 없으면 두 번 눌러도 안 켜진다.
# 파일 이름은 DLL 이름 기준(python311._pth) 하나만 쓴다. 표준 배포본이 그렇게
# 쓰고, python311.dll 이 루트에 있으므로 런처 이름이 무엇이든 찾아진다.
PTH_LINES = [
    f"{APP_DIR}\\{RUNTIME_DIR}\\python{PY_TAG}.zip",
    f"{APP_DIR}\\{RUNTIME_DIR}",
    APP_DIR,
    f"{APP_DIR}\\{LIB_DIR}",
    ".",
    "",
    "import site",
]

README_TXT = """파이보 커넥터 — 풀어서 쓰는 묶음 (버전 {ver})

교실의 파이보·파이브레인을 브라우저 한 장으로 찾고, 같은 코드를 한 번에 실행해요.
노트북에 설치하는 것은 없어요. 이 폴더만 있으면 돼요.


■ 쓰는 방법

  1. 받은 zip 파일을 오른쪽 클릭 - [압축 풀기] 를 누르세요.
     (zip 안에서 바로 두 번 누르면 안 켜져요. 꼭 풀어서 쓰세요.)
  2. 풀린 폴더에서 [{run}] 를 두 번 누르세요.
  3. 검은 창이 하나 뜨고, 잠시 뒤 브라우저가 열려요.
     검은 창은 닫지 마세요 - 닫으면 꺼져요.
  4. 로봇과 노트북이 같은 와이파이에 있는지 확인하고 [로봇 찾기] 를 누르세요.

  끝낼 때는 검은 창을 닫으면 돼요.


■ 폴더 안에 있는 것

  {run}
      켜는 버튼이에요. 이것만 누르면 돼요.
  data\\
      찾은 로봇 목록이에요 (처음 켤 때 생겨요).
  app\\  그리고 이름이 어려운 파일들
      프로그램이 쓰는 것들이에요. 안 건드려도 되고, 지우면 안 켜져요.

  다음 버전으로 바꿀 때는 data\\ 만 남겨 두고 나머지를 덮어쓰면
  찾아둔 로봇 목록이 그대로예요.


■ "이 앱이 차단되었습니다" 가 뜨나요

  이 묶음은 그 창이 뜨지 않도록 만든 거예요. 누르는 파일이 python.org 가
  서명해서 배포하는 공식 파이썬이고, 이름만 알아보기 쉽게 바꾼 거예요.
  (서명은 파일 이름이 아니라 내용에 붙어 있어서 그대로 살아 있어요.)

  그래도 뜬다면, 압축을 풀기 전에 zip 파일을 오른쪽 클릭 - [속성] -
  맨 아래 [차단 해제] 를 체크하고 확인을 누른 다음에 압축을 푸세요.
  그리고 어떤 파일 이름이 창에 나왔는지 알려주세요.


■ 로봇이 안 찾아질 때

  로봇이 켜져 있고 노트북과 같은 와이파이인지 보세요.
  5초쯤 기다렸다 [로봇 찾기] 를 한 번 더 누르세요.

  그래도 안 되면 어디서 막혔는지 짚어 볼 수 있어요.
  이 폴더에서 주소창에 cmd 를 치고 엔터를 누른 다음, 아래를 그대로 쓰세요.
  (192.168.0.51 자리에 로봇 주소를 넣어요)

      {run} -m pibo_connector --check 192.168.0.51

  한 줄씩 어디까지 됐는지 알려줘요. 그 내용을 그대로 보내주시면 돼요.


■ 다른 기기에서도 열고 싶을 때

      {run} -m pibo_connector --host 0.0.0.0

  같은 와이파이의 다른 노트북·태블릿에서도 열려요. 검은 창에 주소와 함께
  암호(토큰)가 같이 나오는데, 그 주소를 통째로 넣어야 열려요.

만든 곳: Circulus
""".format(ver=__version__, run=LAUNCHER)


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
    """dest 아래에 pibo-connect/ 를 만들고 그 경로를 돌려준다.

    선생님 눈에 보이는 건 런처 두 개와 읽을거리뿐이어야 한다. 나머지는
    app/ 안으로 넣는다. 다만 python3*.dll 과 vcruntime*.dll 은 옮길 수 없다 —
    실행 파일이 이름으로 옆에서 찾는다. ROOT_KEEP 참고.
    """
    root = dest / BUNDLE
    if root.exists():
        shutil.rmtree(root)
    app = root / APP_DIR
    runtime = app / RUNTIME_DIR
    runtime.mkdir(parents=True)

    # 일단 runtime 에 통째로 푼 뒤, 루트에 있어야 하는 것만 올린다.
    with zipfile.ZipFile(fetch_embed(cache)) as z:
        z.extractall(runtime)
    exe = runtime / "python.exe"
    if not exe.exists():
        raise SystemExit("!! embeddable 안에 python.exe 가 없다")
    verify_signature(exe)

    moved = []
    for pat in ROOT_KEEP:
        for f in sorted(runtime.glob(pat)):
            shutil.move(str(f), str(root / f.name))
            moved.append(f.name)
    if not any(n.lower() == f"python{PY_TAG}.dll" for n in moved):
        raise SystemExit(f"!! python{PY_TAG}.dll 을 루트로 못 올렸다 — {moved}")
    print(f"  루트 DLL  : {', '.join(moved)}")

    # sys.path 를 우리 것으로. 표준 배포본이 넣어 둔 ._pth 는 버린다.
    for old_pth in runtime.glob("python*._pth"):
        old_pth.unlink()
    write_text(root / f"python{PY_TAG}._pth", "\n".join(PTH_LINES) + "\n", crlf=False)

    copy_app(app)
    install_deps(app / LIB_DIR)

    # 켜는 버튼. python.exe 를 복사해 이름만 바꾼다 — Authenticode 서명은
    # 파일 내용에 붙으므로 이름을 바꿔도 PSF 서명이 그대로 유효하다.
    # 복사본도 다시 확인한다. 복사 과정에서 잘리면 서명이 깨진다.
    shutil.copy2(exe, root / LAUNCHER)
    ok, blob, detail = pe_cert_blob(root / LAUNCHER)
    if not (ok and blob_names_signer(blob)):
        raise SystemExit(f"!! 복사한 런처의 서명이 깨졌다: {LAUNCHER} — {detail}")
    # 원본 python.exe/pythonw.exe 는 남기지 않는다. 옮긴 자리에서는 옆에
    # python311.dll 이 없어 어차피 안 돌고, 무엇을 눌러야 할지 헷갈리게만 한다.
    for name in ("python.exe", "pythonw.exe"):
        (runtime / name).unlink(missing_ok=True)
    print(f"  런처      : {LAUNCHER}  (서명 그대로)")

    write_text(app / README_NAME, README_TXT, bom=True)

    # 탐색기의 zip 풀기가 한글 이름을 못 살리는 경우가 있다. 이름은 전부 ASCII 다.
    bad = [str(f.relative_to(root)) for f in root.rglob("*")
           if not str(f.relative_to(root)).isascii()]
    if bad:
        raise SystemExit(f"!! 묶음에 ASCII 아닌 파일 이름이 있다: {bad[:5]}")
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
