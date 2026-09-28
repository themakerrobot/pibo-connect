# pibo-connect

교실에 켜져 있는 **파이보 / 파이브레인을 브라우저 한 장으로** 찾고, 점호하고,
같은 코드를 한 번에 실행한다.

- **로봇에는 아무것도 설치하지 않는다.** OS 가 이미 띄워둔 두 서버만 쓴다
- **노트북에 파이썬이 없어도 된다.** 릴리스의 실행 파일을 받아 더블클릭하면 브라우저가 열린다
- **소스로도 그대로 돈다.** 같은 코드다 (`python run.py`)
- **오프라인에서 동작한다.** CDN·npm·빌드 없음. 교실 `pibo` 망에 인터넷이 없어도 된다

```
[노트북] pibo-connect ───┬── :80   socket.io  init / executeb / update / stop
   └ 브라우저 (화면)      └── :8080 HTTP       /wifi · /wifi_scan · /device
```

브라우저는 UDP 를 못 쏘고 254개 TCP 스캔도 느리다. 그래서 스캔과 동시 시작
트리거는 커넥터가 맡고, 브라우저는 화면만 담당한다.

## 받기

**파이썬 없는 노트북** — [Releases](https://github.com/themakerrobot/pibo-connect/releases)

| 노트북 | 파일 |
|---|---|
| Windows | `pibo-connect-windows.exe` |
| Linux | `pibo-connect-linux` (`chmod +x` 후 실행) |
| macOS | `pibo-connect-macos` (`chmod +x`, 첫 실행은 우클릭 → 열기) |

`nightly` 는 `main` 이 바뀔 때마다 자동으로 덮어써진다. 수업에 쓸 거면
버전 태그가 붙은 정식 릴리스를 받는 쪽이 낫다.

**소스로 실행**

```bash
pip install -r requirements.txt
python run.py
```

둘 다 `http://127.0.0.1:8900/` 이 열린다. 포트가 막혀 있으면 다음 빈 포트를 잡는다.

```
python run.py --port 9000        # 포트 지정
python run.py --no-browser       # 브라우저 안 염
python run.py --host 0.0.0.0     # 다른 기기에서도 열기 (이때는 토큰이 붙는다)
```

## 쓰는 순서

화면은 **더 메이커 공통 "학습지" 테마**다 — `sense-lab/design/maker-ui.css` 를
`static/maker-ui.css` 로 그대로 복사해 쓰고, 이 서비스 전용 스타일(`static/style.css`)은
그 토큰만 쓴다. 미색 종이 바탕, 갈색 괘선 헤더, 남색 펜, 명조 서비스명, Pretendard
셀프호스팅(오프라인용으로 exe 에 같이 묶인다). 어두운 테마는 없다 — 규격이 단일 톤이다.
문구는 초등 수업 기준(해요체, 짧게). 영어는 `?lang=en`.

테마를 바꾸려면 sense-lab 쪽 `maker-ui.css` 를 고친 뒤 여기로 다시 복사한다.
`style.css` 는 손대지 않아도 된다.

1. **[로봇 찾기]** — 교실 네트워크의 `.1~.254` 를 훑는다. 15대면 보통 3~8초
2. **출석 확인** — 우리 반 로봇 번호(가슴의 8자리)를 출석부에 적으면
   왔어요 / 안 보여요 로 갈린다
3. **이름 붙이기** — 표의 이름칸을 눌러 `1번`, `창가` 처럼. 다음날에도 남는다
4. 표에서 로봇을 고르고(행을 누르면 된다) **코드** → **[실행!]** 또는 **[다 같이 시작]**

### 코드를 어디서 가져오나

| 모드 | 하는 일 |
|---|---|
| **새 코드** | 코드 창의 내용을 고른 로봇 전부에 보내 실행한다. [예제 골라보기…] 로 `examples/` 를 불러오고, [내 컴퓨터 파일 열기] 도 된다. `Ctrl+Enter` 가 실행 |
| **로봇 안의 파일** | 로봇에 **이미 있는 파일**을 경로로 그 자리에서 실행한다. 코드 창은 쓰지 않는다. [찾아보기] 로 로봇 한 대의 `/home/pi/code` 를 열어 고르고, [코드 창으로 가져오기] 로 읽어와 고친 뒤 전부에 밀어넣을 수도 있다 |

로봇 안의 파일은 `executeb` 로 짧은 런처만 보내서 돌린다 — `.py` 는
`runpy.run_path(..., run_name='__main__')`, `.sh` 는 `sh`. 대상 파일은 손대지
않고, 없는 로봇은 출력에 `[missing] 경로` 가 찍힌다. 폴더 목록과 파일 읽기는
IDE 의 `load_directory` · `load` 이벤트를 그대로 쓴다.

> `load_directory` 는 IDE 의 작업 폴더를 바꾼다. 실행 cwd 가 거기 따라가므로
> 커넥터가 목록을 다 본 뒤 `/home/pi/code` 로 되돌려 둔다.

### 찾기

```
1) TCP connect :8080        — 가장 싸다. 없는 IP 를 여기서 전부 떨군다
2) GET /wifi                — {"result":"ok"} 면 파이보 계열
3) socket.io emit('init')   — SN · OS_VERSION · 온도 · SSID 를 한 번에
```

- **[다시 확인]** — 저장된 IP 로만 확인한다. 안 바뀌었으면 1~2초.
  응답 없는 놈이 있으면 그때만 전체 스캔을 돌리면 된다
> 공유기에 못 붙은 로봇(AP 모드, SSID `pibo-<SN>`)을 전파로 찾는 `POST /api/apscan` 이
> 백엔드에 있지만 **화면에서는 뺐다**. 윈도우 노트북의 `netsh wlan` 은 위치 권한이
> 없으면 빈 결과를 주고, 로봇에게 시키는 `/wifi_scan` 은 캐시라 오래된 값이 나온다 —
> 교실에서 믿고 누를 수 있는 버튼이 아니었다. 리눅스 노트북에서 API 로 부르면 된다.

### 목록

키는 **SN** 이다 — Pi 시리얼 뒤 8자리. 가슴 화면의 SN, hostname, AP SSID 의
`pibo-<SN>` 이 전부 같은 값이라 사람이 눈으로 맞춰볼 수 있다. IP 는 DHCP 라
다음날 바뀐다.

[내보내기] / [가져오기] 로 노트북을 바꿔도 목록과 이름을 그대로 옮긴다.

### 기종 판별 (Pibo / PiBrain)

**OS_VERSION** 으로 가른다. `system.sh` 가 `/home/pi/.OS_VERSION` 을 읽어
`init` 응답에 실어 보내므로 추가 통신이 없다.

기본 규칙은 소문자 부분문자열이고, 긴 조각을 먼저 본다:

```json
{ "pibrain": "pibrain", "pi_brain": "pibrain", "pibo": "pibo" }
```

새 이미지 이름이 생기면 화면의 **[종류 구분 설정]** 에서 조각 하나만 더하면 된다
(`rules.json` 에 저장된다. 코드를 안 고친다). 어느 조각에도 안 걸리면 `?` 로
두고 OS_VERSION 원문을 배지에 그대로 띄운다 — 추측으로 기종을 칠하지 않는다.

### 실행

체크한 로봇에 `executeb` 로 동시에 던지고, `update` 이벤트의 `record` 를
로봇별로 받아 마지막 줄을 띄운다. 줄을 누르면 전체 로그가 펼쳐진다.

**[다 같이 시작]** 은 시작 시각을 맞춘다. 그냥 [실행!] 하면 `import openpibo` 시간이
로봇마다 달라 수백 ms 씩 어긋난다. 코드를 한 줄로 나눈다:

```python
from openpibo.motion import Motion   # 준비 — 무거운 import 를 여기서 끝낸다
m = Motion()

# --- GO ---

m.set_motion('dance1', 2)            # 본편 — 트리거를 받은 순간 같이 돈다
```

전부 `[ready]` 를 찍으면 커넥터가 UDP `:50055` 로 트리거를 쏜다. 고정 초를
기다리지 않고 실제 준비 개수를 센다.

> 공유기가 무선 브로드캐스트를 막으면(AP isolation, 멀티캐스트 필터) 트리거가
> 안 간다. 커넥터는 브로드캐스트와 유니캐스트를 둘 다 쏘지만, 그래도 막히면
> `[timeout]` 으로 끝나 바로 알 수 있다. 그때는 그냥 [실행!] 으로 내려오면 된다.
>
> 로봇 안의 파일을 다 같이 시작하려면 내용을 알아야 GO 래퍼로 감쌀 수 있다.
> 그래서 고른 첫 로봇에서 파일을 읽어와 전부에 밀어넣는다 (파이썬만).

### 알아둘 것

- **실행하면 로봇의 `tools` · `classify` · `llama-server` 가 멈춘다.**
  LLM 쓰는 코드는 `Dialog.start_llm` 부터 해야 한다
- **IDE 의 출력창은 전역이다.** 교사 브라우저가 IDE 에 붙어 있으면 그쪽 터미널에도
  출력이 찍히고, 누가 IDE 에서 Run 을 누르면 이쪽 코드가 죽는다
- 15대 동시 카메라는 대당 0.3~0.8 Mbps × airtime 2배 ≈ 24 Mbps.
  5GHz 80MHz 한 채널이면 여유다

## 안전장치

- **WiFi 비밀번호는 어디에도 남지 않는다.** `system` 배열 인덱스 9 와 `/wifi`
  응답의 `psk` 는 평문이다. 커넥터는 받는 즉시 버리고, 저장소는 `psk`·`password`·
  `key` 가 이름에 든 필드를 통째로 거른다. `tests/smoke.py` 가 매 CI 마다 확인한다
- **`codepath` 는 하드코딩이고 화면에 나오지 않는다.** `executeb` 에는 `is_protect`
  검사가 없다 (`execute` 에만 있다). 사용자가 고치게 두면 보호 디렉토리를 덮어쓴다
- 기본 바인딩은 `127.0.0.1` 이다. `--host 0.0.0.0` 으로 열 때만 토큰이 붙는다

## 윈도우에서 경고가 뜰 때

**"Windows의 PC 보호" (SmartScreen)** — 두 조건이 같이 맞을 때 뜬다: 파일에
"인터넷에서 받았다" 표시(Mark of the Web)가 붙어 있고, Microsoft 가 그 파일 해시를
모를 때. 빌드마다 해시가 바뀌므로 새 버전은 늘 "모름"이다. 그래서 같은 종류의 빌드가
어떤 PC 에서는 뜨고 어떤 PC 에서는 안 뜬다 — 차이는 파일이 아니라 **받은 경로**다
(브라우저 다운로드는 표시가 붙고, USB·메신저·드라이브로 온 파일은 안 붙는 경우가 많다).

표시가 붙었는지 보는 법 (PowerShell):

```powershell
Get-Item .\pibo-connect-windows.exe -Stream Zone.Identifier -ErrorAction SilentlyContinue
```

나오면 붙은 것. 넘어가는 법은 셋 중 하나: "추가 정보 → 실행" 한 번 / 파일 속성 맨 아래
"차단 해제" 체크 / 표시가 안 붙는 경로(USB 등)로 전달. 그 PC 에서는 한 번이면 된다.

exe 에는 버전 정보(회사 Circulus · 제품 파이보 커넥터 · 버전)가 들어 있어 속성 창의
'자세히' 탭에 정체가 뜬다. 서명은 아니라서 경고 자체를 없애지는 못한다.

**"스마트 앱 컨트롤이 차단"** (Windows 11) — 서명 없이는 못 넘어간다. 끄면 재설치
전엔 못 켠다.

근본 해결은 **코드 서명**이다. 인증서(.pfx)가 생기면 리포 secret 두 개만 넣으면
CI 가 윈도우 빌드에 자동으로 서명한다 (`.github/workflows/release.yml`):

| secret | 값 |
|---|---|
| `WIN_CERT_PFX_B64` | `.pfx` 를 base64 로 (`certutil -encode cert.pfx out.txt` 또는 `base64 -w0 cert.pfx`) |
| `WIN_CERT_PASSWORD` | pfx 비밀번호 |

secret 이 없으면 그 단계는 건너뛴다. OV 인증서는 평판을 쌓아야 경고가 사라지고,
EV 인증서는 바로 사라진다 — 어느 쪽을 살지는 예산 판단. 가격·발급 조건은 CA 마다
다르니 **확인 필요**.

**exe 아이콘이 옛것으로 보일 때** — 탐색기 아이콘 캐시다. 같은 이름의 exe 를 같은
폴더에 다시 받으면 옛 아이콘이 남는다. 파일 이름을 바꾸거나 다른 폴더로 옮기거나
`ie4uinit.exe -show` 를 한 번 돌리면 된다. 아이콘 자체는 exe 리소스에 들어 있다
(`RT_ICON` 6개, sense-lab 의 ico 와 바이트 단위로 같다 — pefile 로 확인했다).

## 옛날 OS 로봇

**기준: 2024년 판(`240110v4`) 이상.** 설정은 없고, 찾을 때 확인해서 맞춘다.

| | 2024년 판 (`240110v4`~`240701v1`) | 신형 |
|---|---|---|
| IDE | `ide/main.js` — Node.js, **50000** | `ide/run_ide.py` — Python, 80 |
| `system.sh` | 9칸: … `WLAN0, SSID0, ETH1` | 12칸: … `WLAN0, ETH1, SSID, PSK, …` |
| 실행 끝 표시 | `종료됨.` | `[exit]` |

24년 판 5개 태그(`240110v4` `240110v5` `240226v2` `240326v3` `240701v1`)를 전부
대조했다 — `/wifi`·포트·CSV 칸수·socket.io 이벤트가 모두 같다.

### `/wifi` 는 문지기로 쓰지 않는다

파이보인지 가리는 기준은 **socket.io `init` → `system` 배열**이다. 그게 오면
실행·파일 열기도 다 되고, 안 오면 어차피 못 쓴다.

한때 `GET :8080/wifi` 가 `{"result":"ok"}` 를 주는지로 먼저 걸렀는데, 구형 OS 의
그 핸들러가 이렇게 생겼다 (`240701v1` `system/booting.py`):

```python
with open('/etc/wpa_supplicant/wpa_supplicant.conf', 'r') as f:
  tmp = f.readlines()
return JSONResponse(content={'result':'ok', 'ssid':tmp[4].split('"')[1], …})
```

`tmp[4]`·`tmp[5]` 를 무조건 인덱싱하고 `.split('"')[1]` 을 한다. 그 파일이
없거나·6줄이 안 되거나·따옴표가 없으면 500 이 나고, **멀쩡한 로봇이 목록에서
사라졌다.** 실기에서 드러났다. 응답에 PSK 가 평문으로 들어 있기도 해서 지금은
아예 부르지 않는다.

### 2023년 판 이하

`231123v2` 이하도 IDE 포트 50000 이 같고 CSV 8칸을 지금 파서가 그대로 맞게
읽으므로 **원리상 찾아질 수 있다**. 다만 실물이 없어 확인하지 못했고 교실에도
거의 없어, 기준은 2024년 판으로 둔다.

### 안 찾아질 때

```bash
pibo-connect-windows.exe --check 192.168.0.51
```

TCP 8080 → IDE 포트(80/50000) → socket.io init → `system` 배열 → SN·IP·OS 까지
단계별로 찍는다. 어디서 막혔는지 한 줄로 나온다.

- 포트는 `robot.find_ide_port()` 가 80 → 50000 순으로 TCP 만 확인한다(0.6초).
  신형은 80 이 바로 열려 두 번째로 안 간다 — 신형 교실에서 느려지지 않는다.
  찾은 포트는 목록에 `ide_port` 로 저장해 실행·파일 열기에 그대로 쓴다.
- CSV 는 **칸 수**로 가른다 (`robot.parse_system`). 추측이 아니라 두 판의
  `system.sh` echo 줄을 대조한 것이다. 구형에는 PSK 칸이 아예 없다.
- socket.io 이벤트(`init`·`executeb`·`update`·`stop`·`load_directory`·`load`)는
  이름과 형태가 같아 그대로 쓴다. 구형 `executeb` 에도 `isProtect` 검사가 없으므로
  (`main.js:407`) codepath 하드코딩은 똑같이 중요하다.
- 실기로는 검증하지 못했다 — 구형 실물이 없어 `tests/mock_pibo.py --legacy` 로만 봤다.

```bash
python -m tests.mock_pibo --legacy &     # 구형 흉내 (50000, 9칸, '종료됨.')
python run.py                            # 서브넷 127.0.0 으로 [로봇 찾기]
```

## 검증

```bash
python -m tests.smoke            # 파싱 · 판별 · PSK 유출 · 래퍼 · 런처 · 번들 경로 · 서버 기동
python -m tests.exe_smoke dist/pibo-connect   # 묶은 실행 파일이 실제로 뜨는지 (CI 가 세 OS 에서 돌린다)
```

기기 없이 전 경로를 돌려보려면 가짜 로봇을 띄운다:

```bash
python -m tests.mock_pibo --sn cd488e95 --os piBo_260915v1-ph &
python run.py
# 화면에서 서브넷을 127.0.0 으로 두고 [찾기]
```

PiBrain 쪽 판별까지 보려면 OS 이름만 바꿔 한 대 더 띄우면 된다:

```bash
python -m tests.mock_pibo --sn 1a2b3c4d --os piBrain_260915v1 \
  --ide-port 8081 --sys-port 8082
```

기기가 있으면:

1. 로봇 2대를 켜고 커넥터를 띄운 뒤 [찾기] — SN · OS_VERSION 과 함께 뜨는지
2. `print('hello')` 를 [실행] — 양쪽 출력에 `hello` 와 `[exit]` 이 뜨는지
3. 1대를 AP 모드로 만들고 [AP 모드 찾기] — `pibo-<SN>` 이 잡히는지
4. 커넥터를 껐다 켜서 목록이 남아 있는지
5. 15대까지 올려 스캔 시간과 동시 실행이 견디는지

## exe 빌드 (손으로)

```bash
pip install -r requirements.txt pyinstaller
pyinstaller build/pibo-connect.spec --noconfirm
# dist/pibo-connect(.exe)
```

`static/`(테마·폰트·이미지 포함, 약 3.4MB) 과 `examples/` 는 spec 의 `datas` 로
같이 묶인다 — `config.py` 가 보는 자리(`_MEIPASS/static`, `_MEIPASS/examples`)와
정확히 맞아야 하고, `tests/smoke.py` 와 `tests/exe_smoke.py` 가 폰트·이미지까지
실제로 서빙되는지 확인한다. 윈도우 아이콘 `build/pibo-connect.ico` 는
sense-lab 의 파이보 얼굴(`tools/portable/icon.ico`) 그대로다.

CI 가 같은 스펙으로 빌드한다. `main` push 는 `nightly` 를, `v*` 태그는 정식
릴리스를 만든다 (`.github/workflows/release.yml`).

## 근거

전부 `themakerrobot/openpibo-os.pibo` 코드에서 확인한 것이다.

| 사실 | 근거 |
|---|---|
| IDE(80) 가 socket.io 서버다 | `ide/run_ide.py` `SocketManager` |
| CORS 전면 허용 | `ide/run_ide.py` `allow_origins=["*"]` |
| `init` → `system` 이벤트로 기기 정보 | `ide/run_ide.py` `handle_init` |
| 그 배열이 `system.sh` 의 CSV 그대로 | `system/system.sh` 마지막 `echo` |
| `executeb` 로 코드 실행, `update.record` 로 출력 | `ide/run_ide.py` `handle_executeb`, `execute` |
| `executeb` 에는 `is_protect` 가 없다 | `handle_execute` 와 비교 |
| `stop` 이 실행을 죽인다 | `ide/run_ide.py` `handle_stop` |
| 8080 은 `/wifi`, `/wifi_scan`, `/device/{pkt}` | `system/booting.py` |
| `/wifi` 응답에 psk 평문이 있다 | `system/booting.py` |
| 폴더 목록 · 파일 읽기 이벤트가 있다 | `ide/run_ide.py` `handle_load_directory`, `handle_load` |
| `load_directory` 가 IDE 작업 폴더(PATH)를 바꾼다 | `ide/run_ide.py` `global PATH` |
| AP SSID 가 `pibo-<시리얼 뒤 8자리>` | `system/hotspot.sh` `AP_SSID` |
| 구형 IDE 는 Node.js 이고 포트가 50000 | `240701v1` `ide/main.js:12`, `system/init:35` |
| 구형 `system.sh` 는 9칸이고 순서가 다르다 | `240701v1` `system/system.sh` 마지막 `echo` |
| hostname 도 같은 8자리 | `system/init` |
| PiBrain 은 GPIO 직결, Pibo 는 UART device 보드 | `openpibo/device.py` `DeviceByPiBrain` / `DeviceByPibo` |

`system` 배열 인덱스 (`system/system.sh`):

| i | 값 | i | 값 |
|---|---|---|---|
| 0 | Pi 시리얼 (뒤 8자리 = SN) | 6 | wlan0 IP |
| 1 | `.OS_VERSION` | 7 | eth1 IP |
| 2 | uptime | 8 | 접속 SSID |
| 3 | 온도 | **9** | **WiFi 비밀번호 (평문 — 버린다)** |
| 4, 5 | 메모리 | 10, 11 | identity, key-mgmt |
