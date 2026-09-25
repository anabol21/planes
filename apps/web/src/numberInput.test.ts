import { describe, expect, it } from "vitest";

import { formatDecimalInput, normalizeDecimalDraft, parseDecimalInput } from "./numberInput";

describe("parseDecimalInput", () => {
  it("accepts a dotted coordinate and a comma decimal as the same number", () => {
    expect(parseDecimalInput("37.6000")).toBe(37.6);
    expect(parseDecimalInput("37,6000")).toBe(37.6);
    expect(parseDecimalInput("55.7470")).toBe(55.747);
    expect(parseDecimalInput("55,7470")).toBe(55.747);
    expect(parseDecimalInput("144,7")).toBe(144.7);
    expect(parseDecimalInput("30,31")).toBe(30.31);
  });

  it("accepts plain speeds and limits", () => {
    expect(parseDecimalInput("15")).toBe(15);
    expect(parseDecimalInput("2400")).toBe(2400);
    expect(parseDecimalInput("3")).toBe(3);
    expect(parseDecimalInput("270")).toBe(270);
    expect(parseDecimalInput("30")).toBe(30);
  });

  it("accepts a leading minus for coordinates", () => {
    expect(parseDecimalInput("-37.6")).toBe(-37.6);
    expect(parseDecimalInput("-37,6")).toBe(-37.6);
  });

  it("keeps an in-progress fraction usable without a mask", () => {
    expect(parseDecimalInput("37.")).toBe(37);
    expect(parseDecimalInput("37,")).toBe(37);
    expect(parseDecimalInput(".5")).toBe(0.5);
  });

  it("rejects empty text, mixed separators, and extra words", () => {
    expect(parseDecimalInput("")).toBeNull();
    expect(parseDecimalInput(" ")).toBeNull();
    expect(parseDecimalInput("-")).toBeNull();
    expect(parseDecimalInput("37.60,00")).toBeNull();
    expect(parseDecimalInput("1.447,5")).toBeNull();
    expect(parseDecimalInput("37.6000 lon")).toBeNull();
    expect(parseDecimalInput("abc")).toBeNull();
  });
});

describe("formatDecimalInput", () => {
  it("displays one dotted format", () => {
    expect(formatDecimalInput(37.6)).toBe("37.6");
    expect(formatDecimalInput(55.747)).toBe("55.747");
    expect(formatDecimalInput(144.7)).toBe("144.7");
    expect(formatDecimalInput(30.31)).toBe("30.31");
    expect(formatDecimalInput(15)).toBe("15");
    expect(formatDecimalInput(2400)).toBe("2400");
    expect(formatDecimalInput(-37.6)).toBe("-37.6");
  });

  it("round-trips comma entry into a JSON number with a dot", () => {
    const lon = parseDecimalInput("37,6000");
    const lat = parseDecimalInput("55,7470");
    expect(lon).not.toBeNull();
    expect(lat).not.toBeNull();
    expect(formatDecimalInput(lon as number)).toBe("37.6");
    expect(formatDecimalInput(lat as number)).toBe("55.747");
    expect(JSON.stringify({ lon, lat })).toBe('{"lon":37.6,"lat":55.747}');
  });
});

describe("normalizeDecimalDraft", () => {
  it("rewrites a comma to a dot and keeps the typed fraction", () => {
    expect(normalizeDecimalDraft("37,6000")).toBe("37.6000");
    expect(normalizeDecimalDraft("55,7470")).toBe("55.7470");
    expect(normalizeDecimalDraft("144,7")).toBe("144.7");
    expect(normalizeDecimalDraft(" 30,31 ")).toBe("30.31");
  });
});
