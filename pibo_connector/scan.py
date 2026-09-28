"""찾기 — 서브넷 훑기 / 아는 놈만 다시 확인 / AP 모드 로봇 찾기."""

import asyncio
import re
from typing import Callable, List, Optional  # noqa: F401

import aiohttp

from . import config, detect, net, robot
from .store import Fleet

# system/hotspot.sh: AP_SSID="pibo-$(시리얼 뒤 8자리)"
AP_RX = re.compile(r"^pibo-([0-9a-fA-F]{8})$")

Progress = Callable[[dict], None]


def _noop(_: dict) -> None:
    pass


async def _gather_limited(coros, limit: int):
    """동시 실행 수를 묶는다. 254개를 한꺼번에 던지면 WiFi 쪽에서 밀린다."""
    sem = asyncio.Semaphore(limit)

    async def run(c):
        async with sem:
            return await c

    return await asyncio.gather(*(run(c) for c in coros), return_exceptions=True)


async def scan_subnet(fleet: Fleet, subnet: str, progress: Progress = _noop,
                      concurrency: int = 128, connect_timeout: float = 0.5) -> List[dict]:
    """<subnet>.1 ~ .254 를 훑어 파이보 계열만 골라 목록에 넣는다.

    1) TCP connect :8080  — 가장 싸다. 없는 IP 를 여기서 전부 떨군다
    2) GET /wifi          — {"result":"ok"} 로 파이보 계열 확인 (psk 는 즉시 폐기)
    3) socket.io init     — SN · OS_VERSION · 온도 · SSID
    """
    subnet = subnet.strip().rstrip(".")
    if not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}$", subnet):
        raise ValueError(f"서브넷 형식이 아니다: {subnet}  (예: 192.168.0)")

    hosts = [f"{subnet}.{i}" for i in range(1, 255)]
    done = 0
    total = len(hosts)
    progress({"phase": "port", "done": 0, "total": total, "found": 0})

    async def probe(ip: str):
        nonlocal done
        ok = await robot.port_open(ip, config.SYS_PORT, connect_timeout)
        done += 1
        if done % 8 == 0 or done == total:
            progress({"phase": "port", "done": done, "total": total, "found": 0})
        return ip if ok else None

    results = await _gather_limited([probe(h) for h in hosts], concurrency)
    alive = [r for r in results if isinstance(r, str)]
    progress({"phase": "port", "done": total, "total": total, "found": len(alive)})

    rules = detect.load_rules()
    out: List[dict] = []
    if not alive:
        return out

    progress({"phase": "identify", "done": 0, "total": len(alive), "found": 0})
    idone = 0

    async with aiohttp.ClientSession() as session:
        async def check(ip: str):
            nonlocal idone
            # 파이보인지 가리는 기준은 socket.io init → system 배열이다.
            # 그게 오면 실행·파일 열기도 다 되고, 안 오면 어차피 못 쓴다.
            #
            # 예전에는 GET :8080/wifi 가 {"result":"ok"} 를 주는지로 먼저 걸렀는데,
            # 구형 OS(240701v1)의 그 핸들러가 wpa_supplicant.conf 를 무조건
            # tmp[4]·tmp[5] 로 인덱싱해서 파일이 없거나 짧으면 500 이 난다.
            # 멀쩡한 로봇이 그 때문에 목록에서 사라졌다. 그래서 문지기로 안 쓴다.
            info = await robot.identify(ip, session=session, rules=rules)
            idone += 1
            progress({"phase": "identify", "done": idone, "total": len(alive),
                      "found": len(out)})
            return info

        infos = await _gather_limited([check(ip) for ip in alive], 24)

    arp = net.arp_table()
    for ip, info in zip(alive, infos):
        if not isinstance(info, dict):
            continue
        info["mac"] = arp.get(ip, "")
        row = fleet.upsert(info)
        out.append(row)
        progress({"phase": "found", "robot": row})

    fleet.save()
    return out


