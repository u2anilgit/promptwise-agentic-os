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

const ACTIONS: Record<string, { allow?: string; deny?: string; any?: string }> = {
  complete_task: { allow: "A task was accepted.", deny: "A task was rejected." },
  specify: { any: "A feature spec was written." },
  plan: { any: "A plan was added to a spec." },
  tasks: { allow: "Tasks and acceptance checks were locked in.", deny: "Tasks and checks were refused." },
  mcp_root_denied: { any: "A request to use a folder outside the allowed area was blocked." },
  api_auth_denied: { any: "Someone tried to use the dashboard API with a wrong credential." },
  usage_recorded: { any: "An agent reported model usage." },
};

export function explainAction(action: string, result: string): string | null {
  const entry = Object.prototype.hasOwnProperty.call(ACTIONS, action) ? ACTIONS[action] : undefined;
  if (!entry) return null;
  return (result === "allow" ? entry.allow : result === "deny" ? entry.deny : undefined) ?? entry.any ?? null;
}
