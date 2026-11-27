#!/bin/bash
# 연구실 실물 시험용 명령 모음. 소스·설정 파일은 수정하지 않는다
# (build/upload/test는 .pio/, .build/와 PlatformIO 패키지·캐시를 갱신할 수 있다).
# 사용법: ./scripts/lab.sh help
#
# 업로드·모니터는 사용자가 포트를 직접 지정했을 때만 실행한다.
# 업로드 전에는 대상(역할·보드·포트·키링 번호)을 보여 주고 y 입력을 받는다.

set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

# VS Code PlatformIO 확장과 같은 PlatformIO를 우선 사용한다. PIO 환경변수로 바꿀 수 있다.
if [ -z "${PIO:-}" ]; then
  if [ -x "$HOME/.platformio/penv/bin/pio" ]; then
    PIO="$HOME/.platformio/penv/bin/pio"
  else
    PIO="pio"
  fi
fi
export PLATFORMIO_SETTING_ENABLE_TELEMETRY=No

BAUD=115200
# 맥북 자체 포트. ESP32가 아니므로 업로드·모니터 대상에서 뺀다.
EXCLUDED_PORTS="/dev/cu.Bluetooth-Incoming-Port /dev/cu.debug-console"

usage() {
  cat <<'EOF'
연구실 시험 명령 (프로젝트 최상위에서 실행)

  ./scripts/lab.sh doctor                  개발 도구·프로젝트 구성 점검 (장치 불필요)
  ./scripts/lab.sh ports                   연결된 ESP32 후보 USB 포트 목록
  ./scripts/lab.sh build                   송신·수신 펌웨어 빌드 (장치 불필요)
  ./scripts/lab.sh test                    맥북 단위 테스트 (장치 불필요)
  ./scripts/lab.sh upload keyring  <포트>   키링(송신) 펌웨어 업로드
  ./scripts/lab.sh upload roadside <포트>   도로변(수신) 펌웨어 업로드
  ./scripts/lab.sh monitor <포트>           시리얼 로그 보기 (종료: Ctrl+C)

  <포트> 예: /dev/cu.usbserial-0001, /dev/cu.SLAB_USBtoUART  (ports 명령으로 확인)
  upload 뒤에 --yes를 붙이면 확인 질문을 건너뛴다.

업로드 성공은 "펌웨어가 보드에 써졌다"는 뜻일 뿐, BLE 통신 성공이 아니다.
EOF
}

die() { echo "[중단] $*" >&2; exit 2; }

is_excluded() {
  local p  # 호출한 쪽(candidate_ports)의 p를 덮어쓰지 않도록
  for p in $EXCLUDED_PORTS; do [ "$1" = "$p" ] && return 0; done
  return 1
}

# USB 시리얼 후보 포트: /dev/cu.* 중 맥북 자체 포트 제외 (ESP32인지는 확인하지 못함)
candidate_ports() {
  for p in /dev/cu.*; do
    [ -e "$p" ] || continue
    is_excluded "$p" && continue
    echo "$p"
  done
}

port_info() {
  "$PIO" device list --serial --json-output 2>/dev/null | /usr/bin/python3 -c '
import json, sys
want = sys.argv[1]
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for d in data:
    if d.get("port") == want:
        print("      설명: %s" % d.get("description"))
        print("      하드웨어 ID: %s" % d.get("hwid"))
' "$1"
}

# 포트 검증. 우회 옵션은 없다.
check_port() {
  local port="$1"
  [ -n "$port" ] || die "포트를 지정하세요. 먼저 ./scripts/lab.sh ports 로 확인"
  case "$port" in
    /dev/tty.*) die "$port 대신 /dev/cu.${port#/dev/tty.} 를 사용하세요(macOS는 cu.* 사용)" ;;
    /dev/cu.*) ;;
    *) die "$port 는 USB 시리얼 포트 형식(/dev/cu.*)이 아닙니다" ;;
  esac
  is_excluded "$port" && die "$port 는 맥북 자체 포트입니다. ESP32 포트가 아닙니다"
  [ -c "$port" ] || die "$port 가 없습니다. 케이블 연결·드라이버를 확인하고 ./scripts/lab.sh ports 로 다시 확인"
}

# 다른 프로세스가 포트를 열고 있으면 중단한다. macOS는 같은 포트를 동시에 열 수 있어
# 두 프로그램이 출력을 나눠 읽거나 업로드가 섞인다(2026-11-27 실제 발생).
check_port_free() {
  local holders
  holders="$(/usr/sbin/lsof "$1" 2>/dev/null | tail -n +2)"
  [ -z "$holders" ] || die "$1 를 다른 프로그램이 사용 중입니다. 먼저 종료하세요:
$holders"
}

