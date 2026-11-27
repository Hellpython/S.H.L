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


def is_bad(x):
    return x.startswith(("[ROADSIDE]", "[SCAN ERROR]", "[GARBLED]"))


def analyze(events, source=""):
    """회차별 결과. OFF: USB 분리 → WAITING, ON: USB 연결 → WARNING.

    신뢰도 등급
      A: 직전 상태를 알려 준 줄 ~ 이벤트 ~ 전환(+0.2초) 사이에 깨진 줄·리셋·스캔 오류가 없고 전환 줄이 온전
      B: 직전 상태는 확실하고, (a) 전환 줄이 깨졌지만 남은 끝부분이 그 전환에만 나오는 문자열
         ('TING t=..ms' = WAITING, 'NING t=..ms' = WARNING)이고 뒤이은 온전한 [ALIVE]가 같은 상태를 보이거나,
         (b) 전환 줄은 온전하지만 측정 구간 안에 깨진 줄이 있다(보조 값이 틀렸을 수 있음)
      C: 직전 상태 불확실(상태 줄과 이벤트 사이에 깨진 줄), 직전 상태가 기대와 다름, 전환 확인 불가
    결과: 정상 / 실패(로그는 온전한데 기대와 다른 동작) / 판정불가(C)
    """
    results = []
    marks = [(i, t, x) for i, (t, x) in enumerate(events) if x.startswith("[HOST] XIAO USB")]
    for k, (i, t0, text) in enumerate(marks):
        stop = marks[k + 1][0] if k + 1 < len(marks) else len(events)
        seg = events[i + 1:stop]
        off = text.endswith("DISCONNECTED")
        expect_before, expect_after = ("WARNING", "WAITING") if off else ("WAITING", "WARNING")
        r = {"source": source, "kind": "OFF" if off else "ON", "at": t0, "notes": []}

        # 직전 상태: 마지막 온전한 [STATE]/[ALIVE]. 그 뒤 ~ 이벤트 사이에 이상이 있으면 불확실
        state_before, state_idx = None, None
        for j in range(i - 1, -1, -1):
            m = STATE_RE.match(events[j][1]) or ALIVE_RE.match(events[j][1])
            if m:
                state_before, state_idx = m.group(2), j
                break
        between_bad = state_idx is not None and any(is_bad(x) for _, x in events[state_idx + 1:i])
        r["state_before"] = state_before

        # 상태 전환: 온전한 줄 우선, 없으면 깨진 줄의 끝부분으로 복원
        want = f"[STATE] {expect_before} -> {expect_after}"
        trans = None
        for t, x in seg:
            if x.startswith(want):
                trans = (t, int(STATE_RE.match(x).group(3)), False)
                break
            if x.startswith("[GARBLED]"):
                m = re.search(("TING" if off else "NING") + r" t=(\d+)ms$", garbled_tail(x))
                if m:
                    trans = (t, int(m.group(1)), True)
                    break
        corroborated = False
        if trans and trans[2]:
            after = [x for t, x in seg if t > trans[0]]
            alive = next((ALIVE_RE.match(x) for x in after if ALIVE_RE.match(x)), None)
            contrary = any(STATE_RE.match(x) for x in after
                           if STATE_RE.match(x) and STATE_RE.match(x).group(1) == expect_after)
            corroborated = bool(alive) and alive.group(2) == expect_after and not contrary
        window_end = (trans[0] if trans else (seg[-1][0] if seg else t0)) + 0.2
        in_window = [x for t, x in seg if is_bad(x) and t <= window_end and not (trans and trans[2] and t == trans[0])]
        r["anomalies_in_window"] = len(in_window)
        r["anomalies_other"] = sum(1 for _, x in seg if is_bad(x)) - len(in_window) - (1 if trans and trans[2] else 0)

        if trans:
            r["host_delay_s"] = trans[0] - t0
        if off:
            if trans:
                rx_before = [x for t, x in events[:i + 1] + seg if RX_RE.match(x) and t <= trans[0]]
                if rx_before:
                    r["lastrx_to_waiting_ms"] = trans[1] - int(RX_RE.match(rx_before[-1]).group(1))
            r["rx_after_waiting"] = sum(1 for t, x in seg if RX_RE.match(x) and trans and t > trans[0])
            r["rx_after_unplug"] = sum(1 for t, x in seg if RX_RE.match(x) and (not trans or t < trans[0]))
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

        # 등급·결과
        if state_before is None or between_bad:
            r["grade"], r["outcome"] = "C", "판정불가"
            r["notes"].append("직전 상태 불확실")
        elif state_before != expect_before:
            r["grade"], r["outcome"] = "C", "판정불가"
            r["notes"].append(f"직전 상태 {state_before} (기대 {expect_before})")
        elif not trans:
            clean = not any(is_bad(x) for _, x in seg)
            r["grade"], r["outcome"] = ("A", "실패") if clean else ("C", "판정불가")
            r["notes"].append("전환 없음")
        elif trans[2] and not corroborated:
            r["grade"], r["outcome"] = "C", "판정불가"
            r["notes"].append("복원 전환을 뒤이은 [ALIVE]로 확인 못 함")
        else:
            r["grade"] = "B" if (trans[2] or in_window) else "A"
            if trans[2]:
                r["notes"].append("전환 줄 복원")
            if in_window:
                r["notes"].append("구간 안 이상 → 보조 값 신뢰 낮음")
            r["outcome"] = "실패" if off and r["rx_after_waiting"] else "정상"
            if off and r["rx_after_waiting"]:
                r["notes"].append("WAITING 뒤 수신(오수신 후보)")
        results.append(r)
    return results


