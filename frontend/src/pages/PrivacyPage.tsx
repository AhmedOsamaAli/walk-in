import type { ReactNode } from "react";
import { Link } from "../components/Link";
import { Page, PageHead, useDocumentTitle, useFocusOnMount } from "../components/Page";
import { SectionHead } from "../components/SectionHead";
import { BRIEF_URL, PLACES_URL } from "../lib/routes";

/** The day this note last changed: say so here whenever it does. */
const UPDATED = "23 October 2026";
const ISSUES = "https://github.com/AhmedOsamaAli/walk-in/issues";

function Item({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div>
      <dt>{term}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/**
 * Who runs Walk-in, what it stores and why, its cookies, who else sees what, how long it keeps things, how to delete
 * them and whom to ask, in plain words. It is the privacy policy Google's consent screen links to, so it stands on its
 * own: no sign-in and no request to the server, and it prints as a document.
 */
export function PrivacyPage() {
  const titleRef = useFocusOnMount();
  useDocumentTitle("Privacy");
  return (
    <Page className="privacy-page">
      <PageHead
        eyebrow="Walk-in · Privacy"
        title="Your data, in plain words"
        titleRef={titleRef}
        standfirst="Walk-in keeps what it needs to run a survey and to list your surveys for you. Nothing else."
        fields={[
          { label: "Run by", lines: ["A Qloo Agentic Hackathon project"] },
          { label: "Ads and tracking", lines: ["None"] },
          { label: "Sent to Qloo and AI", lines: ["Nothing about you"] },
          { label: "Last updated", lines: [UPDATED] },
        ]}
        actions={
          <button
            type="button"
            className="ghost mono"
            onClick={() => {
              window.print();
            }}
          >
            Print
          </button>
        }
      />
      <section className="pg-sec" aria-labelledby="privacy-who">
        <SectionHead id="privacy-who" no="01" title="Who runs Walk-in" />
        <p className="privacy-plain">
          Walk-in is a Qloo Agentic Hackathon project: an independent app built on Qloo&apos;s taste data and run by the
          people who made it. Questions about your data go to the project on GitHub, below.
        </p>
      </section>
      <section className="pg-sec" aria-labelledby="privacy-stores">
        <SectionHead id="privacy-stores" no="02" title="What Walk-in stores, and why" />
        <dl className="privacy-list">
          <Item term="Surveys">
            The pin you drop, the brief you give (the walk, the business or your own place, your notes and the unit) and
            the results, design sheets included: kept so that each survey has a link that opens it just as it ended.
            Anyone with a survey&apos;s link can open it.
          </Item>
          <Item term="With sign-in">
            Your Google account id, your email, your name and the link to your Google profile picture, only to show that
            you&apos;re signed in and to list your surveys in My places.
          </Item>
          <Item term="In your browser">
            Your light or dark theme, and a “Not now” to the sign-in offer. Neither leaves your browser.
          </Item>
        </dl>
      </section>
      <section className="pg-sec" aria-labelledby="privacy-cookies">
        <SectionHead id="privacy-cookies" no="03" title="Cookies" note="Two, and neither follows you to other sites." />
        <dl className="privacy-list">
          <Item term="A sign-in cookie">
            Set when you sign in, so Walk-in knows it is you; Walk-in keeps only a one-way fingerprint of it. It lasts 30
            days, renewed while you use Walk-in, and signing out deletes it.
          </Item>
          <Item term="A device cookie">
            Set when you run your first survey: a random id with nothing about you in it. Each survey this browser runs
            records it, so the surveys you ran before signing in can join your account when you do. It lasts up to 400
            days, the most a browser allows.
          </Item>
        </dl>
      </section>
      <section className="pg-sec" aria-labelledby="privacy-others">
        <SectionHead id="privacy-others" no="04" title="Who else sees what" />
        <dl className="privacy-list">
          <Item term="Qloo and the AI providers">
            Qloo receives the place and the questions the survey asks about it; the AI providers also read your brief,
            notes included. Nothing personal is ever sent to them: not your name, your email or your account.
          </Item>
          <Item term="OpenStreetMap's services">
            Trace the walk from your pin and find the addresses you search for. Walk-in&apos;s server asks them, never your
            browser, so they learn nothing about you.
          </Item>
          <Item term="Google">
            Runs the sign-in itself when you sign in with Google, and tells Walk-in your account id, email, name and picture
            link.
          </Item>
          <Item term="Walk-in's hosts">
            Cloudflare serves the web app from its worldwide network; the survey engine runs on Render and the database on
            Neon, both in Ohio, in the United States. Like any website&apos;s hosts, they see your IP address with each
            request and may keep it in their logs. Walk-in itself uses it only to limit how much one address can ask of it
            in an hour, and never saves it with your surveys or your account.
          </Item>
          <Item term="The map">
            Its tiles load from the map providers credited on the map, which see your IP address the same way.
          </Item>
          <Item term="Nobody else">
            Walk-in shows no ads and runs no analytics or tracking pixels. Nothing about you is sold or shared.
          </Item>
        </dl>
      </section>
      <section className="pg-sec" aria-labelledby="privacy-kept">
        <SectionHead id="privacy-kept" no="05" title="How long it is kept" />
        <dl className="privacy-list">
          <Item term="Surveys without an account">Deleted after 60 days.</Item>
          <Item term="Surveys saved to an account">
            Kept until you delete your account, which deletes them with it.
          </Item>
          <Item term="Your account">Kept until you delete it. Signing out keeps it, and your surveys with it.</Item>
        </dl>
      </section>
      <section className="pg-sec" aria-labelledby="privacy-delete">
        <SectionHead id="privacy-delete" no="06" title="Deleting it" />
        <dl className="privacy-list">
          <Item term="Your account">
            In{" "}
            <Link className="text-link" href={PLACES_URL}>
              My places
            </Link>
            , “Delete my account” deletes your account and the surveys saved to it; their share links stop working within
            about ten minutes.
          </Item>
          <Item term="This browser">
            Signing out deletes the sign-in cookie, and deleting your account deletes both cookies. Clearing this
            site&apos;s cookies in your browser deletes them too.
          </Item>
        </dl>
      </section>
      <section className="pg-sec" aria-labelledby="privacy-contact">
        <SectionHead id="privacy-contact" no="07" title="Contact" />
        <p className="privacy-plain">
          For a question about your data, or a request about it, open an issue at{" "}
          <a className="text-link" href={ISSUES} target="_blank" rel="noopener">
            github.com/AhmedOsamaAli/walk-in/issues
          </a>
          . Issues are public, so please leave personal details out of them.
        </p>
        <p className="privacy-back">
          <Link className="text-link" href={BRIEF_URL}>
            Survey a storefront <span aria-hidden="true">→</span>
          </Link>
        </p>
      </section>
    </Page>
  );
}