async def diagnose(ip: str) -> List[tuple]:
    """로봇 한 대를 단계별로 짚어 본다. [(단계, 됐나, 자세히)].

    '안 찾아져요' 가 어디서 막힌 건지 보려고 쓴다 — 포트인지, IDE 인지,
    system 배열인지. 화면 없이 콘솔에서 바로 확인할 수 있어야 한다.
    """
    out = []
    sys_open = await robot.port_open(ip, config.SYS_PORT, 1.0)
    out.append((f"TCP :{config.SYS_PORT} (booting.py)", sys_open,
                "" if sys_open else "닫혀 있다. 로봇이 켜져 있고 같은 망인지 확인"))

    ide_port = await robot.find_ide_port(ip, timeout=1.0)
    out.append((f"TCP :{config.IDE_PORT} 또는 :{config.IDE_PORT_LEGACY} (IDE)",
                ide_port is not None,
                f"{ide_port} 번" if ide_port else "둘 다 닫혀 있다"))
    if ide_port is None:
        return out

    row = None
    try:
        async with robot.RobotLink(ip, timeout=8.0, port=ide_port) as link:
            fut = asyncio.get_running_loop().create_future()

            @link.sio.on("system")
            async def _cap(v):
                if not fut.done():
                    fut.set_result(v)

            await link.sio.emit("init")
            row = await asyncio.wait_for(fut, timeout=8.0)
        out.append(("socket.io 접속 + init", True, f"{ide_port} 번"))
    except Exception as ex:
        out.append(("socket.io 접속 + init", False, f"{type(ex).__name__}: {ex}"))
        return out

    n = len(row) if isinstance(row, list) else 0
    # 인덱스 9(신형 PSK)는 찍지 않는다
    shown = [x for i, x in enumerate(row or []) if i != 9]
    out.append(("system 배열", n > 0, f"{n}칸: {shown}"))
    if n:
        info = robot.parse_system(row)
        ok = bool(info.get("sn"))
        out.append(("SN·IP·OS 읽기", ok,
                    f"SN={info.get('sn')} IP={info.get('ip')} OS={info.get('os')}"))
    return out


async def refresh(fleet: Fleet, progress: Progress = _noop) -> dict:
    """아는 로봇의 저장된 IP 로만 init 을 쏴 본다. 안 바뀌었으면 1~2초."""
    rows = fleet.list()
    targets = [(r["sn"], r.get("ip", "")) for r in rows if r.get("ip")]
    if not targets:
        return {"ok": [], "lost": [r["sn"] for r in rows]}

    rules = detect.load_rules()
    progress({"phase": "refresh", "done": 0, "total": len(targets)})
    done = 0

    async with aiohttp.ClientSession() as session:
        async def one(sn: str, ip: str):
            nonlocal done
            info = await robot.identify(ip, session=session, timeout=5.0, rules=rules)
            done += 1
            progress({"phase": "refresh", "done": done, "total": len(targets)})
            return sn, ip, info

        res = await _gather_limited([one(sn, ip) for sn, ip in targets], 24)

    arp = net.arp_table()
    ok, lost = [], []
    for item in res:
        if not isinstance(item, tuple):
            continue
        sn, ip, info = item
        # SN 이 다르면 그 IP 는 다른 로봇에게 넘어간 것이다. 덮어쓰지 않는다.
        if isinstance(info, dict) and info.get("sn") == sn:
            info["mac"] = arp.get(ip, "")
            fleet.upsert(info)
            ok.append(sn)
            progress({"phase": "found", "robot": fleet.get(sn)})
        else:
            fleet.mark_offline(sn)
            lost.append(sn)

    known = {sn for sn, _ in targets}
    lost += [r["sn"] for r in rows if r["sn"] not in known]
    fleet.save()
    return {"ok": ok, "lost": lost}


async def ap_scan(fleet: Fleet, use_robot: Optional[str] = None) -> dict:
    """공유기에 못 붙은 로봇 찾기.

    IP 가 없어 서브넷 스캔에는 안 걸리지만, 자기 WiFi 를 켜고 있고
    그 SSID 가 pibo-<SN> 이다 (system/hotspot.sh).

    노트북 WiFi 스캔을 먼저 쓰고, 안 되면 붙어 있는 로봇에게 시킨다.
    """
    rows, err = net.wifi_scan()
    source = "laptop"
    stale = False

    if not rows:
        ip = use_robot or next((r["ip"] for r in fleet.list() if r.get("ip")), "")
        if ip:
            async with aiohttp.ClientSession() as session:
                remote = await robot.remote_wifi_scan(session, ip)
            rows = [{"ssid": d.get("essid", ""), "bssid": "",
                     "signal": str(d.get("signal_quality", "")),
                     "channel": ""} for d in remote if isinstance(d, dict)]
            source = f"robot:{ip}"
            # wifi.py 의 nmcli 에 --rescan 이 없다. 캐시라 오래됐을 수 있다.
            stale = True

    found = []
    for row in rows:
        m = AP_RX.match((row.get("ssid") or "").strip())
        if not m:
            continue
        sn = m.group(1).lower()
        ch = str(row.get("channel") or "").strip()
        sig = str(row.get("signal") or "").strip()
        bits = ["AP 모드"] + ([f"ch{ch}"] if ch else []) + ([f"{sig}%"] if sig else [])
        info = {"sn": sn, "mode": "ap", "ip": "",
                "ssid": row.get("ssid", ""), "note": " · ".join(bits)}
        fleet.upsert(info)
        found.append({**info, "signal": row.get("signal", ""),
                      "channel": row.get("channel", "")})

    fleet.save()
    return {"found": found, "source": source, "stale": stale,
            "error": err if not rows else "", "scanned": len(rows)}
