import { clearCredential, getCredential } from "./credential";

export class ApiError extends Error {
  constructor(public readonly status: number, message?: string) {
    super(message ?? `request failed with status ${status}`);
  }
}

export function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const credential = getCredential();
  if (!credential) throw new ApiError(401, "no credential");
  return { Authorization: `Bearer ${credential}`, ...extra };
}

/** 401 means the credential is wrong: drop it so the gate asks again. 503 means the gateway's own
 * credential file is unusable: keep ours, the operator has to fix the server. */
export function checkStatus(response: Response): void {
  if (response.status === 401) clearCredential();
  if (!response.ok) throw new ApiError(response.status);
}

export async function apiGet<T>(path: string, init: { signal?: AbortSignal } = {}): Promise<T> {
  const response = await fetch(path, { headers: authHeaders(), signal: init.signal });
  checkStatus(response);
  return (await response.json()) as T;
}
