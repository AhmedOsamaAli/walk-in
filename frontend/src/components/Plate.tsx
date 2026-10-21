import { list } from "../lib/format";

const TILES = [
  { className: "pl-a", title: "Ambience", style: "big" },
  { className: "pl-b", title: "Decor", style: "ser" },
  { className: "pl-c", title: "Setting", style: "ser" },
  { className: "pl-d", title: "On the menu", style: "ser" },
  { className: "pl-e", title: "Amenities", style: "ser" },
] as const;

/** The design DNA of the locals' favorite places, set as a color plate. */
export function Plate({ dna }: { dna: Record<string, unknown> }) {
  const pick = (key: string, count: number) => list(dna[key]).slice(0, count);
  const menu = pick("menu", 2).length ? pick("menu", 2) : pick("offerings", 2);
  const texts = [
    pick("ambience", 3).join(" / ") || "Warm, welcoming",
    pick("decor", 2).join(", ") || "Open",
    pick("setting", 2).join(", ") || "Street level",
    menu.join(", ") || "House specials",
    pick("amenities", 3).join(", ") || "Seating",
  ];
  return (
    <div className="plate">
      {TILES.map((tile, k) => (
        <div key={tile.className} className={tile.className}>
          <span className="mono">{tile.title}</span>
          <span className={tile.style}>{texts[k]}</span>
        </div>
      ))}
    </div>
  );
}
