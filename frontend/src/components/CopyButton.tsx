import { useEffect, useState, type RefObject } from "react";
import { cx } from "../lib/css";

type CopyState = "idle" | "copied" | "selected";

interface CopyButtonProps {
  text: string;
  /** What is copied, inside a sentence: "the Nextdoor setting". */
  what: string;
  /** Selected instead when the browser blocks the clipboard, so it can be copied by hand. */
  target: RefObject<HTMLElement | null>;
  /** The button's visible word; "Copy" unless the place calls for more. */
  label?: string;
  className?: string;
}

/** Copies a line; where the browser blocks the clipboard, selects the line so it can be copied by hand. */
export function CopyButton({ text, what, target, label = "Copy", className }: CopyButtonProps) {
  const [state, setState] = useState<CopyState>("idle");
  useEffect(() => {
    if (state === "idle") return;
    const timer = window.setTimeout(
      () => {
        setState("idle");
      },
      state === "copied" ? 1800 : 6000,
    );
    return () => {
      window.clearTimeout(timer);
    };
  }, [state]);
  const keys = navigator.userAgent.includes("Mac") ? "⌘C" : "Ctrl+C";
  const select = () => {
    const selection = window.getSelection();
    if (!target.current || !selection) return;
    selection.selectAllChildren(target.current);
    setState("selected");
  };
  const status = state === "copied" ? `Copied ${what}` : state === "selected" ? `Selected ${what}: press ${keys} to copy it` : "";
  return (
    <>
      <button
        type="button"
        className={cx("copy mono", className)}
        data-state={state}
        aria-label={`Copy ${what}`}
        onClick={() => {
          if (!("clipboard" in navigator)) {
            select();
            return;
          }
          navigator.clipboard.writeText(text).then(() => {
            setState("copied");
          }, select);
        }}
      >
        {state === "copied" ? "Copied" : state === "selected" ? `Press ${keys}` : label}
      </button>
      <span className="sr-only" role="status">
        {status}
      </span>
    </>
  );
}
