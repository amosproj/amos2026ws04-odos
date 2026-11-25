// The frontend's names for rule types must follow the Rule JSON 2.0 schema: `informational` is a normativeCategory, never a `classification.type`.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { KIND_LABEL } from "./ruleText";

const schema = JSON.parse(readFileSync(fileURLToPath(new URL("../../../backend/schemas/rule-json/rule.schema.json", import.meta.url)), "utf-8"));
const classification = schema.$defs.Classification.properties;

describe("Rule JSON 2.0 classification, as the frontend names it", () => {
  it("labels exactly the rule types of the schema", () => {
    expect(Object.keys(KIND_LABEL).sort()).toEqual([...classification.type.enum].sort());
  });
  it("keeps `informational` out of the types: it only exists as a normative category", () => {
    expect(classification.type.enum).not.toContain("informational");
    expect(classification.normativeCategory.enum).toContain("informational");
    expect(KIND_LABEL.informational).toBeUndefined();
  });
});
