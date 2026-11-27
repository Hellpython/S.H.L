#!/usr/bin/env python3
# 거리별 RSSI 기록 도구. 도로변 ESP32의 기존 [RX] 로그만 읽는다(펌웨어 변경 없음).
#
#   기록: ~/.platformio/penv/bin/python scripts/rssi_survey.py record <ESP32 포트> [--seconds 30]
#   요약: ~/.platformio/penv/bin/python scripts/rssi_survey.py summary <csv 파일>
#
# record는 거리 이름(예: 1m)을 입력받고 Enter를 누르면 그때부터 정해진 시간 동안
# [RX] 줄을 CSV(docs/logs/rssi-<시각>.csv)에 쌓는다. 원문 로그도 같은 이름 .log로 남긴다.
# 주의:
#  - 포트를 열면 ESP32가 리셋될 수 있다(2026-11-27 관찰). 리셋 후 [ROADSIDE]가 나오면 기록을 시작한다.
#  - 도로변 펌웨어는 스캔 1회(약 1.1초)마다 키링 1개당 [RX] 최대 1줄 → 30초 ≈ 27개 표본.
#  - RSSI는 거리 값이 아니다. 이 도구는 거리별 분포를 비교할 뿐이다.
import argparse
import csv
import math
import os
import re
import statistics
import sys
import time

RX_RE = re.compile(r"^\[RX\] t=(\d+)ms keyring=(\d+) rssi=(-?\d+)$")
GAP_MISS_MS = 1600  # 연속 [RX] 간격이 이보다 길면 그 사이 스캔에서 못 받은 것으로 센다(루프 약 1.1초)
FIELDS = ["host_time", "label", "board_t_ms", "keyring", "rssi"]


def summarize(rows):
    """rows: 같은 label의 dict 목록. 통계 dict 반환(표본 없으면 n=0만)."""
    rssi = [int(r["rssi"]) for r in rows]
    if not rssi:
        return {"n": 0}
    ts = [int(r["board_t_ms"]) for r in rows]
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    misses = sum(max(0, round(g / 1100) - 1) for g in gaps if g > GAP_MISS_MS)
    q = sorted(rssi)
    return {
        "n": len(rssi),
        "min": q[0],
        "max": q[-1],
        "mean": statistics.fmean(rssi),
        "median": statistics.median(rssi),
        "stdev": statistics.stdev(rssi) if len(rssi) > 1 else 0.0,
        "p10": q[max(0, math.ceil(0.1 * len(q)) - 1)],
        "p90": q[max(0, math.ceil(0.9 * len(q)) - 1)],
        "missed_scans": misses,
    }


def print_table(rows):
    labels = []
    for r in rows:
        if r["label"] not in labels:
            labels.append(r["label"])
    print(f"{'label':>10} {'n':>4} {'min':>5} {'max':>5} {'mean':>7} {'median':>7} "
          f"{'stdev':>6} {'p10':>5} {'p90':>5} {'miss':>5}")
    for label in labels:
        s = summarize([r for r in rows if r["label"] == label])
        if s["n"] == 0:
            print(f"{label:>10} {0:>4}  (표본 없음)")
            continue
        print(f"{label:>10} {s['n']:>4} {s['min']:>5} {s['max']:>5} {s['mean']:>7.1f} "
              f"{s['median']:>7.1f} {s['stdev']:>6.2f} {s['p10']:>5} {s['p90']:>5} "
              f"{s['missed_scans']:>5}")


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def cmd_summary(args):
    print_table(read_csv(args.csv))


def cmd_record(args):
    import serial  # PlatformIO penv에 포함된 pyserial

    stamp = time.strftime("%Y%m%d-%H%M%S")
    os.makedirs("docs/logs", exist_ok=True)
    csv_path = args.out or f"docs/logs/rssi-{stamp}.csv"
    log_path = os.path.splitext(csv_path)[0] + ".log"

    s = serial.Serial()
    s.port, s.baudrate, s.timeout = args.port, 115200, 0.05
    s.dtr, s.rts = False, False
    s.open()
    buf = b""

    def now():
        t = time.time()
        return time.strftime("%H:%M:%S", time.localtime(t)) + f".{int(t * 1000) % 1000:03d}"

    def lines(log):
        """시리얼에서 완성된 줄을 꺼내 원문 로그에 남기고 돌려준다. 깨진 줄은 hex로 남긴다."""
        nonlocal buf
        buf += s.read(256)
        out = []
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            raw = raw.rstrip(b"\r")
            try:
                text = raw.decode("ascii")
            except UnicodeDecodeError:
                text = "[GARBLED] " + raw.hex(" ")
            log.write(f"{now()} {text}\n")
            out.append(text)
        return out

    rows = []
    new_file = not os.path.exists(csv_path)
    with open(csv_path, "a", newline="") as cf, open(log_path, "a", buffering=1) as log:
        writer = csv.DictWriter(cf, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        log.write(f"{now()} [HOST] open {args.port}\n")
        print(f"기록 파일: {csv_path}\n원문 로그: {log_path}")
        print("거리 이름을 입력하고 Enter(예: 0.5m). 빈 입력은 같은 이름 재측정, q는 종료.")
        label = ""
        while True:
            lines(log)  # 대기 중 줄도 원문 로그에 남긴다
            entered = input(f"\n거리 [{label or '-'}]> ").strip()
            lines(log)
            if entered == "q":
                break
            label = entered or label
            if not label:
                print("거리 이름을 입력하세요.")
                continue
            log.write(f"{now()} [HOST] session start label={label} seconds={args.seconds}\n")
            session, events = [], {"alive": 0, "scan_error": 0, "reset": 0, "garbled": 0}
            end = time.time() + args.seconds
            while time.time() < end:
                for text in lines(log):
                    m = RX_RE.match(text)
                    if m:
                        row = {"host_time": now(), "label": label, "board_t_ms": m.group(1),
                               "keyring": m.group(2), "rssi": m.group(3)}
                        writer.writerow(row)
                        session.append(row)
                        print(f"  {row['host_time']} keyring={row['keyring']} rssi={row['rssi']}")
                    elif text.startswith("[ALIVE]"):
                        events["alive"] += 1
                    elif text.startswith("[SCAN ERROR]"):
                        events["scan_error"] += 1
                    elif text.startswith("[ROADSIDE]"):
                        events["reset"] += 1
                    elif text.startswith("[GARBLED]"):
                        events["garbled"] += 1
            cf.flush()
            log.write(f"{now()} [HOST] session end label={label} events={events}\n")
            rows.extend(session)
            st = summarize(session)
            if st["n"]:
                print(f"  -> n={st['n']} mean={st['mean']:.1f} median={st['median']} "
                      f"min/max={st['min']}/{st['max']} stdev={st['stdev']:.2f} miss={st['missed_scans']}")
            else:
                print("  -> [RX] 없음")
            if any(events[k] for k in ("scan_error", "reset", "garbled")):
                print(f"  !! 이상 이벤트 {events} — 이 회차는 무효로 볼지 판단 필요")
    s.close()
    print("\n이번 실행 요약")
    print_table(rows)
    print(f"\n전체 파일 요약: python scripts/rssi_survey.py summary {csv_path}")


def main():
    p = argparse.ArgumentParser(description="거리별 RSSI 기록·요약 (도로변 ESP32 [RX] 로그)")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("port")
    r.add_argument("--seconds", type=float, default=30)
    r.add_argument("--out")
    r.set_defaults(func=cmd_record)
    sm = sub.add_parser("summary")
    sm.add_argument("csv")
    sm.set_defaults(func=cmd_summary)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
