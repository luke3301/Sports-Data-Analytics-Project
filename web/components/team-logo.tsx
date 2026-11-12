import { teamCode, teamLogo } from "@/lib/teams";

/** Small team logo. Decorative (empty alt): the team code or name is always shown next to it.
 *  `chip` puts it on a white circle, for use on the blue #1 card. Renders nothing for unknown teams. */
export function TeamLogo({ team, size = 20, chip = false }: { team: string | null; size?: number; chip?: boolean }) {
  const src = teamLogo(team);
  if (!src) return null;
  const img = (
    // Plain <img>: a tiny self-hosted SVG (public/logos) needs no Next image optimization.
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt="" width={size} height={size} loading="lazy" decoding="async"
         className="shrink-0 object-contain" title={teamCode(team) ?? undefined} />
  );
  return chip ? (
    <span className="inline-flex shrink-0 items-center justify-center rounded-full bg-white p-1.5 shadow-sm">{img}</span>
  ) : img;
}
