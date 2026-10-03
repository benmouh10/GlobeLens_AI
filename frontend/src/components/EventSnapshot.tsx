"use client";

/**
 * Read-only rendering of a saved dossier snapshot.
 *
 * Intentionally independent of the live event page: that page is wired to
 * comments, fact-checks and related-event fetches that all fail offline. This
 * component only ever reads the frozen copy, so it can promise the reader that
 * everything shown is local and needs no connection.
 */

import React from "react";
import { Shield, AlertTriangle, CheckCircle, ExternalLink, Clock } from "lucide-react";
import type { OfflineEvent, OfflineArticle } from "../lib/offline";

interface Props {
  event: OfflineEvent;
  savedAt: number;
}

function formatSaved(ts: number): string {
  return new Date(ts).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function reliability(event: OfflineEvent): number {
  if (!event.articles || event.articles.length === 0) return 88;
  return Math.round(
    (event.articles.reduce(
      (acc, a) => acc + (a.source.credibility_score || 0.85),
      0
    ) /
      event.articles.length) *
      100
  );
}

export default function EventSnapshot({ event, savedAt }: Props) {
  const articles = event.articles || [];
  const contradictions = event.contradictions || [];

  const byCitation = new Map<number, OfflineArticle>();
  for (const art of articles) {
    if (art.citation_index != null) byCitation.set(art.citation_index, art);
  }

  const paragraphs = (event.summary || "")
    .split("\n\n")
    .filter((p) => p.trim().length > 0);

  return (
    <article className="flex flex-col gap-6">
      {/* Snapshot stamp — the whole point of this surface is that the reader
          can tell this copy is not live. */}
      <div className="flex items-center gap-2 rounded border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[11px] font-mono-data text-amber-400">
        <Clock className="w-3.5 h-3.5 flex-shrink-0" />
        <span>
          Offline copy — saved {formatSaved(savedAt)}. No connection required;
          live updates are not reflected here.
        </span>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-secondary font-label-caps text-label-caps uppercase tracking-wider">
          {event.topic}
        </span>
        <span className="text-outline-variant">•</span>
        <span className="text-on-surface-variant font-mono-data text-mono-data">
          {event.created_at ? new Date(event.created_at).toUTCString() : "Active Intel"}
        </span>
        <div className="flex items-center gap-1.5 px-2.5 py-0.5 bg-surface-container rounded-full border border-outline-variant border-l-2 border-l-primary">
          <Shield className="w-3.5 h-3.5 text-primary" />
          <span className="font-mono-data text-mono-data text-primary">
            {reliability(event)}% Reliable
          </span>
        </div>
      </div>

      <h1 className="font-display-lg text-[26px] md:text-display-lg text-on-surface leading-tight font-bold">
        {event.title}
      </h1>

      <p className="font-body-lg text-body-lg text-secondary leading-relaxed border-l-4 border-surface-variant pl-4">
        Offline dossier snapshot for {event.country || "Global Region"}.
      </p>

      <section className="glass-panel p-stack-md rounded flex flex-col md:flex-row gap-6 justify-between items-start md:items-center w-full">
        <div className="flex flex-col gap-1">
          <h3 className="font-label-caps text-label-caps text-on-surface-variant uppercase">
            Synthesis Metrics
          </h3>
          <p className="font-body-sm text-body-sm text-on-surface max-w-md">
            Aggregated from {articles.length} independent source wire
            {articles.length === 1 ? "" : "s"}.
          </p>
        </div>
        <div className="flex flex-col gap-2 min-w-[160px]">
          <div className="flex justify-between font-mono-data text-mono-data">
            <span className="text-on-surface-variant">Importance</span>
            <span className="text-primary font-bold">
              {event.importance_score.toFixed(1)}/10
            </span>
          </div>
          <div className="h-1.5 w-full bg-zinc-950 rounded-full overflow-hidden">
            <div
              className="h-full bg-primary rounded-r-full"
              style={{ width: `${Math.max(0, Math.min(100, event.importance_score * 10))}%` }}
            />
          </div>
        </div>
      </section>

      <div className="border-b border-outline-variant/40 pb-6">
        <h3 className="font-label-caps text-label-caps text-zinc-500 uppercase tracking-widest text-[10px] mb-4">
          EDITORIAL SYNTHESIS REPORT
        </h3>
        <div className="max-w-3xl">
          {paragraphs.length === 0 && (
            <p className="text-zinc-500 italic">No summary details compiled yet.</p>
          )}
          {paragraphs.map((para, pIdx) => (
            <p key={pIdx} className="mb-6 text-on-surface leading-[1.8] text-body-lg font-body-lg">
              {para.split(/(\[\d+\])/g).map((part, sIdx) => {
                const match = part.match(/\[(\d+)\]/);
                if (!match) return <span key={sIdx}>{part}</span>;
                const art = byCitation.get(parseInt(match[1]));
                if (!art) {
                  return (
                    <span
                      key={sIdx}
                      className="inline-flex items-center justify-center bg-amber-500/10 text-amber-400 text-[10px] rounded px-1 ml-0.5 align-super border border-amber-500/30"
                    >
                      {match[1]}?
                    </span>
                  );
                }
                return (
                  <span
                    key={sIdx}
                    title={`${art.source.name}: ${art.title}`}
                    className="inline-flex items-center justify-center bg-zinc-800 text-[10px] text-zinc-300 rounded px-1 ml-0.5 align-super"
                  >
                    {match[1]}
                  </span>
                );
              })}
            </p>
          ))}
        </div>
      </div>

      {contradictions.length > 0 && (
        <div className="border-b border-outline-variant/40 pb-6">
          <h3 className="font-label-caps text-label-caps text-zinc-500 uppercase tracking-widest text-[10px] mb-4 flex items-center gap-2">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
            Sources Disagree
          </h3>
          <div className="space-y-4 max-w-3xl">
            {contradictions.map((c, i) => (
              <div
                key={`${c.nature}-${i}`}
                className="border-l-2 border-amber-500/60 bg-amber-500/5 pl-4 py-3"
              >
                <p className="text-[11px] font-mono-data text-amber-400/90 mb-3">{c.detail}</p>
                <div className="space-y-2">
                  <blockquote className="text-sm text-zinc-300 border-l border-zinc-600 pl-3">
                    <span className="text-[10px] uppercase tracking-wider text-zinc-500 block mb-1">
                      {c.claim_a.source}
                    </span>
                    {c.claim_a.text}
                  </blockquote>
                  <blockquote className="text-sm text-zinc-300 border-l border-zinc-600 pl-3">
                    <span className="text-[10px] uppercase tracking-wider text-zinc-500 block mb-1">
                      {c.claim_b.source}
                    </span>
                    {c.claim_b.text}
                  </blockquote>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <section className="space-y-4">
        <h3 className="font-label-caps text-label-caps text-zinc-400 uppercase tracking-widest text-[11px]">
          Corroborating Source Documentation ({articles.length})
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {articles.map((art) => (
            <div
              key={art.id}
              className="bg-zinc-950/40 border border-zinc-900 rounded-xl p-4 flex flex-col justify-between"
            >
              <div>
                <div className="flex justify-between items-start mb-2">
                  <span className="font-mono-data text-[10px] px-2 py-0.5 rounded bg-zinc-900 text-zinc-400 font-bold border border-zinc-800 uppercase">
                    {art.source.name}
                  </span>
                  <span className="text-[10px] font-bold text-emerald-400 flex items-center gap-1">
                    <CheckCircle className="w-3 h-3" />{" "}
                    {Math.round((art.source.credibility_score || 0.85) * 100)}% Trust
                  </span>
                </div>
                <h4 className="text-sm font-semibold text-white leading-snug mb-3">{art.title}</h4>
              </div>
              <span className="text-zinc-500 text-[10px] flex items-center gap-1 uppercase tracking-wider border-t border-zinc-900/60 pt-2.5">
                Source link unavailable offline <ExternalLink className="w-3 h-3" />
              </span>
            </div>
          ))}
          {articles.length === 0 && (
            <div className="col-span-2 p-6 rounded bg-zinc-950/20 border border-dashed border-zinc-800 text-center">
              <p className="text-zinc-500 text-sm">
                No external wire references associated with this event.
              </p>
            </div>
          )}
        </div>
      </section>
    </article>
  );
}
