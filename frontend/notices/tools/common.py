"""Shared helpers for the notice evidence tools. Standard library only (Python >= 3.9)."""
import hashlib, io, json, os, re, subprocess, sys, tarfile, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
NOTICES = os.path.dirname(HERE)
UA = {"User-Agent": "odos-notice-evidence"}


def sha(data, algo="sha256"):
    return hashlib.new(algo, data).hexdigest()


class Lock:
    """Provenance register written to sources.lock.json: every image, download and archive the evidence was taken from, with checksums."""

    def __init__(self):
        self.images, self.downloads, self.notes = {}, {}, {}

    def image(self, key, info):
        self.images[key] = info

    def download(self, url, data, used_for, expected=None):
        algo = expected[0] if expected else "sha256"
        self.downloads[url] = {"bytes": len(data), algo: sha(data, algo), "usedFor": used_for}
        if expected:
            self.downloads[url]["checksumSource"] = expected[2]
            self.downloads[url]["verified"] = sha(data, algo) == expected[1]

    def save(self, path):
        out = {"images": self.images, "downloads": dict(sorted(self.downloads.items())), "notes": self.notes}
        with open(path, "w") as f:
            json.dump(out, f, indent=1, sort_keys=True)
            f.write("\n")

    @staticmethod
    def load(path):
        l = Lock()
        if os.path.exists(path):
            d = json.load(open(path))
            l.images, l.downloads, l.notes = d.get("images", {}), d.get("downloads", {}), d.get("notes", {})
        return l


def http(url, cache_dir=None, retries=6, headers=None):
    """GET url (bytes). Results are cached on disk by URL so reruns do not download again."""
    path = None
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        path = os.path.join(cache_dir, sha(url.encode())[:32])
        if os.path.exists(path):
            return open(path, "rb").read()
    last = None
    for i in range(retries):
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers={**UA, **(headers or {})}), timeout=300).read()
            if path:
                open(path + ".part", "wb").write(data)
                os.replace(path + ".part", path)
            return data
        except urllib.error.HTTPError as e:
            if e.code in (404, 403, 410):
                raise
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(3 * (i + 1))  # servers answer 5xx or reset connections under load; back off and retry
    raise last


def docker(args, input_bytes=None):
    r = subprocess.run(["docker"] + args, input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise RuntimeError("docker %s failed: %s" % (" ".join(args[:6]), r.stderr.decode(errors="replace")[:300]))
    return r.stdout


def image_run(image, cmd, input_bytes=None, entrypoint="sh"):
    """Run a shell command inside an existing image (read-only use) and return stdout bytes."""
    a = ["run", "--rm"] + (["-i"] if input_bytes is not None else []) + ["--entrypoint", entrypoint, image]
    return docker(a + (["-c", cmd] if entrypoint == "sh" else cmd), input_bytes)


def image_info(image):
    d = json.loads(docker(["image", "inspect", image]))[0]
    return {"image": image, "id": d["Id"], "architecture": d["Architecture"] + "/" + d["Os"], "repoDigests": d.get("RepoDigests") or []}


def untar(data, dest):
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        try:
            tf.extractall(dest, filter="data")  # Python >= 3.12
        except TypeError:
            tf.extractall(dest)


def tar_members(data, mode="r:*"):
    """Yield (name, TarInfo, tarfile) for a tar archive held in memory; names are returned without their first path component."""
    tf = tarfile.open(fileobj=io.BytesIO(data), mode=mode)
    return tf


def read_text(path):
    try:
        return open(path, encoding="utf-8").read()
    except (UnicodeDecodeError, FileNotFoundError):
        return None


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data)


def leading_comment(text):
    """The exact leading comment of a source file: the comment blocks at the top (/* ... */ or consecutive // or # lines), up to and including the first
    block that carries a copyright line (a title comment is often followed by the copyright block); the first block alone if none does."""
    t = text.lstrip("\ufeff")
    pos, blocks = 0, []
    doc = re.match(r'\s*("""|\'\'\')', t)  # a module docstring may come before the copyright comment (Python)
    if doc:
        close = t.find(doc.group(1), doc.end())
        if close >= 0:
            pos = close + 3
    while len(blocks) < 4:
        m = re.compile(r"\s*").match(t, pos); start = m.end()
        if t.startswith("/*", start):
            end = t.find("*/", start)
            if end < 0:
                break
            end += 2
        elif t.startswith(("//", "#"), start):
            end = start
            while True:
                nl = t.find("\n", end)
                line = t[end: nl if nl >= 0 else len(t)]
                if not re.match(r"\s*(#|//)", line) and not (end == start and line.startswith("#!")):
                    break
                end = nl + 1 if nl >= 0 else len(t)
                if nl < 0:
                    break
            end = max(end, start)
            if end == start:
                break
        else:
            break
        blocks.append((start, end))
        if re.search(r"copyright|\(c\) ?\d{4}|\u00a9", t[start:end], re.I):
            return t[: end].rstrip("\n") if t[:end].strip() else None
        pos = end
    return t[: blocks[0][1]].rstrip("\n") if blocks else None


def log(*a):
    print(*a, file=sys.stderr, flush=True)
