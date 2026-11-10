import type { Policy } from "../../api/types";
import { Button, buttonClass } from "../../design/ui";

/**
 * "Open waiting room display": a real link once policy (display_key) has loaded; until then, or if policy
 * could not be read, a disabled button that says why. Used by the Front desk and the Queue monitor.
 * ponytail: the legacy board (works today, no sign-in); switch to /app/display?key= when the Display milestone lands.
 */
export function DisplayLink({ p, error, className }: { p?: Policy; error?: string; className?: string }) {
  if (p) return <a className={`${buttonClass("secondary")} ${className ?? ""}`} href={`/?display=${p.display_key}`} target="_blank" rel="noopener">Open waiting room display</a>;
  return <Button kind="secondary" className={className} disabled title={error ? `Display link unavailable: ${error}` : undefined}>
    {error ? "Display link unavailable" : "Open waiting room display"}</Button>;
}
