import type { AnchorHTMLAttributes } from "react";
import { useNavigate } from "../lib/navigation";

type LinkProps = AnchorHTMLAttributes<HTMLAnchorElement> & { href: string };

/** A link to another page of the app: a plain click changes the page in place; a modified click opens it as usual. */
export function Link({ href, onClick, ...rest }: LinkProps) {
  const navigate = useNavigate();
  return (
    <a
      {...rest}
      href={href}
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
