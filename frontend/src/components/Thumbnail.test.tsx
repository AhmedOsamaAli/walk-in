import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Thumbnail } from "./Thumbnail";

describe("Thumbnail", () => {
  it("shows Qloo's picture at thumbnail size, lazily and without a referrer, its name written beside it", () => {
    const html = renderToStaticMarkup(<Thumbnail image="https://images.qloo.com/i/ABC-123-420x-auto.jpg" name="Action Bronson" />);
    expect(html).toBe('<img src="https://images.qloo.com/i/ABC-123-200x-auto.jpg" alt="" loading="lazy" referrerPolicy="no-referrer"/>');
  });

  it("shows the name's initials when there is no picture, or none it may show", () => {
    const initials = '<span class="ph" aria-hidden="true">AB</span>';
    expect(renderToStaticMarkup(<Thumbnail image={null} name="Action Bronson" />)).toBe(initials);
    expect(renderToStaticMarkup(<Thumbnail image="javascript:alert(1)" name="Action Bronson" />)).toBe(initials);
  });
});
