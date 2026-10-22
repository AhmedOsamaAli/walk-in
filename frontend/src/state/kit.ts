import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { commerce, type KitView } from "../api/commerce";
import { plainError } from "../lib/commerce";

export const KIT_POLL_MS = 2000;
/** Polls that fail in a row before the page stops asking and says so. */
export const KIT_POLL_TRIES = 5;
export const KIT_GONE = "This kit link isn't valid, or the kit is no longer available.";

/** What following a kit that is being built needs; the hook passes the network and a timer, tests pass stand-ins. */
export interface KitPoll {
  load: () => Promise<KitView>;
  /** Waits for the next poll; resolves false once following was cancelled. */
  wait: () => Promise<boolean>;
  cancelled: () => boolean;
  /** Each copy of the kit, as it is read. */
  update: (view: KitView) => void;
  /** Polling gave up: the kit is gone, or kept failing to load. */
  fail: (message: string, gone: boolean) => void;
}

/** Polls a kit every couple of seconds until it is no longer being built. */
export async function followKit(poll: KitPoll): Promise<void> {
  let failures = 0;
  while (await poll.wait()) {
    let view: KitView;
    try {
      view = await poll.load();
    } catch (error) {
      if (poll.cancelled()) return;
      const gone = error instanceof ApiError && error.status === 404;
      failures += 1;
      if (gone || failures >= KIT_POLL_TRIES) {
        poll.fail(gone ? KIT_GONE : plainError(error, "The kit stopped answering. Reload the page to check on it."), gone);
        return;
      }
      continue;
    }
    if (poll.cancelled()) return;
    failures = 0;
    poll.update(view);
    if (view.status !== "building") return;
  }
}

/** Resolves true after `ms`, or false as soon as the signal aborts. */
export function pause(ms: number, signal: AbortSignal): Promise<boolean> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve(false);
      return;
    }
    const cancel = () => {
      window.clearTimeout(timer);
      resolve(false);
    };
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", cancel);
      resolve(true);
    }, ms);
    signal.addEventListener("abort", cancel, { once: true });
  });
}

export type KitLoad =
  | { state: "loading" }
  | { state: "shown"; view: KitView; stalled: string | null }
  | { state: "missing" }
  | { state: "failed"; message: string };

/**
 * A kit by its token, followed every two seconds while it is being built. `restart` follows it again (after a retry);
 * `replace` shows a copy the page already has (after a refund).
 */
export function useKit(token: string, signedIn: string | null) {
  const [load, setLoad] = useState<{ token: string; load: KitLoad }>({ token, load: { state: "loading" } });
  const [run, setRun] = useState(0);

  useEffect(() => {
    const abort = new AbortController();
    const show = (next: KitLoad) => {
      if (!abort.signal.aborted) setLoad({ token, load: next });
    };
    void (async () => {
      let view: KitView;
      try {
        view = await commerce.kit(token, abort.signal);
      } catch (error) {
        if (abort.signal.aborted) return;
        show(error instanceof ApiError && error.status === 404 ? { state: "missing" } : { state: "failed", message: plainError(error, "The kit could not be loaded.") });
        return;
      }
      show({ state: "shown", view, stalled: null });
      if (view.status !== "building") return;
      await followKit({
        load: () => commerce.kit(token, abort.signal),
        wait: () => pause(KIT_POLL_MS, abort.signal),
        cancelled: () => abort.signal.aborted,
        update: (next) => {
          show({ state: "shown", view: next, stalled: null });
        },
        fail: (message, gone) => {
          if (gone) show({ state: "missing" });
          else setLoad((previous) => (previous.load.state === "shown" && !abort.signal.aborted ? { token, load: { ...previous.load, stalled: message } } : previous));
        },
      });
    })();
    return () => {
      abort.abort();
    };
    // Signing in or out changes whether the reader owns the kit, so it is read again.
  }, [token, run, signedIn]);

  const restart = useCallback(() => {
    setRun((count) => count + 1);
  }, []);

  const replace = useCallback(
    (view: KitView) => {
      setLoad({ token, load: { state: "shown", view, stalled: null } });
    },
    [token],
  );

  return { load: load.token === token ? load.load : ({ state: "loading" } as const), restart, replace };
}
