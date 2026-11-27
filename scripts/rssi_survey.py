#!/usr/bin/env python3
# 거리별 RSSI 기록 도구. 도로변 ESP32의 기존 [RX] 로그만 읽는다(펌웨어 변경 없음).
#
#   기록: ~/.platformio/penv/bin/python scripts/rssi_survey.py record <ESP32 포트> [--seconds 30]
#   요약: ~/.platformio/penv/bin/python scripts/rssi_survey.py summary <rssi-....csv>
#
# record는 거리 이름(예: 1m)을 입력받고 Enter를 누르면 그때부터 정해진 시간 동안
# [RX] 줄을 모은다. 파일(docs/logs/):
#   rssi-<시각>.csv           표본 1줄 = [RX] 1줄
#   rssi-<시각>-sessions.csv  회차 1줄 (수신 0개 회차·이상 이벤트 포함)
#   rssi-<시각>.log           시리얼 원문(맥북 시각). 깨진 줄은 [GARBLED] + hex
# 주의:
#  - 포트를 열면 ESP32가 리셋될 수 있다(2026-11-27 관찰). 첫 프롬프트 뒤 몇 초 기다린다.
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
SCAN_PERIOD_S = 1.1   # 도로변 loop 1회(스캔 1초 + 처리). 2026-11-27 실측 1.04~1.10초
TIMEOUT_S = 3.0       # 도로변 kSignalTimeoutMs. 이보다 긴 공백이면 현재 로직은 경고를 끈다
OUTLIER_DB = 20       # 회차 중앙값에서 이만큼 이상 벗어난 표본을 이상치로 센다(기술용 기준)
FIELDS = ["session", "label", "host_time", "host_epoch", "board_t_ms", "keyring", "rssi"]
SESSION_FIELDS = ["session", "label", "start_epoch", "seconds", "n",
                  "alive", "scan_error", "reset", "garbled"]
EVENTS = ("scan_error", "reset", "garbled")


def quantile(sorted_values, q):
    return sorted_values[max(0, math.ceil(q * len(sorted_values)) - 1)]


def summarize(session, rows):
    """회차 1개의 통계. session: sessions.csv 1줄(dict), rows: 그 회차 표본."""
    start, seconds = float(session["start_epoch"]), float(session["seconds"])
    times = [start] + [float(r["host_epoch"]) for r in rows] + [start + seconds]
    gaps = [b - a for a, b in zip(times, times[1:])]
    s = {
        "n": len(rows),
        "rate": len(rows) / max(1, round(seconds / SCAN_PERIOD_S)),
        "max_gap": max(gaps),
        "long_gaps": sum(1 for g in gaps if g >= TIMEOUT_S),
        "flags": ",".join(k for k in EVENTS if int(session.get(k) or 0)),
    }
    if not rows:
        s["verdict"] = "없음"
        return s
    s["verdict"] = "안정" if s["long_gaps"] == 0 else "간헐"
    rssi = sorted(int(r["rssi"]) for r in rows)
    med = statistics.median(rssi)
    s.update({
        "min": rssi[0], "max": rssi[-1], "mean": statistics.fmean(rssi), "median": med,
        "stdev": statistics.stdev(rssi) if len(rssi) > 1 else 0.0,
        "p10": quantile(rssi, 0.1), "p90": quantile(rssi, 0.9),
        "outliers": sum(1 for v in rssi if abs(v - med) >= OUTLIER_DB),
    })
    return s


def print_table(sessions, rows):
    print(f"{'label':>8} {'start':>8} {'n':>3} {'rate':>5} {'maxgap':>6} {'gap>=3s':>7} "
          f"{'verdict':>4} {'min':>4} {'p10':>4} {'med':>6} {'p90':>4} {'max':>4} "
          f"{'mean':>6} {'stdev':>5} {'outl':>4}  flags")
    for se in sessions:
        s = summarize(se, [r for r in rows if r["session"] == se["session"]])
        head = (f"{se['label']:>8} {se['session']:>8} {s['n']:>3} {s['rate']:>5.0%} "
                f"{s['max_gap']:>5.1f}s {s['long_gaps']:>7} {s['verdict']:>4}")
        if s["n"]:
            head += (f" {s['min']:>4} {s['p10']:>4} {s['median']:>6.1f} {s['p90']:>4} "
                     f"{s['max']:>4} {s['mean']:>6.1f} {s['stdev']:>5.2f} {s['outliers']:>4}")
        else:
            head += " " * 46
        print(head + (f"  !! {s['flags']}" if s["flags"] else ""))
    print(f"rate = n / (회차 초 / {SCAN_PERIOD_S}) 근사. verdict: 안정 = 공백이 한 번도 "
          f"{TIMEOUT_S:.0f}s 이상 아님, 간헐 = 수신했지만 {TIMEOUT_S:.0f}s 이상 공백 있음. "
          f"outl = 중앙값에서 {OUTLIER_DB}dB 이상. !! = 이상 이벤트(무효 검토)")


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def sessions_path(csv_path):
    return os.path.splitext(csv_path)[0] + "-sessions.csv"


