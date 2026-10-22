import { useId, useState, type SyntheticEvent } from "react";
import { commerce, conflictUrl, problemsOf, type CampaignTerms } from "../../api/commerce";
import { ApiError } from "../../api/client";
import {
  deadlineFrom,
  deadlineProblem,
  deadlineRange,
  defaultDeadline,
  localZone,
  LONGEST_CAMPAIGN_DAYS,
  moneyText,
  normalizeAmount,
  plainError,
} from "../../lib/commerce";
import { cx } from "../../lib/css";
import { useNavigate } from "../../lib/navigation";
import { useNow } from "../../lib/useNow";
import { session } from "../../state/session";
import { Link } from "../Link";
import { SandboxNotice } from "../SandboxNotice";

/** The pitch's limits, as the server checks them (pledges.py): longer text is refused with the reason. */
const TITLE_MAX = 60;
const PITCH_MAX = 300;
const PERK_MAX = 80;
const PERKS_MAX = 4;

interface Draft {
  title: string;
  pitch: string;
  perks: string[];
  howItWorks: string;
  /** The terms it was drafted for, to tell the owner when they changed since. */
  terms: string;
}

interface CampaignFormProps {
  token: string;
  name: string;
  currency: string;
  sandbox: boolean;
}

function Counter({ text, max }: { text: string; max: number }) {
  return (
    <span className={cx("counter mono", text.length > max && "over")} aria-hidden="true">
      {text.length}/{max}
    </span>
  );
}

