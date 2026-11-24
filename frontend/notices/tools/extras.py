"""Step `extras`: evidence that does not come from an installed package or a lockfile - upstream release tags for packages that ship no license file,
the Debian cases whose copyright files refer to files outside themselves, files bundled inside Python distributions, installed-file copyright headers
and the standard license texts. Every recipe is pinned to an exact version; if the version in the images changes, the recipe is skipped and reported."""
import glob, io, json, os, tarfile, urllib.parse
from common import http, leading_comment, log, sha, write
import images

UPSTREAM_NPM = [("@napi-rs/canvas-", "Brooooooklyn/canvas"), ("@rolldown/binding-", "rolldown/rolldown"), ("saxes", "lddubeau/saxes")]
UPSTREAM_PY = {("docling", "2.143.0"): ("docling-project/docling", "v2.143.0"), ("latex2mathml", "3.81.1"): ("roniemartinez/latex2mathml", "3.81.1")}
PY_HEADERS = {"psycopg": "psycopg/__init__.py", "psycopg-binary": "psycopg_binary/__init__.py", "defusedxml": "defusedxml/__init__.py"}
STANDARD = [  # (SPDX ids, file in the image's /usr/share/common-licenses)
    (["MPL-2.0"], "MPL-2.0"), (["Apache-2.0"], "Apache-2.0"), (["GPL-2.0-only", "GPL-2.0-or-later"], "GPL-2"), (["GPL-3.0-only", "GPL-3.0-or-later"], "GPL-3"),
    (["LGPL-2.1-only", "LGPL-2.1-or-later"], "LGPL-2.1"), (["LGPL-2.0-only", "LGPL-2.0-or-later"], "LGPL-2"), (["LGPL-3.0-only", "LGPL-3.0-or-later"], "LGPL-3")]


def gh(path, ctx):
    try:
        return json.loads(http("https://api.github.com/" + path, ctx.cache, headers={"Accept": "application/vnd.github+json"}))
    except Exception:  # noqa: BLE001
        return None


def tag_commit(slug, tag, ctx):
    r = gh("repos/%s/git/ref/tags/%s" % (slug, urllib.parse.quote(tag)), ctx)
    if not r or "object" not in r:
        return None
    o = r["object"]
    if o["type"] == "tag":
        t = gh("repos/%s/git/tags/%s" % (slug, o["sha"]), ctx)
        return t["object"]["sha"] if t else o["sha"]
    return o["sha"]


def put(ctx, name, data):
    write(os.path.join(ctx.extra_files, name), data)
    return "files/" + name


