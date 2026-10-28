/* The brief being filled in: the site (a place searched for, or a pin dropped on the map), the form's answers, and the
   area traced around the site as the form asks for it. */
import { useState } from "react";
import type { PlaceHit } from "../api/types";
import { briefArea, initialBrief, type BriefForm } from "./brief";
import { useSiteWalk, type Site } from "./site";

export function useBriefForm() {
  const [site, setSite] = useState<Site | null>(null);
  const [form, setForm] = useState<BriefForm>(initialBrief);
  const trace = useSiteWalk(site, briefArea(form));
  /** The area around the site, once traced. */
  const walk = trace.phase === "shown" ? trace.walk : null;

  function patchForm(patch: Partial<BriefForm>) {
    setForm((previous) => ({ ...previous, ...patch }));
  }

  /** A new site leaves the place picked for the old one behind. */
  function chooseSite(next: Site) {
    setSite(next);
    patchForm({ place: null });
  }

  /** Picking the owner's place moves the pin onto it. */
  function choosePlace(place: PlaceHit | null) {
    patchForm({ place });
    if (place) setSite({ id: null, label: place.name, lat: place.lat, lon: place.lon });
  }

  return { site, form, trace, walk, setSite, setForm, patchForm, chooseSite, choosePlace };
}
