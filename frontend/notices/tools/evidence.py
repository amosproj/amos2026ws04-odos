#!/usr/bin/env python3
"""Collect the license and copyright evidence behind frontend/notices/notices.json into a (gitignored) evidence folder, then run the collector.

  python3 notices/tools/evidence.py [steps...] [--out DIR] [--cache DIR]      steps: images npm extras (default: all, in that order)

Needs: Python >= 3.9, network access and the backend Docker image (docker compose build). The image is only read. Every download is checksum-verified where the source publishes a checksum, and recorded in notices/sources.lock.json.
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extras, images, npm  # noqa: E402
from common import Lock, NOTICES, log  # noqa: E402

STEPS = ["images", "npm", "extras"]


class Ctx:
    pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("steps", nargs="*", default=STEPS)
    ap.add_argument("--out", default=os.path.join(NOTICES, ".evidence"))
    ap.add_argument("--cache", default=None, help="download cache (default: <out>/cache)")
    ap.add_argument("--lock", default=os.path.join(NOTICES, "sources.lock.json"))
    ap.add_argument("--image", action="append", default=[], metavar="KEY=IMAGE", help="override the image: backend=IMAGE")
    a = ap.parse_args()
    c = Ctx()
    c.out = os.path.abspath(a.out); c.cache = os.path.abspath(a.cache or os.path.join(c.out, "cache"))
    c.repo = os.path.dirname(os.path.dirname(NOTICES)); c.lock = Lock.load(a.lock) if set(a.steps) != set(STEPS) else Lock()
    c.images = dict(images.IMAGES); c.images.update(dict(x.split("=", 1) for x in a.image))
    c.extra_dir = os.path.join(c.out, "extra"); c.extra_files = os.path.join(c.extra_dir, "files"); c.extras = []
    os.makedirs(c.extra_files, exist_ok=True)
    parts = os.path.join(c.extra_dir, "parts")
    for s in a.steps:
        log("== step", s)
        before = len(c.extras)
        {"images": images.run, "npm": npm.run, "extras": extras.run}[s](c)
        if s != "extras":  # each step keeps the evidence entries it contributed, so steps can be rerun one at a time
            os.makedirs(parts, exist_ok=True)
            json.dump(c.extras[before:], open(os.path.join(parts, s + ".json"), "w"), indent=1, sort_keys=True)
    c.lock.save(a.lock)
    log("evidence in", c.out, "| provenance register:", a.lock)


if __name__ == "__main__":
    main()
