"use client";

import React, { useState, useEffect } from "react";
import { Activity, Minus, RefreshCw, TrendingDown, TrendingUp } from "lucide-react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface TrendTopic {
  topic: string;
  current: number;
  previous: number;
  delta: number;
  change_pct: number | null;
  direction: "up" | "down" | "flat";
  is_new: boolean;
}

interface TrendsResponse {
  window_days: number;
  current_start: string;
  current_end: string;
  previous_start: string;
  previous_end: string;
  topics: TrendTopic[];
}

function topicLabel(topic: string) {
  return topic
    .toLowerCase()
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export default function TopicTrends({ token }: { token: string }) {
  const [data, setData] = useState<TrendsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/v1/insights/trends?window_days=7`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error("Could not load coverage trends");
        const json = await res.json();
        if (!cancelled) setData(json);
      } catch (err: any) {
        if (!cancelled) setError(err.message || "Could not load coverage trends");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const gainers = data?.topics.filter((t) => t.delta > 0) ?? [];

  return (
    <section className="bg-surface-container border border-outline-variant rounded-lg p-stack-md">
      <div className="flex items-center justify-between gap-2 mb-4">
        <h3 className="font-label-caps text-label-caps text-zinc-400 uppercase tracking-widest text-[10px] flex items-center gap-2">
          <Activity className="w-3.5 h-3.5 text-primary" />
          Topics gaining coverage
        </h3>
        {data && (
          <span className="text-[9px] text-zinc-600 font-mono-data uppercase tracking-wider">
            {data.window_days}d vs prior {data.window_days}d
          </span>
        )}
      </div>

      {loading && (
        <div className="flex items-center gap-2 py-6 text-primary text-xs font-mono-data animate-pulse">
          <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Comparing coverage windows...
        </div>
      )}

      {!loading && error && (
        <div className="p-3 rounded-xl bg-cyber-rose/10 border border-cyber-rose/30 text-cyber-rose text-xs font-mono-data">
          {error}
        </div>
      )}

      {!loading && !error && data && data.topics.length === 0 && (
        <p className="text-[11px] text-zinc-500 font-mono-data">
          Not enough processed coverage to compare yet.
        </p>
      )}

      {!loading && !error && data && data.topics.length > 0 && (
        <div className="space-y-2">
          {gainers.length === 0 && (
            <p className="text-[10px] text-zinc-500 font-mono-data mb-1">
              No topic gained coverage over this window &mdash; showing the ranking below.
            </p>
          )}
          {data.topics.map((t) => {
            const Icon = t.direction === "up" ? TrendingUp : t.direction === "down" ? TrendingDown : Minus;
            const color =
              t.direction === "up" ? "text-cyber-emerald" : t.direction === "down" ? "text-cyber-rose" : "text-zinc-500";
            return (
              <div
                key={t.topic}
                className="flex items-center gap-3 p-2.5 rounded-xl bg-zinc-950/40 border border-zinc-900"
              >
                <Icon className={`w-4 h-4 flex-shrink-0 ${color}`} />
                <span className="flex-1 min-w-0 text-xs text-zinc-200 truncate">{topicLabel(t.topic)}</span>
                {t.is_new && (
                  <span className="px-1.5 py-0.5 rounded bg-cyber-indigo/15 border border-cyber-indigo/30 text-cyber-indigo text-[9px] font-mono-data uppercase tracking-wider">
                    New
                  </span>
                )}
                <span className={`text-xs font-mono-data font-bold ${color}`}>
                  {t.delta > 0 ? `+${t.delta}` : t.delta < 0 ? t.delta : "0"}
                </span>
                <span className="w-14 text-right text-[10px] text-zinc-500 font-mono-data">
                  {t.current} events
                </span>
              </div>
            );
          })}
        </div>
      )}

      <p className="mt-3 text-[10px] text-zinc-600 font-mono-data leading-relaxed">
        Counts processed events only. An event is counted in the window it was created, so this is a
        view of emerging coverage, not of when a story was published.
      </p>
    </section>
  );
}
