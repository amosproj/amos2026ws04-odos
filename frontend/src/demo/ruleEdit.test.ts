// The simple editor: which values of a Rule JSON 2.0 record it offers, how typed text becomes a JSON value, and that writing
// them back changes exactly those values (same JSON types) in a copy, never the record itself.
import { describe, expect, it } from "vitest";
import { applyFields, editableFields, parseField, pathKey, type EditField } from "./ruleEdit";

const RULE = {
  schemaVersion: "2.0", id: "r", source: { documentId: "d", elements: [{ elementId: "e" }] },
  classification: { type: "obligation", summary: "Türen mindestens 0,90 m." },
  applicability: { conditions: { kind: "all", conditions: [
    { kind: "comparison", fact: "storeys", operator: ">", value: 3, valueType: "integer" },
    { kind: "comparison", fact: "use", operator: "in", value: ["a", "b"], valueType: "string_array" }, // a list: changed in the JSON editor
  ] } },
  requirements: [
    { kind: "numeric", fact: "door_width", operator: ">=", value: 0.9, unit: "m" },
    { kind: "boolean", fact: "self_closing", value: true },
    { kind: "formula", fact: "y", operator: "==", unit: "m", expression: { kind: "fact", name: "h" } }, // structure: JSON editor
  ],
  exceptions: [{ kind: "alternative", description: "x", requirements: [{ kind: "text", fact: "material", operator: "==", value: "A1" }] }],
  review: { status: "draft" },
};

const field = (fields: EditField[], label: string) => fields.find((f) => f.label === label)!;

describe("editable fields", () => {
  it("offers the values a form can change safely, in reading order, and leaves structure to the JSON editor", () => {
    const fields = editableFields(RULE);
    expect(fields.map((f) => [f.label, f.kind, f.value])).toEqual([
      ["Summary", "longtext", "Türen mindestens 0,90 m."],
      ["Applies when: storeys", "integer", 3],
      ["Requirement 1: door width (bound)", "operator", ">="],
      ["Requirement 1: door width", "number", 0.9],
      ["Requirement 2: self closing", "boolean", true],
      ["Exception 1, then: material", "text", "A1"],
    ]);
    expect(field(fields, "Requirement 1: door width").unit).toBe("m");
  });

  it("reads typed text as the JSON value of the field's type", () => {
    const fields = editableFields(RULE);
    expect(parseField(field(fields, "Requirement 1: door width"), "1,25")).toEqual({ ok: true, value: 1.25 });
    expect(parseField(field(fields, "Requirement 1: door width"), "breit")).toMatchObject({ ok: false });
    expect(parseField(field(fields, "Requirement 1: door width"), "")).toMatchObject({ ok: false });
    expect(parseField(field(fields, "Applies when: storeys"), "3.5")).toMatchObject({ ok: false, error: expect.stringContaining("whole number") });
    expect(parseField(field(fields, "Requirement 1: door width (bound)"), "=>")).toMatchObject({ ok: false });
    expect(parseField(field(fields, "Requirement 2: self closing"), false)).toEqual({ ok: true, value: false });
    expect(parseField(field(fields, "Exception 1, then: material"), "  ")).toMatchObject({ ok: false });
  });

  it("writes changed values to their places in a copy: same structure, same JSON types, the record untouched", () => {
    const before = JSON.stringify(RULE);
    const fields = editableFields(RULE);
    const changes = new Map([field(fields, "Requirement 1: door width"), field(fields, "Requirement 2: self closing"), field(fields, "Applies when: storeys")]
      .map((f, i) => [pathKey(f.path), { path: f.path, value: [1, false, 4][i] }]));
    const edited = applyFields(RULE, changes) as typeof RULE;
    expect(JSON.stringify(RULE)).toBe(before);
    expect(edited.requirements[0]).toEqual({ ...RULE.requirements[0], value: 1 });
    expect(edited.requirements[1]).toEqual({ ...RULE.requirements[1], value: false });
    expect(edited.applicability.conditions.conditions[0]).toEqual({ ...RULE.applicability.conditions.conditions[0], value: 4 });
    expect({ ...edited, requirements: RULE.requirements, applicability: RULE.applicability }).toEqual(RULE); // nothing else changed
  });

  it("finds values inside a requirement expression and a definition", () => {
    const expr = { ...RULE, requirements: undefined, requirementExpression: { kind: "any", requirements: [{ kind: "requirement", requirement: { kind: "numeric", fact: "h", operator: ">=", value: 0.3, unit: "m" } }] } };
    expect(editableFields(expr).map((f) => f.path.join("/"))).toContain("requirementExpression/requirements/0/requirement/value");
    const def = { ...RULE, requirements: undefined, definition: { term: "Gebäude", text: "bauliche Anlagen" } };
    expect(editableFields(def).map((f) => f.label)).toContain("Definition of “Gebäude”");
  });
});
