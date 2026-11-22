// A Rule JSON 2.0 record in plain language, for the review page. Deterministic and without a model: every part of the record
// that carries legal meaning (applicability, requirements, the requirement expression, the definition, exceptions and
// references) is turned into lines that state exactly the operators, values and units of the record. Nothing is summarised
// away, nothing is added. A part this formatter does not know is not guessed at: it is reported in `gaps`, the reading is
// marked incomplete and the page points to the complete structured rule. Fact names are shown as the record names them
// (underscores and dots read as spaces); they are not translated or interpreted.

export interface TextLine {
  text: string;
  /** The record's own wording for this part (a `description`), shown beside the exact statement, never instead of it. */
  note?: string;
  children?: TextLine[];
  /** Text the record itself could not express precisely (`unresolved`), or a part this formatter cannot show. */
  unclear?: boolean;
}

export interface TextBlock {
  key: "targets" | "actors" | "when" | "notWhen" | "requires" | "definition" | "exceptions" | "references";
  title: string;
  lines: TextLine[];
}

export interface ReadableRule {
  /** Plain-language name of `classification.type` ("Obligation", "Definition", …). */
  kind: string;
  /** `classification.summary`: the one-sentence summary written with the rule. */
  summary: string;
  blocks: TextBlock[];
  /** Parts of the record that could not be put into words; the reading is then not the complete rule. */
  gaps: string[];
  /** Parts the record itself marks as not precisely expressible (`unresolved`). */
  unresolved: number;
}

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : null);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const s = (v: unknown): string | undefined => (typeof v === "string" && v.trim() ? v : undefined);

export const KIND_LABEL: Record<string, string> = {
  definition: "Definition", obligation: "Obligation", prohibition: "Prohibition", permission: "Permission",
  conditional_requirement: "Conditional requirement", procedural_requirement: "Procedural requirement",
};

/** `fire_wall_height_above_roof` → "fire wall height above roof"; `building.height` → "building height". The name, not a translation. */
export const factName = (fact: unknown): string => (s(fact) ?? "(unnamed fact)").replace(/[_.]+/g, " ").trim();

const UNIT_SYMBOL: Record<string, string> = { m2: "m²", m3: "m³", cm2: "cm²", mm2: "mm²", Cel: "°C", deg: "°", "kN/m2": "kN/m²" };
/** The unit as it is printed; a code without a common symbol stays as written. `1` (dimensionless) prints nothing. */
export const unitText = (u: unknown): string => { const x = s(u); return !x || x === "1" ? "" : UNIT_SYMBOL[x] ?? x; };

