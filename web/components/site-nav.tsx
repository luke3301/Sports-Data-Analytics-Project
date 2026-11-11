import Link from "next/link";

const LINKS = [
  { href: "/", label: "MVP" },
  { href: "/roy", label: "Rookie of the Year" },
] as const;

/** Section switcher shown in each dashboard header. `current` is the active href. */
export function SiteNav({ current }: { current: (typeof LINKS)[number]["href"] }) {
  return (
    <nav aria-label="Award races" className="flex gap-5 text-sm">
      {LINKS.map((l) => (
        <Link
          key={l.href}
          href={l.href}
          aria-current={l.href === current ? "page" : undefined}
          className={l.href === current ? "text-zinc-100" : "text-zinc-500 transition-colors hover:text-zinc-300"}
        >
          {l.label}
        </Link>
      ))}
    </nav>
  );
}
