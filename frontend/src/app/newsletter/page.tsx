"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  BellRing,
  CalendarClock,
  CheckCircle2,
  Loader2,
  Mail,
  Tag,
  X,
} from "lucide-react";
import PillNav from "../components/PillNav";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const API = `${API_BASE_URL}/api/v1`;

// Coarse interests that map onto the event topics stored by the pipeline.
const TOPICS = ["POLITICS", "WORLD", "TECHNOLOGY", "ECONOMY", "HEALTH", "SPORTS", "ENVIRONMENT"];

export default function NewsletterPage() {
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [frequency, setFrequency] = useState<"daily" | "weekly">("daily");
  const [interests, setInterests] = useState<string[]>([]);
  const [status, setStatus] = useState<"idle" | "sending" | "success" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);

  const toggleTopic = (topic: string) => {
    setInterests((prev) =>
      prev.includes(topic) ? prev.filter((t) => t !== topic) : [...prev, topic]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (status === "sending") return;

    const trimmed = email.trim();
    if (!trimmed) {
      setStatus("error");
      setMessage("Enter an email address.");
      return;
    }

    setStatus("sending");
    setMessage(null);
    try {
      const res = await fetch(`${API}/newsletter/subscribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: trimmed, interests, frequency }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail =
          typeof data.detail === "string"
            ? data.detail
            : Array.isArray(data.detail)
            ? data.detail.map((d: any) => d.msg).join(", ")
            : "Could not subscribe.";
        throw new Error(detail);
      }
      setStatus("success");
      setMessage(data.message || "Check your inbox to confirm your subscription.");
      setEmail("");
    } catch (err: any) {
      setStatus("error");
      setMessage(err.message || "Could not subscribe. Please try again.");
    }
  };

  return (
    <div className="bg-background text-on-background min-h-screen flex flex-col font-body-md relative overflow-x-hidden">
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
            { label: "Dispatches", href: "/dispatches" },
            { label: "Reading Lists", href: "/reading-lists" },
            { label: "Profile", href: "/profile" },
            { label: "Fact Checker", href: "/fact-checker" },
            { label: "Offline", href: "/offline" },
          ]}
          activeHref="/newsletter"
          baseColor="#080c16"
          pillColor="#0c101b"
          hoveredPillTextColor="#22d3ee"
          pillTextColor="#94a3b8"
          initialLoadAnimation={false}
        />
      </header>

      <div className="absolute inset-0 bg-[linear-gradient(to_right,rgba(69,70,77,0.06)_1px,transparent_1px),linear-gradient(to_bottom,rgba(69,70,77,0.06)_1px,transparent_1px)] bg-[size:40px_40px] pointer-events-none z-0"></div>

      <main className="flex-grow w-full max-w-4xl mx-auto px-margin-mobile md:px-margin-desktop py-stack-lg z-10 relative">
        <button
          onClick={() => router.push("/")}
          className="flex items-center gap-1.5 text-zinc-500 hover:text-primary transition-colors font-label-caps text-[10px] uppercase tracking-wider font-bold mb-6"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to Global Map
        </button>

        <div className="flex items-center gap-3 mb-8">
          <div className="w-8 h-8 rounded bg-primary/10 text-primary flex items-center justify-center">
            <BellRing className="w-4 h-4" />
          </div>
          <div>
            <h1 className="font-display-lg text-[26px] md:text-display-lg text-on-surface leading-tight font-bold">
              Intelligence Brief
            </h1>
            <span className="font-label-caps text-label-caps text-on-surface-variant text-[10px] uppercase tracking-wider">
              Personalized World Coverage, Delivered
            </span>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-5 gap-gutter">
          {/* Form */}
          <form
            onSubmit={handleSubmit}
            className="md:col-span-3 bg-surface-container border border-outline-variant rounded-lg p-6"
          >
            <label className="block font-mono-data text-[10px] text-zinc-400 uppercase tracking-widest font-bold mb-2">
              Email
            </label>
            <div className="relative">
              <Mail className="w-4 h-4 text-zinc-600 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (status !== "idle") {
                    setStatus("idle");
                    setMessage(null);
                  }
                }}
                placeholder="you@domain.com"
                className="w-full bg-zinc-950/60 border border-outline-variant rounded-xl pl-9 pr-3 py-2.5 text-sm text-zinc-200 focus:outline-none focus:border-primary transition-all"
              />
            </div>

            <label className="block font-mono-data text-[10px] text-zinc-400 uppercase tracking-widest font-bold mt-6 mb-2">
              Cadence
            </label>
            <div className="grid grid-cols-2 gap-2">
              {(["daily", "weekly"] as const).map((f) => {
                const active = frequency === f;
                return (
                  <button
                    key={f}
                    type="button"
                    onClick={() => setFrequency(f)}
                    className={`flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl border font-mono-data text-[11px] font-bold uppercase tracking-widest transition-all ${
                      active
                        ? "border-primary/40 bg-primary/10 text-primary"
                        : "border-outline-variant text-zinc-400 hover:text-zinc-200"
                    }`}
                  >
                    <CalendarClock className="w-3.5 h-3.5" />
                    {f === "daily" ? "Daily Brief" : "Weekly Deep Dive"}
                  </button>
                );
              })}
            </div>

            <label className="block font-mono-data text-[10px] text-zinc-400 uppercase tracking-widest font-bold mt-6 mb-2">
              Interests <span className="text-zinc-600">(optional)</span>
            </label>
            <div className="flex flex-wrap gap-2">
              {TOPICS.map((topic) => {
                const active = interests.includes(topic);
                return (
                  <button
                    key={topic}
                    type="button"
                    onClick={() => toggleTopic(topic)}
                    className={`px-3 py-1.5 rounded-full border font-mono-data text-[10px] font-bold uppercase tracking-wider transition-all ${
                      active
                        ? "border-cyber-cyan/50 bg-cyber-cyan/10 text-cyber-cyan"
                        : "border-outline-variant text-zinc-500 hover:text-zinc-300"
                    }`}
                  >
                    {topic}
                  </button>
                );
              })}
            </div>
            <p className="mt-2 text-[11px] text-zinc-600">
              Leave empty to receive the highest-impact stories worldwide.
            </p>

            <button
              type="submit"
              disabled={status === "sending"}
              className="mt-6 w-full flex items-center justify-center gap-2 px-4 py-3 bg-primary/10 hover:bg-primary/20 border border-primary/30 text-primary font-mono-data text-[12px] font-bold tracking-widest uppercase rounded-xl transition-all disabled:opacity-60"
            >
              {status === "sending" ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Subscribing…
                </>
              ) : (
                <>
                  <BellRing className="w-4 h-4" />
                  Subscribe
                </>
              )}
            </button>

            {message && (
              <div
                className={`mt-4 p-3 rounded-xl border text-xs font-mono-data tracking-wide flex items-start gap-2 ${
                  status === "success"
                    ? "bg-cyber-emerald/10 border-cyber-emerald/30 text-cyber-emerald"
                    : "bg-cyber-rose/10 border-cyber-rose/30 text-cyber-rose"
                }`}
              >
                {status === "success" ? (
                  <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" />
                ) : (
                  <X className="w-4 h-4 shrink-0 mt-0.5" />
                )}
                <span>{message}</span>
              </div>
            )}
          </form>

          {/* Info panel */}
          <aside className="md:col-span-2 bg-surface-container border border-outline-variant rounded-lg p-6">
            <h2 className="font-mono-data text-[11px] text-zinc-300 uppercase tracking-widest font-bold mb-4">
              What you get
            </h2>
            <ul className="space-y-4 text-sm text-zinc-400 leading-relaxed">
              <li className="flex gap-3">
                <Tag className="w-4 h-4 text-cyber-cyan shrink-0 mt-0.5" />
                <span>
                  A curated digest of the highest-importance dossiers, ranked by
                  our intelligence score.
                </span>
              </li>
              <li className="flex gap-3">
                <BellRing className="w-4 h-4 text-cyber-indigo shrink-0 mt-0.5" />
                <span>
                  Interest-based filtering: pick topics and receive only the
                  stories that matter to you.
                </span>
              </li>
              <li className="flex gap-3">
                <Mail className="w-4 h-4 text-cyber-amber shrink-0 mt-0.5" />
                <span>
                  Double opt-in. We send a confirmation link first, and every
                  email has a one-click unsubscribe.
                </span>
              </li>
            </ul>
          </aside>
        </div>
      </main>
    </div>
  );
}
