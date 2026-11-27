#!/bin/bash
# lab.sh 셀프테스트: 인자 처리·포트 검증·종료 코드·출력 문구·소스 파일 불변만 검사한다.
# 실제 USB 장치, 업로드, 보드 역할, PlatformIO 동작은 검증하지 않는다(모의 pio 사용).
# 실행: ./scripts/test_lab.sh
set -u
cd "$(dirname "$0")/.." || exit 1

TMP="$(mktemp -d "${TMPDIR:-/tmp}/labtest.XXXXXX")"
FAKE_PIO="$TMP/fake-pio"
CALLS="$TMP/calls.log"
FAKE_PORT="$TMP/cu.fake-esp32"   # 일반 파일. 실제 lab.sh는 이 경로를 거부해야 한다
touch "$FAKE_PORT"

# 모의 pio: 받은 인자를 기록하고, FAKE_PIO_RC/FAKE_PIO_MSG로 실패를 흉내 낸다
cat > "$FAKE_PIO" <<EOF
#!/bin/bash
echo "\$*" >> "$CALLS"
case "\$*" in "device list"*) echo "[]" ;; esac
[ "\${FAKE_PIO_RC:-0}" = 0 ] || echo "\${FAKE_PIO_MSG:-A fatal error occurred (모의 오류)}" >&2
exit "\${FAKE_PIO_RC:-0}"
EOF
chmod +x "$FAKE_PIO"

# 가짜 포트를 받아들이도록 check_port만 바꿔 끼운 lab.sh (lab.sh 자체에는 우회 경로가 없다)
FAKE_PORT_WRAPPER='source scripts/lab.sh
check_port() { [ "$1" = "$LAB_TEST_FAKE_PORT" ] || die "selftest: unexpected port $1"; echo "[셀프테스트] 가짜 포트: $1 (실제 USB 장치 아님)"; }
main "$@"'

pass=0; fail=0
LAST_OUT=""; LAST_RC=0

run() {  # 실제 lab.sh (실제 포트 검증) + 모의 pio
  : > "$CALLS"
  LAST_OUT="$(PIO="$FAKE_PIO" ./scripts/lab.sh "$@" < /dev/null 2>&1)"
  LAST_RC=$?
}

run_fp() {  # 가짜 포트 허용 래퍼 + 모의 pio
  : > "$CALLS"
  LAST_OUT="$(PIO="$FAKE_PIO" LAB_TEST_FAKE_PORT="$FAKE_PORT" bash -c "$FAKE_PORT_WRAPPER" lab "$@" < /dev/null 2>&1)"
  LAST_RC=$?
}

tty_run() {  # 가상 터미널(expect)에서 질문이 뜬 뒤 답한다. 인자는 공백 없는 경로 전제
  local answer="$1"; shift
  : > "$CALLS"
  LAST_OUT="$(T_ANSWER="$answer" T_ARGS="$*" T_WRAPPER="$FAKE_PORT_WRAPPER" PIO="$FAKE_PIO" LAB_TEST_FAKE_PORT="$FAKE_PORT" /usr/bin/expect -c '
    set timeout 10
    spawn bash -c $env(T_WRAPPER) lab {*}$env(T_ARGS)
    expect "\[y/N\]" { send "$env(T_ANSWER)\r" } timeout { exit 9 }
    expect eof
    catch wait result
    exit [lindex $result 3]
  ' 2>&1)"
  LAST_RC=$?
}

expect_ok() {  # expect_ok <이름> <조건 결과(0이면 통과)>
  if [ "$2" -eq 0 ]; then pass=$((pass+1)); echo "PASS $1"
  else fail=$((fail+1)); echo "FAIL $1"; echo "$LAST_OUT" | sed 's/^/    | /'; fi
}

no_upload_called() { ! grep -q "upload" "$CALLS"; }

snapshot() {  # 소스·문서·설정 파일 지문 (빌드 산출물 .pio, .build 제외)
  find . -path ./.pio -prune -o -path ./.build -prune -o -type f -print0 | sort -z | xargs -0 shasum | shasum
}
BEFORE="$(snapshot)"

