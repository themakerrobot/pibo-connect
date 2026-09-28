"""로봇 한 대와의 통신. 로봇에는 아무것도 설치하지 않는다.

쓰는 것은 OS 가 이미 띄워둔 두 서버뿐이다.
  :80   ide/run_ide.py   socket.io — init / executeb / update / stop
  :8080 system/booting.py HTTP     — /wifi, /wifi_scan, /device/{pkt}
"""

import asyncio
import contextlib
from typing import Any, Callable, Dict, List, Optional, Tuple

import aiohttp
import socketio
from yarl import URL

from . import config, detect


# ── HTTP (:8080) ──────────────────────────────────────────────────────
async def is_alive(session: aiohttp.ClientSession, ip: str,
                   timeout: float = 1.5) -> bool:
    """:8080/wifi 가 {"result":"ok"} 를 주면 파이보 계열이다.

    ⚠ 이 응답에는 WiFi 비밀번호(psk)가 평문으로 들어 있다 (booting.py).
    result 만 보고 나머지는 즉시 버린다. 호출자에게 돌려주지 않는다.
    """
    try:
        async with session.get(f"http://{ip}:{config.SYS_PORT}/wifi",
                               timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            if r.status != 200:
                return False
            d = await r.json(content_type=None)
            return isinstance(d, dict) and d.get("result") == "ok"
    except Exception:
        return False
    # 여기서 d 는 스코프를 벗어나 GC 된다. 어디에도 남기지 않는다.


async def device_probe(session: aiohttp.ClientSession, ip: str,
                       timeout: float = 2.0) -> Optional[str]:
    """GET /device/#40:! — device 보드 시스템 패킷. 기종 보조 판별용."""
    try:
        # '#40:!' 를 경로에 그대로 넣으면 '#' 이 프래그먼트로 잘린다.
        # 미리 인코딩한 뒤 yarl 에 encoded=True 로 넘겨 재인코딩을 막는다.
        url = URL(f"http://{ip}:{config.SYS_PORT}/device/%2340%3A%21", encoded=True)
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            return str(await r.json(content_type=None))
    except Exception:
        return None


async def remote_wifi_scan(session: aiohttp.ClientSession, ip: str,
                           timeout: float = 20.0) -> List[dict]:
    """붙어 있는 로봇에게 주변 WiFi 를 스캔시킨다.

    ⚠ wifi.py 의 nmcli 에 --rescan 이 없다. 캐시된 결과라 오래됐을 수 있다.
    화면에 '참고용' 이라고 적어 둘 것.
    """
    try:
        async with session.get(f"http://{ip}:{config.SYS_PORT}/wifi_scan",
                               timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            d = await r.json(content_type=None)
            return d if isinstance(d, list) else []
    except Exception:
        return []


async def find_ide_port(ip: str, timeout: float = 0.6) -> Optional[int]:
    """IDE 가 열려 있는 포트. 신형 80, 구형(240701v1) 50000. 없으면 None.

    TCP 접속만 해보므로 싸다 — 신형 교실에서는 80 이 바로 열려 두 번째는 안 간다.
    """
    for port in (config.IDE_PORT, config.IDE_PORT_LEGACY):
        if await port_open(ip, port, timeout):
            return port
    return None


async def port_open(ip: str, port: int, timeout: float = 0.5) -> bool:
    """TCP connect 만 해본다. 254개를 훑을 때 HTTP 보다 훨씬 싸다."""
    try:
        fut = asyncio.open_connection(ip, port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        return True
    except Exception:
        return False


# ── socket.io (:80) ───────────────────────────────────────────────────
def parse_system(v: List[str]) -> Dict[str, Any]:
    """system.sh 의 CSV 를 사람이 읽을 형태로.

    OS 판에 따라 **칸 수와 순서가 다르다**. 앞 여섯 칸은 같고 뒤가 갈린다:

      신형 (12칸)  … 6 WLAN0  7 ETH1   8 SSID  9 PSK  10 IDENTITY  11 KEY_MGMT
      구형 ( 9칸)  … 6 WLAN0  7 SSID0  8 ETH1                      (PSK 없음)

    칸 수로 가른다 — 추측이 아니라 두 판의 system.sh echo 줄을 대조한 사실이다.
    ⚠ 신형 인덱스 9 는 WiFi 비밀번호 평문이다. 어느 쪽이든 담지 않는다.
    """
    def at(i: int) -> str:
        return v[i].strip() if len(v) > i and v[i] is not None else ""

    if len(v) >= 12:
        wlan, eth, ssid = at(6), at(7), at(8)
    else:
        wlan, ssid, eth = at(6), at(7), at(8)

    serial = at(0)
    return {
        "sn": serial[-8:].lower(),
        "os": at(1),
        "uptime": at(2),
        "temp": at(3),
        "mem_total": at(4),
        "mem_avail": at(5),
        "ip": wlan or eth,
        "ssid": ssid,
    }


class RobotLink:
    """로봇 한 대와의 socket.io 세션. async with 로 쓴다."""

    def __init__(self, ip: str, timeout: float = 8.0, port: Optional[int] = None):
        self.ip = ip
        self.timeout = timeout
        self.port = port or config.IDE_PORT
        self.sio = socketio.AsyncClient(reconnection=False, logger=False,
                                        engineio_logger=False)
        self._system: "asyncio.Future[List[str]]" = asyncio.get_running_loop().create_future()
        self._exit = asyncio.Event()
        self._dir: Optional["asyncio.Future[dict]"] = None      # load_directory 응답
        self._code: Optional["asyncio.Future[Tuple[str, str]]"] = None   # load 응답
        self.record = ""
        self.on_record: Optional[Callable[[str], None]] = None

        @self.sio.on("update_file_manager")
        async def _on_fm(d):
            if self._dir and not self._dir.done():
                self._dir.set_result(d if isinstance(d, dict) else {})

        @self.sio.on("system")
        async def _on_system(v):
            if not self._system.done():
                self._system.set_result(v if isinstance(v, list) else [])

        @self.sio.on("update")
        async def _on_update(d):
            if not isinstance(d, dict):
                return
            if "record" in d:
                self.record = d["record"] or ""
                if self.on_record:
                    self.on_record(self.record)
            if d.get("exit"):
                self._exit.set()
            # handle_load 의 응답. 보호 경로면 dialog=err_load_protected 가 온다.
            if self._code and not self._code.done():
                if "code" in d:
                    self._code.set_result((d.get("code") or "", d.get("filepath") or ""))
                elif str(d.get("dialog", "")).startswith("err_load"):
                    self._code.set_exception(RuntimeError(
                        f"{d['dialog']}: {d.get('detail', '')}".strip(": ")))

    async def __aenter__(self) -> "RobotLink":
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def connect(self) -> None:
        await self.sio.connect(f"http://{self.ip}:{self.port}",
                               transports=["websocket"],
                               wait_timeout=self.timeout)

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self.sio.disconnect()

    async def system(self) -> Optional[Dict[str, Any]]:
        """init 한 번으로 기기 정보를 통째로 받는다 (run_ide.py 의 init 핸들러)."""
        await self.sio.emit("init")
        try:
            v = await asyncio.wait_for(self._system, timeout=self.timeout)
        except asyncio.TimeoutError:
            return None
        return parse_system(v)

    async def execute(self, code: str, codetype: str = "python") -> None:
        """executeb 로 코드를 던진다.

        ⚠ executeb 에는 is_protect 검사가 없다 (execute 에만 있다).
        codepath 는 config.CODEPATH 고정이고 UI 에 노출하지 않는다.
        """
        await self.sio.emit("executeb", {
            "codepath": config.CODEPATH,
            "codetext": code,
            "codetype": codetype if codetype in ("python", "shell") else "python",
        })

    async def wait_exit(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._exit.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def stop(self) -> None:
        await self.sio.emit("stop")

    async def list_dir(self, path: str) -> dict:
        """load_directory — 로봇의 폴더 목록. 없는 경로면 IDE 가 현재 폴더를 준다.

        ⚠ 이 호출은 IDE 의 작업 폴더(전역 PATH)를 그 경로로 바꾼다. 실행의
        cwd 가 거기 따라가므로, 다 보고 나면 ROBOT_HOME 으로 되돌려 둘 것.
        """
        self._dir = asyncio.get_running_loop().create_future()
        await self.sio.emit("load_directory", path)
        d = await asyncio.wait_for(self._dir, timeout=self.timeout)
        return {"path": d.get("path") or path, "entries": d.get("data") or []}

    async def load_file(self, path: str) -> Tuple[str, str]:
        """load — 파일 내용을 읽는다. (code, filepath). 보호 경로는 거부된다."""
        self._code = asyncio.get_running_loop().create_future()
        await self.sio.emit("load", path)
        return await asyncio.wait_for(self._code, timeout=self.timeout)


async def identify(ip: str, session: Optional[aiohttp.ClientSession] = None,
                   timeout: float = 8.0, rules: Optional[dict] = None) -> Optional[dict]:
    """한 대를 식별한다. init 한 번 + (필요하면) device 보조 판별."""
    ide_port = await find_ide_port(ip)
    if ide_port is None:
        return None

    info: Optional[dict] = None
    try:
        async with RobotLink(ip, timeout=timeout, port=ide_port) as link:
            info = await link.system()
    except Exception:
        return None
    if not info or not info.get("sn"):
        return None

    info["ip"] = info.get("ip") or ip
    info["ide_port"] = ide_port
    info["mode"] = "net"

    device_reply = None
    if not info.get("os") and session is not None:
        device_reply = await device_probe(session, ip)

    kind, conf, evidence = detect.classify(info.get("os", ""), device_reply, rules)
    info["kind"] = kind
    info["kind_confidence"] = conf
    info["kind_evidence"] = evidence
    return info
