"""Step `images`: read the Python distributions and the Debian copyright files out of the backend Docker image (the image is only read, never built or modified)."""
import os, re, shutil
from common import image_info, image_run, log, untar, write

IMAGES = {"backend": "amos2026ws04-odos-next-backend:latest"}
SITE = "/usr/local/lib/python3.12/site-packages"
DPKG_FORMAT = "${Package}\t${Version}\t${Architecture}\n"
LIC = re.compile(r"(^|/)(licen[sc]es?|copying|notice)([._-][^/]*)?$|(^|/)(licen[sc]es?|copying)[^/]*$", re.I)


def run(ctx):
    out = os.path.join(ctx.out, "images", "backend")
    img = ctx.images["backend"]
    ctx.lock.image("backend", image_info(img))
    write(os.path.join(out, "dpkg.tsv"), image_run(img, ["-W", "-f", DPKG_FORMAT], entrypoint="dpkg-query"))
    log("images: copyright files")
    untar(image_run(img, "cd /usr/share/doc && tar -cf - */copyright 2>/dev/null"), os.path.join(out, "doc"))
    untar(image_run(img, "tar -C /usr/share/common-licenses -cf - ."), os.path.join(out, "common-licenses"))
    log("images: python distributions")
    untar(image_run(img, "cd %s && tar -cf - *.dist-info" % SITE), os.path.join(out, "site-packages"))
    # the collector reads one folder per Debian package: <pkg>/{version,copyright}
    for line in open(os.path.join(out, "dpkg.tsv")):
        n, v = line.rstrip("\n").split("\t")[:2]
        src = os.path.join(out, "doc", n, "copyright")
        if os.path.exists(src):
            os.makedirs(os.path.join(ctx.out, "debian", n), exist_ok=True)
            shutil.copy(src, os.path.join(ctx.out, "debian", n, "copyright"))
            write(os.path.join(ctx.out, "debian", n, "version"), v)
    shutil.rmtree(os.path.join(ctx.out, "common-licenses"), ignore_errors=True)
    shutil.copytree(os.path.join(out, "common-licenses"), os.path.join(ctx.out, "common-licenses"))


def python_dists(ctx):
    """(dist-info directory, normalised name, name, version) of every installed Python distribution."""
    base = os.path.join(ctx.out, "images", "backend", "site-packages")
    for d in sorted(os.listdir(base)):
        if d.endswith(".dist-info"):
            meta = open(os.path.join(base, d, "METADATA"), errors="replace").read()
            name = re.search(r"^Name: (.+)$", meta, re.M).group(1).strip()
            ver = re.search(r"^Version: (.+)$", meta, re.M).group(1).strip()
            yield d, re.sub(r"[-_.]+", "-", name).lower(), name, ver


def bundled_python_files(ctx):
    """License/notice files an installed distribution ships OUTSIDE its own dist-info (vendored packages, third-party notices), found through its RECORD."""
    base = os.path.join(ctx.out, "images", "backend", "site-packages")
    want, per = [], {}
    for d, n, name, ver in python_dists(ctx):
        own = d + "/"
        paths = [l.split(",")[0] for l in open(os.path.join(base, d, "RECORD"), errors="replace")]
        sel = [p for p in paths if LIC.search(p) and not p.startswith(own) and (".dist-info/" not in p.split("/")[0] + "/" or "/_vendor/" in p)]
        sel = [p for p in sel if not p.split("/")[0].endswith(".dist-info")]
        if sel:
            per[(n, ver)] = sorted(set(sel)); want += per[(n, ver)]
    if not want:
        return {}
    dest = os.path.join(ctx.out, "images", "backend", "bundled")
    untar(image_run(ctx.images["backend"], "cd %s && tar -cf - -T -" % SITE, input_bytes=("\n".join(sorted(set(want))) + "\n").encode()), dest)
    return {k: [(p, os.path.join(dest, p)) for p in v if os.path.isfile(os.path.join(dest, p))] for k, v in per.items()}


def python_header_files(ctx, wanted):
    """Exact files from the installed distributions (for copyright headers): wanted = [relative path inside site-packages]."""
    dest = os.path.join(ctx.out, "images", "backend", "headers")
    untar(image_run(ctx.images["backend"], "cd %s && tar -cf - -T -" % SITE, input_bytes=("\n".join(wanted) + "\n").encode()), dest)
    return dest
