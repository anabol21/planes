/**
 * Plain decimal entry for fleet, survey, and optimization fields.
 * A comma and a dot are both a decimal separator. Display stays dotted
 * so the scenario JSON stays a normal number.
 */

export function normalizeDecimalDraft(raw: string): string {
  return raw.replace(/[\s\u00a0\u202f]/g, "").replace(/,/g, ".");
}

export function parseDecimalInput(raw: string): number | null {
  const text = normalizeDecimalDraft(raw);
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(text)) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

export function formatDecimalInput(value: number): string {
  if (!Number.isFinite(value)) return "";
  if (Object.is(value, -0)) return "0";
  const plain = value.toString();
  if (!/[eE]/.test(plain)) return plain;
  const fixed = value.toFixed(12).replace(/\.?0+$/, "");
  return fixed === "-0" ? "0" : fixed;
}
