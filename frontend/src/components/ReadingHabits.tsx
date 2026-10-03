"use client";

import React, { useState, useEffect } from "react";
import { BarChart3, Bookmark, CalendarClock, Info, RefreshCw, ShieldAlert } from "lucide-react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ReadingStats {
  user_id: string;
  total_events_saved: number;
  saved_last_7_days: number;
  bias_distribution: Record<string, number>;
  bias_distribution_7d: Record<string, number>;
  topic_distribution: Record<string, number>;
  weekly_bias_message: string | null;
  gamification_message: string | null;
}

// Ordered left-to-right so the bar reads as a spectrum rather than a ranking.
const LEAN_ORDER = ["LEFT", "CENTER_LEFT", "CENTER", "CENTER_RIGHT", "RIGHT"] as const;
const LEAN_META: Record<string, { label: string; bar: string }> = {
  LEFT: { label: "Left", bar: "bg-cyber-rose" },
  CENTER_LEFT: { label: "Center-left", bar: "bg-cyber-rose/60" },
  CENTER: { label: "Center", bar: "bg-zinc-500" },
  CENTER_RIGHT: { label: "Center-right", bar: "bg-cyber-cyan/60" },
  RIGHT: { label: "Right", bar: "bg-cyber-cyan" },
};

function DistributionBars({
  data,
  order,
  emptyLabel,
}: {
  data: Record<string, number>;
  order?: readonly string[];
  emptyLabel: string;
}) {
  const entries = Object.entries(data).filter(([, n]) => n > 0);
  if (entries.length === 0) {
    return <p className="text-[11px] text-zinc-500 font-mono-data">{emptyLabel}</p>;
  }

  const keys = order ? order.filter((k) => (data[k] || 0) > 0) : entries.map(([k]) => k);
  if (!order) {
    keys.sort((a, b) => (data[b] || 0) - (data[a] || 0));
  }
  const max = Math.max(...keys.map((k) => data[k] || 0), 1);

  return (
    <div className="space-y-2.5">
      {keys.map((key) => {
        const count = data[key] || 0;
        const meta = LEAN_META[key];
        const label = meta ? meta.label : key.replace(/_/g, " ");
        const bar = meta ? meta.bar : "bg-cyber-indigo";
        return (
          <div key={key} className="flex items-center gap-3">
            <span className="w-28 flex-shrink-0 text-[10px] uppercase tracking-wider font-mono-data text-zinc-400 truncate">
              {label}
            </span>
            <div className="flex-1 h-2 rounded-full bg-zinc-900/80 overflow-hidden">
              <div
                className={`h-full rounded-full ${bar} transition-all`}
                style={{ width: `${Math.round((count / max) * 100)}%` }}
              />
            </div>
            <span className="w-8 text-right text-xs font-mono-data text-zinc-300">{count}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function ReadingHabits({ token, userId }: { token: string; userId: string }) {
  const [stats, setStats] = useState<ReadingStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/v1/users/${userId}/reading-stats`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error("Could not load your reading habits");
        const data = await res.json();
        if (!cancelled) setStats(data);
      } catch (err: any) {
        if (!cancelled) setError(err.message || "Could not load your reading habits");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [token, userId]);

  return (
    <section className="bg-surface-container border border-outline-variant rounded-lg p-stack-md">
      <h3 className="font-label-caps text-label-caps text-zinc-400 uppercase tracking-widest text-[10px] mb-4 flex items-center gap-2">
        <BarChart3 className="w-3.5 h-3.5 text-primary" />
        Reading Habits
      </h3>

      {loading && (
        <div className="flex items-center gap-2 py-6 text-primary text-xs font-mono-data animate-pulse">
          <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Computing from your saved events...
        </div>
      )}

      {!loading && error && (
        <div className="p-3 rounded-xl bg-cyber-rose/10 border border-cyber-rose/30 text-cyber-rose text-xs font-mono-data">
          {error}
        </div>
      )}

      {!loading && !error && stats && stats.total_events_saved === 0 && (
        <div className="p-4 rounded-xl bg-zinc-950/40 border border-zinc-900 text-zinc-400 text-xs leading-relaxed flex gap-3">
          <Bookmark className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
          <span>
            You have not saved any events yet. Use <span className="text-zinc-200">Save</span> or add
            an event to a reading list, and your habits will appear here. We only ever report what you
            actually saved &mdash; never invented figures.
          </span>
        </div>
      )}

      {!loading && !error && stats && stats.total_events_saved > 0 && (
        <div className="flex flex-col gap-5">
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-zinc-950/40 border border-zinc-900 rounded-xl p-3">
              <span className="text-[9px] text-zinc-500 uppercase tracking-wider font-mono-data block">
                Events saved
              </span>
              <span className="text-xl text-on-surface font-bold font-mono-data">
                {stats.total_events_saved}
              </span>
            </div>
            <div className="bg-zinc-950/40 border border-zinc-900 rounded-xl p-3">
              <span className="text-[9px] text-zinc-500 uppercase tracking-wider font-mono-data block flex items-center gap-1">
                <CalendarClock className="w-3 h-3" /> This week
              </span>
              <span className="text-xl text-on-surface font-bold font-mono-data">
                {stats.saved_last_7_days}
              </span>
            </div>
          </div>

          {stats.weekly_bias_message && (
            <div className="p-3 rounded-xl bg-cyber-indigo/10 border border-cyber-indigo/30 text-zinc-200 text-xs leading-relaxed">
              <span className="flex items-start gap-2">
                <Info className="w-3.5 h-3.5 text-cyber-indigo flex-shrink-0 mt-0.5" />
                <span>{stats.weekly_bias_message}</span>
              </span>
              <p className="mt-1.5 ml-5 text-[10px] text-zinc-500 font-mono-data">
                Based on what you saved, not on what you browsed.
              </p>
            </div>
          )}

          <div>
            <h4 className="text-[10px] text-zinc-500 uppercase tracking-widest font-mono-data mb-3">
              Sources behind your saved events
            </h4>
            <DistributionBars
              data={stats.bias_distribution}
              order={LEAN_ORDER}
              emptyLabel="No source bias recorded for your saved events."
            />
            <p className="mt-2 text-[10px] text-zinc-600 font-mono-data leading-relaxed">
              An event that draws on several outlets counts once per lean.
            </p>
            {Object.values(stats.bias_distribution_7d).some((n) => n > 0) && (
              <div className="mt-4">
                <h4 className="text-[10px] text-zinc-500 uppercase tracking-widest font-mono-data mb-3">
                  This week
                </h4>
                <DistributionBars
                  data={stats.bias_distribution_7d}
                  order={LEAN_ORDER}
                  emptyLabel="Nothing saved in the last 7 days."
                />
              </div>
            )}
          </div>

          {Object.values(stats.topic_distribution).some((n) => n > 0) && (
            <div>
              <h4 className="text-[10px] text-zinc-500 uppercase tracking-widest font-mono-data mb-3">
                Topics you save most
              </h4>
              <DistributionBars
                data={stats.topic_distribution}
                emptyLabel="No topics recorded for your saved events."
              />
            </div>
          )}

          {stats.gamification_message && (
            <div className="p-3 rounded-xl bg-zinc-950/40 border border-zinc-900 text-zinc-300 text-[11px] leading-relaxed flex gap-2">
              <ShieldAlert className="w-3.5 h-3.5 text-primary flex-shrink-0 mt-0.5" />
              <span>{stats.gamification_message}</span>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
