import Link from "next/link";

const LINKS = [
  { href: "/", label: "MVP", title: "Most Valuable Player race" },
  { href: "/roy", label: "ROY", title: "Rookie of the Year race" },
  { href: "/dpoy", label: "DPOY", title: "Defensive Player of the Year race" },
] as const;

export type NavHref = (typeof LINKS)[number]["href"];

/** Award-race switcher (segmented pill control) shown in each dashboard header. */
export function SiteNav({ current }: { current: NavHref }) {
  return (
    <nav aria-label="Award races" className="inline-flex rounded-full bg-panel p-1 ring-1 ring-line">
      {LINKS.map((l) => (
        <Link
          key={l.href}
          href={l.href}
          title={l.title}
          aria-current={l.href === current ? "page" : undefined}
          className={
            "rounded-full px-4 py-1.5 text-sm font-semibold transition-colors " +
            (l.href === current ? "bg-white text-brand shadow-sm ring-1 ring-line" : "text-muted hover:text-ink")
          }
        >
          {l.label}
        </Link>
      ))}
    </nav>
  );
}
