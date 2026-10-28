import { useState } from "react";
import { thumbnailSources } from "../lib/format";
import { initials } from "../lib/initials";

/**
 * A small picture of a title or an artist (36–44 px, sized by its list's styles): Qloo's picture at thumbnail size,
 * then at the size the API sent should that one fail, then the name's initials, which also stand in when there is no
 * picture. The name is written beside it, so the picture has no alt text of its own.
 */
export function Thumbnail({ image, name }: { image: unknown; name: string | null | undefined }) {
  const [failures, setFailures] = useState(0);
  const src = thumbnailSources(image)[failures];
  return src ? (
    <img
      src={src}
      alt=""
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => {
        setFailures((count) => count + 1);
      }}
    />
  ) : (
    <span className="ph" aria-hidden="true">
      {initials(name)}
    </span>
  );
}
