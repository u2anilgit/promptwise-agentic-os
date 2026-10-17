import { useState, type FormEvent } from "react";
import { ApiError, apiGet } from "../../api/client";
import { clearCredential, setCredential } from "../../api/credential";

export function TokenGate({ onAuthed }: { onAuthed: () => void }) {
  const [value, setValue] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const candidate = value.trim();
    if (!candidate) return;
    setBusy(true);
    setMessage(null);
    setCredential(candidate);
    try {
      await apiGet("/api/v1/policy");
      onAuthed();
    } catch (e) {
      clearCredential();
      if (e instanceof ApiError && e.status === 401) setMessage("That credential was not accepted.");
      else if (e instanceof ApiError && e.status === 503)
        setMessage("The gateway's credential file is unusable (missing, too short, or a symlink). Check the gateway logs.");
      else setMessage("Could not reach the gateway.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mx-auto mt-24 max-w-md space-y-4 rounded border bg-white p-6 shadow-sm">
      <h1 className="text-xl font-semibold">PromptWise Agentic OS</h1>
      <p className="text-sm text-slate-600">
        Enter the gateway credential. Print it on the machine running the gateway with{" "}
        <code className="rounded bg-slate-100 px-1">promptwise dashboard token</code>. It is kept for this tab only.
      </p>
      <label className="flex flex-col gap-1 text-sm">
        Credential
        <input
          type="password"
          autoComplete="off"
          className="rounded border px-2 py-1"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      </label>
      {message && <p role="alert" className="text-sm text-status-block">{message}</p>}
      <button disabled={busy} className="rounded bg-accent px-4 py-1.5 text-accent-fg disabled:opacity-50">
        Continue
      </button>
    </form>
  );
}
