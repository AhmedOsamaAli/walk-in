import type { GapRow } from "../api/types";
import { GapItem } from "./GapItem";
import { SectionHead } from "./SectionHead";

interface GapsSectionProps {
  gaps: GapRow[];
  openGap: number | null;
  onToggle: (index: number) => void;
}

export function GapsSection({ gaps, openGap, onToggle }: GapsSectionProps) {
  return (
    <section id="s-gaps" className="sec reveal">
      <SectionHead
        no="03"
        title="What's missing"
        note="Place types locals love, compared with same-size areas around the site and ranked by how under-supplied they are inside the walk. Open one to see the competitors and the places locals love most."
      />
      <div className="gap-key mono" aria-hidden="true">
        <span>
          <i className="k-score" />
          Gap score
        </span>
        <span>
          <i className="k-supply" />
          Inside the walk
        </span>
        <span>
          <i className="k-far" />
          Local favorites outside it
        </span>
      </div>
      <ol className="gaps">
        {gaps.length ? (
          gaps.map((gap, index) => (
            <GapItem key={`${gap.genre_id}-${index}`} gap={gap} index={index} open={openGap === index} onToggle={onToggle} />
          ))
        ) : (
          <li className="gap-empty serif">
            Not enough Qloo data around this site to rank what is missing. Try a busier block.
          </li>
        )}
      </ol>
    </section>
  );
}
