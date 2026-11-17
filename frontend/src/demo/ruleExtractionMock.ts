// MOCK DATA for the Rule Extraction & Mapping preview (UI Preview · Coming Soon). None of this is derived from the
// uploaded document or produced by an LLM: the real extraction pipeline does not exist yet. Kept separate from any
// production API data so it is obvious at a glance which parts of the page are real.

export type RuleStatus = "auto" | "review";

export interface MockRule {
  id: string;
  title: string;
  status: RuleStatus;
  confidence: number;
  sourceRef: string;
  sourceText: string;
  json: {
    rule_id: string;
    entity: string;
    property: string;
    operator: string;
    value: number | string | boolean;
    unit: string | null;
    source: string;
  };
}

const rule = (id: string, title: string, status: RuleStatus, confidence: number, json: MockRule["json"], sourceText: string): MockRule => ({
  id, title, status, confidence, sourceRef: json.source, sourceText, json,
});

/** Twelve example rules in the shape the real extraction would produce, standing in until the LLM pipeline is wired up. */
export const MOCK_RULES: MockRule[] = [
  rule("R-001", "Mindestbreite von Türen", "auto", 0.93,
    { rule_id: "R-001", entity: "Door", property: "clear_width", operator: ">=", value: 0.9, unit: "m", source: "§ 4 Abs. 3 MusterBauVO" },
    "(3) Türen müssen eine lichte Breite von mindestens 0,90 m haben."),
  rule("R-002", "Brandabschnitte", "auto", 0.91,
    { rule_id: "R-002", entity: "FireCompartment", property: "max_area", operator: "<=", value: 1600, unit: "m2", source: "§ 28 Abs. 2 MusterBauVO" },
    "(2) Brandabschnitte dürfen eine Fläche von 1.600 m² nicht überschreiten."),
  rule("R-003", "Fluchtwege und Rettungswege", "review", 0.62,
    { rule_id: "R-003", entity: "EscapeRoute", property: "max_length", operator: "<=", value: 35, unit: "m", source: "§ 33 Abs. 1 MusterBauVO" },
    "(1) Rettungswege dürfen eine Lauflänge von 35 m nicht überschreiten."),
  rule("R-004", "Maximale Kinderzahl pro Jahrgang", "auto", 0.88,
    { rule_id: "R-004", entity: "Classroom", property: "max_occupancy", operator: "<=", value: 25, unit: null, source: "§ 45 Abs. 4 MusterBauVO" },
    "(4) Die Zahl der Kinder je Klassenraum soll 25 nicht überschreiten."),
  rule("R-005", "Klassenzimmerfläche", "review", 0.58,
    { rule_id: "R-005", entity: "Classroom", property: "min_area_per_pupil", operator: ">=", value: 1.6, unit: "m2", source: "§ 45 Abs. 5 MusterBauVO" },
    "(5) Je Schüler ist eine Grundfläche von mindestens 1,6 m² vorzusehen."),
  rule("R-006", "Blitzschutzanlage", "auto", 0.95,
    { rule_id: "R-006", entity: "Building", property: "lightning_protection", operator: "==", value: true, unit: null, source: "§ 17 Abs. 1 MusterBauVO" },
    "(1) Gebäude sind mit Blitzschutzanlagen auszustatten, soweit nach Art oder Nutzung ein Blitzschlag zu schweren Folgen führen kann."),
  rule("R-007", "Treppenbreite", "auto", 0.89,
    { rule_id: "R-007", entity: "Staircase", property: "clear_width", operator: ">=", value: 1.0, unit: "m", source: "§ 32 Abs. 1 MusterBauVO" },
    "(1) Notwendige Treppen müssen eine nutzbare Breite von mindestens 1,00 m haben."),
  rule("R-008", "Notbeleuchtung", "auto", 0.92,
    { rule_id: "R-008", entity: "EscapeRoute", property: "emergency_lighting", operator: "==", value: true, unit: null, source: "§ 33 Abs. 5 MusterBauVO" },
    "(5) Rettungswege sind mit einer Sicherheitsbeleuchtung auszustatten."),
  rule("R-009", "Abstandsflächen", "review", 0.67,
    { rule_id: "R-009", entity: "Building", property: "min_setback", operator: ">=", value: 3.0, unit: "m", source: "§ 6 Abs. 5 MusterBauVO" },
    "(5) Die Tiefe der Abstandsfläche beträgt mindestens 3 m."),
  rule("R-010", "Stellplätze pro Wohnung", "auto", 0.85,
    { rule_id: "R-010", entity: "Dwelling", property: "min_parking_spaces", operator: ">=", value: 1, unit: null, source: "§ 48 Abs. 1 MusterBauVO" },
    "(1) Je Wohnung ist mindestens ein Stellplatz herzustellen."),
  rule("R-011", "Rauchwarnmelder", "auto", 0.94,
    { rule_id: "R-011", entity: "Dwelling", property: "smoke_detector", operator: "==", value: true, unit: null, source: "§ 47 Abs. 4 MusterBauVO" },
    "(4) In Wohnungen müssen Schlafräume, Kinderzimmer und Flure mit Rauchwarnmeldern ausgestattet sein."),
  rule("R-012", "Aufzugspflicht", "review", 0.55,
    { rule_id: "R-012", entity: "Building", property: "elevator_required", operator: "==", value: true, unit: null, source: "§ 39 Abs. 4 MusterBauVO" },
    "(4) Gebäude mit mehr als 13 m Höhe müssen einen Aufzug haben."),
];

export const AUTO_ACCEPTED_COUNT = MOCK_RULES.filter((r) => r.status === "auto").length;
export const NEEDS_REVIEW_COUNT = MOCK_RULES.filter((r) => r.status === "review").length;
