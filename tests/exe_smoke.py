"""묶은 실행 파일이 실제로 뜨는지 본다. 세 OS 에서 같은 스크립트를 쓴다.

    python -m tests.exe_smoke dist/pibo-connect.exe [--timeout 120]

실패하면 실행 파일이 찍은 stdout/stderr 를 통째로 보여준다.
PyInstaller 로 묶인 뒤에야 드러나는 문제(모듈 누락, static 경로)는
이 출력이 없으면 원인을 알 수 없다.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests._launch import Server, utf8_console   # noqa: E402


def main() -> int:
    utf8_console(sys.stdout, sys.stderr)
    ap = argparse.ArgumentParser()
    ap.add_argument("exe")
    ap.add_argument("--timeout", type=float, default=120.0,
                    help="onefile 은 첫 실행에 압축을 푼다. 넉넉히 준다")
    args = ap.parse_args()

    exe = Path(args.exe).resolve()
    if not exe.exists():
        print(f"!! 실행 파일이 없다: {exe}")
        return 1
    print(f"exe: {exe}  ({exe.stat().st_size / 1e6:.1f} MB)")

    log = Path(tempfile.gettempdir()) / "exe_smoke.log"
    fails = []

    with Server([str(exe), "--no-browser"], log) as srv:
        info, died = srv.wait_ready(args.timeout)
        if info is None:
            print(f"!! 실행 파일이 그냥 끝났다 (exit {srv.proc.returncode})" if died
                  else f"!! {args.timeout:.0f}초 안에 뜨지 않았다")
            fails.append("기동")
        else:
            print(f"ok  {srv.base}/api/info")
            print("    " + json.dumps(info, ensure_ascii=False))
            if not info.get("frozen"):
                print("!! frozen 이 False 다 — 묶인 실행 파일이 아니다")
                fails.append("frozen")

            # static 이 번들에 안 들어갔으면 여기서 걸린다
            # static 이 번들에 안 들어갔으면 여기서 걸린다. 폰트·이미지까지 본다.
            for path, want in (("/", "파이보 커넥터"), ("/static/app.js", ""),
                               ("/static/maker-ui.css", "--paper"),
                               ("/static/fonts/pretendard.css", "Pretendard"),
                               ("/static/fonts/woff2-dynamic-subset/PretendardVariable.subset.0.woff2", ""),
                               ("/static/img/pibo-logo.png", ""), ("/favicon.ico", "")):
                try:
                    st, body = srv.get(path, 8)
                    if st != 200 or (want and want not in body):
                        print(f"!! {path} 이 이상하다 (status {st})")
                        fails.append(path)
                    else:
                        print(f"ok  {path}")
                except Exception as ex:
                    print(f"!! {path} 을 못 받았다: {ex}")
                    fails.append(path)

        out = srv.log().strip()

    # 윈도우: 버전 정보 리소스. 속성 창 '자세히' 에 회사·제품·버전이 떠야 한다.
    if sys.platform == "win32":
        try:
            import pefile
            from pibo_connector import __version__
            pe = pefile.PE(str(exe), fast_load=True)
            pe.parse_data_directories()
            got = ""
            for fi in getattr(pe, "FileInfo", []):
                for entry in fi:
                    if entry.Key == b"StringFileInfo":
                        for st in entry.StringTable:
                            got = st.entries.get(b"ProductVersion", b"").decode("utf-8", "replace")
            if got == __version__:
                print(f"ok  VERSIONINFO ProductVersion={got}")
            else:
                print(f"!! VERSIONINFO 가 없거나 버전이 다르다: '{got}' (기대 {__version__})")
                fails.append("VERSIONINFO")
        except ImportError:
            print("(pefile 없음 — VERSIONINFO 검사 생략)")

    if out or fails:
        print("─── 실행 파일 출력 " + "─" * 40)
        print(out or "(출력 없음)")
        print("─" * 58)

    if fails:
        print("실패: " + ", ".join(fails))
        return 1
    print("exe 정상")
    return 0


if __name__ == "__main__":
    sys.exit(main())
