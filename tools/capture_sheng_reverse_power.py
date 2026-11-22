#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Capture USB reverse power state; optional UCSI GET queries never set limits."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess


def decode_fixed_pdo(value):
    result = {"raw": f"0x{value:08x}", "type": value >> 30}
    if value >> 30 == 0:
        result.update(voltage_mv=((value >> 10) & 1023) * 50,
                      current_ma=(value & 1023) * 10)
        result["max_watts"] = result["voltage_mv"] * result["current_ma"] / 1e6
    elif value >> 30 == 2:
        # Linux include/linux/usb/pd.h: variable supply, 50 mV / 10 mA units.
        # For a sink PDO these are acceptable input capabilities, not output.
        result.update(min_voltage_mv=((value >> 10) & 1023) * 50,
                      max_voltage_mv=((value >> 20) & 1023) * 50,
                      current_ma=(value & 1023) * 10)
    return result


def decode_query(log, command):
    """Ignore stale MSG_IN bytes and reject incomplete/error completions."""
    control = " ".join(f"{x:02x}" for x in command.to_bytes(8, "little"))
    begin = log.lower().rfind("sync_write: control: " + control)
    if begin < 0:
        return {"error": "GET transaction absent from IPC log"}
    transaction = log[begin:]
    # Never associate a response from a subsequent command with this GET.
    end = transaction.find("sync_write: CONTROL:", 1)
    if end >= 0:
        transaction = transaction[:end]
    cci = None
    for line in transaction.splitlines():
        match = re.search(r"read: CCI: ((?:[\da-fA-F]{2} ?){4})", line)
        if match:
            cci = int.from_bytes(bytes.fromhex(match[1]), "little")
        match = re.search(r"read: MSG_IN: ((?:[\da-fA-F]{2} ?){1,16})", line)
        if match and cci is not None:
            if not cci & (1 << 31) or cci & (0x3f << 25):
                return {"error": "UCSI command did not complete successfully", "cci": hex(cci)}
            size = (cci >> 8) & 255
            raw = bytes.fromhex(match[1])
            if size > len(raw) or size % 4:
                return {"error": "Invalid PDO payload length", "length": size}
            return {"cci": hex(cci), "valid_bytes": size,
                    "pdos": [decode_fixed_pdo(int.from_bytes(raw[i:i+4], "little"))
                             for i in range(0, size, 4)],
                    "ignored_buffer_bytes": raw[size:].hex()}
    return {"error": "No complete CCI/MSG_IN pair; raw response is not decoded"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--expected-serial", required=True)
    parser.add_argument("--query-pdos", action="store_true",
                        help="Issue only UCSI GET_PDOS requests through debugfs (root required)")
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[4]
    adb = [str(workspace / "tools/platform-tools/adb.exe"), "-s", args.serial]

    def read(command):
        result = subprocess.run(adb + ["shell", command], capture_output=True, timeout=25)
        return {"rc": result.returncode, "stdout": result.stdout.decode(errors="replace"),
                "stderr": result.stderr.decode(errors="replace")}

    def verify():
        if read("getprop ro.serialno")["stdout"].strip() != args.expected_serial:
            raise RuntimeError("Device identity mismatch")
        if read("getprop ro.product.vendor.device")["stdout"].strip() != "sheng":
            raise RuntimeError("This capture is for sheng only")

    verify()
    out = workspace / "reports" / ("reverse-power-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    out.mkdir()
    report = {"serial": args.expected_serial, "transport": args.serial,
              "electrical_settings_changed": False, "queries": {}}
    commands = {
        "state": "date; cat /proc/uptime; getprop ro.product.device; "
                 "cat /sys/class/typec/port0/power_role /sys/class/typec/port0/data_role "
                 "/sys/class/typec/port0/power_operation_mode; "
                 "cat /sys/class/typec/port0-partner/usb_power_delivery_revision; "
                 "dumpsys battery; dumpsys usb",
        "charger": "for n in current_state typec_mode adapter_svid adapter_id "
                   "otg_ui_support pd_verifed verify_process reverse_chg_mode reverse_chg_state; "
                   "do echo NODE:$n; cat /sys/class/qcom-battery/$n; done; "
                   "cat /sys/class/power_supply/usb/uevent; "
                   "cat /sys/kernel/debug/charger_ulog/enable "
                   "/sys/kernel/debug/charger_ulog/category /sys/kernel/debug/charger_ulog/level",
        "kernel": "dmesg", "system": "logcat -b all -d -t 3000 -v threadtime",
    }
    for name, command in commands.items():
        verify()
        (out / (name + ".json")).write_text(json.dumps(read(command), indent=2), encoding="utf-8")
    if args.query_pdos:
        path = "/sys/kernel/debug/usb/ucsi/soc:qcom,pmic_glink:qcom,ucsi"
        # Four PDOs from offset zero. Source bit 34, partner bit 23, connector 1.
        for name, command in {"local_source": 0x700010010, "partner_sink": 0x300810010,
                              "partner_source": 0x700810010, "local_sink": 0x300010010}.items():
            verify()
            result = read(f"echo {hex(command)} > {path}/command && cat {path}/response")
            ipc = read("timeout 2 cat /sys/kernel/debug/ipc_logging/ucsi/log")
            (out / (name + "-ipc.json")).write_text(json.dumps(ipc, indent=2), encoding="utf-8")
            report["queries"][name] = {"command": hex(command), "response": result}
            if result["rc"] == 0 and ipc["rc"] == 0:
                report["queries"][name]["decoded"] = decode_query(ipc["stdout"], command)
    report["note"] = "PDOs are protocol capabilities, not measured output or proof of hardware limits."
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print("OUTPUT: " + str(out), flush=True)


if __name__ == "__main__":
    main()
