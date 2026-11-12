"use client";

import { useEffect, useRef, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Award, TrendPoint } from "@/lib/trends";

// Season trajectory of a player's predicted vote share (and rank) in one award race. Lives inside an
// expandable row, so it fetches /api/trends only the first time its <details> is opened, not for
// every row on page load.

const BRAND = "#1f6bff"; // matches --color-brand in globals.css (theme tokens aren't runtime CSS vars)

type State = { status: "idle" | "ready" | "error"; points: TrendPoint[] };

const shortDate = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });

export function TrendChart({ award, playerId, onBrand = false }: { award: Award; playerId: string; onBrand?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<State>({ status: "idle", points: [] });

  useEffect(() => {
    const details = ref.current?.closest("details");
    let started = false;
    let cancelled = false;
    const load = () => {
      if (started) return;
      started = true;
      fetch(`/api/trends?award=${award}&playerId=${encodeURIComponent(playerId)}`)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
        .then((d: { points: TrendPoint[] }) => !cancelled && setState({ status: "ready", points: d.points }))
        .catch(() => !cancelled && setState({ status: "error", points: [] }));
    };
    if (!details || details.open) {
      load();
      return () => { cancelled = true; };
    }
    const onToggle = () => details.open && load();
    details.addEventListener("toggle", onToggle);
    return () => {
      cancelled = true;
      details.removeEventListener("toggle", onToggle);
    };
  }, [award, playerId]);

  const muted = onBrand ? "text-white/70" : "text-muted";
  const data = state.points.map((p) => ({
    label: shortDate(p.date),
    share: p.voteShare === null ? null : +(p.voteShare * 100).toFixed(1),
    rank: p.rank,
  }));

  let body;
  if (state.status === "idle") {
    body = <p className={`text-sm ${muted}`}>Loading trend…</p>;
  } else if (state.status === "error") {
    body = <p className={`text-sm ${muted}`}>The trend isn&apos;t available right now.</p>;
  } else if (data.length < 2) {
    body = (
      <p className={`text-sm ${muted}`}>
        The trend line starts after two daily updates ({data.length} so far
        {data[0]?.rank ? `: #${data[0].rank} at ${data[0].share}%` : ""}).
      </p>
    );
  } else {
    const line = onBrand ? "#ffffff" : BRAND;
    const axis = onBrand ? "rgba(255,255,255,0.7)" : "#64748b";
    const grid = onBrand ? "rgba(255,255,255,0.15)" : "#e4e8ef";
    body = (
      <div className="h-44 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={grid} vertical={false} />
            <XAxis dataKey="label" tick={{ fill: axis, fontSize: 12 }} tickLine={false} axisLine={{ stroke: grid }} />
            <YAxis tick={{ fill: axis, fontSize: 12 }} tickLine={false} axisLine={false} width={52}
                   domain={[0, "auto"]} tickFormatter={(v: number) => `${v}%`} />
            <Tooltip
              cursor={{ stroke: grid }}
              content={({ active, payload }) => {
                const p = active && payload?.length ? (payload[0].payload as (typeof data)[number]) : null;
                return p ? (
                  <div className="rounded-lg bg-ink px-3 py-2 text-xs text-white shadow-lg">
                    <p className="font-semibold">{p.label}</p>
                    <p>Vote share {p.share ?? "—"}%</p>
                    <p>Rank #{p.rank ?? "—"}</p>
                  </div>
                ) : null;
              }}
            />
            <Line type="monotone" dataKey="share" stroke={line} strokeWidth={2.5} dot={{ r: 3.5, fill: line }}
                  activeDot={{ r: 5 }} connectNulls isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    );
  }

  return <div ref={ref}>{body}</div>;
}