/** The owner's terms, then words drafted by the agent to edit, then the published pledge page. */
export function CampaignForm({ token, name, currency, sandbox }: CampaignFormProps) {
  const navigate = useNavigate();
  const ids = useId();
  const now = useNow(30_000);
  const [first] = useState(() => defaultDeadline(Date.now()));
  const range = deadlineRange(now);
  const [amount, setAmount] = useState("25");
  const [goal, setGoal] = useState("25");
  const [date, setDate] = useState(first.date);
  const [time, setTime] = useState(first.time);
  const [discount, setDiscount] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState<"drafting" | "publishing" | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [conflict, setConflict] = useState<string | null>(null);

  const amountValue = normalizeAmount(amount);
  const goalValue = /^\d{1,4}$/.test(goal.trim()) ? Number(goal) : null;
  const deadline = deadlineFrom(date, time);
  const termErrors = {
    amount: amountValue ? null : "Enter the amount each supporter pledges, such as 25.",
    goal: goalValue && goalValue >= 1 ? null : "Enter how many supporters you need, such as 25.",
    deadline: deadlineProblem(deadline, now),
  };
  const termsKey = JSON.stringify([amountValue, goalValue, deadline, discount.trim()]);
  const stale = draft !== null && draft.terms !== termsKey;

  /** The terms as the API takes them; null, with the reasons shown, when they cannot be sent. */
  function terms(): CampaignTerms | null {
    if (!amountValue || !goalValue || goalValue < 1 || !deadline || termErrors.deadline) {
      setProblems(Object.values(termErrors).filter((problem): problem is string => problem !== null));
      return null;
    }
    return { kit_token: token, amount: amountValue, goal: goalValue, deadline, discount: discount.trim() || null };
  }

  function fail(error: unknown, fallback: string) {
    if (error instanceof ApiError && error.status === 401) void session.refresh();
    const url = conflictUrl(error);
    if (url) {
      setConflict(url);
      setProblems([]);
      return;
    }
    const listed = error instanceof ApiError && error.status === 422 ? problemsOf(error) : [];
    setProblems(listed.length ? listed : [plainError(error, fallback)]);
  }

  async function writeDraft(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    const asked = terms();
    if (!asked) return;
    setBusy("drafting");
    setProblems([]);
    setConflict(null);
    try {
      const written = await commerce.draftCampaign(asked);
      if (written.problems.length) setProblems(written.problems);
      else {
        setDraft({
          title: written.title,
          pitch: written.pitch,
          perks: written.perks.slice(0, PERKS_MAX),
          howItWorks: written.how_it_works,
          terms: termsKey,
        });
      }
    } catch (error) {
      fail(error, "The draft could not be written. Try again.");
    } finally {
      setBusy(null);
    }
  }

  async function publish() {
    const asked = terms();
    if (!asked || !draft) return;
    setBusy("publishing");
    setProblems([]);
    setConflict(null);
    try {
      const perks = draft.perks.map((perk) => perk.trim()).filter(Boolean);
      const { url } = await commerce.createCampaign({ ...asked, title: draft.title.trim(), pitch: draft.pitch.trim(), perks });
      navigate(url);
    } catch (error) {
      fail(error, "The campaign could not be published. Try again.");
      setBusy(null);
    }
  }

  function patchDraft(patch: Partial<Draft>) {
    setDraft((previous) => (previous ? { ...previous, ...patch } : previous));
  }

  const pledgeText = amountValue ? moneyText(amountValue, currency) : null;

  return (
    <div className="campaign-form">
      <form className="cf-terms" onSubmit={(event) => void writeDraft(event)} noValidate>
        <fieldset className="cf-grid" disabled={busy !== null}>
          <legend className="sr-only">Your terms</legend>
          <label className="cf-field">
            <span className="mono label">Each supporter pledges</span>
            <span className="cf-money">
              <span className="cf-currency mono" aria-hidden="true">
                {currency}
              </span>
              <input
                className="field-input"
                type="text"
                inputMode="decimal"
                autoComplete="off"
                value={amount}
                aria-invalid={termErrors.amount !== null}
                aria-describedby={`${ids}-amount`}
                onChange={(event) => {
                  setAmount(event.target.value);
                }}
              />
            </span>
            <span className={cx("cf-hint", termErrors.amount && amount.trim() && "bad")} id={`${ids}-amount`}>
              {termErrors.amount && amount.trim() ? termErrors.amount : "A fixed amount, the same for everyone."}
            </span>
          </label>
          <label className="cf-field">
            <span className="mono label">Supporters needed</span>
            <input
              className="field-input"
              type="number"
              min={1}
              step={1}
              inputMode="numeric"
              value={goal}
              aria-invalid={termErrors.goal !== null}
              aria-describedby={`${ids}-goal`}
              onChange={(event) => {
                setGoal(event.target.value);
              }}
            />
            <span className={cx("cf-hint", termErrors.goal && goal.trim() && "bad")} id={`${ids}-goal`}>
              {termErrors.goal && goal.trim() ? termErrors.goal : "Pledges are collected only if this many people pledge."}
            </span>
          </label>
          <div className="cf-field cf-deadline" role="group" aria-labelledby={`${ids}-deadline-label`}>
            <span className="mono label" id={`${ids}-deadline-label`}>
              Deadline
            </span>
            <span className="cf-when">
              <input
                className="field-input"
                type="date"
                aria-label="Deadline date"
                min={range.min}
                max={range.max}
                value={date}
                aria-invalid={termErrors.deadline !== null}
                aria-describedby={`${ids}-deadline`}
                onChange={(event) => {
                  setDate(event.target.value);
                }}
              />
              <input
                className="field-input"
                type="time"
                aria-label="Deadline time"
                value={time}
                aria-describedby={`${ids}-deadline`}
                onChange={(event) => {
                  setTime(event.target.value);
                }}
              />
            </span>
            <span className={cx("cf-hint", termErrors.deadline && "bad")} id={`${ids}-deadline`}>
              {termErrors.deadline ??
                `Your time zone (${localZone()}). At most ${LONGEST_CAMPAIGN_DAYS} days away: PayPal holds a pledge for 29 days.`}
            </span>
          </div>
          <label className="cf-field cf-wide">
            <span className="mono label">
              Founding-supporter discount <span className="muted">optional</span>
            </span>
            <input
              className="field-input"
              type="text"
              maxLength={120}
              placeholder="10% off every visit in the first year"
              value={discount}
              onChange={(event) => {
                setDiscount(event.target.value);
              }}
            />
            <span className="cf-hint">Put on the page word for word. Leave it empty if you offer none.</span>
          </label>
        </fieldset>
        {sandbox ? <SandboxNotice /> : null}
        <div className="cf-actions">
          <button className="go" type="submit" disabled={busy !== null}>
            <span>{busy === "drafting" ? "Drafting…" : draft ? "Draft again with AI" : "Draft with AI"}</span>
            <i aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="M4 12h15M13 6l6 6-6 6" />
              </svg>
            </i>
          </button>
          <p className="cf-note">
            The agent writes a title, a pitch and perks from {name}&apos;s evidence. Your terms go in unchanged; you edit the
            words before anything is published.
          </p>
        </div>
      </form>

      <div className="cf-feedback" role="status" aria-live="polite">
        {busy === "drafting" ? <p className="cf-busy mono">Writing the page from the evidence…</p> : null}
        {busy === "publishing" ? <p className="cf-busy mono">Publishing…</p> : null}
      </div>
      {problems.length ? (
        <div className="cf-problems" role="alert">
          <p className="mono">{draft ? "Not published yet" : "Not drafted"}</p>
          <ul>
            {problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {conflict ? (
        <p className="cf-problems" role="alert">
          This kit already has an open campaign.{" "}
          <Link className="text-link" href={conflict}>
            Open it <span aria-hidden="true">→</span>
          </Link>
        </p>
      ) : null}

      {draft ? (
        <div className="cf-draft" aria-labelledby={`${ids}-draft`}>
          <h3 className="cf-draft-title" id={`${ids}-draft`}>
            The page, ready to edit
          </h3>
          {stale ? (
            <p className="cf-stale">You changed the terms after this draft: draft again, or check the words still match them.</p>
          ) : null}
          <label className="cf-field cf-wide">
            <span className="cf-label-row">
              <span className="mono label">Title</span>
              <Counter text={draft.title} max={TITLE_MAX} />
            </span>
            <input
              className="field-input cf-title-input"
              type="text"
              value={draft.title}
              onChange={(event) => {
                patchDraft({ title: event.target.value });
              }}
            />
          </label>
          <label className="cf-field cf-wide">
            <span className="cf-label-row">
              <span className="mono label">Pitch to neighbors</span>
              <Counter text={draft.pitch} max={PITCH_MAX} />
            </span>
            <textarea
              className="field-input cf-textarea"
              rows={4}
              value={draft.pitch}
              onChange={(event) => {
                patchDraft({ pitch: event.target.value });
              }}
            />
          </label>
          <fieldset className="cf-perks">
            <legend className="mono label">What founding supporters get</legend>
            <ol>
              {draft.perks.map((perk, index) => (
                <li key={index}>
                  <input
                    className="field-input"
                    type="text"
                    aria-label={`Perk ${index + 1}`}
                    value={perk}
                    onChange={(event) => {
                      patchDraft({ perks: draft.perks.map((old, at) => (at === index ? event.target.value : old)) });
                    }}
                  />
                  <Counter text={perk} max={PERK_MAX} />
                  <button
                    type="button"
                    className="text-button"
                    aria-label={`Remove perk ${index + 1}`}
                    onClick={() => {
                      patchDraft({ perks: draft.perks.filter((_, at) => at !== index) });
                    }}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ol>
            {draft.perks.length < PERKS_MAX ? (
              <button
                type="button"
                className="ghost mono"
                onClick={() => {
                  patchDraft({ perks: [...draft.perks, ""] });
                }}
              >
                + Add a perk
              </button>
            ) : null}
          </fieldset>
          <div className="cf-how">
            <p className="mono label">How it works · fixed words</p>
            <p>{draft.howItWorks}</p>
          </div>
          <div className="cf-actions">
            <button className="go" type="button" disabled={busy !== null} onClick={() => void publish()}>
              <span>{busy === "publishing" ? "Publishing…" : "Publish the campaign"}</span>
              <i aria-hidden="true">
                <svg viewBox="0 0 24 24">
                  <path d="M4 12h15M13 6l6 6-6 6" />
                </svg>
              </i>
            </button>
            <p className="cf-note">
              {pledgeText && goalValue
                ? `Neighbors pledge ${pledgeText}; PayPal collects every pledge only if ${goalValue} of them pledge by the deadline.`
                : "PayPal collects the pledges only if the goal is met by the deadline."}
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}
