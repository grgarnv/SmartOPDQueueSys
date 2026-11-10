import grid from "../design/icons/grid.svg";
import users from "../design/icons/users.svg";
import shield from "../design/icons/shield.svg";
import pulse from "../design/icons/pulse.svg";
import settings from "../design/icons/settings.svg";
import down from "../design/icons/down.svg";
import s from "./AppShell.module.css";

// The Figma icons are not exact Lucide icons (different strokes and shapes), so the downloaded SVGs are used
// as-is. As a CSS mask they keep their exact geometry and take the text colour (teal when active, muted otherwise).
export const ICONS = { grid, users, shield, pulse, settings, down } as const;

export function Icon({ name, size = 20 }: { name: keyof typeof ICONS; size?: number }) {
  const url = `url("${ICONS[name]}")`;
  return <span className={s.icon} style={{ width: size, height: size, maskImage: url, WebkitMaskImage: url }} aria-hidden="true" />;
}
