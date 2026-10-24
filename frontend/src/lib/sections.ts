/** The survey's sections, each the content of one of its tabs (lib/surveyTabs.ts), by their element ids. */
export type SectionId = "s-log" | "s-block" | "s-gaps" | "s-verdict" | "s-improve" | "s-concepts" | "s-taste";

/** The button that opens a concept's design sheet: focus returns to it when a sheet opened from a link closes. */
export const posterButtonId = (index: number) => `poster-${index}-open`;
