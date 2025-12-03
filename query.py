#!/usr/bin/env python3
"""Query GOES flares from HEK and save them to a TSV cache."""

import sys
import re
import datetime as dt
from typing import NoReturn

from sunpy.net import Fido, attrs as a


def die(msg: str) -> NoReturn:
  print(msg)
  sys.exit(1)


def fmt_iso(val) -> str:
  """Return original ISO-ish time string (keep T/Z), or empty when missing."""
  if not val:
    return ""
  return getattr(val, "isot", str(val))


def fmt_human(val) -> str:
  """Human-friendly time: drop fractional seconds and trailing Z, replace T with space."""
  if not val:
    return ""
  s = getattr(val, "isot", str(val))
  s = s.rstrip("Z").replace("T", " ")
  if "." in s:
    s = s.split(".", 1)[0]
  return s


def goes_score(cls: str) -> float:
  """Return a sortable numeric score for GOES class (higher = stronger)."""
  if not cls:
    return -1.0
  m = re.match(r"\s*([A-Za-z])\s*([0-9.]+)?", cls)
  if not m:
    return -1.0
  letter = m.group(1).upper()
  mag = float(m.group(2) or 0.0)
  scale = {"A": 1e-8, "B": 1e-7, "C": 1e-6, "M": 1e-5, "X": 1e-4}.get(letter)
  if scale is None:
    return -1.0
  return scale * mag


def main() -> None:
  args = sys.argv[1:]
  if len(args) not in (5, 6):
    die("usage: query.py START END CMP CLASS WAVE [OUTFILE]")

  t0, t1, cmp_sym, flare = args[0], args[1], args[2], args[3].upper()
  wave = args[4]
  outpath = args[5] if len(args) == 6 else "flare_cache.tsv"

  if cmp_sym.lower() == "all":
    cmp_sym = "All"

  base = a.hek.FL.GOESCls
  cmp_attr = {
    ">": base > flare,
    ">=": base >= flare,
    "==": base == flare,
    "=": base == flare,
    "<=": base <= flare,
    "<": base < flare,
    "All": base >= "A0.0",
  }.get(cmp_sym)
  if cmp_attr is None:
    die(f"unsupported comparator: {cmp_sym}")

  hek = Fido.search(
    a.Time(dt.datetime.fromisoformat(t0), dt.datetime.fromisoformat(t1)),
    a.hek.EventType("FL"),
    cmp_attr,
    a.hek.OBS.Observatory == "GOES",
  )["hek"]

  events = sorted(hek, key=lambda ev: goes_score(ev.get("fl_goescls")), reverse=True)

  with open(outpath, "w", encoding="utf-8") as f:
    f.write("description\tflare_class\tstart\tend\tcoordinates\twavelength\n")
    for ev in events:
      s = ev.get("event_starttime")
      e = ev.get("event_endtime")
      x = ev.get("hpc_x", "")
      y = ev.get("hpc_y", "")
      cls = (ev.get("fl_goescls") or "").strip()
      start_s = fmt_iso(s)
      end_s = fmt_iso(e) or start_s
      desc = f"{cls or 'Unknown'} flare occurred at {fmt_human(s)} and ended at {fmt_human(e) or fmt_human(s)}"
      coords = f"({x},{y})"
      f.write(f"{desc}\t{cls}\t{start_s}\t{end_s}\t{coords}\t{wave}\n")


if __name__ == "__main__":
  main()
