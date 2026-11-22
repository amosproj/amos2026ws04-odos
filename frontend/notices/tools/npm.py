"""Step `npm`: license files of every package in package-lock.json, taken from the registry tarballs the lockfile pins (integrity verified)."""
import base64, json, os, re, tarfile, io
from common import http, log, sha, write

LICENSE_FILE = re.compile(r"^(licen[sc]e|copying|notice|unlicense|third[-_]?party[-_]?(licen[sc]es?|notices?))\d*([._-].*)?$", re.I)


def lock_packages(repo):
    pl = json.load(open(os.path.join(repo, "frontend", "package-lock.json")))
    out = {}
    for k, v in pl["packages"].items():
        if k.startswith("node_modules/") and v.get("resolved"):
            out[k.split("node_modules/")[-1]] = v
    return out


def run(ctx):
    pk = lock_packages(ctx.repo)
    dest = os.path.join(ctx.out, "npm")
    no_license = []
    for i, (name, v) in enumerate(sorted(pk.items()), 1):
        data = http(v["resolved"], ctx.cache)
        algo, b64 = v["integrity"].split("-", 1)
        hexd = base64.b64decode(b64).hex()
        ctx.lock.download(v["resolved"], data, "npm " + name + " " + v["version"], (algo, hexd, "package-lock.json integrity"))
        if sha(data, algo) != hexd:
            raise SystemExit("integrity mismatch for %s" % name)
        n = 0
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            for m in tf:
                parts = m.name.split("/")
                if m.isfile() and len(parts) == 2 and LICENSE_FILE.match(parts[1]):
                    write(os.path.join(dest, name, parts[1]), tf.extractfile(m).read()); n += 1
        write(os.path.join(dest, name, "package.json"), json.dumps({"name": name, "version": v["version"]}))
        if not n:
            no_license.append((name, v["version"]))
        if i % 20 == 0:
            log("npm: %d/%d" % (i, len(pk)))
    write(os.path.join(dest, "_without_license.json"), json.dumps(no_license))
    log("npm: %d packages, %d without a license file in the tarball" % (len(pk), len(no_license)))
