#!/usr/bin/env python3
"""Compare two winetest reports (winetest.exe -o FILE): real Windows vs vermouth.

Usage: compare.py WINDOWS_REPORT [WINDOWS_REPORT ...] VERMOUTH_REPORT [--all]

With several Windows reports (one per image), a unit counts as passing on
Windows only if it passes on every image.

Wine's tests are written to pass on Windows, so every unit is sorted by what
the two runs say:
  diverges   passes on Windows, fails or crashes on vermouth  -> the work list
  todo       passes on both, but vermouth only passes via todo_wine marks
             (known gaps the tests tolerate)
  windows    fails on Windows too: the test or the runner, not us
  unreliable no usable Windows answer: the images disagree, Windows ran 0
             checks, or the unit needs hardware or a driver the hosted
             runners can't provide (see RUNNER_UNRELIABLE)
  missing    ran on one side only
"""
import re
import sys
from collections import defaultdict

START = re.compile(r"^(\S+:\S+) start ")
DONE = re.compile(r"^(\S+:\S+?):[0-9a-f]+ done \((-?\d+)\)")
SUMMARY = re.compile(r"^[0-9a-f]+:(\S+?):(?:[\d.]+)? (\d+) tests executed \((\d+) marked as todo, (?:\d+ as flaky, )?(\d+) failures?\)")
FAILED = re.compile(r"Test failed: (.*)")

# Units that install winetest's virtual HID/bus kernel driver, or need an
# interactive desktop. On GitHub's hosted runners they time out, fail to
# create devices or crash, and differently on each image, so they say nothing
# about Windows. Check them on an interactive Windows machine instead.
RUNNER_UNRELIABLE = {
    "dinput:device8": "needs a foreground window on an interactive desktop",
    "dinput:force_feedback": "virtual HID driver; crashes on windows-2022 runners",
    "dinput:hid": "virtual HID driver; device creation fails on runners",
    "dinput:hotplug": "virtual HID driver",
    "dinput:joystick8": "virtual HID driver; fails or crashes on runners",
    "hid:device": "needs real HID devices; 0 checks run on runners",
    "ntoskrnl.exe:ntoskrnl": "test kernel driver; 5-122 failures on runners",
}


def parse(path):
    units = {}
    cur = None
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        m = START.match(line)
        if m:
            cur = m.group(1)
            units[cur] = {"rc": None, "executed": 0, "todo": 0, "failures": 0, "failed": []}
            continue
        if cur is None:
            continue
        u = units[cur]
        m = SUMMARY.match(line)
        if m:
            u["executed"] += int(m.group(2))
            u["todo"] += int(m.group(3))
            u["failures"] += int(m.group(4))
            continue
        m = DONE.match(line)
        if m and m.group(1) == cur:
            u["rc"] = int(m.group(2))
            continue
        m = FAILED.search(line)
        if m and len(u["failed"]) < 5:
            u["failed"].append(line.strip())
    return units


def ok(u):
    return u["rc"] == 0 and u["failures"] == 0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    show_all = "--all" in sys.argv
    if len(args) < 2:
        print(__doc__)
        sys.exit(2)
    wins, vm = [parse(a) for a in args[:-1]], parse(args[-1])
    names = set(vm).union(*wins)
    groups = defaultdict(list)
    for name in sorted(names):
        ws = [w.get(name) for w in wins]
        w, v = ws[0], vm.get(name)
        if name in RUNNER_UNRELIABLE:
            groups["unreliable"].append((name, w, v, RUNNER_UNRELIABLE[name]))
        elif not all(ws) or not v:
            groups["missing"].append((name, w, v))
        elif len({ok(x) for x in ws}) > 1:
            groups["unreliable"].append((name, w, v, "Windows images disagree"))
        elif any(x["executed"] == 0 for x in ws) and v["executed"]:
            groups["unreliable"].append((name, w, v, "0 checks run on Windows"))
        elif not all(ok(x) for x in ws):
            groups["windows"].append((name, w, v))
        elif not ok(v):
            groups["diverges"].append((name, w, v))
        elif v["todo"]:
            groups["todo"].append((name, w, v))
        else:
            groups["match"].append((name, w, v))

    print(f"{len(wins[0])} units on Windows ({len(wins)} images), {len(vm)} on vermouth")
    for g in ("match", "diverges", "todo", "windows", "unreliable", "missing"):
        print(f"  {g:9} {len(groups[g])}")

    print("\nDiverges from Windows (work list), most failures first:")
    for name, w, v in sorted(groups["diverges"], key=lambda e: -e[2]["failures"]):
        why = "crash/timeout rc=%s" % v["rc"] if v["rc"] not in (0, None) and not v["failures"] else f"{v['failures']} failures"
        print(f"  {name:40} {why}")
        for f in v["failed"][:3]:
            print(f"      {f}")
    print("\nPasses only through todo_wine (known gaps), most todos first:")
    for name, w, v in sorted(groups["todo"], key=lambda e: -e[2]["todo"])[: None if show_all else 40]:
        print(f"  {name:40} {v['todo']} todo")
    print("\nNo usable Windows answer (not counted either way):")
    for name, w, v, why in groups["unreliable"]:
        print(f"  {name:40} {why}")
    if show_all:
        for g in ("windows", "missing"):
            print(f"\n{g}:")
            for name, w, v in groups[g]:
                print(f"  {name}")


if __name__ == "__main__":
    main()
