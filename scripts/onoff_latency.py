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


def analyze(events):
    """회차별 결과 dict 목록. OFF 회차: USB 분리 → WAITING, ON 회차: USB 연결 → WARNING."""
    results = []
    marks = [(i, t, x) for i, (t, x) in enumerate(events) if x.startswith("[HOST] XIAO USB")]
    for k, (i, t0, text) in enumerate(marks):
        stop = marks[k + 1][0] if k + 1 < len(marks) else len(events)
        seg = events[i + 1:stop]
        before = [x for _, x in events[:i]]
        state_before = None
        for x in reversed(before):  # 직전 상태: 마지막 [STATE] 또는 [ALIVE]의 state
            m = STATE_RE.match(x) or ALIVE_RE.match(x)
            if m:
                state_before = m.group(2)
                break
        anomalies = sum(1 for _, x in seg if x.startswith(("[ROADSIDE]", "[SCAN ERROR]", "[GARBLED]")))
        r = {"kind": "OFF" if text.endswith("DISCONNECTED") else "ON", "at": t0,
             "state_before": state_before, "anomalies": anomalies}
        if r["kind"] == "OFF":
            trans = next(((t, x) for t, x in seg if x.startswith("[STATE] WARNING -> WAITING")), None)
            rx_before = [(t, x) for t, x in events[:i + 1 + (seg.index(trans) if trans else len(seg))]
                         if RX_RE.match(x)]
            r["ok"] = state_before == "WARNING" and trans is not None
            if trans:
                r["host_delay_s"] = trans[0] - t0
                if rx_before:
                    r["lastrx_to_waiting_ms"] = int(STATE_RE.match(trans[1]).group(3)) - \
                        int(RX_RE.match(rx_before[-1][1]).group(1))
                after = seg[seg.index(trans) + 1:]
                r["rx_after_waiting"] = sum(1 for _, x in after if RX_RE.match(x))  # 오경고 후보
                r["ok"] = r["ok"] and r["rx_after_waiting"] == 0
            r["rx_after_unplug"] = sum(1 for t, x in seg if RX_RE.match(x) and (not trans or t < trans[0]))
        else:
            rx = [(t, x) for t, x in seg if RX_RE.match(x)]
            trans = next(((t, x) for t, x in seg if x.startswith("[STATE] WAITING -> WARNING")), None)
            r["ok"] = state_before == "WAITING" and trans is not None
            if rx:
                r["host_delay_s"] = rx[0][0] - t0
                ts = [int(RX_RE.match(x).group(1)) for _, x in rx]
                gaps = [b - a for a, b in zip(ts, ts[1:])]
                span = (ts[-1] - ts[0]) / 1000
                r["rx_count"] = len(rx)
                r["rx_per_s"] = (len(rx) - 1) / span if span > 0 else None
                r["max_rx_gap_ms"] = max(gaps) if gaps else None
        r["ok"] = r["ok"] and anomalies == 0
        results.append(r)
    return results


def cmd_analyze(args):
    results = analyze(parse(args.log))
    if not results:
        print("XIAO USB 연결/분리 이벤트가 없습니다.")
        return
    for n, r in enumerate(results, 1):
        at = time.strftime("%H:%M:%S", time.gmtime(r["at"]))
        line = f"{n:>2} {r['kind']:>3} {at} 직전={r['state_before']}"
        if r["kind"] == "OFF":
            line += (f" 분리→WAITING={r.get('host_delay_s', float('nan')):.2f}s"
                     f" 마지막RX→WAITING={r.get('lastrx_to_waiting_ms', '-')}ms"
                     f" 분리후RX={r['rx_after_unplug']} WAITING후RX={r.get('rx_after_waiting', '-')}")
        else:
            rate = r.get("rx_per_s")
            line += (f" 연결→첫RX={r.get('host_delay_s', float('nan')):.2f}s RX={r.get('rx_count', 0)}"
                     f" RX/s={rate:.2f}" if rate else
                     f" 연결→첫RX={r.get('host_delay_s', float('nan')):.2f}s RX={r.get('rx_count', 0)}")
            line += f" 최대RX간격={r.get('max_rx_gap_ms') or '-'}ms"
        line += f" 이상={r['anomalies']} 판정={'성공' if r['ok'] else '실패/무효'}"
        print(line)
    print("판정 기준: OFF = 직전 WARNING + WAITING 전환 + 이후 오수신 없음, ON = 직전 WAITING + WARNING 전환,"
          " 둘 다 구간 내 리셋·스캔 오류·깨진 줄 없음")


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
