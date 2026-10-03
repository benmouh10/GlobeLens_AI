"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Calendar, ExternalLink, FileText, RefreshCw, User } from "lucide-react";
import PillNav from "../components/PillNav";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const API = `${API_BASE_URL}/api/v1`;
const PAGE_SIZE = 12;

interface Article {
  id: string;
  title: string;
  content: string;
  url: string | null;
  published_at: string | null;
  created_at: string | null;
  author: { id: string; name: string } | null;
}

function excerpt(text: string, max = 180): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max)}…` : flat;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export default function DispatchesPage() {
  const router = useRouter();
  const [articles, setArticles] = useState<Article[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [userRole, setUserRole] = useState<string | null>(null);

  const load = useCallback(async (targetPage: number) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/articles/authored?page=${targetPage}&limit=${PAGE_SIZE}`);
      if (!res.ok) throw new Error(`Could not load dispatches (${res.status})`);
      const data = await res.json();
      setArticles(data.articles || []);
      setTotal(data.total || 0);
    } catch (err: any) {
      setError(err.message || "Could not load dispatches");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(page);
  }, [page, load]);

  useEffect(() => {
    const token = typeof window !== "undefined" ? localStorage.getItem("admin_token") : null;
    if (!token) return;
    fetch(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : null))
      .then((me) => {
        if (me) setUserRole(me.role);
      })
      .catch(() => {});
  }, []);

  const showAdmin = userRole === "ADMIN";

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

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
            { label: "Newsletter", href: "/newsletter" },
            { label: "Profile", href: "/profile" },
            ...(showAdmin ? [{ label: "Admin", href: "/admin/dashboard" }] : []),
            { label: "Fact Checker", href: "/fact-checker" },
            { label: "Offline", href: "/offline" },
          ]}
          activeHref="/dispatches"
          baseColor="#080c16"
          pillColor="#0c101b"
          hoveredPillTextColor="#22d3ee"
          pillTextColor="#94a3b8"
          initialLoadAnimation={false}
        />
      </header>

      <div className="absolute inset-0 bg-[linear-gradient(to_right,rgba(69,70,77,0.06)_1px,transparent_1px),linear-gradient(to_bottom,rgba(69,70,77,0.06)_1px,transparent_1px)] bg-[size:40px_40px] pointer-events-none z-0"></div>

      <main className="flex-grow w-full max-w-5xl mx-auto px-margin-mobile md:px-margin-desktop py-stack-lg z-10 relative">
        <button
          onClick={() => router.push("/")}
          className="flex items-center gap-1.5 text-zinc-500 hover:text-primary transition-colors font-label-caps text-[10px] uppercase tracking-wider font-bold mb-6"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to Global Map
        </button>

        <div className="flex items-center gap-3 mb-8">
          <div className="w-8 h-8 rounded bg-primary/10 text-primary flex items-center justify-center">
            <FileText className="w-4 h-4" />
          </div>
          <div>
            <h1 className="font-display-lg text-[26px] md:text-display-lg text-on-surface leading-tight font-bold">
              Dispatches
            </h1>
            <span className="font-label-caps text-label-caps text-on-surface-variant text-[10px] uppercase tracking-wider">
              Newsroom Reporting
            </span>
          </div>
        </div>

        {loading && (
          <div className="flex items-center justify-center gap-2 py-24 text-primary text-sm font-mono-data animate-pulse">
            <RefreshCw className="w-4 h-4 animate-spin" /> Loading dispatches...
          </div>
        )}

        {!loading && error && (
          <div className="p-4 rounded border border-cyber-rose/30 bg-cyber-rose/10 text-cyber-rose text-sm font-mono-data">
            {error}
          </div>
        )}

        {!loading && !error && articles.length === 0 && (
          <div className="max-w-lg mx-auto text-center bg-surface-container border border-outline-variant rounded-lg p-8 mt-8">
            <div className="w-12 h-12 mx-auto rounded-full bg-zinc-900 border border-outline-variant flex items-center justify-center mb-4">
              <FileText className="w-5 h-5 text-zinc-500" />
            </div>
            <h2 className="font-headline-lg text-[20px] text-on-surface font-bold">No Dispatches Yet</h2>
            <p className="text-on-surface-variant text-sm mt-2 leading-relaxed">
              Nothing has been published by the newsroom desk so far. Check back shortly.
            </p>
          </div>
        )}

        {!loading && !error && articles.length > 0 && (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-stack-md">
              {articles.map((a) => (
                <Link
                  key={a.id}
                  href={`/dispatches/${a.id}`}
                  className="group bg-surface-container border border-outline-variant rounded-lg p-stack-md hover:border-primary/40 transition-all flex flex-col"
                >
                  <h2 className="font-headline-lg text-[19px] text-on-surface font-bold leading-snug group-hover:text-primary transition-colors">
                    {a.title}
                  </h2>
                  <p className="text-on-surface-variant text-sm mt-3 leading-relaxed flex-grow">
                    {excerpt(a.content)}
                  </p>
                  <div className="flex items-center gap-3 mt-4 pt-3 border-t border-outline-variant/60 flex-wrap">
                    <span className="inline-flex items-center gap-1.5 text-[10px] text-zinc-400 font-mono-data uppercase tracking-wider">
                      <User className="w-3.5 h-3.5 text-primary" />
                      {a.author?.name || "Newsroom"}
                    </span>
                    <span className="inline-flex items-center gap-1.5 text-[10px] text-zinc-500 font-mono-data uppercase tracking-wider">
                      <Calendar className="w-3.5 h-3.5" />
                      {formatDate(a.published_at || a.created_at)}
                    </span>
                    {a.url && (
                      <span className="inline-flex items-center gap-1 text-[10px] text-cyber-cyan font-mono-data uppercase tracking-wider ml-auto">
                        <ExternalLink className="w-3.5 h-3.5" /> Source
                      </span>
                    )}
                  </div>
                </Link>
              ))}
            </div>

            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-4 mt-8 font-mono-data text-xs uppercase tracking-wider">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="px-4 py-2 rounded-lg border border-outline-variant text-zinc-400 hover:text-primary hover:border-primary/40 transition-all disabled:opacity-40 disabled:hover:text-zinc-400 disabled:hover:border-outline-variant"
                >
                  Prev
                </button>
                <span className="text-zinc-500">
                  Page {page} / {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="px-4 py-2 rounded-lg border border-outline-variant text-zinc-400 hover:text-primary hover:border-primary/40 transition-all disabled:opacity-40 disabled:hover:text-zinc-400 disabled:hover:border-outline-variant"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
