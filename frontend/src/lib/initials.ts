/** Up to two initials of a name, shown in place of a photo that is missing or fails to load: "Action Bronson" -> "AB". */
export function initials(name: string | null | undefined): string {
  const words = (name ?? "")
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .split(/\s+/)
    .filter(Boolean);
  const kept = words.length > 1 && /^the$/i.test(words[0] ?? "") ? words.slice(1) : words;
  return kept
    .slice(0, 2)
    .map((word) => (Array.from(word)[0] ?? "").toUpperCase())
    .join("");
}
