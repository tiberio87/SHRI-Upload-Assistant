"""
Generic Tracker Test Suite

Tests tracker name generation logic across different trackers.

Usage:
    python test_tracker.py SHRI                            # Test mock data only
    python test_tracker.py BASE generated_meta_file.json   # Test file only
    python test_tracker.py SHRI meta.json --with-mocks     # Test file + mocks
"""

import sys
import json
import asyncio
import os
from src.trackers.SHRI import SHRI
from src.trackers.AITHER import AITHER
from src.trackers.BLU import BLU


class BaseTracker:
    """Shows Upload Assistant's original name generation without tracker customization"""

    def __init__(self, config):
        pass

    async def get_name(self, meta):
        from src.get_name import get_name

        required_fields = {
            "manual_year": 0,
            "category": "MOVIE",
            "no_season": False,
            "no_year": False,
            "no_aka": False,
            "edition": "",
            "debug": False,
        }

        for key, default_value in required_fields.items():
            meta.setdefault(key, default_value)

        try:
            name_notag, name, clean_name, potential_missing = await get_name(meta)
            return {"name": name}
        except Exception as e:
            print(f"[ERROR] get_name() failed: {e}")
            import traceback

            traceback.print_exc()
            return {"name": meta.get("name", "ERROR")}


TRACKER_MAP = {
    "SHRI": SHRI,
    "BASE": BaseTracker,
    "AITHER": AITHER,
    "BLU": BLU,
    # Add more: "HUNO": HUNO, "RED": RED, etc.
}


def get_mock_test_cases(json_file="mock_test_cases.json"):
    if os.path.exists(json_file):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARNING] Failed to load {json_file}: {e}")

    return [
        {
            "desc": "UNTOUCHED detection",
            "filename": "Movie.1998.UNTOUCHED.1080p.BluRay.AVC-Group.mkv",
            "meta": {
                "name": "Movie 1998 UNTOUCHED 1080p BluRay DD 5.1 AVC-Group",
                "type": "REMUX",
                "resolution": "1080p",
                "video_codec": "AVC",
                "source": "BluRay",
                "audio": "DD 5.1",
                "year": "1998",
                "title": "Movie",
                "tag": "-Group",
            },
        }
    ]


def load_generated_meta(json_file=None, overrides=None):
    if json_file is None:
        json_file = "generated_meta.json"

    if not os.path.exists(json_file):
        return None

    try:
        with open(json_file, "r", encoding="utf-8") as f:
            real_meta = json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to parse {json_file}: {e}")
        return None

    if overrides:
        real_meta.update(overrides)

    # Handle empty filelist or missing path
    filelist = real_meta.get("filelist", [])
    if filelist and len(filelist) > 0:
        filename = os.path.basename(filelist[0])
    else:
        path = real_meta.get("path", "unknown.mkv")
        filename = os.path.basename(path)

    return {
        "desc": f"Generated meta from {os.path.basename(json_file)}",
        "filename": filename,
        "meta": real_meta,
    }


async def run_test(test_case, tracker_instance, tracker_name):
    meta = test_case["meta"].copy()

    defaults = {
        "filelist": [test_case["filename"]],
        "path": test_case["filename"],
        "video_encode": "x264",
        "is_disc": False,
        "language_checked": True,
        "audio_languages": ["ENG"],
        "dual_audio": False,
    }

    for key, value in defaults.items():
        meta.setdefault(key, value)

    result = await tracker_instance.get_name(meta)

    if not isinstance(result, dict) or "name" not in result:
        print(f"[ERROR] Invalid result structure from {tracker_name}.get_name()")
        print(f"Result: {result}")
        return

    print(f"Tracker: {tracker_name}")
    print(f"Test: {test_case['desc']}")
    print(f"File: {test_case['filename']}")
    print(f"In:   {meta['name']}")
    print(f"Out:  {result['name']}")
    print()


async def test_tracker():
    if len(sys.argv) < 2:
        print(
            "Usage: python test_tracker.py TRACKER_NAME [meta_file.json] [--with-mocks]"
        )
        print(f"Available trackers: {', '.join(TRACKER_MAP.keys())}")
        sys.exit(1)

    tracker_name = sys.argv[1].upper()
    meta_file = None
    include_mocks = False

    for arg in sys.argv[2:]:
        if arg == "--with-mocks":
            include_mocks = True
        elif not arg.startswith("--"):
            meta_file = arg

    if tracker_name not in TRACKER_MAP:
        print(f"[ERROR] Unknown tracker: {tracker_name}")
        print(f"Available: {', '.join(TRACKER_MAP.keys())}")
        sys.exit(1)

    config = {"TRACKERS": {tracker_name: {"use_italian_title": True}}}
    tracker_class = TRACKER_MAP[tracker_name]
    tracker_instance = tracker_class(config)

    test_cases = []

    generated = load_generated_meta(json_file=meta_file)
    if generated:
        test_cases.append(generated)
        if include_mocks:
            test_cases.extend(get_mock_test_cases())
            print("[INFO] Also including mock test cases")
            print()
    else:
        if meta_file:
            print(f"[ERROR] File not found or invalid: {meta_file}")
            sys.exit(1)
        print("[INFO] No metadata file provided, using mock data only\n")
        test_cases.extend(get_mock_test_cases())

    for test_case in test_cases:
        await run_test(test_case, tracker_instance, tracker_name)


if __name__ == "__main__":
    asyncio.run(test_tracker())
