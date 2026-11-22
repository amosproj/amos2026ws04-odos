/**
 * Does a set of stored license files actually contain the license(s) a component declares, and does it carry a copyright notice?
 * Used by collect-notices.mjs to decide the evidence status. It checks the stored TEXTS, never the identifiers alone:
 * an identifier, a URL or an apk/PyPI metadata field is not a notice.
 */

// A text marker per SPDX identifier: a phrase every copy of that license contains. Identifiers without a marker are reported as unverifiable.
const M = {
  "MIT": /Permission is hereby granted, free of charge/i,
  "X11": /Permission is hereby granted, free of charge/i,
  "MIT-CMU": /Permission to use, copy, modify,? and distribute this software and its documentation for any purpose and without fee/i,
  "ISC": /Permission to use, copy, modify,? (and\/or |and |or )?distribute this software for any purpose with or without fee/i,
  "0BSD": /Permission to use, copy, modify, and\/or distribute this software for any purpose with or without fee/i,
  "BSD-1-Clause": /Redistribution and use in source and binary forms/i,
  "BSD-2-Clause": /Redistribution and use in source and binary forms/i,
  "BSD-3-Clause": /Redistribution and use in source and binary forms/i,
  "BSD-3-Clause-Attribution": /Redistribution and use in source and binary forms/i,
  "BSD-4-Clause": /Redistribution and use in source and binary forms/i,
  "Apache-2.0": /Apache License\s+Version 2\.0/i,
  "GPL-2.0-only": /GNU GENERAL PUBLIC LICENSE\s+Version 2/i,
  "GPL-2.0-or-later": /GNU GENERAL PUBLIC LICENSE\s+Version 2/i,
  "GPL-3.0-only": /GNU GENERAL PUBLIC LICENSE\s+Version 3/i,
  "GPL-3.0-or-later": /GNU GENERAL PUBLIC LICENSE\s+Version 3/i,
  "LGPL-2.0-or-later": /GNU (LIBRARY|LESSER) GENERAL PUBLIC LICENSE\s+Version 2/i,
  "LGPL-2.1-or-later": /GNU LESSER GENERAL PUBLIC LICENSE\s+Version 2\.1/i,
  "LGPL-2.1-only": /GNU LESSER GENERAL PUBLIC LICENSE\s+Version 2\.1/i,
  "LGPL-3.0-only": /GNU LESSER GENERAL PUBLIC LICENSE\s+Version 3/i,
  // the license text itself (with its definitions section), not the short "subject to the terms of the Mozilla Public License, v. 2.0" notice
  "MPL-2.0": /Mozilla Public License,? (Version|v\.) ?2\.0.*?1\. Definitions/i,
  "Zlib": /This software is provided ['"]?as-is['"]?/i,
  "BSL-1.0": /Boost Software License/i,
  "Unlicense": /This is free and unencumbered software/i,
  "CC0-1.0": /CC0 1\.0 Universal|Creative Commons Zero/i,
  "ICU": /COPYRIGHT AND PERMISSION NOTICE \(ICU|ICU License/i,
  "Unicode-3.0": /UNICODE LICENSE|Unicode, Inc\./i,
  "OLDAP-2.8": /The OpenLDAP Public License\s+Version 2\.8/i,
  // the MIT Student Information Processing Board permission notice used by e2fsprogs lib/et (not the SPDX MIT text)
  "LicenseRef-MIT-SIPB": /Permission to use, copy, modify, and distribute this software and its documentation for any purpose is hereby granted, provided that the names of M\.I\.T\. and the M\.I\.T\. S\.I\.P\.B\./i,
  "PostgreSQL": /Permission to use, copy, modify, and distribute this software and its documentation for any purpose, without fee, and without a written agreement/i,
  "PSF-2.0": /PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2/i,
  "Artistic-2.0": /The Artistic License 2\.0/i,
  "Public-Domain": /public domain/i,
  "LicenseRef-Alpine-Public-Domain": /public domain/i,
};
// Exceptions that follow WITH: the text that proves the exception is written out.
const EXC = { "LLVM-exception": /LLVM Exceptions?/i, "GCC-exception-3.1": /GCC Runtime Library Exception/i };
// Licenses that require the copyright notice to be kept: their text without any copyright line is not a complete notice.
const NOTICE_REQUIRED = new Set(["MIT", "X11", "MIT-CMU", "ISC", "BSD-1-Clause", "BSD-2-Clause", "BSD-3-Clause", "BSD-3-Clause-Attribution", "BSD-4-Clause", "ICU", "Unicode-3.0", "OLDAP-2.8"]);

/** SPDX expression -> tree. Supports AND, OR, WITH and parentheses; identifiers are compared case-insensitively. */
export function parse(expr) {
  const tokens = expr.replace(/\(/g, " ( ").replace(/\)/g, " ) ").trim().split(/\s+/).filter(Boolean);
  let i = 0;
  const atom = () => {
    const t = tokens[i++];
    if (t === "(") { const n = or(); i++; return n; }
    if (tokens[i]?.toUpperCase() === "WITH") { i++; return { id: t, exception: tokens[i++] }; }
    return { id: t };
  };
  const and = () => { const l = [atom()]; while (tokens[i]?.toUpperCase() === "AND") { i++; l.push(atom()); } return l.length > 1 ? { and: l } : l[0]; };
  const or = () => { const l = [and()]; while (tokens[i]?.toUpperCase() === "OR") { i++; l.push(and()); } return l.length > 1 ? { or: l } : l[0]; };
  return or();
}

const marker = (id) => Object.entries(M).find(([k]) => k.toLowerCase() === id.toLowerCase())?.[1];
const exception = (id) => Object.entries(EXC).find(([k]) => k.toLowerCase() === id.toLowerCase())?.[1];

/** Is the license text for every required identifier present in `text`? OR needs one alternative, AND needs all. */
export function evaluate(expr, rawText) {
  const text = rawText.replace(/\s+/g, " "); // phrases wrap across lines
  const present = new Set(), missing = new Set(), unverifiable = new Set(), notice = new Set();
  const leaf = (n) => {
    const m = marker(n.id);
    if (!m) { unverifiable.add(n.id); return null; }
    const ok = m.test(text) && (!n.exception || (exception(n.exception) ? exception(n.exception).test(text) : null) !== false);
    if (n.exception && !exception(n.exception)) unverifiable.add(`${n.id} WITH ${n.exception}`);
    (ok ? present : missing).add(n.id + (n.exception ? ` WITH ${n.exception}` : ""));
    if (ok && NOTICE_REQUIRED.has(n.id)) notice.add(n.id);
    return ok;
  };
  // returns true/false, or null when it cannot be decided from texts (an unverifiable identifier)
  const walk = (n) => {
    if (n.id) return leaf(n);
    const r = n.and ? n.and.map(walk) : n.or.map(walk);
    if (n.and) return r.includes(false) ? false : r.includes(null) ? null : true;
    return r.includes(true) ? true : r.includes(null) ? null : false;
  };
  const satisfied = walk(parse(expr));
  return { satisfied, present: [...present], missing: [...missing], unverifiable: [...unverifiable], noticeRequired: [...notice] };
}

/** Does any file carry a real copyright notice line? Placeholders, generic license wording and the FSF's own license-text copyright do not count. */
export function hasAttribution(files) {
  const line = /^[\s*#/;>|-]*(copyright\b|\(c\)|©)/i;
  const notAHolder = /copyright (notice|holders?|owners?|law|statement|and permission)|\[(yyyy|year)\]|<year>|yyyy|name of copyright owner|copyright and related/i;
  return files.some((f) => {
    if (/GNU (LESSER |LIBRARY )?GENERAL PUBLIC LICENSE|GNU FREE DOCUMENTATION LICENSE/.test(f.text.slice(0, 400))) return false;
    // a line that starts with the notice, or one that carries it after a few words ("Portions Copyright (c) 1996-2025 ...", "Debian support files Copyright (C) 2006 ...")
    return f.text.split("\n").some((l) => (line.test(l) || /\bcopyright\b.{0,60}\b(19|20)\d\d\b/i.test(l)) && !notAHolder.test(l));
  });
}
