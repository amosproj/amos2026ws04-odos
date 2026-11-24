// The plain-language reading of Rule JSON 2.0 records: every operator, value, unit, condition and exception of the record is
// stated, nothing is added, and a part the formatter does not know is reported instead of guessed. Records follow
// backend/schemas/rule-json/rule.schema.json; several are taken from real MBO and EU extractions.
import { describe, expect, it } from "vitest";
import { factName, readRule, readingText, unitText, type TextLine } from "./ruleText";

const base = (extra: Record<string, unknown>, type = "obligation") => ({
  schemaVersion: "2.0", id: "r", source: { documentId: "d", elements: [{ elementId: "e" }] },
  classification: { type, summary: "Zusammenfassung." }, review: { status: "draft" }, ...extra,
});
const lines = (rule: Record<string, unknown>, key: string) => readRule(rule).blocks.find((b) => b.key === key)?.lines ?? [];
const flat = (ls: TextLine[]): string[] => ls.flatMap((l) => [l.text, ...flat(l.children ?? [])]);

describe("values, operators and units", () => {
  it("states each numeric operator exactly", () => {
    const ops = ["==", "!=", ">", ">=", "<", "<="];
    const rule = base({ requirements: ops.map((operator, i) => ({ kind: "numeric", fact: `f${i}`, operator, value: 7, unit: "m" })) });
    expect(flat(lines(rule, "requires"))).toEqual(["f0 is 7 m", "f1 is not 7 m", "f2 is more than 7 m", "f3 is at least 7 m", "f4 is less than 7 m", "f5 is at most 7 m"]);
  });

  it("prints units as symbols where a common one exists, and keeps any other code as written", () => {
    expect([unitText("m2"), unitText("m3"), unitText("Cel"), unitText("deg"), unitText("kN/m2"), unitText("min"), unitText("1"), unitText(undefined)])
      .toEqual(["m²", "m³", "°C", "°", "kN/m²", "min", "", ""]);
  });

  it("keeps numbers as stored: no rounding, no locale formatting", () => {
    const rule = base({ requirements: [{ kind: "numeric", fact: "area", operator: "<=", value: 400.125, unit: "m2" }, { kind: "numeric", fact: "count", operator: "<=", value: 2, unit: "1" }] });
    expect(flat(lines(rule, "requires"))).toEqual(["area is at most 400.125 m²", "count is at most 2"]);
  });

  it("reads fact names as written, without translating them", () => {
    expect(factName("fire_wall_height_above_roof")).toBe("fire wall height above roof");
    expect(factName("building.height")).toBe("building height");
  });

  it("states yes/no facts, texts and lists of allowed values", () => {
    const rule = base({ requirements: [
      { kind: "boolean", fact: "subject_to_mbo", value: true },
      { kind: "boolean", fact: "has_window", value: false },
      { kind: "text", fact: "fire_behaviour_class", operator: "==", value: "schwerentflammbar" },
      { kind: "text", fact: "material", operator: "in", value: ["A1", "A2"] },
      { kind: "text", fact: "label", operator: "contains", value: "CE" },
    ] });
    expect(flat(lines(rule, "requires"))).toEqual([
      "subject to mbo: yes", "has window: no", "fire behaviour class is “schwerentflammbar”", "material is one of “A1” or “A2”", "label contains “CE”",
    ]);
  });

  it("shows the record's own description beside the exact statement, never instead of it", () => {
    const rule = base({ requirements: [{ kind: "numeric", fact: "fire_wall_height_above_roof", operator: ">=", value: 0.3, unit: "m", description: "Brandwand 0,30 m über die Bedachung geführt" }] });
    expect(lines(rule, "requires")[0]).toEqual({ text: "fire wall height above roof is at least 0.3 m", note: "Brandwand 0,30 m über die Bedachung geführt",
      threshold: { fact: "fire_wall_height_above_roof", operator: ">=", value: 0.3, unit: "m" } });
  });

  it("gives a numeric requirement its stored fields as a threshold, with no unit when the record has none", () => {
    const rule = base({ requirements: [{ kind: "numeric", fact: "anzahl_geschosse", operator: "<=", value: 2 }, { kind: "boolean", fact: "x", value: true }] });
    const [numeric, flag] = lines(rule, "requires");
    expect(numeric.threshold).toEqual({ fact: "anzahl_geschosse", operator: "<=", value: 2 });
    expect(flag.threshold).toBeUndefined(); // nothing is invented for a requirement without an operator and value
  });
});

