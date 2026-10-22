import { Fragment } from "react";

/** "Mon–Thu 11 am–10 pm · Fri–Sat 11 am–11:30 pm": lines break between day groups, never inside one. */
export function HoursText({ hours }: { hours: string }) {
  return (
    <>
      {hours.split(" · ").map((group, index) => (
        <Fragment key={`${String(index)}-${group}`}>
          {index ? " · " : null}
          <span className="nowrap">{group}</span>
        </Fragment>
      ))}
    </>
  );
}
