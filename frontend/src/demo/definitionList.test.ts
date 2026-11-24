import { describe, expect, it } from "vitest";
import { parseDefinitionList, type DefItem } from "./definitionList";
import { splitChecks } from "./ruleResults";

const KLASSEN = "Gebäude werden in folgende Gebäudeklassen eingeteilt: Gebäudeklasse 1: a) freistehende Gebäude mit einer Höhe bis zu 7 m und nicht mehr als zwei Nutzungseinheiten von insgesamt nicht mehr als 400 m² und b) freistehende land- oder forstwirtschaftlich genutzte Gebäude; Gebäudeklasse 2: Gebäude mit einer Höhe bis zu 7 m; Gebäudeklasse 3: sonstige Gebäude mit einer Höhe bis zu 7 m; Gebäudeklasse 4: Gebäude mit einer Höhe bis zu 13 m; Gebäudeklasse 5: sonstige Gebäude einschließlich unterirdischer Gebäude.";
const SONDER = "Anlagen und Räume besonderer Art oder Nutzung, die einen der nachfolgenden Tatbestände erfüllen: 1. Hochhäuser (Gebäude mit einer Höhe nach Absatz 3 Satz 2 von mehr als 22 m); 2. bauliche Anlagen mit einer Höhe von mehr als 30 m; 3. Gebäude mit mehr als 1 600 m² Grundfläche; 4. Verkaufsstätten mit mehr als 800 m² Grundfläche.";
const flat = (items: DefItem[]): string => items.map((i) => `${i.marker} ${i.text} ${i.items ? flat(i.items) : ""}`).join(" ");
const words = (s: string) => s.replace(/\s+/g, " ").trim();

describe("definition lists", () => {
  it("splits numbered items at their own markers and keeps every word", () => {
    const l = parseDefinitionList(SONDER)!;
    expect(l.intro).toBe("Anlagen und Räume besonderer Art oder Nutzung, die einen der nachfolgenden Tatbestände erfüllen:");
    expect(l.items.map((i) => i.marker)).toEqual(["1.", "2.", "3.", "4."]);
    expect(l.items[0].text).toBe("Hochhäuser (Gebäude mit einer Höhe nach Absatz 3 Satz 2 von mehr als 22 m);");
    expect(words(`${l.intro} ${flat(l.items)}`)).toBe(words(SONDER));
  });

  it("splits labelled classes and their lettered sub-items", () => {
    const l = parseDefinitionList(KLASSEN)!;
    expect(l.items.map((i) => i.marker)).toEqual(["Gebäudeklasse 1", "Gebäudeklasse 2", "Gebäudeklasse 3", "Gebäudeklasse 4", "Gebäudeklasse 5"]);
    expect(l.items[0].items?.map((i) => i.marker)).toEqual(["a)", "b)"]);
    expect(l.items[0].items?.[0].text.endsWith("400 m² und")).toBe(true);
    expect(words(`${l.intro} ${flat(l.items).replace(/(Gebäudeklasse \d)/g, "$1:")}`)).toBe(words(KLASSEN));
  });

  it("leaves text without a reliable sequence as it is", () => {
    expect(parseDefinitionList("Aufenthaltsräume sind Räume, die zum nicht nur vorübergehenden Aufenthalt bestimmt sind.")).toBeNull();
    expect(parseDefinitionList("Gemäß Nummern 1 und 2. gilt Absatz 3.")).toBeNull(); // no "1." after a separator
    expect(parseDefinitionList("Die Höhe: 1. bis 7 m.")).toBeNull(); // a single item is not a list
  });
});

describe("automatic checks of definitions", () => {
  const DESC = "the source text of 'x' states '7 m', which no condition, requirement, duration or deadline of the records citing it contains; a threshold only in a description cannot be checked.";
  const SUMMARY = "the summary or a description states '7 m', which the record's conditions and requirements do not contain; express it as a predicate or requirement.";
  const SOURCE = "source element 'doc/x' is not in the document";
  it("treats numbers only in a definition's text as an informational note", () => {
    expect(splitChecks([DESC, SUMMARY, SOURCE], "definition")).toEqual({ checkFlags: [SOURCE], checkNotes: [DESC, SUMMARY] });
  });
  it("keeps the same result an issue for every other rule type", () => {
    expect(splitChecks([DESC], "obligation")).toEqual({ checkFlags: [DESC], checkNotes: [] });
  });
});
