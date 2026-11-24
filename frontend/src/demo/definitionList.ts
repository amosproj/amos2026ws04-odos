// The explicit enumeration in a definition's text, for display only. A definition like "… erfüllen: 1. Hochhäuser …; 2. bauliche
// Anlagen …" or "… eingeteilt: Gebäudeklasse 1: a) … und b) …; Gebäudeklasse 2: …" is split at its own markers, which must run
// in sequence (1., 2., 3. … / <Word> 1:, <Word> 2: … / a), b), c) …). Nothing is added or dropped: the intro plus every item's
// text is the whole text, cut only at the markers. When no such sequence is found, the text stays as it is.

export interface DefItem { marker: string; text: string; items?: DefItem[] }
export interface DefList { intro: string; items: DefItem[] }

interface Kind {
  /** The marker of item n (1-based), as a regex source. */
  marker: (n: number) => string;
  /** What must end the text before a marker (start of text, or a separator the source uses between items). */
  before: RegExp;
}

const LETTERS = "abcdefghijklmnopqrstuvwxyz";
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const NUMBERED: Kind = { marker: (n) => `${n}\\.`, before: /(^|[:;])\s*$/ };
const LETTERED: Kind = { marker: (n) => `${LETTERS[n - 1]}\\)`, before: /(^|[:;,]|\b(?:und|oder|and|or|sowie))\s*$/u };
const labelled = (label: string): Kind => ({ marker: (n) => `${esc(label)} ${n}:`, before: /(^|[:;])\s*$/ });

/** The positions of markers 1, 2, 3 … of one kind, in order; fewer than two means no list. */
function find(text: string, kind: Kind): Array<{ start: number; end: number; marker: string }> {
  const found: Array<{ start: number; end: number; marker: string }> = [];
  let from = 0;
  for (let n = 1; n <= LETTERS.length; n++) {
    const re = new RegExp(`(?<![\\p{L}\\p{N}])${kind.marker(n)}(?=\\s)`, "gu");
    re.lastIndex = from;
    let m: RegExpExecArray | null;
    let hit: RegExpExecArray | null = null;
    while ((m = re.exec(text))) {
      if (kind.before.test(text.slice(0, m.index))) { hit = m; break; }
    }
    if (!hit) break;
    found.push({ start: hit.index, end: hit.index + hit[0].length, marker: hit[0].replace(/:$/, "") });
    from = hit.index + hit[0].length;
  }
  return found.length >= 2 ? found : [];
}

function cut(text: string, kinds: Kind[]): { intro: string; items: Array<{ marker: string; text: string }> } | null {
  for (const kind of kinds) {
    const at = find(text, kind);
    if (at.length === 0) continue;
    return {
      intro: text.slice(0, at[0].start).trim(),
      items: at.map((m, i) => ({ marker: m.marker, text: text.slice(m.end, i + 1 < at.length ? at[i + 1].start : text.length).trim() })),
    };
  }
  return null;
}

/** A label used as "<Label> 1: … ; <Label> 2: …" (e.g. "Gebäudeklasse 1:", "Class 1:"). */
function labels(text: string): Kind[] {
  const m = /(?:^|[:;]\s*)(\p{Lu}[\p{L}-]{2,}) 1:\s/u.exec(text);
  return m ? [labelled(m[1])] : [];
}

/** The definition's enumeration, or null when the text has none that can be split reliably. */
export function parseDefinitionList(text: string): DefList | null {
  const top = cut(text, [NUMBERED, ...labels(text), LETTERED]);
  if (!top) return null;
  return {
    intro: top.intro,
    items: top.items.map((it) => {
      const sub = cut(it.text, [LETTERED]);
      return sub ? { ...it, text: sub.intro, items: sub.items } : it;
    }),
  };
}

/** Long enough to need its own scroll area. */
export const LONG_DEFINITION = 420;
