"""Deprecated wrapper for :mod:`event_aoi_area`."""

import sys

from event_aoi_area import main


if __name__ == "__main__":
    print("NOTE: district_area.py is deprecated; using state-level event_aoi_area.py")
    main(sys.argv[1:])
