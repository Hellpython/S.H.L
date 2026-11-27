#!/usr/bin/env python3
# 키링 ON/OFF 지연 측정. 도로변 ESP32 시리얼과 XIAO USB 연결/분리 시각을 맥북 시각으로 함께 기록하고,
# 회차별 감지·해제 지연을 계산한다. 펌웨어 변경 전후 비교용.
#
#   기록: ~/.platformio/penv/bin/python scripts/onoff_latency.py record <ESP32 포트> [--minutes 10]
#         (기록 중 XIAO USB 케이블을 뽑았다 꽂는다. 한 상태를 15초 이상 유지)
#   분석: ~/.platformio/penv/bin/python scripts/onoff_latency.py analyze <로그 파일>
#
# XIAO 전원 = 맥북 USB라 "USB 분리 시각" = 키링 전원 OFF 시각으로 본다(포트 소실 감지는 약 0.2초 주기).
import argparse
import glob
import os
import re
import subprocess
import sys
import time
from datetime import datetime

LINE_RE = re.compile(r"^(\d\d:\d\d:\d\d\.\d{3}) (.*)$")
RX_RE = re.compile(r"^\[RX\] t=(\d+)ms keyring=(\d+) rssi=(-?\d+)")
STATE_RE = re.compile(r"^\[STATE\] (\w+) -> (\w+) t=(\d+)ms")
ALIVE_RE = re.compile(r"^\[ALIVE\] roadside .*scan_errors=(\d+) state=(\w+)")


def hms(t):
    return time.strftime("%H:%M:%S", time.localtime(t)) + f".{int(t * 1000) % 1000:03d}"


def cmd_record(args):
    import serial  # PlatformIO penv에 포함된 pyserial

    holders = subprocess.run(["/usr/sbin/lsof", args.port], capture_output=True, text=True).stdout
    if holders.strip():
        sys.exit(f"[중단] {args.port} 를 다른 프로그램이 사용 중입니다. 먼저 종료하세요:\n{holders}")
    os.makedirs("docs/logs", exist_ok=True)
    path = args.out or f"docs/logs/onoff-{time.strftime('%Y%m%d-%H%M%S')}.log"
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = args.port, 115200, 0.05
    s.dtr, s.rts, s.exclusive = False, False, True
    s.open()

    def xiao_present():
        return bool(glob.glob("/dev/cu.usbmodem*"))

    end, xiao, buf = time.time() + args.minutes * 60, xiao_present(), b""
    counts = {"CONNECTED": 0, "DISCONNECTED": 0}
    print(f"기록: {path} ({args.minutes:.0f}분, Ctrl+C로 일찍 끝내도 됨)")
    print(f"현재 XIAO USB: {'연결됨' if xiao else '분리됨'}. 15초 이상 간격으로 뽑았다 꽂기를 반복하세요.")
    with open(path, "a", buffering=1) as f:
        f.write(f"{hms(time.time())} [HOST] logger start port={args.port} xiao_usb={'ON' if xiao else 'OFF'}\n")
        try:
            while time.time() < end:
                present = xiao_present()
                if present != xiao:
                    xiao = present
                    kind = "CONNECTED" if xiao else "DISCONNECTED"
                    counts[kind] += 1
                    msg = f"[HOST] XIAO USB {kind}"
                    f.write(f"{hms(time.time())} {msg}\n")
                    print(f"{msg}  (분리 {counts['DISCONNECTED']}회 / 연결 {counts['CONNECTED']}회)")
                buf += s.read(256)
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    raw = raw.rstrip(b"\r")
                    try:
                        text = raw.decode("ascii")
                    except UnicodeDecodeError:
                        text = "[GARBLED] " + raw.hex(" ")
                    f.write(f"{hms(time.time())} {text}\n")
        except KeyboardInterrupt:
            pass
        f.write(f"{hms(time.time())} [HOST] logger end\n")
    s.close()
    print(f"잡힌 이벤트: 분리 {counts['DISCONNECTED']}회 / 연결 {counts['CONNECTED']}회")
    if min(counts.values()) < 5:
        print("!! ON/OFF 5회가 기록되지 않았습니다. 이 기록은 기준선으로 쓸 수 없습니다(재측정 필요).")
    print(f"분석: python scripts/onoff_latency.py analyze {path}")


