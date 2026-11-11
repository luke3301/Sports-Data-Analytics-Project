import Link from "next/link";

const LINKS = [
  { href: "/", label: "MVP", title: "Most Valuable Player race" },
  { href: "/roy", label: "ROY", title: "Rookie of the Year race" },
  { href: "/dpoy", label: "DPOY", title: "Defensive Player of the Year race" },
] as const;

export type NavHref = (typeof LINKS)[number]["href"];

/** Award-race switcher shown in each dashboard header. `current` is the active href. */
export function SiteNav({ current }: { current: NavHref }) {
  return (
    <nav aria-label="Award races" className="flex gap-5 text-sm">
      {LINKS.map((l) => (
        <Link
          key={l.href}
          href={l.href}
          title={l.title}
          aria-current={l.href === current ? "page" : undefined}
          className={l.href === current ? "text-zinc-100" : "text-zinc-500 transition-colors hover:text-zinc-300"}
        >
          {l.label}
        </Link>
      ))}
    </nav>
  );
}
