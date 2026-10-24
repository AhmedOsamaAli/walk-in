import "../styles/crash.css";

/** What the page shows when a screen fails to draw: what happened and a way back, never a blank page. */
export function CrashScreen() {
  return (
    <main className="crash" role="alert">
      <h1>Something went wrong on this screen.</h1>
      <p>Reload the page to try again. A survey that has started keeps running on the server.</p>
      <div className="crash-actions">
        <button
          className="ink-button"
          type="button"
          onClick={() => {
            window.location.reload();
          }}
        >
          Reload
        </button>
        <a className="mono" href="/">
          Start over
        </a>
      </div>
    </main>
  );
}
