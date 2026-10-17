// Builder-mode wording. A lookup table keyed by the core's own reason codes and audit actions: unknown codes
// are shown as-is, never paraphrased by guesswork. Pro mode never uses this.

const REASONS: Record<string, (arg: string) => string> = {
  acceptance_check_failed: (r) => `The check for requirement ${r} did not pass.`,
  baseline_not_proven: (r) => `The check for requirement ${r} was never seen failing before the work, so it cannot prove anything yet.`,
  checks_failing: (r) => `Requirement ${r} is not satisfied yet; its check is still failing.`,
  acceptance_check_modified: (f) => `A check file (${f}) was changed after it was frozen.`,
};

export function explainReason(code: string): string {
  const index = code.indexOf(":");
  const key = index === -1 ? code : code.slice(0, index);
  const arg = index === -1 ? "" : code.slice(index + 1);
  const make = Object.prototype.hasOwnProperty.call(REASONS, key) ? REASONS[key] : undefined;
  return make ? make(arg) : code;
}

// Each sentence is only true of entries written by the component that owns the action. The MCP boundary also
// records complete_task/specify/... rows (actor "mcp") around every call, even when the engine then rejects it,
// so wording is keyed on the actor as well as the action.
const ACTIONS: Record<string, { actor: string; allow?: string; deny?: string; any?: string }> = {
  complete_task: { actor: "spec_engine", allow: "A task was accepted.", deny: "A task was rejected." },
  specify: { actor: "spec_engine", any: "A feature spec was written." },
  plan: { actor: "spec_engine", any: "A plan was added to a spec." },
  tasks: { actor: "spec_engine", allow: "Tasks and acceptance checks were locked in.", deny: "Tasks and checks were refused." },
  mcp_root_denied: { actor: "mcp", any: "A request to use a folder outside the allowed area was blocked." },
  api_auth_denied: { actor: "api", any: "Someone tried to use the dashboard API with a wrong credential." },
  usage_recorded: { actor: "usage", any: "An agent reported model usage." },
};

export function explainAction(action: string, result: string, actor: string): string | null {
  const entry = Object.prototype.hasOwnProperty.call(ACTIONS, action) ? ACTIONS[action] : undefined;
  if (!entry || entry.actor !== actor) return null;
  return (result === "allow" ? entry.allow : result === "deny" ? entry.deny : undefined) ?? (result === "error" ? undefined : entry.any) ?? null;
}
