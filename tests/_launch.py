"""테스트용 기동 헬퍼. 소스 실행과 묶은 실행 파일에 같은 걸 쓴다.

포트를 고정으로 가정하지 않는다 — __main__.py 의 _free_port 는 그 포트가
막혀 있으면 다음 포트로 옮긴다. 대신 서버가 stdout 에 찍는 주소를 읽어
실제 포트를 알아낸다.
"""

import json
import os
import re
import signal
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

ADDR_RX = re.compile(r"주소\s*:\s*(http://[0-9.]+:(\d+)/\S*)")


def utf8_console(*streams) -> None:
    """윈도우 콘솔은 cp1252 다. 한글을 찍다 죽으면 로그를 못 본다."""
    for stream in streams:
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


class Server:
    def __init__(self, cmd: List[str], log_path: Path, cwd: Optional[str] = None):
        self.cmd = cmd
        self.log_path = log_path
        self.cwd = cwd
        self.proc: Optional[subprocess.Popen] = None
        self.port: Optional[int] = None
        self.base = ""

    def __enter__(self) -> "Server":
        self._fh = open(self.log_path, "wb")
        # PyInstaller onefile 은 부트로더가 진짜 파이썬을 자식으로 띄운다.
        # 부모만 죽이면 자식이 고아로 남는다 — CI 정리 단계에
        # 'Terminate orphan process (pibo-connect)' 가 찍히던 이유다.
        # POSIX 는 새 세션으로 띄워 그룹째, 윈도우는 taskkill /T 로 트리째 죽인다.
        kw = {} if os.name == "nt" else {"start_new_session": True}
        self.proc = subprocess.Popen(self.cmd, stdout=self._fh,
                                     stderr=subprocess.STDOUT, cwd=self.cwd, **kw)
        return self

    def __exit__(self, *exc) -> None:
        if self.proc:
            self._kill_tree()
        try:
            self._fh.close()
        except Exception:
            pass

    def _kill_tree(self) -> None:
        p = self.proc
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                               capture_output=True, timeout=20)
            else:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except Exception:
            try:
                p.terminate()
            except Exception:
                pass
        try:
            p.wait(timeout=15)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass

    def log(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    def wait_ready(self, timeout: float = 90.0) -> Tuple[Optional[dict], bool]:
        """(api_info, died). 서버가 찍은 주소를 읽어 그 포트로 확인한다."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc and self.proc.poll() is not None:
                return None, True
            if self.port is None:
                m = ADDR_RX.search(self.log())
                if m:
                    self.base = m.group(1).split("?")[0].rstrip("/")
                    self.port = int(m.group(2))
            if self.port is not None:
                try:
                    return self.get_json("/api/info", 3), False
                except Exception:
                    pass
            time.sleep(0.5)
        return None, False

    def get(self, path: str, timeout: float = 5.0) -> Tuple[int, str]:
        with urllib.request.urlopen(self.base + path, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")

    def get_json(self, path: str, timeout: float = 5.0) -> dict:
        return json.loads(self.get(path, timeout)[1])