def median_max(values):
    v = sorted(x for x in values if x is not None)
    if not v:
        return "-"
    mid = len(v) // 2
    med = v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2
    return f"중앙값 {med:.2f} / 최대 {v[-1]:.2f} (n={len(v)})"


def print_stats(title, rs):
    offs = [r for r in rs if r["kind"] == "OFF"]
    ons = [r for r in rs if r["kind"] == "ON"]

    def aux(rows, key):  # 측정 구간 안에 이상이 있는 회차의 보조 값은 쓰지 않는다
        return (r.get(key) for r in rows if r["anomalies_in_window"] == 0)

    print(f"\n{title}: OFF {len(offs)}개, ON {len(ons)}개 (보조 값은 구간 안 이상이 없는 회차만)")
    print(f"  분리→WAITING s       {median_max(r.get('host_delay_s') for r in offs)}")
    print(f"  마지막RX→WAITING ms  {median_max(aux(offs, 'lastrx_to_waiting_ms'))}")
    print(f"  연결→WARNING s       {median_max(r.get('host_delay_s') for r in ons)}")
    print(f"  ON 구간 RX/s          {median_max(aux(ons, 'rx_per_s'))}")
    print(f"  ON 구간 최대RX간격 ms {median_max(aux(ons, 'max_rx_gap_ms'))}")


def cmd_analyze(args):
    results = []
    for path in args.log:
        results += analyze(parse(path), os.path.basename(path))
    if not results:
        print("XIAO USB 연결/분리 이벤트가 없습니다.")
        return
    for n, r in enumerate(results, 1):
        at = time.strftime("%H:%M:%S", time.gmtime(r["at"]))
        d = r.get("host_delay_s")
        line = f"{n:>2} {r['source'][:22]:>22} {r['kind']:>3} {at} 직전={r['state_before']}"
        if r["kind"] == "OFF":
            line += f" 분리→WAITING={d:.2f}s" if d is not None else " 분리→WAITING=-"
            line += (f" 마지막RX→WAITING={r.get('lastrx_to_waiting_ms', '-')}ms"
                     f" 분리후RX={r['rx_after_unplug']} WAITING후RX={r.get('rx_after_waiting', '-')}")
        else:
            line += f" 연결→WARNING={d:.2f}s" if d is not None else " 연결→WARNING=-"
            fr = r.get("first_rx_s")
            line += f" 연결→첫RX={fr:.2f}s" if fr is not None else " 연결→첫RX=-"
            rate = r.get("rx_per_s")
            line += f" RX={r.get('rx_count', 0)} RX/s={rate:.2f}" if rate else f" RX={r.get('rx_count', 0)}"
            line += f" 최대RX간격={r.get('max_rx_gap_ms') or '-'}ms"
        line += (f" 이상(구간안/밖)={r['anomalies_in_window']}/{r['anomalies_other']}"
                 f" 등급={r['grade']} 결과={r['outcome']}")
        if r["notes"]:
            line += f" ({'; '.join(r['notes'])})"
        print(line)
    ok = [r for r in results if r["outcome"] == "정상"]
    print_stats("주 통계 — 등급 A, 결과 정상", [r for r in ok if r["grade"] == "A"])
    print_stats("보조 통계 — 등급 A+B, 결과 정상", [r for r in ok if r["grade"] in ("A", "B")])
    fails = [r for r in results if r["outcome"] == "실패"]
    print(f"\n실패 {len(fails)}개, 판정불가(C) {sum(1 for r in results if r['grade'] == 'C')}개")
    print("등급: A 온전 / B 복원·구간 안 이상(보조 값 신뢰 낮음) / C 판정불가. "
          "연결→첫RX는 첫 [RX] 줄이 깨지면 늦게 잡혀 연결→WARNING을 주 지표로 쓴다.")


def main():
    p = argparse.ArgumentParser(description="키링 ON/OFF 감지·해제 지연 측정")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("port")
    r.add_argument("--minutes", type=float, default=10)
    r.add_argument("--out")
    r.set_defaults(func=cmd_record)
    a = sub.add_parser("analyze")
    a.add_argument("log", nargs="+")
    a.set_defaults(func=cmd_analyze)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