def parse(path):
    """(맥북 시각 초, 문자열) 목록. 날짜는 같은 날로 본다."""
    events = []
    for line in open(path, errors="replace"):
        m = LINE_RE.match(line.rstrip("\n"))
        if m:
            t = datetime.strptime(m.group(1), "%H:%M:%S.%f")
            events.append((t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1e6, m.group(2)))
    return events


def garbled_tail(text):
    """[GARBLED] 줄에서 0xFF 블록 뒤에 이어진 문자열(손상되지 않은 원래 줄의 끝부분)."""
    raw = bytes.fromhex(text[len("[GARBLED] "):])
    return raw.lstrip(b"\xff").decode("ascii", "replace")


def find_transition(seg, kind):
    """seg에서 상태 전환 줄 (시각, 보드 t ms, 복원 여부). kind: 'WAITING'(OFF) / 'WARNING'(ON).
    전환 줄이 깨졌어도 끝부분에 '<kind> t=..ms'가 남아 있으면 그 시각으로 복원한다."""
    want = "[STATE] WARNING -> WAITING" if kind == "WAITING" else "[STATE] WAITING -> WARNING"
    for t, x in seg:
        if x.startswith(want):
            return t, int(STATE_RE.match(x).group(3)), False
        if x.startswith("[GARBLED]"):
            m = re.search(kind[-4:] + r" t=(\d+)ms$", garbled_tail(x))  # 'TING t=..' 형태도 잡는다
            if m:
                return t, int(m.group(1)), True
    return None


def analyze(events):
    """회차별 결과. OFF: USB 분리 → WAITING, ON: USB 연결 → WARNING.
    깨진 줄은 측정 구간(이벤트 ~ 전환 + 0.2초) 안이면 영향으로, 밖이면 참고로 센다."""
    results = []
    marks = [(i, t, x) for i, (t, x) in enumerate(events) if x.startswith("[HOST] XIAO USB")]
    for k, (i, t0, text) in enumerate(marks):
        stop = marks[k + 1][0] if k + 1 < len(marks) else len(events)
        seg = events[i + 1:stop]
        state_before = None
        for _, x in reversed(events[:i]):  # 직전 상태: 마지막 [STATE] 또는 [ALIVE]의 state
            m = STATE_RE.match(x) or ALIVE_RE.match(x)
            if m:
                state_before = m.group(2)
                break
        off = text.endswith("DISCONNECTED")
        r = {"kind": "OFF" if off else "ON", "at": t0, "state_before": state_before}
        trans = find_transition(seg, "WAITING" if off else "WARNING")
        window_end = (trans[0] if trans else seg[-1][0] if seg else t0) + 0.2
        bad = [x for t, x in seg if x.startswith(("[ROADSIDE]", "[SCAN ERROR]", "[GARBLED]"))
               and t <= window_end and not (trans and trans[2] and t == trans[0])]
        r["anomalies_in_window"] = len(bad)
        r["anomalies_other"] = sum(1 for t, x in seg if x.startswith(("[ROADSIDE]", "[SCAN ERROR]", "[GARBLED]"))) \
            - len(bad) - (1 if trans and trans[2] else 0)
        r["recovered"] = bool(trans and trans[2])
        if trans:
            r["host_delay_s"] = trans[0] - t0
        if off:
            if trans:
                rx_before = [x for t, x in events[:i + 1] + seg if RX_RE.match(x) and t <= trans[0]]
                if rx_before:
                    r["lastrx_to_waiting_ms"] = trans[1] - int(RX_RE.match(rx_before[-1]).group(1))
                r["rx_after_waiting"] = sum(1 for t, x in seg if RX_RE.match(x) and t > trans[0])
            r["rx_after_unplug"] = sum(1 for t, x in seg if RX_RE.match(x) and (not trans or t < trans[0]))
            ok = state_before == "WARNING" and trans is not None and r.get("rx_after_waiting", 1) == 0
        else:
            rx = [(t, x) for t, x in seg if RX_RE.match(x)]
            if rx:
                r["first_rx_s"] = rx[0][0] - t0
                ts = [int(RX_RE.match(x).group(1)) for _, x in rx]
                gaps = [b - a for a, b in zip(ts, ts[1:])]
                span = (ts[-1] - ts[0]) / 1000
                r["rx_count"] = len(rx)
                r["rx_per_s"] = (len(rx) - 1) / span if span > 0 else None
                r["max_rx_gap_ms"] = max(gaps) if gaps else None
            ok = state_before == "WAITING" and trans is not None
        # 측정 구간 안의 이상이 있으면, 마지막RX 같은 보조 값이 틀렸을 수 있다 -> 무효
        r["verdict"] = ("무효" if r["anomalies_in_window"] else
                        ("성공(복원)" if r["recovered"] else "성공") if ok else "실패")
        results.append(r)
    return results


