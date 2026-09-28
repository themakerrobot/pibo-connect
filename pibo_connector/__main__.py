"""진입점. 소스로도 실행 파일로도 같은 경로로 뜬다.

    python -m pibo_connector          # 소스 실행
    pibo-connect.exe                  # 파이썬 없는 노트북

기본은 127.0.0.1 바인딩이다. 교실 노트북을 남이 건드릴 일이 없게.
다른 기기에서 열어야 하면 --host 0.0.0.0 을 주고, 그때는 토큰이 붙는다.
"""

import argparse
import secrets
import socket
import sys
import threading
import webbrowser

from . import __version__, config


def _utf8_console() -> None:
    """윈도우 콘솔이 cp1252/cp949 여도 한글 출력에 죽지 않게 한다.

    영어권 윈도우의 기본 코드페이지는 cp1252 다. 여기에 한글을 찍으면
    UnicodeEncodeError 로 프로세스가 통째로 끝난다 — 실행 파일이 첫 줄에서
    죽는다는 뜻이다. errors='replace' 로 물러나게 해둔다.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _free_port(host: str, port: int) -> int:
    """그 포트가 막혀 있으면 다음 빈 포트를 찾는다."""
    for p in range(port, port + 20):
        s = socket.socket()
        try:
            s.bind((host if host != "0.0.0.0" else "", p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    return port


def main(argv=None) -> int:
    _utf8_console()

    ap = argparse.ArgumentParser(
        prog="pibo-connect",
        description="파이보/파이브레인 다대수 제어 — 브라우저 한 장으로 찾고 실행한다")
    ap.add_argument("--host", default=config.DEFAULT_HOST,
                    help=f"바인딩 주소 (기본 {config.DEFAULT_HOST})")
    ap.add_argument("--port", type=int, default=config.DEFAULT_PORT,
                    help=f"포트 (기본 {config.DEFAULT_PORT}, 막혀 있으면 다음 포트)")
    ap.add_argument("--no-browser", action="store_true", help="브라우저를 열지 않는다")
    ap.add_argument("--token", default="", help="접속 토큰 직접 지정")
    ap.add_argument("--version", action="version", version=f"pibo-connect {__version__}")
    args = ap.parse_args(argv)

    # 밖으로 여는 경우에만 토큰을 건다. 로컬 전용이면 성가시기만 하다.
    token = args.token
    if not token and args.host not in ("127.0.0.1", "localhost"):
        token = secrets.token_urlsafe(9)

    port = _free_port(args.host, args.port)
    shown = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host
    url = f"http://{shown}:{port}/"
    if token:
        url += f"?token={token}"

    from .app import create_app
    import uvicorn

    print(f"pibo-connect {__version__}")
    print(f"  데이터: {config.data_dir()}")
    print(f"  주소  : {url}")
    if token:
        print(f"  토큰  : {token}   (--host {args.host} 이라 토큰이 필요하다)")
    print("  종료  : Ctrl+C")
    sys.stdout.flush()

    try:
        app = create_app(token)
    except Exception as ex:
        print(f"!! 서버를 만들지 못했다: {ex}")
        return 1

    if not args.no_browser:
        threading.Timer(1.0, lambda: _open(url)).start()

    uvicorn.run(app, host=args.host, port=port, log_level="warning",
                access_log=False)
    return 0


def _open(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
