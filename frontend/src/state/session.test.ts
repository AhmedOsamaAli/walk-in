import { describe, expect, it, vi } from "vitest";
import type { AppConfig, User } from "../api/account";
import { ApiError } from "../api/client";
import { createSessionStore, INITIAL_SESSION, type SessionApi } from "./session";

const CONFIG: AppConfig = { google_client_id: "123.apps.googleusercontent.com", dev_login: false };
const ADA: User = { id: "u1", email: "ada@example.com", name: "Ada Lovelace", picture: null };
const BOB: User = { id: "u2", email: "bob@example.com", name: "Bob", picture: "https://lh3.googleusercontent.com/b" };

/** A promise the test settles by hand. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function fakeApi(overrides: Partial<SessionApi> = {}): SessionApi {
  return {
    config: vi.fn(() => Promise.resolve(CONFIG)),
    me: vi.fn(() => Promise.resolve({ user: null })),
    signInGoogle: vi.fn(() => Promise.resolve({ user: ADA })),
    signInDev: vi.fn((email: string, name: string) => Promise.resolve({ user: { ...ADA, email, name } })),
    signOut: vi.fn(() => Promise.resolve(undefined)),
    deleteMe: vi.fn(() => Promise.resolve(undefined)),
    ...overrides,
  };
}

describe("session", () => {
  it("loads the settings and who is signed in once", async () => {
    const api = fakeApi({ me: vi.fn(() => Promise.resolve({ user: ADA })) });
    const store = createSessionStore(api);
    expect(store.get()).toEqual(INITIAL_SESSION);
    await Promise.all([store.load(), store.load()]);
    await store.load();
    expect(store.get()).toEqual({ phase: "ready", config: CONFIG, user: ADA, busy: false, error: null });
    expect(api.config).toHaveBeenCalledTimes(1);
    expect(api.me).toHaveBeenCalledTimes(1);
  });

  it("says why the settings failed, and loads them again when asked", async () => {
    let calls = 0;
    const api = fakeApi({
      config: vi.fn(() => {
        calls += 1;
        return calls === 1 ? Promise.reject(new TypeError("Failed to fetch")) : Promise.resolve(CONFIG);
      }),
    });
    const store = createSessionStore(api);
    await store.load();
    expect(store.get().phase).toBe("failed");
    expect(store.get().error).toBe("Walk-in can't be reached. Check your connection and try again.");
    await store.load();
    expect(store.get()).toMatchObject({ phase: "ready", config: CONFIG, error: null });
  });

  it("signs in with Google and with the development form", async () => {
    const api = fakeApi();
    const store = createSessionStore(api);
    await store.load();
    const seen: boolean[] = [];
    const stop = store.subscribe(() => seen.push(store.get().busy));
    expect(await store.signInWithGoogle("id-token")).toBe(true);
    expect(api.signInGoogle).toHaveBeenCalledWith("id-token");
    expect(store.get().user).toEqual(ADA);
    expect(seen).toEqual([true, false]);
    stop();
    expect(await store.signInDev("tester@example.com", "Tester")).toBe(true);
    expect(store.get().user).toMatchObject({ email: "tester@example.com", name: "Tester" });
    expect(seen).toEqual([true, false]);
  });

  it("keeps the server's reason when a sign-in fails", async () => {
    const api = fakeApi({
      signInGoogle: vi.fn(() => Promise.reject(new ApiError("That Google sign-in has expired.", 400, null, true))),
    });
    const store = createSessionStore(api);
    await store.load();
    expect(await store.signInWithGoogle("old")).toBe(false);
    expect(store.get()).toMatchObject({ user: null, busy: false, error: "That Google sign-in has expired." });
    store.clearError();
    expect(store.get().error).toBeNull();
  });

  it("never lets an older answer undo a sign-in", async () => {
    const who = deferred<{ user: User | null }>();
    const api = fakeApi({ me: vi.fn(() => who.promise) });
    const store = createSessionStore(api);
    const loading = store.load();
    await store.signInWithGoogle("id-token");
    who.resolve({ user: null });
    await loading;
    expect(store.get().user).toEqual(ADA);
  });

  it("signs out, and keeps the user when signing out fails", async () => {
    const api = fakeApi({ me: vi.fn(() => Promise.resolve({ user: BOB })) });
    const store = createSessionStore(api);
    await store.load();
    expect(await store.signOut()).toBe(true);
    expect(store.get().user).toBeNull();

    const failing = createSessionStore(fakeApi({ me: vi.fn(() => Promise.resolve({ user: BOB })), signOut: () => Promise.reject(new ApiError("Request failed (500).", 500)) }));
    await failing.load();
    expect(await failing.signOut()).toBe(false);
    expect(failing.get()).toMatchObject({ user: BOB, error: "Walk-in's server had a problem. Try again in a moment." });
  });

  it("checks again who is signed in", async () => {
    let user: User | null = ADA;
    const store = createSessionStore(fakeApi({ me: vi.fn(() => Promise.resolve({ user })) }));
    await store.load();
    user = null;
    await store.refresh();
    expect(store.get().user).toBeNull();
  });

  it("deletes the account and ends signed out", async () => {
    const api = fakeApi({ me: vi.fn(() => Promise.resolve({ user: ADA })) });
    const store = createSessionStore(api);
    await store.load();
    const seen: boolean[] = [];
    store.subscribe(() => seen.push(store.get().busy));
    expect(await store.deleteAccount()).toBe(true);
    expect(api.deleteMe).toHaveBeenCalledTimes(1);
    expect(store.get()).toMatchObject({ user: null, busy: false, error: null });
    expect(seen).toEqual([true, false]);
  });

  it("keeps the account when deleting it fails, and says nothing was removed", async () => {
    const store = createSessionStore(
      fakeApi({ me: vi.fn(() => Promise.resolve({ user: ADA })), deleteMe: () => Promise.reject(new ApiError("Request failed (500).", 500)) }),
    );
    await store.load();
    expect(await store.deleteAccount()).toBe(false);
    expect(store.get()).toMatchObject({ user: ADA, busy: false, error: "Walk-in's server had a problem. Try again in a moment." });
    const offline = createSessionStore(
      fakeApi({ me: vi.fn(() => Promise.resolve({ user: ADA })), deleteMe: () => Promise.reject(new Error("?")) }),
    );
    await offline.load();
    await offline.deleteAccount();
    expect(offline.get().error).toBe("Your account could not be deleted. Nothing was removed; try again.");
  });

  it("never lets an older answer undo a deletion", async () => {
    const who = deferred<{ user: User | null }>();
    const store = createSessionStore(fakeApi({ me: vi.fn(() => who.promise) }));
    const loading = store.load();
    await store.deleteAccount();
    who.resolve({ user: ADA });
    await loading;
    expect(store.get().user).toBeNull();
  });
});