describe("when a rule applies", () => {
  it("lifts a top-level all / any into the title so the conditions read as bullets", () => {
    const all = base({ applicability: { conditions: { kind: "all", conditions: [
      { kind: "comparison", fact: "building_height", operator: "<=", value: 7, valueType: "number", unit: "m" },
      { kind: "comparison", fact: "unit_count", operator: "<=", value: 2, valueType: "integer" },
      { kind: "comparison", fact: "total_area", operator: "<=", value: 400, valueType: "number", unit: "m2" },
    ] } }, requirements: [{ kind: "boolean", fact: "class_1a", value: true }] });
    const block = readRule(all).blocks.find((b) => b.key === "when")!;
    expect(block.title).toBe("Applies when all of these are true");
    expect(flat(block.lines)).toEqual(["building height is at most 7 m", "unit count is at most 2", "total area is at most 400 m²"]);

    const any = base({ applicability: { conditions: { kind: "any", conditions: [
      { kind: "comparison", fact: "a", operator: "==", value: true, valueType: "boolean" }, { kind: "comparison", fact: "b", operator: "==", value: false, valueType: "boolean" },
    ] } }, requirements: [{ kind: "boolean", fact: "x", value: true }] });
    expect(readRule(any).blocks.find((b) => b.key === "when")!.title).toBe("Applies when at least one of these is true");
    expect(flat(lines(any, "when"))).toEqual(["a: yes", "b: no"]);
  });

  it("keeps nested logic nested, and negation explicit", () => {
    const rule = base({ applicability: { conditions: { kind: "all", conditions: [
      { kind: "comparison", fact: "building_class", operator: "in", value: [1, 2, 3], valueType: "integer_array" },
      { kind: "any", conditions: [{ kind: "comparison", fact: "use", operator: "==", value: "residential", valueType: "string" }, { kind: "not", condition: { kind: "comparison", fact: "basement", operator: "==", value: true, valueType: "boolean" } }] },
    ] } }, requirements: [{ kind: "boolean", fact: "x", value: true }] });
    const ls = lines(rule, "when");
    expect(ls[0].text).toBe("building class is one of 1, 2 or 3");
    expect(ls[1].text).toBe("At least one of the following:");
    expect(ls[1].children!.map((c) => c.text)).toEqual(["use is “residential”", "This is not the case: basement: yes"]);
  });

  it("lists scope exclusions, targets and actors", () => {
    const rule = base({ applicability: {
      targets: [{ entity: "Brandwände", description: "innere Brandwände" }], actors: [{ role: "duty_holder", entity: "Bauherr" }],
      scopeExclusions: [{ kind: "comparison", fact: "building_class", operator: "not_in", value: [4, 5], valueType: "integer_array" }],
    }, requirements: [{ kind: "boolean", fact: "x", value: true }] });
    expect(lines(rule, "targets")).toEqual([{ text: "Brandwände", note: "innere Brandwände" }]);
    expect(flat(lines(rule, "actors"))).toEqual(["Obliged party: Bauherr"]);
    expect(flat(lines(rule, "notWhen"))).toEqual(["building class is none of 4 and 5"]);
  });
});

