// The API credential lives in sessionStorage only: it dies with the tab, and is never put in a URL or localStorage.
const KEY = "promptwise.credential";

export function getCredential(): string | null {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setCredential(value: string): void {
  try {
    sessionStorage.setItem(KEY, value);
  } catch {
    /* storage unavailable: the user will be asked again */
  }
}

export function clearCredential(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* nothing to clear */
  }
}
