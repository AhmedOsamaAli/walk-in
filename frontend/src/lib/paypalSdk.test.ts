import { describe, expect, it } from "vitest";
import { namespaceOf, SDK_URLS } from "./paypalSdk";

describe("PayPal's JS SDK v6", () => {
  it("loads its core script from PayPal, for the sandbox or live", () => {
    expect(SDK_URLS.sandbox).toBe("https://www.sandbox.paypal.com/web-sdk/v6/core");
    expect(SDK_URLS.live).toBe("https://www.paypal.com/web-sdk/v6/core");
  });

  it("is ready once the script defines paypal.createInstance", () => {
    const createInstance = () => Promise.reject(new Error("unused"));
    expect(namespaceOf({ createInstance })).toEqual({ createInstance });
    // The v5 SDK's namespace, or nothing at all, is not it.
    expect(namespaceOf({ Buttons: () => undefined })).toBeNull();
    expect(namespaceOf({ createInstance: "no" })).toBeNull();
    expect(namespaceOf(undefined)).toBeNull();
    expect(namespaceOf(null)).toBeNull();
  });
});
