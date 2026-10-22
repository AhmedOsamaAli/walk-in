import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import type { User } from "../api/account";
import { forgetGoogleChoice } from "../lib/google";
import { PLACES_URL } from "../lib/routes";
import { session, useSession } from "../state/session";
import { Avatar } from "./Avatar";
import { Link } from "./Link";
import { SignInOptions } from "./SignIn";

/** The menu's items, for arrow-key focus. */
function menuItems(menu: HTMLElement | null): HTMLElement[] {
  return menu ? Array.from(menu.querySelectorAll<HTMLElement>('[role="menuitem"]')) : [];
}

/** Set when signing in or out from the open popup replaced the control: the new one takes focus. */
let handFocus = false;

function AccountControl({
  user,
  busy,
  error,
  pending = false,
}: {
  user: User | null;
  busy: boolean;
  error: string | null;
  /** Nobody is known to be signed in yet: the control shows signed out, and eases in rather than flashing. */
  pending?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const isOpen = useRef(false);
  const focusOnOpen = useRef<"first" | "last" | "panel" | null>(null);
  const popupId = useId();

  useEffect(() => {
    if (handFocus) {
      handFocus = false;
      trigger.current?.focus();
    }
    return () => {
      if (isOpen.current) handFocus = true;
    };
  }, []);

  useEffect(() => {
    isOpen.current = open;
    if (!open) return;
    const target = focusOnOpen.current;
    focusOnOpen.current = null;
    if (target === "panel") popup.current?.focus();
    else if (target) {
      const items = menuItems(menu.current);
      (target === "first" ? items[0] : items.at(-1))?.focus();
    }
    const outside = (event: PointerEvent) => {
      const node = event.target as Node | null;
      if (node && (trigger.current?.contains(node) || popup.current?.contains(node))) return;
      setOpen(false);
    };
    // A link inside it (My places, the privacy note) moves the page on: the popup goes with the page it opened on.
    const moved = () => {
      setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    window.addEventListener("popstate", moved);
    return () => {
      document.removeEventListener("pointerdown", outside);
      window.removeEventListener("popstate", moved);
    };
  }, [open]);

  function show(focus: "first" | "last" | "panel") {
    focusOnOpen.current = focus;
    session.clearError();
    setOpen(true);
  }

  function close(returnFocus: boolean) {
    setOpen(false);
    if (returnFocus) trigger.current?.focus();
  }

  function onMenuKey(event: KeyboardEvent<HTMLDivElement>) {
    const items = menuItems(menu.current);
    const at = items.indexOf(document.activeElement as HTMLElement);
    let next: HTMLElement | undefined;
    if (event.key === "ArrowDown") next = items[(at + 1) % items.length];
    else if (event.key === "ArrowUp") next = items[(at - 1 + items.length) % items.length];
    else if (event.key === "Home") next = items[0];
    else if (event.key === "End") next = items.at(-1);
    else if (event.key === "Escape") {
      event.preventDefault();
      close(true);
      return;
    } else {
      if (event.key === "Tab") close(false);
      return;
    }
    event.preventDefault();
    next?.focus();
  }

  if (user) {
    const name = user.name || user.email;
    return (
      <div className="account">
        <button
          ref={trigger}
          type="button"
          className="avatar"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={open ? popupId : undefined}
          aria-label={`Account: ${name}`}
          title={name}
          onClick={() => {
            if (open) close(false);
            else show("first");
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              show(event.key === "ArrowDown" ? "first" : "last");
            }
          }}
        >
          <Avatar user={user} />
        </button>
        {open ? (
          <div ref={popup} className="account-pop">
            <p className="account-who">
              <b>{user.name || "Signed in"}</b>
              <span>{user.email}</span>
            </p>
            <div ref={menu} id={popupId} role="menu" aria-label="Account" className="account-menu" onKeyDown={onMenuKey}>
              <Link
                role="menuitem"
                tabIndex={-1}
                className="account-item"
                href={PLACES_URL}
                onClick={() => {
                  close(false);
                }}
              >
                <span>My places</span>
                <span aria-hidden="true">→</span>
              </Link>
              <button
                role="menuitem"
                tabIndex={-1}
                type="button"
                className="account-item"
                aria-disabled={busy || undefined}
                onClick={() => {
                  if (busy) return;
                  void session.signOut().then((done) => {
                    if (done) forgetGoogleChoice();
                  });
                }}
              >
                <span>{busy ? "Signing out…" : "Sign out"}</span>
              </button>
            </div>
            {error ? (
              <p className="signin-error" role="alert">
                {error}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="account" data-pending={pending || undefined}>
      <button
        ref={trigger}
        type="button"
        className="account-signin mono"
        aria-expanded={open}
        aria-controls={open ? popupId : undefined}
        onClick={() => {
          if (open) close(false);
          else show("panel");
        }}
      >
        Sign in
      </button>
      {open ? (
        <div
          ref={popup}
          id={popupId}
          className="account-pop account-panel"
          role="dialog"
          aria-label="Sign in"
          tabIndex={-1}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              close(true);
            }
          }}
          onBlur={(event) => {
            // Tabbing past the panel closes it; focus moving into Google's button (an iframe) has no target and stays.
            const next = event.relatedTarget;
            if (next && !popup.current?.contains(next) && !trigger.current?.contains(next)) close(false);
          }}
        >
          <p className="account-title">Sign in to Walk-in</p>
          <SignInOptions why="Your surveys are then saved to My places, on any device. Running a survey never needs an account." />
        </div>
      ) : null}
    </div>
  );
}

/**
 * The account control in the top bar. Signed out, "Sign in" opens the ways to sign in; signed in, the avatar opens a
 * menu with My places and Sign out, operated with the keyboard like any menu button. Until the server says who is
 * signed in (a napping engine can take a minute), it shows signed out.
 */
export function AccountMenu() {
  const { phase, user, busy, error } = useSession();
  // A new control for each account, so signing in or out closes whatever the old one had open.
  return (
    <AccountControl
      key={user?.id ?? "signed-out"}
      user={user}
      busy={busy}
      error={error}
      pending={phase === "loading" && !user}
    />
  );
}
