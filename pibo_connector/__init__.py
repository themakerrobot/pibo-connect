"""pibo-connect — 파이보/파이브레인 다대수 제어 커넥터.

노트북에서 로컬 웹서버를 띄우고, 브라우저 한 장으로 교실의 로봇을
찾고(scan) · 점호하고(roster) · 같은 코드를 한 번에 실행한다(run/sync).

로봇에는 아무것도 설치하지 않는다. OS 가 이미 띄워둔 두 서버만 쓴다.
  - :80   run_ide.py   socket.io  (init / executeb / update / stop)
  - :8080 booting.py   HTTP       (/wifi, /wifi_scan, /device/{pkt})
"""

__version__ = "0.3.3"