const num = (v: unknown, unit?: unknown) => { const u = unitText(unit); return `${String(v)}${u ? ` ${u}` : ""}`; };
const scalar = (v: unknown): string => (typeof v === "string" ? `“${v}”` : typeof v === "boolean" ? (v ? "yes" : "no") : String(v));
const list = (items: string[], last: "and" | "or") => (items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} ${last} ${items[items.length - 1]}`);

const OPERATOR: Record<string, string> = {
  "==": "is", "!=": "is not", ">": "is more than", ">=": "is at least", "<": "is less than", "<=": "is at most",
  in: "is one of", not_in: "is none of", contains: "contains",
};

class Reader {
  gaps: string[] = [];
  unresolved = 0;

  gap(where: string, what: unknown): TextLine {
    const kind = s(obj(what)?.kind);
    this.gaps.push(kind ? `${where}: unknown kind “${kind}”` : where);
    return { text: "This part cannot be shown in plain language. See the complete rule under Advanced details.", unclear: true };
  }

  unresolvedLine(x: Obj): TextLine {
    this.unresolved += 1;
    return { text: s(x.text) ?? "(no text)", note: s(x.reason) ? `Not expressed as a precise check: ${x.reason as string}` : undefined, unclear: true };
  }

  // ── predicates (when a rule applies, exceptions) ─────────────────────────────────────────────────────────────────────
  predicate(p: unknown, where: string): TextLine {
    const x = obj(p);
    switch (x?.kind) {
      case "comparison": return { text: this.comparison(x) };
      case "all": return { text: "All of the following:", children: arr(x.conditions).map((c, i) => this.predicate(c, `${where} › ${i + 1}`)) };
      case "any": return { text: "At least one of the following:", children: arr(x.conditions).map((c, i) => this.predicate(c, `${where} › ${i + 1}`)) };
      case "not": return { text: "This is not the case:", children: [this.predicate(x.condition, `${where} › not`)] };
      case "unresolved": return this.unresolvedLine(x);
      default: return this.gap(where, p);
    }
  }

  comparison(x: Obj): string {
    const op = s(x.operator) ?? "";
    const fact = factName(x.fact);
    const v = x.value;
    if ((op === "==" || op === "!=") && typeof v === "boolean") return `${fact}: ${(op === "==") === v ? "yes" : "no"}`;
    const value = Array.isArray(v)
      ? list(v.map((item) => (typeof item === "number" ? num(item, x.unit) : scalar(item))), op === "in" ? "or" : "and")
      : typeof v === "number" ? num(v, x.unit) : scalar(v);
    return `${fact} ${OPERATOR[op] ?? `(${op})`} ${value}`;
  }

  /** The top predicate of a block, its `all` / `any` lifted into the block title so the conditions read as plain bullets. */
  predicateBlock(key: TextBlock["key"], p: unknown, title: { one: string; all: string; any: string }, where: string): TextBlock {
    const x = obj(p);
    if (x?.kind === "all" || x?.kind === "any") {
      return { key, title: x.kind === "all" ? title.all : title.any, lines: arr(x.conditions).map((c, i) => this.predicate(c, `${where} › ${i + 1}`)) };
    }
    return { key, title: title.one, lines: [this.predicate(p, where)] };
  }

  // ── requirements ─────────────────────────────────────────────────────────────────────────────────────────────────────
  requirement(r: unknown, where: string, modality: string): TextLine {
    const x = obj(r);
    const note = s(x?.description);
    switch (x?.kind) {
      case "boolean": return { text: `${factName(x.fact)}: ${x.value === true ? "yes" : x.value === false ? "no" : String(x.value)}`, note };
      case "numeric": return { text: `${factName(x.fact)} ${OPERATOR[s(x.operator) ?? ""] ?? `(${String(x.operator)})`} ${num(x.value, x.unit)}`, note };
      case "text": {
        const op = s(x.operator) ?? "";
        const v = Array.isArray(x.value) ? list(x.value.map(scalar), "or") : scalar(x.value);
        return { text: `${factName(x.fact)} ${OPERATOR[op] ?? `(${op})`} ${v}`, note };
      }
      case "formula": {
        const op = s(x.operator) ?? "";
        const word = op === "==" ? "equals" : OPERATOR[op] ?? `(${op})`;
        const u = unitText(x.unit);
        return { text: `${factName(x.fact)} ${word} ${this.arithmetic(x.expression, `${where} › formula`, false)}${u ? ` (in ${u})` : ""}`, note };
      }
      case "temporal": return { text: this.temporal(x, modality), note };
      case "unresolved": return this.unresolvedLine(x);
      default: return this.gap(where, r);
    }
  }

  arithmetic(e: unknown, where: string, nested: boolean): string {
    const x = obj(e);
    if (x?.kind === "literal") return num(x.value, x.unit);
    if (x?.kind === "fact") return factName(x.name);
    if (x?.kind === "operation") {
      const ops = arr(x.operands);
      const op = s(x.operator);
      if (op === "min" || op === "max") return `the ${op === "min" ? "smaller" : "larger"} of ${list(ops.map((o, i) => this.arithmetic(o, `${where} › ${i + 1}`, false)), "and")}`;
      const sign = { add: " + ", subtract: " − ", multiply: " × ", divide: " ÷ " }[op ?? ""];
      if (sign) {
        const text = ops.map((o, i) => this.arithmetic(o, `${where} › ${i + 1}`, true)).join(sign);
        return nested ? `(${text})` : text;
      }
    }
    this.gap(where, e);
    return "[a calculation that cannot be shown]";
  }

  temporal(x: Obj, modality: string): string {
    const d = obj(x.duration);
    const span = d ? `${String(d.value)} ${String(d.unit)}${d.value === 1 ? "" : "s"}` : "";
    const start = s(x.startEvent) ?? "";
    const endOrDate = s(x.endEvent) ?? (s(x.deadline) ? `${x.deadline as string}` : "");
    const anchorBefore = span ? `${span} before ${endOrDate}` : endOrDate;
    const when = {
      within: `within ${span} after ${start}`,
      for_at_least: `for at least ${span} from ${start}`,
      after: span ? `not earlier than ${span} after ${start}` : `not before ${start}`,
      before: `before ${anchorBefore}`,
      no_later_than: `no later than ${anchorBefore}`,
      until: `${start ? `from ${start} ` : ""}until ${endOrDate}`,
    }[s(x.relation) ?? ""] ?? `(${String(x.relation)})`;
    // the relation carries no modality; the rule's type does (Rule JSON documentation)
    const verb = modality === "obligation" ? "must take place" : modality === "permission" ? "may take place" : modality === "prohibition" ? "must not take place" : "takes place";
    return `${s(x.action) ?? "(no action)"}: ${verb} ${when}`;
  }

  expression(e: unknown, where: string, modality: string): TextLine {
    const x = obj(e);
    switch (x?.kind) {
      case "requirement": return this.requirement(x.requirement, where, modality);
      case "all": return { text: "All of the following:", children: arr(x.requirements).map((r, i) => this.expression(r, `${where} › ${i + 1}`, modality)) };
      case "any": return { text: "At least one of the following:", children: arr(x.requirements).map((r, i) => this.expression(r, `${where} › ${i + 1}`, modality)) };
      case "not": return { text: "This must not be the case:", children: [this.expression(x.requirement, `${where} › not`, modality)] };
      default: return this.gap(where, e);
    }
  }

  references(refs: unknown): TextLine[] {
    return arr(refs).map((r) => {
      const x = obj(r) ?? {};
      const rel = s(x.relationship);
      return {
        text: `${s(x.citation) ?? "(no citation)"}${rel ? ` (${rel.replace(/_/g, " ")})` : ""}`,
        note: x.resolution === "unresolved" ? "Not resolved in the document" : undefined,
      };
    });
  }
}

const ROLE: Record<string, string> = { duty_holder: "Obliged party", recipient: "Recipient", authority: "Authority", assessor: "Assessor", beneficiary: "Beneficiary", other: "Other party" };
const EXCEPTION_KIND: Record<string, string> = { exception: "Exception", exemption: "Exemption", alternative: "Alternative", override: "Override", unresolved: "Unclear exception" };
const EFFECT: Record<string, string> = {
  disapplies_rule: "The rule does not apply", modifies_rule: "The rule applies in a changed form", adds_alternative: "Adds another way to comply",
  requires_review: "Needs a closer review", unspecified: "Effect not specified",
};

/** The record in plain language. Never throws: a malformed part becomes a gap. */
export function readRule(rule: Record<string, unknown>): ReadableRule {
  const r = new Reader();
  const classification = obj(rule.classification) ?? {};
  const type = s(classification.type) ?? "";
  const blocks: TextBlock[] = [];
  const app = obj(rule.applicability);

  const targets = arr(app?.targets).map((t) => { const x = obj(t) ?? {}; return { text: s(x.entity) ?? "(unnamed)", note: s(x.description) } as TextLine; });
  if (targets.length) blocks.push({ key: "targets", title: "Applies to", lines: targets });
  const actors = arr(app?.actors).map((a) => { const x = obj(a) ?? {}; return { text: `${ROLE[s(x.role) ?? ""] ?? s(x.role) ?? "Party"}: ${s(x.entity) ?? "(unnamed)"}` } as TextLine; });
  if (actors.length) blocks.push({ key: "actors", title: "Who is involved", lines: actors });
  if (app && app.conditions !== undefined) {
    blocks.push(r.predicateBlock("when", app.conditions, { one: "Applies when", all: "Applies when all of these are true", any: "Applies when at least one of these is true" }, "Applies when"));
  }
  const exclusions = arr(app?.scopeExclusions);
  if (exclusions.length) blocks.push({ key: "notWhen", title: "Does not apply when", lines: exclusions.map((p, i) => r.predicate(p, `Does not apply when › ${i + 1}`)) });

  if (Array.isArray(rule.requirements)) {
    const lines = rule.requirements.map((q, i) => r.requirement(q, `Requirement ${i + 1}`, type));
    blocks.push({ key: "requires", title: lines.length > 1 ? "Requirements (all must be met)" : "Requirement", lines });
  } else if (rule.requirementExpression !== undefined) {
    const x = obj(rule.requirementExpression);
    if (x?.kind === "all" || x?.kind === "any") {
      blocks.push({ key: "requires", title: x.kind === "all" ? "Requirements (all must be met)" : "Requirements (at least one must be met)",
                    lines: arr(x.requirements).map((q, i) => r.expression(q, `Requirement ${i + 1}`, type)) });
    } else {
      blocks.push({ key: "requires", title: "Requirement", lines: [r.expression(rule.requirementExpression, "Requirement", type)] });
    }
  }

  const def = obj(rule.definition);
  if (def) {
    const term = s(def.term) ?? "(no term)";
    const line: TextLine = s(def.text) ? { text: `“${term}” means: ${def.text as string}` }
      : def.meaning !== undefined ? { text: `“${term}”:`, children: [r.requirement(def.meaning, "Definition", type)] }
      : r.gap("Definition without text or meaning", def);
    const extra: TextLine[] = [];
    if (def.condition !== undefined) extra.push({ text: "Only when:", children: [r.predicate(def.condition, "Definition condition")] });
    const refs = r.references(def.references);
    if (refs.length) extra.push({ text: "Refers to:", children: refs });
    blocks.push({ key: "definition", title: "Definition", lines: [{ ...line, children: [...(line.children ?? []), ...extra] }] });
  }

  if (!def && !Array.isArray(rule.requirements) && rule.requirementExpression === undefined) {
    r.gaps.push("The record states no requirement and no definition");
  }

  const exceptions = arr(rule.exceptions).map((e, i) => {
    const x = obj(e) ?? {};
    const kind = s(x.kind) ?? "";
    if (!(kind in EXCEPTION_KIND)) return r.gap(`Exception ${i + 1}`, e);
    if (kind === "unresolved") r.unresolved += 1;
    const children: TextLine[] = [];
    if (x.condition !== undefined) children.push({ text: "When:", children: [r.predicate(x.condition, `Exception ${i + 1} › when`)] });
    const reqs = arr(x.requirements).map((q, j) => r.requirement(q, `Exception ${i + 1} › requirement ${j + 1}`, type));
    if (reqs.length) children.push({ text: reqs.length > 1 ? "Then all of these apply:" : "Then:", children: reqs });
    const effect = s(x.effect);
    if (effect) children.push({ text: `Effect: ${EFFECT[effect] ?? effect.replace(/_/g, " ")}` });
    const refs = r.references(x.references);
    if (refs.length) children.push({ text: "Refers to:", children: refs });
    return { text: `${EXCEPTION_KIND[kind]}: ${s(x.description) ?? "(no description)"}`, children, unclear: kind === "unresolved" } as TextLine;
  });
  if (exceptions.length) blocks.push({ key: "exceptions", title: exceptions.length > 1 ? "Exceptions" : "Exception", lines: exceptions });

  const refs = r.references(rule.references);
  if (refs.length) blocks.push({ key: "references", title: "Refers to", lines: refs });

  return {
    kind: KIND_LABEL[type] ?? (type ? type.replace(/_/g, " ") : "Rule"), summary: s(classification.summary) ?? "",
    blocks: blocks.map((b) => ({ ...b, lines: b.lines.map(compact) })), gaps: r.gaps, unresolved: r.unresolved,
  };
}

/** "When:" with a single plain statement under it reads as one line ("When: building class is one of 1, 2 or 3"). Only the
 *  layout changes: the words, and what belongs to what, stay the same. */
function compact(line: TextLine): TextLine {
  const children = line.children?.map(compact);
  if (line.text.endsWith(":") && !line.note && children?.length === 1 && !children[0].children?.length && !children[0].unclear) {
    return { text: `${line.text} ${children[0].text}`, note: children[0].note, unclear: line.unclear };
  }
  return children ? { ...line, children } : line;
}

/** Every line of a reading as flat text (tests, search). */
export function readingText(reading: ReadableRule): string {
  const walk = (l: TextLine): string[] => [l.text, ...(l.note ? [l.note] : []), ...(l.children ?? []).flatMap(walk)];
  return [reading.summary, ...reading.blocks.flatMap((b) => [b.title, ...b.lines.flatMap(walk)])].join("\n");
}