describe("requirements, formulas and periods", () => {
  it("says whether all requirements or at least one must be met", () => {
    expect(readRule(base({ requirements: [{ kind: "boolean", fact: "a", value: true }, { kind: "boolean", fact: "b", value: true }] })).blocks[0].title).toBe("Requirements (all must be met)");
    const any = base({ requirementExpression: { kind: "any", requirements: [
      { kind: "requirement", requirement: { kind: "numeric", fact: "fire_wall_height_above_roof", operator: ">=", value: 0.3, unit: "m" } },
      { kind: "requirement", requirement: { kind: "boolean", fact: "fire_wall_terminated_with_cantilever_plate", value: true } },
    ] } });
    const block = readRule(any).blocks[0];
    expect(block.title).toBe("Requirements (at least one must be met)");
    expect(flat(block.lines)).toEqual(["fire wall height above roof is at least 0.3 m", "fire wall terminated with cantilever plate: yes"]);
    const not = base({ requirementExpression: { kind: "not", requirement: { kind: "requirement", requirement: { kind: "boolean", fact: "smoking", value: true } } } }, "prohibition");
    expect(flat(readRule(not).blocks[0].lines)).toEqual(["This must not be the case: smoking: yes"]);
  });

  it("writes formulas out with their operators, factors and units (MBO § 6 Abs. 5)", () => {
    const rule = base({ requirements: [{ kind: "formula", fact: "setback_area_depth", operator: "==", unit: "m", expression: { kind: "operation", operator: "max", operands: [
      { kind: "operation", operator: "multiply", operands: [{ kind: "literal", value: 0.4 }, { kind: "fact", name: "measure_h", unit: "m" }] },
      { kind: "literal", value: 3, unit: "m" },
    ] } }] });
    expect(flat(lines(rule, "requires"))).toEqual(["setback area depth equals the larger of 0.4 × measure h and 3 m (in m)"]);
  });

  it("puts brackets around nested arithmetic so the order of operations stays exact", () => {
    const rule = base({ requirements: [{ kind: "formula", fact: "y", operator: ">=", unit: "m2", expression: { kind: "operation", operator: "divide", operands: [
      { kind: "operation", operator: "add", operands: [{ kind: "fact", name: "a" }, { kind: "fact", name: "b" }] }, { kind: "literal", value: 8 },
    ] } }] });
    expect(flat(lines(rule, "requires"))).toEqual(["y is at least (a + b) ÷ 8 (in m²)"]);
  });

  it("states periods with the modality of the rule type", () => {
    const t = (type: string, req: Record<string, unknown>) => flat(lines(base({ requirements: [{ kind: "temporal", action: "Anzeige einreichen", ...req }] }, type), "requires"))[0];
    expect(t("obligation", { relation: "before", endEvent: "Baubeginn", duration: { value: 1, unit: "week" } })).toBe("Anzeige einreichen: must take place before 1 week before Baubeginn");
    expect(t("permission", { relation: "within", startEvent: "Zugang", duration: { value: 3, unit: "month" } })).toBe("Anzeige einreichen: may take place within 3 months after Zugang");
    expect(t("prohibition", { relation: "after", startEvent: "Fristablauf" })).toBe("Anzeige einreichen: must not take place not before Fristablauf");
    expect(t("obligation", { relation: "no_later_than", deadline: "2027-01-01" })).toBe("Anzeige einreichen: must take place no later than 2027-01-01");
    expect(t("obligation", { relation: "until", startEvent: "A", endEvent: "B" })).toBe("Anzeige einreichen: must take place from A until B");
    expect(t("obligation", { relation: "for_at_least", startEvent: "Abnahme", duration: { value: 5, unit: "year" } })).toBe("Anzeige einreichen: must take place for at least 5 years from Abnahme");
  });
});

