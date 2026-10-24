import { describe, expect, it } from "vitest";
import { initials } from "./initials";

describe("initials", () => {
  it("takes the first letters of the first two words", () => {
    expect(initials("Action Bronson")).toBe("AB");
    expect(initials("Las Culturistas with Matt Rogers")).toBe("LC");
  });

  it("skips a leading 'The' and punctuation", () => {
    expect(initials("The Dave Chang Show")).toBe("DC");
    expect(initials("Seek Treatment with Cat & Pat")).toBe("ST");
    expect(initials("Glossier.")).toBe("G");
    expect(initials("The")).toBe("T");
  });

  it("keeps one letter for one word, digits and other scripts", () => {
    expect(initials("SZA")).toBe("S");
    expect(initials("2 Dope Queens")).toBe("2D");
    expect(initials("مقهى بوخارست")).toBe("مب");
  });

  it("gives nothing for no name", () => {
    expect(initials("")).toBe("");
    expect(initials(null)).toBe("");
    expect(initials(undefined)).toBe("");
  });
});
