import { useEffect, useState } from "react";

export type Route =
  | { name: "audit" }
  | { name: "diagnostics" }
  | { name: "specs" }
  | { name: "spec"; id: string };

/** Tiny hash router (no dependency). Anything unrecognised or malformed falls back to the audit view. */
export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/");
  switch (parts[0]) {
    case "diagnostics":
      return { name: "diagnostics" };
    case "specs": {
      if (parts.length < 2 || parts[1] === "") return { name: "specs" };
      try {
        return { name: "spec", id: decodeURIComponent(parts.slice(1).join("/")) };
      } catch {
        return { name: "specs" };
      }
    }
    default:
      return { name: "audit" };
  }
}

export function hrefFor(route: Route): string {
  return route.name === "spec" ? `#/specs/${encodeURIComponent(route.id)}` : `#/${route.name}`;
}

export function navigate(route: Route): void {
  window.location.hash = hrefFor(route);
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
