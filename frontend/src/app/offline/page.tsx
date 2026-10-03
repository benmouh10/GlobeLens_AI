"use client";

/**
 * Offline Library — browse dossiers saved to this device.
 *
 * This route is precached by the service worker, so it is reachable with no
 * network at all. Saved snapshots are rendered inline (not via the Next router)
 * because client-side route transitions fetch RSC payloads and would fail
 * offline; keeping everything on one route makes the promise real.
 */

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Trash2, RefreshCw, HardDriveDownload, Clock } from "lucide-react";
import PillNav from "../components/PillNav";
import EventSnapshot from "../../components/EventSnapshot";
import { listSavedEvents, removeEventForOffline, SavedEvent } from "../../lib/offline";

function formatSaved(ts: number): string {
  return new Date(ts).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function OfflinePage() {
  const router = useRouter();
  const [items, setItems] = useState<SavedEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [online, setOnline] = useState(true);

  useEffect(() => {
    let cancelled = false;
    listSavedEvents().then((rows) => {
      if (cancelled) return;
      setItems(rows);
      setSelectedId((prev) => prev || (rows[0] ? rows[0].id : null));
      setLoading(false);
    });
    const update = () => setOnline(navigator.onLine);
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      cancelled = true;
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  const handleRemove = async (id: string) => {
    if (!window.confirm("Remove this offline copy from this device?")) return;
    await removeEventForOffline(id);
    const next = items.filter((r) => r.id !== id);
    setItems(next);
    if (selectedId === id) setSelectedId(next[0] ? next[0].id : null);
  };

  const selected = items.find((r) => r.id === selectedId) || null;

  return (
    <div className="bg-background text-on-background min-h-screen flex flex-col font-body-md">
      <header className="flex justify-between items-center px-margin-desktop w-full h-16 sticky top-0 z-50 bg-[#080c16]/80 backdrop-blur-lg border-b border-indigo-950/40 flex-shrink-0">
        <PillNav
          logo="/logo.svg"
          logoAlt="GlobeLens AI Logo"
          items={[
            {
              label: "Standard",
              href: "/?view=standard",
              onClick: (e) => {
                e.preventDefault();
                router.push("/?view=standard");
              },
            },
            {
              label: "Map",
              href: "/?view=map",
              onClick: (e) => {
                e.preventDefault();
                router.push("/?view=map");
              },
            },
            { label: "Profile", href: "/profile" },
            { label: "Dispatches", href: "/dispatches" },
            { label: "Reading Lists", href: "/reading-lists" },
            { label: "Newsletter", href: "/newsletter" },
            { label: "Fact Checker", href: "/fact-checker" },
            { label: "Offline", href: "/offline" },
          ]}
          activeHref="/offline"
          baseColor="#080c16"
          pillColor="#0c101b"
          hoveredPillTextColor="#22d3ee"
          pillTextColor="#94a3b8"
          initialLoadAnimation={false}
        />
      </header>

      <div className="flex-1 max-w-[1440px] mx-auto w-full grid grid-cols-1 lg:grid-cols-12 gap-gutter px-margin-mobile lg:px-margin-desktop py-stack-lg">
        {/* Library list */}
        <aside className="col-span-1 lg:col-span-4 flex flex-col gap-4">
          <div className="flex items-center justify-between gap-3">
            <h1 className="font-headline-xl text-headline-xl text-primary tracking-tight flex items-center gap-2">
              <HardDriveDownload className="w-6 h-6" />
              Offline Library
            </h1>
            {!online && (
              <span className="text-[10px] font-mono-data uppercase tracking-wider text-amber-400 border border-amber-500/30 bg-amber-500/5 rounded px-2 py-1">
                No connection
              </span>
            )}
          </div>
          <p className="text-sm text-zinc-500 leading-relaxed">
            Dossiers you chose to save on this device. They open without a
            connection and are stamped with the time they were saved.
          </p>

          {loading && (
            <div className="flex items-center gap-2 text-primary text-xs font-mono-data animate-pulse py-4">
              <RefreshCw className="w-4 h-4 animate-spin" /> Loading saved dossiers...
            </div>
          )}

          {!loading && items.length === 0 && (
            <div className="rounded border border-dashed border-outline-variant p-6 text-center">
              <p className="text-sm text-zinc-400 mb-4">
                Nothing saved yet. Open a dossier and use “Save offline”.
              </p>
              <button
                onClick={() => router.push("/")}
                className="inline-flex items-center gap-2 bg-primary hover:bg-primary-fixed text-on-primary font-label-caps text-[12px] px-5 py-2.5 rounded tracking-wider uppercase font-bold transition-all"
              >
                <ArrowLeft className="w-4 h-4" />
                Browse news
              </button>
            </div>
          )}

          {items.length > 0 && (
            <ul className="flex flex-col gap-2">
              {items.map((item) => (
                <li key={item.id}>
                  <div
                    className={`flex items-start gap-3 rounded-lg border p-3 transition-colors ${
                      selectedId === item.id
                        ? "border-primary bg-surface-container"
                        : "border-outline-variant hover:border-primary/60"
                    }`}
                  >
                    <button
                      onClick={() => setSelectedId(item.id)}
                      className="flex-1 text-left min-w-0"
                    >
                      <span className="block text-sm font-semibold text-on-surface leading-snug line-clamp-2">
                        {item.title}
                      </span>
                      <span className="mt-1 flex items-center gap-1.5 text-[10px] text-zinc-500 font-mono-data">
                        <Clock className="w-3 h-3" />
                        Saved {formatSaved(item.savedAt)}
                      </span>
                    </button>
                    <button
                      onClick={() => handleRemove(item.id)}
                      title="Remove offline copy"
                      className="text-zinc-600 hover:text-cyber-rose transition-colors flex-shrink-0 p-1"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </aside>

        {/* Reader */}
        <main className="col-span-1 lg:col-span-8">
          {selected ? (
            <div className="glass-panel rounded p-stack-md">
              <EventSnapshot event={selected.event} savedAt={selected.savedAt} />
            </div>
          ) : (
            !loading && (
              <div className="h-full flex items-center justify-center text-center px-6">
                <p className="text-sm text-zinc-500">
                  Select a saved dossier to read it offline.
                </p>
              </div>
            )
          )}
        </main>
      </div>
    </div>
  );
}