def run(ctx):
    out = ctx.out
    parts = os.path.join(ctx.extra_dir, "parts")
    ctx.extras = []
    for s in ("npm",):  # entries contributed by the npm step (this run or an earlier one)
        p = os.path.join(parts, s + ".json")
        if os.path.exists(p):
            ctx.extras += json.load(open(p))
    nl = os.path.join(out, "npm", "_without_license.json")
    ctx.npm_without_license = json.load(open(nl)) if os.path.exists(nl) else []
    dists = {(n, v): d for d, n, name, v in images.python_dists(ctx)}
    # ---- upstream release tags for npm packages whose tarball ships no license file
    for name, version in ctx.npm_without_license:
        rule = next((s for p, s in UPSTREAM_NPM if name.startswith(p)), None)
        if not rule:
            log("extras: no upstream recipe for npm", name, version); continue
        meta = json.loads(http("https://registry.npmjs.org/%s/%s" % (urllib.parse.quote(name, safe="@"), version), ctx.cache))
        repo = meta.get("repository"); repo = repo.get("url", "") if isinstance(repo, dict) else (repo or "")
        if rule.lower() not in repo.lower() or meta.get("version") != version:
            log("extras: registry repository of", name, "does not match", rule); continue
        tag = "v" + version; url = "https://raw.githubusercontent.com/%s/%s/LICENSE" % (rule, tag)
        try:
            b = http(url, ctx.cache)
        except Exception:  # noqa: BLE001
            log("extras: no LICENSE at", url); continue
        ctx.lock.download(url, b, "upstream license of npm %s %s" % (name, version))
        c = tag_commit(rule, tag, ctx)
        ctx.extras.append({"kind": "npm", "name": name, "version": version, "evidence":
            "upstream repository %s, tag %s%s: %s (sha256 %s...). The npm package ships no license file; the npm registry's repository field names this repository and its version equals the tag" % (rule, tag, " = commit " + c if c else "", url, sha(b)[:16]),
            "files": [{"name": "LICENSE", "path": put(ctx, "upstream-%s-%s-LICENSE" % (name.replace("/", "_"), version), b)}]})
    # ---- Python distributions without a license file in the installed package
    for (name, version), (slug, tag) in UPSTREAM_PY.items():
        d = dists.get((name, version))
        if not d or glob.glob(os.path.join(out, "images/backend/site-packages", d, "licenses", "*")) or glob.glob(os.path.join(out, "images/backend/site-packages", d, "LICENSE*")):
            if not d: log("extras: Python recipe for", name, version, "skipped: that version is not installed")
            continue
        url = "https://raw.githubusercontent.com/%s/%s/LICENSE" % (slug, tag)
        b = http(url, ctx.cache); ctx.lock.download(url, b, "upstream license of PyPI %s %s" % (name, version))
        c = tag_commit(slug, tag, ctx)
        ctx.extras.append({"kind": "Python", "name": name, "version": version, "evidence":
            "upstream repository %s, tag %s%s: %s (sha256 %s...); the PyPI wheel and sdist of this version contain no license file" % (slug, tag, " = commit " + c if c else "", url, sha(b)[:16]),
            "files": [{"name": "LICENSE", "path": put(ctx, "upstream-%s-%s-LICENSE" % (name, version), b)}]})
    tok = next(((n, v, d) for (n, v), d in dists.items() if n == "tokenizers"), None)
    if tok and not glob.glob(os.path.join(out, "images/backend/site-packages", tok[2], "licenses", "*")):
        pj = json.loads(http("https://pypi.org/pypi/tokenizers/%s/json" % tok[1], ctx.cache))
        sd = next(u for u in pj["urls"] if u["packagetype"] == "sdist")
        data = http(sd["url"], ctx.cache)
        ctx.lock.download(sd["url"], data, "tokenizers %s sdist" % tok[1], ("sha256", sd["digests"]["sha256"], "PyPI release metadata"))
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:
            m = next(m for m in tf if m.name.endswith("/tokenizers/LICENSE") and m.name.count("/") == 2)
            b = tf.extractfile(m).read()
        ctx.extras.append({"kind": "Python", "name": "tokenizers", "version": tok[1], "evidence":
            "PyPI source distribution of the same version (sha256 verified against PyPI); file tokenizers/LICENSE of the Rust core crate in the sdist; the wheel contains no license file",
            "files": [{"name": "tokenizers/LICENSE", "path": put(ctx, "tokenizers-%s-sdist-LICENSE" % tok[1], b)}]})
    # ---- bundled license/notice files inside Python distributions (vendored packages, third-party notices)
    for (n, v), fl in sorted(images.bundled_python_files(ctx).items()):
        files = [{"name": rel, "path": put(ctx, "bundled-%s--%s" % (n, rel.replace("/", "__")), open(p, "rb").read())} for rel, p in fl]
        ctx.extras.append({"kind": "Python", "name": n, "version": v, "attach": True, "evidence":
            "license and notice files that %s %s ships inside its package directories (listed in its RECORD), from the installed distribution in the backend image" % (n, v), "files": files})
    # ---- copyright headers of installed files
    wanted = {n: p for n, p in PY_HEADERS.items() if any(k[0] == n for k in dists)}
    if wanted:
        dest = images.python_header_files(ctx, sorted(wanted.values()))
        for n, p in wanted.items():
            h = leading_comment(open(os.path.join(dest, p), errors="replace").read())
            v = next(k[1] for k in dists if k[0] == n)
            if h:
                ctx.extras.append({"kind": "Python", "name": n, "version": v, "attach": True, "evidence": "leading comment of %s in the installed %s %s (backend image)" % (p, n, v),
                                   "files": [{"name": "%s (copyright header)" % p, "path": put(ctx, "header-%s.txt" % n, h)}]})
    cl = os.path.join(out, "common-licenses")
    # ---- standard license texts (authoritative, attached by the collector only where a component's own files lack the declared license text)
    std = []
    for ids, fn in STANDARD:
        p = os.path.join(cl, fn)
        if os.path.exists(p):
            std.append({"ids": ids, "name": fn, "path": put(ctx, "standard-" + fn, open(p, "rb").read()), "source": "Debian common-licenses (base-files of the backend image); the authoritative standard text"})
    write(os.path.join(ctx.extra_dir, "standard.json"), json.dumps(std, indent=1))
    write(os.path.join(ctx.extra_dir, "extra.json"), json.dumps(ctx.extras, indent=1, sort_keys=True))
    log("extras: %d evidence entries, %d standard texts" % (len(ctx.extras), len(std)))