def cmd_summary(args):
    print_table(read_csv(sessions_path(args.csv)), read_csv(args.csv))


def cmd_record(args):
    import threading

    import serial  # PlatformIO penv에 포함된 pyserial

    os.makedirs("docs/logs", exist_ok=True)
    csv_path = args.out or f"docs/logs/rssi-{time.strftime('%Y%m%d-%H%M%S')}.csv"
    log_path = os.path.splitext(csv_path)[0] + ".log"

    s = serial.Serial()
    s.port, s.baudrate, s.timeout = args.port, 115200, 0.05
    s.dtr, s.rts = False, False
    s.open()

    def hms(t):
        return time.strftime("%H:%M:%S", time.localtime(t)) + f".{int(t * 1000) % 1000:03d}"

    # 시리얼은 별도 스레드가 계속 읽는다. 입력을 기다리는 동안 읽지 않으면 OS 버퍼에 쌓였다가
    # 한꺼번에 들어와 도착 시각이 틀어진다(2026-11-27 관찰). 모든 줄은 (도착 시각, 문자열)로 보관.
    received, lock, stop = [], threading.Lock(), threading.Event()
    log = open(log_path, "a", buffering=1)

    def reader():
        buf = b""
        while not stop.is_set():
            buf += s.read(256)
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                raw = raw.rstrip(b"\r")
                try:
                    text = raw.decode("ascii")
                except UnicodeDecodeError:
                    text = "[GARBLED] " + raw.hex(" ")
                t = time.time()
                log.write(f"{hms(t)} {text}\n")
                with lock:
                    received.append((t, text))

    opened = time.time()
    log.write(f"{hms(opened)} [HOST] open {args.port} (이후 2초간 도착한 줄은 이전에 쌓인 출력일 수 있어 집계 안 함)\n")
    threading.Thread(target=reader, daemon=True).start()
    time.sleep(2)

    all_sessions, all_rows = [], []
    with open(csv_path, "a", newline="") as cf, open(sessions_path(csv_path), "a", newline="") as sf:
        writer = csv.DictWriter(cf, fieldnames=FIELDS)
        swriter = csv.DictWriter(sf, fieldnames=SESSION_FIELDS)
        if cf.tell() == 0:
            writer.writeheader()
        if sf.tell() == 0:
            swriter.writeheader()
        print(f"표본: {csv_path}\n회차: {sessions_path(csv_path)}\n원문: {log_path}")
        print("거리 이름을 입력하고 Enter(예: 0.5m). 빈 입력은 같은 이름 재측정, q는 종료.")
        label = ""
        while True:
            entered = input(f"\n거리 [{label or '-'}]> ").strip()
            if entered == "q":
                break
            label = entered or label
            if not label:
                print("거리 이름을 입력하세요.")
                continue
            start = time.time()
            end = start + args.seconds
            session = {"session": hms(start)[:8], "label": label, "start_epoch": f"{start:.3f}",
                       "seconds": args.seconds, "alive": 0, "scan_error": 0, "reset": 0, "garbled": 0}
            log.write(f"{hms(start)} [HOST] session start label={label} seconds={args.seconds}\n")
            rows, seen = [], 0
            while True:
                with lock:
                    window = [(t, x) for t, x in received if start <= t < end]
                for t, text in window[seen:]:
                    m = RX_RE.match(text)
                    if m:
                        row = {"session": session["session"], "label": label, "host_time": hms(t),
                               "host_epoch": f"{t:.3f}", "board_t_ms": m.group(1),
                               "keyring": m.group(2), "rssi": m.group(3)}
                        writer.writerow(row)
                        rows.append(row)
                        print(f"  {row['host_time']} keyring={row['keyring']} rssi={row['rssi']}")
                    elif text.startswith("[ALIVE]"):
                        session["alive"] += 1
                    elif text.startswith("[SCAN ERROR]"):
                        session["scan_error"] += 1
                    elif text.startswith("[ROADSIDE]"):
                        session["reset"] += 1
                    elif text.startswith("[GARBLED]"):
                        session["garbled"] += 1
                seen = len(window)
                if time.time() >= end + 0.2:  # 끝 직전에 도착한 줄까지 반영
                    break
                time.sleep(0.05)
            session["n"] = len(rows)
            swriter.writerow(session)
            cf.flush()
            sf.flush()
            log.write(f"{hms(time.time())} [HOST] session end label={label} n={len(rows)}\n")
            all_sessions.append(session)
            all_rows.extend(rows)
            print_table([session], rows)
    stop.set()
    time.sleep(0.1)
    s.close()
    log.close()
    print("\n이번 실행 요약")
    print_table(all_sessions, all_rows)
    print(f"\n다시 보기: python scripts/rssi_survey.py summary {csv_path}")


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
