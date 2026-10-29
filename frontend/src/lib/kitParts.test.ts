import { describe, expect, it } from "vitest";
import { KIT_PARTS, kitPart, partInHash } from "./kitParts";

describe("the kit's parts", () => {
  it("are the poster, the ad copy, the links, the report and Founders, in that order", () => {
    expect(KIT_PARTS.map((part) => part.id)).toEqual(["poster", "copy", "links", "report", "founders"]);
  });

  it("are named by their ids only", () => {
    expect(kitPart("links")).toBe("links");
    expect(kitPart("founders")).toBe("founders");
    expect(kitPart("Links")).toBeNull();
    expect(kitPart("")).toBeNull();
  });

  it("are read from an address's hash, the old section links included", () => {
    expect(partInHash("#report")).toBe("report");
    expect(partInHash("#founders")).toBe("founders");
    expect(partInHash("#kit-poster")).toBe("poster");
    expect(partInHash("#kit-copy")).toBe("copy");
    expect(partInHash("")).toBeNull();
    expect(partInHash("#")).toBeNull();
    expect(partInHash("#kit-own-link")).toBeNull();
    expect(partInHash("#main")).toBeNull();
  });
});
