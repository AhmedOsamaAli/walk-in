import type { AnchorHTMLAttributes } from "react";
import { useNavigate } from "../lib/navigation";
import { preloadLink } from "../preload";

type LinkProps = AnchorHTMLAttributes<HTMLAnchorElement> & { href: string };

/**
 * A link to another page of the app: a plain click changes the page in place; a modified click opens it as usual. What
 * the page needs (its code, its survey or kit) starts loading as the link is pointed at, touched or focused.
 */
export function Link({ href, onClick, onPointerEnter, onFocus, ...rest }: LinkProps) {
  const navigate = useNavigate();
  return (
    <a
      {...rest}
      href={href}
      onPointerEnter={(event) => {
        onPointerEnter?.(event);
        preloadLink(href);
      }}
      onFocus={(event) => {
        onFocus?.(event);
        preloadLink(href);
      }}
      onClick={(event) => {
        onClick?.(event);
        const modified = event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
        if (event.defaultPrevented || event.button !== 0 || modified) return;
        if (rest.target && rest.target !== "_self") return;
        event.preventDefault();
        navigate(href);
      }}
    />
  );
}