bash -n scripts/lab.sh;      expect_ok "syntax lab.sh" $?
bash -n scripts/test_lab.sh; expect_ok "syntax test_lab.sh" $?

run help;  [ $LAST_RC -eq 0 ] && echo "$LAST_OUT" | grep -q "upload keyring"; expect_ok "help" $?
run bogus; [ $LAST_RC -eq 2 ]; expect_ok "unknown command -> 2" $?

# is_excluded가 호출한 쪽의 루프 변수 p를 덮어쓰면 ports가 실제 USB 포트 대신 맥북 포트를 보여 준다(실물 연결 때 발견)
LAST_OUT="$(bash -c 'source scripts/lab.sh; p=/dev/cu.usbserial-1; is_excluded "$p"; echo "$p"' 2>&1)"
[ "$LAST_OUT" = "/dev/cu.usbserial-1" ]; expect_ok "is_excluded keeps caller's loop variable" $?

# --- 실제 lab.sh의 거부 경로 (업로드 명령이 호출되면 안 됨)
run upload;                  [ $LAST_RC -eq 2 ] && no_upload_called; expect_ok "upload: no role" $?
run upload keyrnig /dev/cu.usbserial-1 --yes; [ $LAST_RC -eq 2 ] && no_upload_called; expect_ok "upload: typo role" $?
run upload keyring;          [ $LAST_RC -eq 2 ] && no_upload_called; expect_ok "upload: no port" $?
run upload keyring /dev/cu.Bluetooth-Incoming-Port --yes; [ $LAST_RC -eq 2 ] && no_upload_called; expect_ok "upload: mac bluetooth port rejected" $?
run upload keyring /dev/cu.debug-console --yes; [ $LAST_RC -eq 2 ] && no_upload_called; expect_ok "upload: debug-console rejected" $?
run upload keyring /dev/tty.usbserial-1 --yes; [ $LAST_RC -eq 2 ] && no_upload_called && echo "$LAST_OUT" | grep -q "cu.usbserial-1"; expect_ok "upload: tty.* rejected with cu.* hint" $?
run upload keyring /dev/cu.usbserial-DOESNOTEXIST --yes; [ $LAST_RC -eq 2 ] && no_upload_called; expect_ok "upload: missing port rejected" $?
run upload keyring "$FAKE_PORT" --yes; [ $LAST_RC -eq 2 ] && no_upload_called; expect_ok "upload: regular file (non-/dev) rejected" $?
LAST_OUT="$(: > "$CALLS"; LAB_SELFTEST_PORT="$FAKE_PORT" PIO="$FAKE_PIO" ./scripts/lab.sh upload keyring "$FAKE_PORT" --yes 2>&1)"; LAST_RC=$?
[ $LAST_RC -eq 2 ] && no_upload_called; expect_ok "upload: no bypass via old LAB_SELFTEST_PORT env" $?
run upload keyring /dev/cu.usbserial-1 --force; [ $LAST_RC -eq 2 ] && no_upload_called; expect_ok "upload: unknown option rejected" $?

# --- 업로드 명령 조합·확인 질문 (가짜 포트 래퍼)
run_fp upload keyring "$FAKE_PORT"; [ $LAST_RC -eq 2 ] && no_upload_called; expect_ok "upload: no tty and no --yes -> abort" $?
tty_run n  upload roadside "$FAKE_PORT"; [ $LAST_RC -eq 1 ] && no_upload_called && echo "$LAST_OUT" | grep -q "취소"; expect_ok "upload: answer n -> cancelled" $?
tty_run "" upload roadside "$FAKE_PORT"; [ $LAST_RC -eq 1 ] && no_upload_called; expect_ok "upload: Enter only (default N) -> cancelled" $?
tty_run y  upload roadside "$FAKE_PORT"; [ $LAST_RC -eq 0 ] && grep -qx "run -e roadside -t upload --upload-port $FAKE_PORT" "$CALLS" && echo "$LAST_OUT" | grep -q "도로변"; expect_ok "upload: answer y -> roadside upload command" $?

