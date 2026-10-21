import { useEffect, useState } from "react";
import { messageOf } from "../api/client";
import type { RenderResult, Shot } from "../api/types";
import { safeUrl } from "../lib/format";
import { loadRender } from "../state/designs";

type Render = { state: "loading" } | { state: "failed"; message: string } | { state: "image"; url: string; model: string | null };

function toRender(result: RenderResult): Render {
  const url = safeUrl(result.image);
  if (url) return { state: "image", url, model: result.model ?? null };
  const message = result.detail ? `${result.detail} Reopen the sheet in a few minutes.` : "No render this time";
  return { state: "failed", message };
}

interface RenderFrameProps {
  runId: string;
  index: number;
  shot: Shot;
  name: string;
  /** Renders on free volunteer GPUs can wait minutes in a queue. */
  volunteer: boolean;
}

export function RenderFrame({ runId, index, shot, name, volunteer }: RenderFrameProps) {
  const [render, setRender] = useState<Render>({ state: "loading" });
  const [shape, setShape] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    loadRender(runId, index, shot.kind).then(
      (result) => {
        if (live) setRender(toRender(result));
      },
      (error: unknown) => {
        if (live) setRender({ state: "failed", message: messageOf(error) });
      },
    );
    return () => {
      live = false;
    };
  }, [runId, index, shot.kind]);

  const status = render.state === "failed" ? "failed" : render.state === "image" && shape ? "ready" : "loading";
  const wait = volunteer ? " on free volunteer GPUs · 1–5 min" : "";
  return (
    <figure className={`render ${status}`}>
      <div className="render-frame" style={shape ? { aspectRatio: shape } : undefined}>
        <img
          alt={`${shot.label}: AI render of ${name}`}
          src={render.state === "image" ? render.url : undefined}
          onLoad={(event) => {
            // Some free models only make square images: the frame takes the image's shape instead of cropping it.
            const { naturalWidth: width, naturalHeight: height } = event.currentTarget;
            setShape(width && height ? `${width} / ${height}` : "16 / 9");
          }}
        />
        <span className="render-wait mono">
          {render.state === "failed" ? render.message : `Rendering ${shot.label.toLowerCase()}${wait}`}
        </span>
      </div>
      <figcaption className="mono">
        <span>{shot.label}</span>
        <span className="render-credit">{render.state === "image" && render.model ? `AI render · ${render.model}` : "AI render"}</span>
      </figcaption>
    </figure>
  );
}
