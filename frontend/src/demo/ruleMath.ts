// Mathematical notation for the numeric parts of a Rule JSON 2.0 record. Deterministic and data-driven: a formula is written only
// from the record's own `formula` requirement (fact, operator, unit, expression tree of literal / fact / operation) and a bound only
// from its own `numeric` requirement. An expression the schema does not define for this reader (unknown kind, a subtract or divide
// without exactly two operands, a missing value) yields `null`: the caller then keeps the plain-language line, which is always shown.
// No operator is guessed, no relationship between rules is inferred, and nothing is sent anywhere.

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : null);
const str = (v: unknown): string | undefined => (typeof v === "string" && v.trim() ? v : undefined);

const UNIT_SYMBOL: Record<string, string> = { m2: "m²", m3: "m³", cm2: "cm²", mm2: "mm²", Cel: "°C", deg: "°", "kN/m2": "kN/m²" };
/** The unit as it is printed; a code without a common symbol stays as written. `1` (dimensionless) prints nothing. */
export const unitText = (u: unknown): string => { const x = str(u); return !x || x === "1" ? "" : UNIT_SYMBOL[x] ?? x; };

/** The schema's comparison operators as symbols. `==` on a formula states a calculated value, so it reads "=". */
export const OPERATOR_SYMBOL: Record<string, string> = { "==": "=", "!=": "≠", ">": ">", ">=": "≥", "<": "<", "<=": "≤" };
/** What an operator means in words (tooltips and screen readers). */
export const OPERATOR_WORDS: Record<string, string> = { "==": "equals", "!=": "is not", ">": "is more than", ">=": "is at least", "<": "is less than", "<=": "is at most" };

export type MathToken = { kind: "fact" | "num" | "op" | "punct"; text: string };

export interface MathFact { name: string; unit?: string }

export interface MathExpression { tokens: MathToken[]; facts: MathFact[] }

const OPS: Record<string, { sign: string; prec: number }> = {
  add: { sign: "+", prec: 1 }, subtract: { sign: "−", prec: 1 }, multiply: { sign: "×", prec: 2 }, divide: { sign: "÷", prec: 2 },
};

const number = (v: number) => String(v);

/** An arithmetic expression as tokens, or null when any part of it is not one the schema defines. */
export function mathExpression(e: unknown): MathExpression | null {
  const facts = new Map<string, MathFact>();
  const walk = (node: unknown, parentPrec: number, rightOfNonAssoc: boolean): MathToken[] | null => {
    const x = obj(node);
    if (x?.kind === "literal" && typeof x.value === "number" && Number.isFinite(x.value)) {
      const u = unitText(x.unit);
      return [{ kind: "num", text: number(x.value) }, ...(u ? [{ kind: "punct" as const, text: ` ${u}` }] : [])];
    }
    if (x?.kind === "fact" && str(x.name)) {
      const name = x.name as string;
      const unit = unitText(x.unit) || undefined;
      const known = facts.get(name);
      facts.set(name, { name, unit: known?.unit ?? unit });
      return [{ kind: "fact", text: name }];
    }
    if (x?.kind === "operation" && Array.isArray(x.operands)) {
      const op = str(x.operator) ?? "";
      const operands = x.operands;
      if (op === "min" || op === "max") {
        if (operands.length < 2) return null;
        const out: MathToken[] = [{ kind: "op", text: op }, { kind: "punct", text: "(" }];
        for (let i = 0; i < operands.length; i++) {
          const part = walk(operands[i], 0, false);
          if (!part) return null;
          if (i) out.push({ kind: "punct", text: ", " });
          out.push(...part);
        }
        return [...out, { kind: "punct", text: ")" }];
      }
      const spec = OPS[op];
      if (!spec || operands.length < 2 || ((op === "subtract" || op === "divide") && operands.length !== 2)) return null;
      const out: MathToken[] = [];
      for (let i = 0; i < operands.length; i++) {
        // operands of a lower-precedence operation are bracketed, and so is the right operand of − and ÷ when it is itself an
        // operation of the same precedence: a − (b − c) is not a − b − c
        const part = walk(operands[i], spec.prec, (op === "subtract" || op === "divide") && i > 0);
        if (!part) return null;
        if (i) out.push({ kind: "op", text: ` ${spec.sign} ` });
        out.push(...part);
      }
      const wrap = spec.prec < parentPrec || (spec.prec === parentPrec && rightOfNonAssoc);
      return wrap ? [{ kind: "punct", text: "(" }, ...out, { kind: "punct", text: ")" }] : out;
    }
    return null;
  };
  const tokens = walk(e, 0, false);
  return tokens ? { tokens, facts: [...facts.values()] } : null;
}

export interface Formula {
  /** The fact the formula determines (`==`) or bounds (`>=`, `<=`). */
  fact: string;
  operator: string;
  unit?: string;
  expression: MathExpression;
  /** The record's own wording of this formula. */
  description?: string;
}

/** A `formula` requirement as a formula; null when it is not one this reader can state unambiguously. */
export function formulaOf(requirement: Obj): Formula | null {
  const fact = str(requirement.fact);
  const operator = str(requirement.operator);
  if (!fact || !operator || !(operator in OPERATOR_SYMBOL)) return null;
  const expression = mathExpression(requirement.expression);
  if (!expression) return null;
  return { fact, operator, unit: unitText(requirement.unit) || undefined, expression, description: str(requirement.description) };
}

/** The unit of each fact of a formula, where the record states one: the units written on the fact nodes, and the formula's own unit
 *  for the fact it determines. A fact without a stated unit has none. */
export function formulaParameters(f: Formula): MathFact[] {
  const byName = new Map(f.expression.facts.map((p) => [p.name, p]));
  const own = byName.get(f.fact);
  const all = [{ name: f.fact, unit: f.unit ?? own?.unit }, ...f.expression.facts.filter((p) => p.name !== f.fact)];
  return all;
}

/** How a fact is written in a formula: a one-letter variable when its identifier ends in one (`measure_h` → h, `wall.H` → H),
 *  else its identifier in words (`setback_area_depth` → setback area depth). The exact identifier stays available (legend, tooltip). */
export function mathName(id: string): { text: string; symbol: boolean } {
  const parts = id.split(/[._]+/).filter(Boolean);
  const last = parts[parts.length - 1] ?? id;
  if (/^\p{L}$/u.test(last)) return { text: last, symbol: true };
  return { text: parts.join(" ") || id, symbol: false };
}