def median_max(values):
    v = sorted(x for x in values if x is not None)
    if not v:
        return "-"
    mid = len(v) // 2
    med = v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2
    return f"중앙값 {med:.2f} / 최대 {v[-1]:.2f} (n={len(v)})"


def cmd_analyze(args):
    results = analyze(parse(args.log))
    if not results:
        print("XIAO USB 연결/분리 이벤트가 없습니다.")
        return
    for n, r in enumerate(results, 1):
        at = time.strftime("%H:%M:%S", time.gmtime(r["at"]))
        d = r.get("host_delay_s")
        line = f"{n:>2} {r['kind']:>3} {at} 직전={r['state_before']}"
        if r["kind"] == "OFF":
            line += (f" 분리→WAITING={d:.2f}s" if d is not None else " 분리→WAITING=-")
            line += (f" 마지막RX→WAITING={r.get('lastrx_to_waiting_ms', '-')}ms"
                     f" 분리후RX={r['rx_after_unplug']} WAITING후RX={r.get('rx_after_waiting', '-')}")
        else:
            line += (f" 연결→WARNING={d:.2f}s" if d is not None else " 연결→WARNING=-")
            fr = r.get("first_rx_s")
            line += f" 연결→첫RX={fr:.2f}s" if fr is not None else " 연결→첫RX=-"
            rate = r.get("rx_per_s")
            line += f" RX={r.get('rx_count', 0)} RX/s={rate:.2f}" if rate else f" RX={r.get('rx_count', 0)}"
            line += f" 최대RX간격={r.get('max_rx_gap_ms') or '-'}ms"
        line += f" 이상(구간안/밖)={r['anomalies_in_window']}/{r['anomalies_other']} 판정={r['verdict']}"
        print(line)
    ok = [r for r in results if r["verdict"].startswith("성공")]
    offs = [r for r in ok if r["kind"] == "OFF"]
    ons = [r for r in ok if r["kind"] == "ON"]
    print("\n성공 회차 요약 (복원 포함)")
    print(f"  분리→WAITING s       {median_max(r.get('host_delay_s') for r in offs)}")
    print(f"  마지막RX→WAITING ms  {median_max(r.get('lastrx_to_waiting_ms') for r in offs)}")
    print(f"  연결→WARNING s       {median_max(r.get('host_delay_s') for r in ons)}")
    print(f"  ON 구간 RX/s          {median_max(r.get('rx_per_s') for r in ons)}")
    print(f"  ON 구간 최대RX간격 ms {median_max(r.get('max_rx_gap_ms') for r in ons)}")
    print(f"  회차: OFF {len([r for r in results if r['kind'] == 'OFF'])} (성공 {len(offs)}), "
          f"ON {len([r for r in results if r['kind'] == 'ON'])} (성공 {len(ons)})")
    print("판정: OFF 성공 = 직전 WARNING + WAITING 전환 + 이후 오수신 없음 / ON 성공 = 직전 WAITING + WARNING 전환."
          " 측정 구간(이벤트~전환+0.2초) 안에 리셋·스캔 오류·깨진 줄이 있으면 무효."
          " 성공(복원) = 깨진 전환 줄의 남은 끝부분('... t=..ms')에서 시각을 읽음."
          " 연결→첫RX는 첫 [RX] 줄이 깨지면 늦게 잡힐 수 있어 연결→WARNING을 주 지표로 쓴다.")


def main():
    p = argparse.ArgumentParser(description="키링 ON/OFF 감지·해제 지연 측정")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("port")
    r.add_argument("--minutes", type=float, default=10)
    r.add_argument("--out")
    r.set_defaults(func=cmd_record)
    a = sub.add_parser("analyze")
    a.add_argument("log")
    a.set_defaults(func=cmd_analyze)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
