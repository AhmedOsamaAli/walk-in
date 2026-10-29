/* The parts of the app that load on demand, a chunk each, so the first screen loads only what it shows. Each can be
   started early (`load`), as the app does where the next step is likely: a survey's link, a hovered example. */
import { lazyModule } from "./lib/lazy";

/** The map and Leaflet: on the first screen, but drawn once the screen itself is up. */
export const mapChunk = lazyModule(() => import("./map/SurveyMap"));
/** A survey's status, title block and results. */
export const surveyChunk = lazyModule(() => import("./pages/SurveyView"));
/** A concept's design sheet. */
export const designChunk = lazyModule(() => import("./components/DesignContent"));
/** The launch kit's page and its report, with the poster's QR code and the kit's styles. */
export const kitChunk = lazyModule(() => import("./pages/kitPages"));
export const examplesChunk = lazyModule(() => import("./pages/ExamplesPage"));
export const placesChunk = lazyModule(() => import("./pages/PlacesPage"));
export const privacyChunk = lazyModule(() => import("./pages/PrivacyPage"));
/** Walk-in Founders: the open campaigns and a campaign's page, with PayPal's buttons and the Founders styles. */
export const foundersChunk = lazyModule(() => import("./pages/foundersPages"));
