#!/usr/bin/env python3
"""Query GOES flares from HEK and save them to a TSV cache."""

import sys
import datetime as dt
from typing import NoReturn

from sunpy.net import Fido, attrs as a


def die(msg: str) -> NoReturn:
  print(msg)
  sys.exit(1)


def fmt_time(val) -> str:
  """Format HEK time-like values without fractional seconds or trailing Z."""
  if not val:
    return ""
  s = getattr(val, "isot", str(val)).rstrip("Z").replace("T", " ")
  return s.split(".", 1)[0]


def main() -> None:
  args = sys.argv[1:]
  if len(args) not in (5, 6):
    die("usage: query.py START END CMP CLASS WAVE [OUTFILE]")

  t0, t1, cmp_sym, flare = args[0], args[1], args[2], args[3].upper()
  wave = args[4]
  outpath = args[5] if len(args) == 6 else "flare_cache.tsv"

  base = a.hek.FL.GOESCls
  cmp_attr = {
    ">": base > flare,
    ">=": base >= flare,
    "≥": base >= flare,
    "==": base == flare,
    "=": base == flare,
    "<=": base <= flare,
    "≤": base <= flare,
    "<": base < flare,
    "ALL": base >= "A0.0",
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

  with open(outpath, "w", encoding="utf-8") as f:
    f.write("description\tcoordinates\twavelength\n")
    for ev in hek:
      s = ev.get("event_starttime")
      e = ev.get("event_endtime")
      x = ev.get("hpc_x", "")
      y = ev.get("hpc_y", "")
      start_s = fmt_time(s)
      end_s = fmt_time(e) or start_s
      desc = f"{flare} flare occurred at {start_s} and ended at {end_s}"
      coords = f"({x},{y})"
      f.write(f"{desc}\t{coords}\t{wave}\n")


if __name__ == "__main__":
  main()
