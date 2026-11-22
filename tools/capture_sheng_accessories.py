#!/usr/bin/env python3
"""Read-only accessory capture, pinned to the authorized Lineage tablet."""
import argparse
import json
from pathlib import Path
import subprocess
import threading
import time

SERIAL = "ca10ede3"
ROOT = Path(__file__).resolve().parents[4]
ADB = ROOT / "tools/platform-tools/adb.exe"
PATHS = ["/sys/class/nanodev/nanodev0/_version176x"] + [
    "/sys/class/qcom-battery/" + name for name in
    ("pen_hall3", "pen_hall4", "pen_mac", "pen_soc", "pen_tx_ss", "pen_place_err")]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--seconds", type=int, default=300)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    state = subprocess.check_output([str(ADB), "-s", SERIAL, "shell",
        "getprop ro.boot.slot_suffix; getprop ro.build.fingerprint"], text=True)
    if not state.startswith("_a\n") or "Xiaomi/lineage_sheng/sheng" not in state:
        raise SystemExit("Unexpected target; capture refused")
    (args.output / "identity.txt").write_text(state, encoding="utf-8")
    hall_file = (args.output / "hall-events.txt").open("w", encoding="utf-8")
    pen_files = [(args.output / ("pen-events-" + str(i) + ".txt")).open("w", encoding="utf-8")
        for i in (7, 8)]
    hall = subprocess.Popen([str(ADB), "-s", SERIAL, "shell", "getevent -lt /dev/input/event5"],
        stdout=hall_file, stderr=subprocess.STDOUT)
    pens = [subprocess.Popen([str(ADB), "-s", SERIAL, "shell", "getevent -lt /dev/input/event" + str(i)],
        stdout=stream, stderr=subprocess.STDOUT) for i, stream in zip((7, 8), pen_files)]
    stop = threading.Event()
    def read_states():
        command = "for p in " + " ".join(PATHS) + '; do printf "%s=" "$p"; cat "$p"; printf "\\n"; done; printf "hall_switches="; getevent -S /dev/input/event5'
        last = None
        with (args.output / "states.jsonl").open("w", encoding="utf-8") as stream:
            while not stop.is_set():
                started = time.time()
                try:
                    result = subprocess.run([str(ADB), "-s", SERIAL, "shell", command],
                        capture_output=True, text=True, timeout=10)
                    current = result.stdout
                    stream.write(json.dumps({"time": started, "returncode": result.returncode,
                        "state": current, "stderr": result.stderr}) + "\n")
                    stream.flush()
                    if current != last:
                        print(json.dumps({"time": started, "state": current}), flush=True)
                        last = current
                except subprocess.TimeoutExpired:
                    stream.write(json.dumps({"time": started, "error": "read timeout"}) + "\n")
                    stream.flush()
                stop.wait(0.75)
    thread = threading.Thread(target=read_states)
    thread.start()
    print("Capture ready; hall, pen input and cached accessory states are recording", flush=True)
    try:
        end = time.monotonic() + args.seconds
        while time.monotonic() < end and not (args.output / "STOP").exists():
            time.sleep(0.5)
    finally:
        stop.set()
        thread.join(12)
        hall.terminate()
        for pen in pens:
            pen.terminate()
        hall.wait(5)
        for pen in pens:
            pen.wait(5)
        hall_file.close()
        for stream in pen_files:
            stream.close()
    print("Capture stopped", flush=True)

if __name__ == "__main__":
    main()