describe("exceptions, definitions and references", () => {
  it("states each exception with its kind, condition, changed requirement and effect", () => {
    const rule = base({ requirements: [{ kind: "text", fact: "fire_resistance_class", operator: "==", value: "feuerbeständig" }], exceptions: [
      { kind: "alternative", effect: "modifies_rule", description: "Für Gebäude der Gebäudeklasse 4 sind hochfeuerhemmende Wände zulässig.",
        condition: { kind: "comparison", fact: "building_class", operator: "==", value: 4, valueType: "integer" },
        requirements: [{ kind: "text", fact: "fire_resistance_class", operator: "==", value: "hochfeuerhemmend" }] },
      { kind: "exception", effect: "disapplies_rule", description: "Gilt nicht für Gebäude der Gebäudeklassen 1 bis 3.",
        condition: { kind: "comparison", fact: "building_class", operator: "in", value: [1, 2, 3], valueType: "integer_array" } },
    ] });
    const [alt, exc] = lines(rule, "exceptions");
    expect(alt.text).toBe("Alternative: Für Gebäude der Gebäudeklasse 4 sind hochfeuerhemmende Wände zulässig.");
    expect(alt.children!.map((c) => c.text)).toEqual(["When: building class is 4", "Then: fire resistance class is “hochfeuerhemmend”", "Effect: The rule applies in a changed form"]);
    expect(exc.children!.map((c) => c.text)).toEqual(["When: building class is one of 1, 2 or 3", "Effect: The rule does not apply"]);
  });

  it("marks what the record itself could not express precisely, with its reason", () => {
    const rule = base({ requirements: [{ kind: "unresolved", text: "Das Grundstück muss angemessen breit an einer Verkehrsfläche liegen.", reason: "Disjunktive Bedingung." }] });
    const reading = readRule(rule);
    expect(reading.unresolved).toBe(1);
    expect(reading.gaps).toEqual([]); // shown in full, so not a gap
    expect(reading.blocks[0].lines[0]).toEqual({ text: "Das Grundstück muss angemessen breit an einer Verkehrsfläche liegen.", note: "Not expressed as a precise check: Disjunktive Bedingung.", unclear: true });
  });

  it("states definitions by their text or by their meaning, and references with their relation", () => {
    const text = base({ definition: { term: "Gebäude", text: "selbstständig benutzbare, überdeckte bauliche Anlagen" } }, "definition");
    expect(flat(lines(text, "definition"))).toEqual(["“Gebäude” means: selbstständig benutzbare, überdeckte bauliche Anlagen"]);
    const meaning = base({ definition: { term: "Hochhaus", meaning: { kind: "numeric", fact: "height", operator: ">", value: 22, unit: "m" } } }, "definition");
    expect(flat(lines(meaning, "definition"))).toEqual(["“Hochhaus”: height is more than 22 m"]);
    const refs = base({ requirements: [{ kind: "boolean", fact: "x", value: true }], references: [{ citation: "Artikel 3", resolution: "unresolved", relationship: "subject_to" }] });
    expect(lines(refs, "references")).toEqual([{ text: "Artikel 3 (subject to)", note: "Not resolved in the document" }]);
  });
});

describe("safe fallback", () => {
  it("reports a requirement, predicate, exception or calculation of an unknown kind instead of guessing", () => {
    const rule = base({
      applicability: { conditions: { kind: "fuzzy", fact: "x" } },
      requirements: [{ kind: "spline", fact: "x" }, { kind: "formula", fact: "y", operator: "==", unit: "m", expression: { kind: "operation", operator: "pow", operands: [{ kind: "literal", value: 2 }, { kind: "literal", value: 3 }] } }],
      exceptions: [{ kind: "maybe", description: "?" }],
    });
    const reading = readRule(rule);
    expect(reading.gaps).toEqual([
      "Applies when: unknown kind “fuzzy”", "Requirement 1: unknown kind “spline”", "Requirement 2 › formula: unknown kind “operation”", "Exception 1: unknown kind “maybe”",
    ]);
    expect(readingText(reading)).toContain("This part cannot be shown in plain language");
    expect(readingText(reading)).toContain("[a calculation that cannot be shown]");
  });

  it("says so when a record states neither a requirement nor a definition", () => {
    expect(readRule(base({})).gaps).toEqual(["The record states no requirement and no definition"]);
  });

  it("never throws on malformed parts", () => {
    expect(() => readRule({ classification: null, applicability: "x", requirements: [null, 3], exceptions: [null] } as never)).not.toThrow();
  });
});

describe("preservation", () => {
  /** Every number and every unit of the record's meaning appears in the reading: nothing is dropped or rounded. */
  it("keeps every value and unit of a rich record (applicability, requirements, exceptions)", () => {
    const rule = base({
      applicability: { conditions: { kind: "all", conditions: [
        { kind: "comparison", fact: "height", operator: "<=", value: 13, valueType: "number", unit: "m" },
        { kind: "comparison", fact: "unit_area", operator: "<", value: 400.5, valueType: "number", unit: "m2" },
      ] } },
      requirements: [{ kind: "numeric", fact: "door_width", operator: ">=", value: 0.9, unit: "m" }, { kind: "numeric", fact: "temperature", operator: "<=", value: 35, unit: "Cel" }],
      exceptions: [{ kind: "exemption", description: "Ausnahme.", condition: { kind: "comparison", fact: "storeys", operator: ">", value: 3, valueType: "integer" }, requirements: [{ kind: "numeric", fact: "door_width", operator: ">=", value: 1.2, unit: "m" }] }],
    });
    const out = readingText(readRule(rule));
    for (const piece of ["at most 13 m", "less than 400.5 m²", "at least 0.9 m", "at most 35 °C", "storeys is more than 3", "door width is at least 1.2 m", "Exemption: Ausnahme."]) expect(out).toContain(piece);
  });
});
