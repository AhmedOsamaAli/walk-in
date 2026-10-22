import { useState } from "react";
import type { User } from "../api/account";
import { initials } from "../lib/account";
import { cx } from "../lib/css";
import { safeUrl } from "../lib/format";

/** The account's Google picture, or its initials on the highlighter when there is none or it fails to load. */
export function Avatar({ user, className }: { user: User; className?: string }) {
  const [broken, setBroken] = useState(false);
  const picture = safeUrl(user.picture);
  return (
    <span className={cx("avatar-face", className)} aria-hidden="true">
      {picture && !broken ? (
        <img
          className="avatar-img"
          src={picture}
          alt=""
          referrerPolicy="no-referrer"
          onError={() => {
            setBroken(true);
          }}
        />
      ) : (
        <span className="avatar-initials mono">{initials(user.name, user.email)}</span>
      )}
    </span>
  );
}