config_value() {  # include/app_config.h 에서 상수 값 읽기 (표시용)
  sed -n "s/.*$1 = \([0-9]*\);.*/\1/p" include/app_config.h | head -1
}

board_name() {
  sed -n 's/^board *= *\(.*\)$/\1/p' platformio.ini | head -1
}

cmd_doctor() {
  local fail=0
  echo "== 맥북"
  echo "  아키텍처: $(uname -m), macOS $(sw_vers -productVersion 2>/dev/null)"
  echo "== PlatformIO"
  if "$PIO" --version >/dev/null 2>&1; then
    echo "  사용: $PIO ($("$PIO" --version 2>/dev/null))"
  else
    echo "  [문제] PlatformIO 실행 불가: $PIO"; fail=1
  fi
  if command -v pio >/dev/null 2>&1 && [ "$(command -v pio)" != "$PIO" ]; then
    echo "  참고: PATH에도 다른 pio가 있음: $(command -v pio) ($(pio --version 2>/dev/null | tail -1))"
    echo "        이 스크립트는 위 '사용' 경로만 쓴다."
  fi
  echo "== ESP32 플랫폼·도구 (설치 여부)"
  local pf="$HOME/.platformio/platforms/espressif32/platform.json"
  if [ -f "$pf" ]; then
    echo "  espressif32 $(/usr/bin/python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$pf")"
  else
    echo "  [문제] espressif32 플랫폼 없음 (첫 빌드 때 인터넷으로 내려받음)"; fail=1
  fi
  for t in framework-arduinoespressif32 toolchain-xtensa-esp32 tool-esptoolpy; do
    if [ -d "$HOME/.platformio/packages/$t" ]; then echo "  $t 있음"; else echo "  [문제] $t 없음"; fail=1; fi
  done
  echo "== 프로젝트"
  echo "  보드 설정: $(board_name)  (실물 보드 확인 전 가정값)"
  echo "  빌드 환경: $(sed -n 's/^\[env:\(.*\)\]$/\1/p' platformio.ini | tr '\n' ' ')"
  echo "  키링 번호: $(config_value kKeyringId), LED 핀: GPIO$(config_value kLedPin), 시리얼 속도: $BAUD"
  echo "== USB 포트"
  local ports; ports="$(candidate_ports)"
  if [ -n "$ports" ]; then echo "$ports" | sed 's/^/  USB 시리얼 후보: /'; else echo "  USB 시리얼 후보 없음 (장치를 연결하지 않았다면 정상)"; fi
  echo
  if [ $fail -eq 0 ]; then echo "결과: 도구 준비됨 (빌드 가능 여부는 ./scripts/lab.sh build 로 확인)"; else echo "결과: 위 [문제] 확인 필요"; fi
  return $fail
}

cmd_ports() {
  local ports; ports="$(candidate_ports)"
  if [ -z "$ports" ]; then
    cat <<'EOF'
USB 시리얼 포트가 없습니다.

확인 순서:
  1. 데이터 전송 가능한 USB 케이블인지 (충전 전용 케이블은 포트가 안 생김) → 다른 케이블로 교체
  2. 보드의 전원 LED가 켜졌는지
  3. USB 허브·어댑터를 빼고 맥북에 직접 연결
  4. 시스템 정보 > USB 에 CP210x / CH340 / USB Serial 등이 보이는지:
       system_profiler SPUSBDataType
     보이는데 포트가 없으면 USB-시리얼 칩 드라이버 문제일 수 있음 (보드의 칩 이름 확인)
EOF
    return 1
  fi
  echo "USB 시리얼 후보 포트 (ESP32인지는 이 목록만으로 알 수 없음):"
  for p in $ports; do
    echo "  $p"
    port_info "$p"
  done
  cat <<'EOF'

두 보드를 구분하는 방법:
  - 한 대씩 꽂고 ports를 실행해 새로 생긴 포트와 하드웨어 ID를 적는다 → 보드에 "키링"/"도로변" 라벨
  - 다른 USB 시리얼 장치(아두이노 등)는 빼 둔다
  - 업로드 후에는 monitor의 [ALIVE] keyring / [ALIVE] roadside 로그로 역할 확인 (약 10초 간격, 20초까지 기다림)
EOF
}

cmd_build() {
  "$PIO" run -e keyring -e roadside
}

