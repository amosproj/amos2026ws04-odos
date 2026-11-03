// Helpers shared by the fixture script (scripts/build-demo-fixtures.mjs, in Node) and the live mode of the app
// (src/demo/live.ts, in the browser). Plain JavaScript so both can import it unchanged.

export const pick = (o, keys) => Object.fromEntries(keys.filter((k) => o[k] !== undefined).map((k) => [k, o[k]]));

export function findNode(node, id) {
  if (Array.isArray(node)) {
    for (const n of node) {
      const hit = findNode(n, id);
      if (hit) return hit;
    }
    return null;
  }
  if (!node || typeof node !== "object") return null;
  if (node.id === id) return node;
  return findNode(node.children ?? [], id);
}

// Presentation names (temporary, for the stakeholder presentation): only the key is renamed, in place; values, order,
// ids and hierarchy stay. The Legal JSON schema, document.json and every download keep `nativeType`.
const PRESENTATION_NAMES = { nativeType: "germanType" };

export function forPresentation(value) {
  if (Array.isArray(value)) return value.map(forPresentation);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value).map(([k, v]) => [PRESENTATION_NAMES[k] ?? k, forPresentation(v)]));
}

/** Indented JSON with page lists on one line ("pages": [9, 10]). */
export const toJsonText = (value) =>
  JSON.stringify(value, null, 2).replace(/\[\s+(\d+(?:,\s+\d+)*)\s+\]/g, (_m, ns) => `[${ns.split(/,\s+/).join(", ")}]`);