run_fp upload keyring "$FAKE_PORT" --yes
[ $LAST_RC -eq 0 ] && grep -qx "run -e keyring -t upload --upload-port $FAKE_PORT" "$CALLS" \
  && echo "$LAST_OUT" | grep -q "BLE 통신 성공을 뜻하지 않음" && echo "$LAST_OUT" | grep -q "키링 번호"
expect_ok "upload --yes: exact keyring command + success wording" $?

for msg in "A fatal error occurred: Failed to connect to ESP32 (모의)" \
           "could not open port: [Errno 16] Resource busy (모의)"; do
  LAST_OUT="$(: > "$CALLS"; FAKE_PIO_RC=1 FAKE_PIO_MSG="$msg" PIO="$FAKE_PIO" LAB_TEST_FAKE_PORT="$FAKE_PORT" bash -c "$FAKE_PORT_WRAPPER" lab upload keyring "$FAKE_PORT" --yes 2>&1)"; LAST_RC=$?
  [ $LAST_RC -eq 1 ] && echo "$LAST_OUT" | grep -qF "$msg" && echo "$LAST_OUT" | grep -q "업로드 실패" && ! echo "$LAST_OUT" | grep -q "업로드 성공"
  expect_ok "upload failure passthrough: ${msg%% (*}" $?
done

# --- 모니터
run monitor;                              [ $LAST_RC -eq 2 ]; expect_ok "monitor: no port" $?
run monitor /dev/cu.usbserial-DOESNOTEXIST; [ $LAST_RC -eq 2 ] && ! grep -q "monitor" "$CALLS"; expect_ok "monitor: missing port rejected" $?
run_fp monitor "$FAKE_PORT";              grep -qx "device monitor -p $FAKE_PORT -b 115200" "$CALLS"; expect_ok "monitor: exact command" $?

# --- 다른 프로세스가 포트를 열고 있으면 거부 (2026-11-27 동시 접근 사고)
( exec 3<"$FAKE_PORT"; exec sleep 30 ) & HOLDER=$!
for _ in 1 2 3 4 5 6 7 8 9 10; do /usr/sbin/lsof "$FAKE_PORT" >/dev/null 2>&1 && break; sleep 0.2; done
run_fp monitor "$FAKE_PORT"; [ $LAST_RC -eq 2 ] && ! grep -q "monitor" "$CALLS" && echo "$LAST_OUT" | grep -q "사용 중"; expect_ok "monitor: busy port rejected" $?
run_fp upload keyring "$FAKE_PORT" --yes; [ $LAST_RC -eq 2 ] && no_upload_called; expect_ok "upload: busy port rejected" $?
kill $HOLDER 2>/dev/null; wait $HOLDER 2>/dev/null

# --- 실제 환경의 ports/doctor (실제 pio, 장치는 목록 조회만)
if [ -z "$(ls /dev/cu.* 2>/dev/null | grep -v -e Bluetooth-Incoming-Port -e debug-console)" ]; then
  LAST_OUT="$(./scripts/lab.sh ports 2>&1)"; LAST_RC=$?
  [ $LAST_RC -eq 1 ] && echo "$LAST_OUT" | grep -q "케이블"; expect_ok "ports (no USB serial device): guidance + rc 1" $?
else
  echo "SKIP ports-no-device (USB 시리얼 장치가 연결돼 있음)"
fi
LAST_OUT="$(./scripts/lab.sh doctor 2>&1)"; LAST_RC=$?
[ $LAST_RC -eq 0 ]; expect_ok "doctor (real tools)" $?

[ "$BEFORE" = "$(snapshot)" ]; expect_ok "source/doc/config files unchanged" $?

rm -f "$FAKE_PIO" "$CALLS" "$FAKE_PORT"; rmdir "$TMP" 2>/dev/null
echo
echo "$pass passed, $fail failed"
echo "(검사 범위: 인자·포트 검증·종료 코드·출력 문구·소스 불변. 모의 pio 사용 — 실제 USB 업로드·보드 역할 검증 아님)"
[ $fail -eq 0 ]
