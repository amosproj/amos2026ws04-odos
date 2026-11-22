// The simple editor of the review page: the values of a Rule JSON 2.0 record that a person can change in a form without
// touching its structure (numbers, operators of numeric bounds, texts, yes/no values, the summary and a definition's text).
// Each field writes back to exactly the place it was read from, with the same JSON type, so the edited record is the same
// record with other values. Structure (adding a condition, changing a kind, a formula) is changed in the JSON editor. The
// backend validates every edit against the schema either way.
import { factName, unitText } from "./ruleText";

export type FieldKind = "number" | "integer" | "operator" | "boolean" | "text" | "longtext";
export type Path = Array<string | number>;

export interface EditField {
  path: Path;
  label: string;
  kind: FieldKind;
  value: string | number | boolean;
  unit?: string;
}

export const NUMERIC_OPERATORS = ["==", "!=", ">", ">=", "<", "<="] as const;
export const OPERATOR_LABEL: Record<string, string> = { "==": "exactly", "!=": "not", ">": "more than", ">=": "at least", "<": "less than", "<=": "at most" };

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : null);

/** The fields of a record the simple editor offers, in reading order. */
export function editableFields(rule: Record<string, unknown>): EditField[] {
  const out: EditField[] = [];
  const summary = obj(rule.classification)?.summary;
  if (typeof summary === "string") out.push({ path: ["classification", "summary"], label: "Summary", kind: "longtext", value: summary });

  const requirement = (r: unknown, path: Path, where: string) => {
    const x = obj(r);
    if (!x) return;
    const name = `${where}: ${factName(x.fact)}`;
    if (x.kind === "numeric" && typeof x.value === "number") {
      if (typeof x.operator === "string") out.push({ path: [...path, "operator"], label: `${name} (bound)`, kind: "operator", value: x.operator });
      out.push({ path: [...path, "value"], label: name, kind: "number", value: x.value, unit: unitText(x.unit) || undefined });
    } else if (x.kind === "boolean" && typeof x.value === "boolean") {
      out.push({ path: [...path, "value"], label: name, kind: "boolean", value: x.value });
    } else if (x.kind === "text" && typeof x.value === "string") {
      out.push({ path: [...path, "value"], label: name, kind: "text", value: x.value });
    }
  };
  const predicate = (p: unknown, path: Path, where: string) => {
    const x = obj(p);
    if (!x) return;
    if (x.kind === "comparison") {
      const name = `${where}: ${factName(x.fact)}`;
      const v = x.value;
      if (x.valueType === "integer" && typeof v === "number") out.push({ path: [...path, "value"], label: name, kind: "integer", value: v, unit: unitText(x.unit) || undefined });
      else if (x.valueType === "number" && typeof v === "number") out.push({ path: [...path, "value"], label: name, kind: "number", value: v, unit: unitText(x.unit) || undefined });
      else if (x.valueType === "boolean" && typeof v === "boolean") out.push({ path: [...path, "value"], label: name, kind: "boolean", value: v });
      else if (x.valueType === "string" && typeof v === "string") out.push({ path: [...path, "value"], label: name, kind: "text", value: v });
    } else if ((x.kind === "all" || x.kind === "any") && Array.isArray(x.conditions)) {
      x.conditions.forEach((c, i) => predicate(c, [...path, "conditions", i], where));
    } else if (x.kind === "not") predicate(x.condition, [...path, "condition"], where);
  };
  const expression = (e: unknown, path: Path) => {
    const x = obj(e);
    if (!x) return;
    if (x.kind === "requirement") requirement(x.requirement, [...path, "requirement"], "Requirement");
    else if ((x.kind === "all" || x.kind === "any") && Array.isArray(x.requirements)) x.requirements.forEach((r, i) => expression(r, [...path, "requirements", i]));
    else if (x.kind === "not") expression(x.requirement, [...path, "requirement"]);
  };

  const app = obj(rule.applicability);
  if (app?.conditions !== undefined) predicate(app.conditions, ["applicability", "conditions"], "Applies when");
  if (Array.isArray(app?.scopeExclusions)) app.scopeExclusions.forEach((p, i) => predicate(p, ["applicability", "scopeExclusions", i], "Does not apply when"));
  if (Array.isArray(rule.requirements)) rule.requirements.forEach((r, i) => requirement(r, ["requirements", i], rule.requirements && (rule.requirements as unknown[]).length > 1 ? `Requirement ${i + 1}` : "Requirement"));
  if (rule.requirementExpression !== undefined) expression(rule.requirementExpression, ["requirementExpression"]);
  const def = obj(rule.definition);
  if (def && typeof def.text === "string") out.push({ path: ["definition", "text"], label: `Definition of “${String(def.term)}”`, kind: "longtext", value: def.text });
  if (Array.isArray(rule.exceptions)) {
    rule.exceptions.forEach((e, i) => {
      const x = obj(e);
      if (!x) return;
      const where = `Exception ${i + 1}`;
      if (x.condition !== undefined) predicate(x.condition, ["exceptions", i, "condition"], `${where}, when`);
      if (Array.isArray(x.requirements)) x.requirements.forEach((r, j) => requirement(r, ["exceptions", i, "requirements", j], `${where}, then`));
    });
  }
  return out;
}

export const pathKey = (p: Path) => p.join("/");

/** A value typed into a field as the JSON value it stands for, or an error message. */
export function parseField(field: EditField, input: string | boolean): { ok: true; value: string | number | boolean } | { ok: false; error: string } {
  if (field.kind === "boolean") return typeof input === "boolean" ? { ok: true, value: input } : { ok: false, error: `${field.label}: choose yes or no.` };
  const text = String(input);
  if (field.kind === "number" || field.kind === "integer") {
    const n = Number(text.trim().replace(",", "."));
    if (!text.trim() || !Number.isFinite(n)) return { ok: false, error: `${field.label}: enter a number.` };
    if (field.kind === "integer" && !Number.isInteger(n)) return { ok: false, error: `${field.label}: enter a whole number.` };
    return { ok: true, value: n };
  }
  if (field.kind === "operator") return (NUMERIC_OPERATORS as readonly string[]).includes(text) ? { ok: true, value: text } : { ok: false, error: `${field.label}: choose a bound.` };
  if (!text.trim()) return { ok: false, error: `${field.label}: cannot be empty.` };
  return { ok: true, value: text };
}

/** A copy of the record with the given values written to their places; the record itself is not changed. */
export function applyFields(rule: Record<string, unknown>, values: Map<string, { path: Path; value: string | number | boolean }>): Record<string, unknown> {
  const copy = JSON.parse(JSON.stringify(rule)) as Record<string, unknown>; // a JSON record: a JSON copy is exact
  for (const { path, value } of values.values()) {
    let at: unknown = copy;
    for (const step of path.slice(0, -1)) at = (at as Record<string | number, unknown>)[step];
    (at as Record<string | number, unknown>)[path[path.length - 1]] = value;
  }
  return copy;
}
