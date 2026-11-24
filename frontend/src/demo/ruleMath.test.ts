// The mathematical notation is written only from what the record states; anything it cannot state unambiguously is left to the
// plain-language line (no `formula` on the line, no invented operator).
import { describe, expect, it } from "vitest";
import { formulaOf, formulaParameters, mathExpression } from "./ruleMath";
import { readRule } from "./ruleText";

const lit = (value: number, unit?: string) => ({ kind: "literal", value, ...(unit ? { unit } : {}) });
const fact = (name: string, unit?: string) => ({ kind: "fact", name, ...(unit ? { unit } : {}) });
const op = (operator: string, ...operands: unknown[]) => ({ kind: "operation", operator, operands });
const text = (e: unknown) => mathExpression(e)?.tokens.map((t) => t.text).join("");

describe("mathExpression", () => {
  it("writes the record's own operations with mathematical signs and units", () => {
    expect(text(op("max", op("multiply", lit(0.4), fact("measure_h", "m")), lit(3, "m")))).toBe("max(0.4 × measure_h, 3 m)");
    expect(text(op("add", fact("wall_height", "m"), op("divide", fact("roof_height", "m"), lit(3))))).toBe("wall_height + roof_height ÷ 3");
    expect(text(op("min", fact("a"), fact("b"), lit(2)))).toBe("min(a, b, 2)");
  });

  it("brackets only where the order of operations needs it", () => {
    expect(text(op("multiply", op("add", fact("a"), fact("b")), lit(2)))).toBe("(a + b) × 2");
    expect(text(op("add", op("multiply", fact("a"), lit(2)), fact("b")))).toBe("a × 2 + b");
    expect(text(op("subtract", fact("a"), op("subtract", fact("b"), fact("c"))))).toBe("a − (b − c)"); // not a − b − c
    expect(text(op("divide", fact("a"), op("multiply", fact("b"), fact("c"))))).toBe("a ÷ (b × c)");
    expect(text(op("subtract", op("subtract", fact("a"), fact("b")), fact("c")))).toBe("a − b − c");
  });

  it("collects the facts with the units the record states, once each", () => {
    const e = mathExpression(op("add", fact("h", "m"), fact("h", "m"), fact("w")))!;
    expect(e.facts).toEqual([{ name: "h", unit: "m" }, { name: "w", unit: undefined }]);
  });

  it("gives up (null) on anything the schema does not define, rather than guessing", () => {
    expect(mathExpression(op("power", fact("a"), lit(2)))).toBeNull(); // unknown operator
    expect(mathExpression(op("subtract", fact("a"), fact("b"), fact("c")))).toBeNull(); // subtract takes exactly two operands
    expect(mathExpression(op("divide", fact("a")))).toBeNull();
    expect(mathExpression({ kind: "literal", value: "3" })).toBeNull(); // not a number
    expect(mathExpression({ kind: "sqrt", value: 4 })).toBeNull();
    expect(mathExpression(op("add", fact("a"), { kind: "mystery" }))).toBeNull(); // one unknown part voids the whole expression
    expect(mathExpression(undefined)).toBeNull();
  });
});

describe("formulaOf and the rule reading", () => {
  const formulaRule = (requirement: unknown) => ({
    schemaVersion: "2.0", id: "r", classification: { type: "obligation", summary: "s" },
    requirements: [requirement],
  } as Record<string, unknown>);
  const setback = { kind: "formula", fact: "setback_area_depth", operator: "==", unit: "m", description: "0,4 H, mindestens 3 m",
    expression: op("max", op("multiply", lit(0.4), fact("measure_h", "m")), lit(3, "m")) };

  it("keeps the fact, the relation as stored and the unit of the formula", () => {
    const f = formulaOf(setback)!;
    expect(f).toMatchObject({ fact: "setback_area_depth", operator: "==", unit: "m", description: "0,4 H, mindestens 3 m" });
    expect(formulaOf({ ...setback, operator: ">=" })?.operator).toBe(">="); // a minimum stays a minimum
    expect(formulaOf({ ...setback, operator: "approx" })).toBeNull(); // an operator outside the schema is not turned into a symbol
    expect(formulaOf({ ...setback, fact: undefined })).toBeNull();
  });

  it("lists the parameters: the determined fact with the formula's unit, the others with their own", () => {
    expect(formulaParameters(formulaOf(setback)!)).toEqual([{ name: "setback_area_depth", unit: "m" }, { name: "measure_h", unit: "m" }]);
    const noUnit = formulaOf({ ...setback, unit: "1", expression: op("add", fact("x"), lit(1)) })!;
    expect(formulaParameters(noUnit).map((p) => p.unit)).toEqual([undefined, undefined]); // "no unit stated", nothing assumed
  });

  it("puts the formula on the reading line, next to the unchanged plain-language text", () => {
    const [line] = readRule(formulaRule(setback)).blocks.find((b) => b.key === "requires")!.lines;
    expect(line.formula?.fact).toBe("setback_area_depth");
    expect(line.text).toBe("setback area depth equals the larger of 0.4 × measure h and 3 m (in m)");
  });

  it("leaves a formula it cannot state without a formula, but with its text line", () => {
    const [line] = readRule(formulaRule({ ...setback, expression: op("subtract", fact("a"), fact("b"), fact("c")) })).blocks.find((b) => b.key === "requires")!.lines;
    expect(line.formula).toBeUndefined();
    expect(line.text).toContain("setback area depth");
  });

  it("gives a numeric bound its stored operator, value and unit and a boolean requirement nothing numeric", () => {
    const lines = readRule({ ...formulaRule({}), requirements: [
      { kind: "numeric", fact: "room_height", operator: "<=", value: 2.3, unit: "m" }, { kind: "boolean", fact: "ventilated", value: true },
    ] }).blocks.find((b) => b.key === "requires")!.lines;
    expect(lines[0].threshold).toEqual({ fact: "room_height", operator: "<=", value: 2.3, unit: "m" });
    expect(lines[1].threshold).toBeUndefined();
    expect(lines[1].formula).toBeUndefined();
  });
});
