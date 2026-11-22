# SBOM and third-party notices

ODOS ships a Software Bill of Materials (`../../sbom.spdx.json`, SPDX 2.3 JSON) and a **Legal Notices** page (`#/legal`, linked from the footer on every screen) that lists the same inventory with its
licenses. This folder holds the evidence behind the license texts in `THIRD-PARTY-NOTICES.txt`. It is an academic deliverable, **not legal advice**.

## What the SBOM contains: 259 packages (2 project roots + 257 components)

| Ecosystem | Count | Source |
|---|---:|---|
| npm | 133 | every package in `frontend/package-lock.json`, including transitive ones (115 development-only, 59 optional/platform-specific) |
| Python | 118 | every pin in `backend/requirements.lock` (112 runtime, 4 development) plus `setuptools` and `websockets`, which the lock leaves out |
| Docker base images | 3 | `node:22-bookworm-slim`, `python:3.12-slim-bookworm`, `postgres:17-alpine`, by tag (no single license is assigned to an image) |
| apt packages | 3 | `libgl1`, `libglib2.0-0`, `fonts-liberation`, installed by `backend/Dockerfile` |

These are **inventory entries from lockfiles, not a list of what runs in production**: development tools and platform-specific optional packages are included and marked in each package's `comment`
(the linux/arm64 frontend image, for example, installs 79 of the 133 npm packages). `relationships` record which package depends on which.

**Deliberately excluded:** the operating-system packages and runtime software (Node.js, CPython, PostgreSQL, ...) inside the Docker images, Rust crates and libraries embedded in Python wheels, and packages
vendored inside other packages. The SBOM is the lockfile inventory, not a complete inventory of everything in the images.

## Legal Notices page

Shows the project copyright and license (a link to the repository's `LICENSE`, MIT), the academic-project disclaimer, the public repository link and a searchable, license-filterable table of exactly the SBOM's
257 components (name, version, license, type, source link). `THIRD-PARTY-NOTICES.txt`, linked from the page and generated at build time, reproduces the license and copyright files of those components.
The page is built from `sbom.spdx.json`, so replacing the SBOM changes it on the next build.

## Files

| Path | Purpose |
|---|---|
| `notices.json` | The notice store: one entry per SBOM component (stored license/copyright files, where they come from), each text stored once by hash. |
| `sources.lock.json` | Provenance register: the Docker image used and every download with its checksum. |
| `regenerate.sh`, `tools/` | Rebuild the store (below). Python >= 3.9, standard library only. |
| `../scripts/check-sbom.mjs` | Consistency check: SBOM against the lockfiles, Dockerfiles, relationships, identities. |
| `../scripts/verify-notices.mjs` | Integrity check of the store against the SBOM and the register. |
| `../scripts/collect-notices.mjs`, `license-check.mjs` | Build the store from the evidence; check that a stored text really is the license a component declares. |

A store entry is `VERIFIED_FULL_TEXT` (the stored files hold the declared license text), `VERIFIED_METADATA_ONLY` or `UNRESOLVED`; only full text counts as a notice. Current result
(`node scripts/verify-notices.mjs`): **254 of 257 components with verified full text**; the other three are the composite Docker images, for which no single license exists.

## Regenerate

```bash
cd frontend
sh notices/regenerate.sh      # Python >= 3.9, Node >= 22.18, network, and the backend image (`docker compose build`); about 0.5 GB of npm tarballs, cached
git diff                      # shows exactly what changed
```

It reads the backend image (never builds or modifies it), downloads the registry tarballs `package-lock.json` pins (checked against the lockfile's sha512) and a few upstream license files pinned to a version or commit,
rebuilds `notices.json` and `sources.lock.json`, then runs the two checks below.

**Updating the SBOM when a lockfile changes.** `sbom.spdx.json` is a committed file. When `package-lock.json`, `requirements.lock` or a Dockerfile changes, `node scripts/check-sbom.mjs` (and CI) fails and names what to
add, change or remove in `sbom.spdx.json`: versions and development/runtime scope come from the lockfiles, licenses of new Python packages from PyPI metadata. Then run `sh notices/regenerate.sh`, and
`pyspdxtools -i sbom.spdx.json` (`pip install spdx-tools`) to validate the SPDX schema.

## CI

The frontend job runs `npm run typecheck`, `npm test` and `npm run build`. The tests include `src/legal/sbom.consistency.test.ts` (the same checks as `check-sbom.mjs`; the page lists exactly the SBOM),
`src/legal/notices.verify.test.ts` (the same checks as `verify-notices.mjs`) and `src/App.test.tsx` (one footer on every screen, `#/legal` routing, the 257-row table, search and license filter), so a lockfile change
without a matching SBOM or store update fails CI. The Docker builds receive `sbom.spdx.json` through the `repo` build context.

## Limitations

* Not legal advice. Reproducing a license text does not discharge obligations such as source access or relinking (for example LGPL `psycopg`, MPL-2.0 `certifi`, `lightningcss`); `THIRD-PARTY-NOTICES.txt` lists the components that need review.
* Copyright attribution is evidenced for 253 of 257 components; not for the three Docker images and for `certifi` (its package carries only an MPL notice, no copyright text). Nothing is fabricated.
* Evidence is version-exact; an entry for another version is never used. Python and Debian evidence comes from the linux/arm64 backend image.