cmd_test() {
  ./scripts/run_tests.sh
}

cmd_upload() {
  local role="${1:-}" port="${2:-}" yes="${3:-}"
  case "$role" in
    keyring|roadside) ;;
    *) die "역할은 keyring 또는 roadside 중 하나 (입력: '${role}')" ;;
  esac
  [ -z "$yes" ] || [ "$yes" = "--yes" ] || die "알 수 없는 옵션: $yes"
  check_port "$port"
  check_port_free "$port"

  echo "업로드 대상"
  if [ "$role" = keyring ]; then
    echo "  역할:     키링(송신)  — 키링 번호 $(config_value kKeyringId)"
  else
    echo "  역할:     도로변(수신 + LED GPIO$(config_value kLedPin))"
  fi
  echo "  빌드 환경: $role"
  echo "  보드 설정: $(board_name)"
  echo "  포트:     $port"
  port_info "$port"

  if [ "$yes" != "--yes" ]; then
    [ -t 0 ] || die "확인 입력을 받을 수 없습니다. 터미널에서 실행하거나 --yes 를 붙이세요"
    printf "이 보드에 %s 펌웨어를 업로드할까요? [y/N] " "$role"
    read -r answer
    [ "$answer" = "y" ] || [ "$answer" = "Y" ] || { echo "취소했습니다."; return 1; }
  fi

  "$PIO" run -e "$role" -t upload --upload-port "$port"
  local rc=$?
  echo
  if [ $rc -eq 0 ]; then
    echo "업로드 성공: 펌웨어가 보드에 써졌습니다. (BLE 통신 성공을 뜻하지 않음)"
    echo "다음: ./scripts/lab.sh monitor $port"
  else
    cat <<EOF
업로드 실패 (종료 코드 $rc). 위의 오류 메시지 원문을 기록하세요.
자주 있는 원인:
  - "Failed to connect" / "Wrong boot mode": BOOT 버튼을 누른 채로 업로드를 다시 실행,
    "Connecting...." 이 보이면 버튼을 뗀다
  - "Resource busy" / "could not open port": 다른 창의 시리얼 모니터를 Ctrl+C로 끄고 다시 시도
  - 포트가 사라짐: 케이블·연결 확인 후 ./scripts/lab.sh ports
EOF
  fi
  return $rc
}

cmd_monitor() {
  local port="${1:-}"
  check_port "$port"
  check_port_free "$port"
  cat <<EOF
시리얼 모니터: $port @ $BAUD (종료: Ctrl+C). 로그의 t=..ms는 보드 시각(부팅 후 경과).

  [ROADSIDE] / [KEYRING]   부팅 직후 1번 (EN 버튼을 누르면 다시 보임)
  [ALIVE] ...              약 10초마다(스캔 경계 때문에 조금 늦을 수 있음). 20초 넘게 없으면 정지 의심.
                           나온다고 스캔·수신이 정상이라는 보증은 아님(loop가 돌고 있다는 뜻)
  [RX] t=.. keyring=.. rssi=..   키링 신호 수신
  [STATE] WAITING -> WARNING t=..   경고 시작
  [STATE] WARNING -> WAITING t=..   신호 소실로 경고 종료 (마지막 [RX] t와의 차이 = 종료까지 걸린 시간)
  [LED] ON / OFF           LED 출력 명령
  [SCAN ERROR] ...         라이브러리가 알려 준 스캔 시작 오류
  [E] ...                  라이브러리 오류 로그
  주의: [RX]가 없어도 [ALIVE]가 계속 나와야 "스캔은 돌고 있음"이다. 로그가 없다고 정상은 아니다.
       (스캔 시작 뒤의 일부 실패는 감지하지 못한다 — README 알려진 한계 2)

EOF
  # -f time은 쓰지 않는다: 실물 시험(2026-11-12)에서 같은 출력이 수십 번 겹쳐 보였다
  "$PIO" device monitor -p "$port" -b "$BAUD"
}

main() {
  case "${1:-help}" in
    doctor)  cmd_doctor ;;
    ports)   cmd_ports ;;
    build)   cmd_build ;;
    test)    cmd_test ;;
    upload)  shift; cmd_upload "$@" ;;
    monitor) shift; cmd_monitor "$@" ;;
    help|-h|--help) usage ;;
    *) usage; die "알 수 없는 명령: $1" ;;
  esac
}

# 직접 실행했을 때만 main을 부른다(셀프테스트는 source 후 함수를 바꿔 끼운다).
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
