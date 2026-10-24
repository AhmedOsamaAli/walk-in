import type { GapRow } from "../api/types";
import { AREA } from "../map/pins";
import { GapItem } from "./GapItem";
import { SectionHead } from "./SectionHead";

interface GapsSectionProps {
  gaps: GapRow[];
  openGap: number | null;
  onToggle: (index: number) => void;
  /** The area inside a sentence, as the survey measured it: "the walk", or "the drive" for a drive or a road distance. */
  area?: string;
}

export function GapsSection({ gaps, openGap, onToggle, area = AREA }: GapsSectionProps) {
  return (
    <section id="s-gaps" className="sec reveal">
      <SectionHead
        no="03"
        title="What's missing"
        note={`Place types people here love, compared with same-size areas around the site and ranked by how under-supplied they are inside ${area}. Open one to see its competitors and the places people here love most, and where each one is on the map.`}
      />
      <div className="gap-key mono" aria-hidden="true">
        <span>
          <i className="k-score" />
          Gap score
        </span>
        <span>
          <i className="k-supply" />
          Inside {area}
        </span>
        <span>
          <i className="k-far" />
          Favorites of people here, outside it
        </span>
      </div>
      <ol className="gaps">
        {gaps.length ? (
          gaps.map((gap, index) => (
            <GapItem
              key={`${gap.genre_id}-${index}`}
              gap={gap}
              index={index}
              open={openGap === index}
              onToggle={onToggle}
              area={area}
            />
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
