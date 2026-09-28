"""로봇 목록 저장소.

키는 **SN** 이다. IP 는 DHCP 라 다음날 바뀌고, MAC 은 사람이 눈으로
맞춰볼 수 없다. SN 은 가슴 화면에 뜨는 값(Pi 시리얼 뒤 8자리)과 같다.

    /proc/cpuinfo Serial 뒤 8자리 = hostname (system/init)
                                  = AP SSID 의 pibo-<SN> (system/hotspot.sh)
                                  = 가슴 화면 SN

WiFi 비밀번호(system 배열 인덱스 9, /wifi 응답의 psk)는 이 파일에 절대
들어오지 않는다. 받는 즉시 버린다 — scan.py 를 볼 것.
"""

import json
import threading
import time
from typing import Dict, List, Optional

from . import config

_LOCK = threading.RLock()

# 저장하는 필드. 여기에 없는 키는 저장 단계에서 걸러낸다 (psk 유입 차단).
FIELDS = (
    "sn", "name", "ip", "mac", "kind", "kind_confidence", "kind_evidence",
    "os", "temp", "uptime", "mem_total", "mem_avail", "ssid",
    "mode", "last_seen", "note",
    "ide_port",          # 신형 80, 2024년 판 50000. 찾을 때 확인한 값
)

BLOCKED = ("psk", "password", "pw", "key", "secret")


class Fleet:
    def __init__(self, path=None):
        self.path = path or config.fleet_path()
        self.robots: Dict[str, dict] = {}
        self.roster: List[str] = []      # 점호용 기대 SN 목록
        self.load()

    # ── 파일 ────────────────────────────────────────────────────────
    def load(self) -> None:
        with _LOCK:
            try:
                if self.path.exists():
                    d = json.loads(self.path.read_text(encoding="utf-8"))
                    self.robots = {k: _clean(v) for k, v in (d.get("robots") or {}).items()}
                    self.roster = [s for s in (d.get("roster") or []) if s]
            except Exception:
                self.robots, self.roster = {}, []

    def save(self) -> None:
        with _LOCK:
            payload = {
                "version": 1,
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "robots": {k: _clean(v) for k, v in self.robots.items()},
                "roster": self.roster,
            }
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(self.path)

    # ── 조회 ────────────────────────────────────────────────────────
    def list(self) -> List[dict]:
        with _LOCK:
            rows = [dict(v) for v in self.robots.values()]
        rows.sort(key=lambda r: (r.get("name") or "~", r.get("sn") or ""))
        return rows

    def get(self, sn: str) -> Optional[dict]:
        with _LOCK:
            v = self.robots.get(sn)
            return dict(v) if v else None

    def ips(self, sns: Optional[List[str]] = None) -> List[str]:
        with _LOCK:
            items = self.robots.items()
            out = [(k, v.get("ip")) for k, v in items if v.get("ip")]
        if sns:
            want = set(sns)
            out = [(k, ip) for k, ip in out if k in want]
        return [ip for _, ip in out]

    def ip_of(self, sn: str) -> str:
        with _LOCK:
            return (self.robots.get(sn) or {}).get("ip", "")

    def ide_port_of(self, sn: str) -> int:
        """그 로봇의 IDE 포트. 모르면 신형 기본값."""
        from . import config
        with _LOCK:
            return (self.robots.get(sn) or {}).get("ide_port") or config.IDE_PORT

    def target_of(self, sn: str):
        """(ip, ide_port). ip 가 없으면 ("", port)."""
        return self.ip_of(sn), self.ide_port_of(sn)

    # ── 갱신 ────────────────────────────────────────────────────────
    def upsert(self, info: dict) -> dict:
        """스캔 결과 한 대를 반영한다. 사람이 붙인 이름과 메모는 보존한다."""
        sn = (info.get("sn") or "").lower()
        if not sn:
            return {}
        with _LOCK:
            old = self.robots.get(sn, {})
            new = {**old, **_clean(info)}
            new["sn"] = sn
            new["name"] = info.get("name") or old.get("name") or ""
            new["note"] = info.get("note") or old.get("note") or ""
            new["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.robots[sn] = new
            return dict(new)

    def mark_offline(self, sn: str) -> None:
        with _LOCK:
            if sn in self.robots:
                self.robots[sn]["mode"] = "offline"

    def rename(self, sn: str, name: str) -> bool:
        with _LOCK:
            if sn not in self.robots:
                return False
            self.robots[sn]["name"] = name
        self.save()
        return True

    def set_note(self, sn: str, note: str) -> bool:
        with _LOCK:
            if sn not in self.robots:
                return False
            self.robots[sn]["note"] = note
        self.save()
        return True

    def remove(self, sn: str) -> bool:
        with _LOCK:
            gone = self.robots.pop(sn, None) is not None
        if gone:
            self.save()
        return gone

    def set_roster(self, sns: List[str]) -> None:
        with _LOCK:
            seen, out = set(), []
            for s in sns:
                s = (s or "").strip().lower()
                if s and s not in seen:
                    seen.add(s)
                    out.append(s)
            self.roster = out
        self.save()

    def roster_status(self) -> dict:
        """점호. 기대 목록과 실제 목록을 맞춰본다."""
        with _LOCK:
            roster = list(self.roster)
            robots = {k: dict(v) for k, v in self.robots.items()}

        present, ap, missing = [], [], []
        for sn in roster:
            r = robots.get(sn)
            if not r:
                missing.append(sn)
            elif r.get("mode") == "ap":
                ap.append(sn)
            elif r.get("ip"):
                present.append(sn)
            else:
                missing.append(sn)
        extra = [sn for sn in robots if roster and sn not in roster]
        return {
            "expected": len(roster),
            "present": present,
            "ap": ap,
            "missing": missing,
            "extra": sorted(extra),
        }

    # ── 내보내기/가져오기 ───────────────────────────────────────────
    def export(self) -> dict:
        with _LOCK:
            return {
                "version": 1,
                "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "robots": {k: _clean(v) for k, v in self.robots.items()},
                "roster": list(self.roster),
            }

    def import_(self, payload: dict, merge: bool = True) -> int:
        robots = (payload or {}).get("robots") or {}
        if not isinstance(robots, dict):
            raise ValueError("robots 가 객체가 아니다")
        with _LOCK:
            if not merge:
                self.robots = {}
            n = 0
            for k, v in robots.items():
                if not isinstance(v, dict):
                    continue
                sn = (v.get("sn") or k or "").lower()
                if not sn:
                    continue
                old = self.robots.get(sn, {})
                self.robots[sn] = {**old, **_clean(v), "sn": sn}
                n += 1
            roster = (payload or {}).get("roster")
            if isinstance(roster, list):
                self.roster = [str(s).strip().lower() for s in roster if str(s).strip()]
        self.save()
        return n


def _clean(v: dict) -> dict:
    """저장 가능한 필드만 남긴다. PSK 계열은 어떤 이름으로도 통과시키지 않는다."""
    out = {}
    for k, val in (v or {}).items():
        lk = str(k).lower()
        if any(b in lk for b in BLOCKED):
            continue
        if lk in FIELDS:
            out[lk] = val
    return out
