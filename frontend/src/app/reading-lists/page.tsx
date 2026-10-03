"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  BookOpen,
  ChevronDown,
  ChevronUp,
  FileText,
  Globe,
  Loader2,
  Plus,
  Printer,
  Trash2,
  X,
} from "lucide-react";
import PrimaryNav from "../components/PrimaryNav";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const API = `${API_BASE_URL}/api/v1`;

interface ReadingListSummary {
  id: string;
  name: string;
  description: string | null;
  is_public: boolean;
  item_count: number;
  created_at: string | null;
  updated_at: string | null;
}

interface Target {
  id: string;
  title: string;
  topic?: string;
  country?: string;
  summary?: string | null;
  importance_score?: number;
  publication_status?: string;
}

interface ReadingListItem {
  id: string;
  type: "event" | "article";
  position: number;
  note: string | null;
  target: Target | null;
}

interface ReadingListDetail extends ReadingListSummary {
  items: ReadingListItem[];
}

export default function ReadingListsPage() {
  const router = useRouter();

  const [token, setToken] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [userRole, setUserRole] = useState<string | null>(null);
  const [lists, setLists] = useState<ReadingListSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ReadingListDetail | null>(null);

  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [newListName, setNewListName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState("");

  // Resolve identity from storage in an effect (client component), then load.
  useEffect(() => {
    const saved = typeof window !== "undefined" ? localStorage.getItem("admin_token") : null;
    if (!saved) {
      router.push("/login");
      return;
    }
    setToken(saved);

    const boot = async () => {
      try {
        const meRes = await fetch(`${API}/auth/me`, {
          headers: { Authorization: `Bearer ${saved}` },
        });
        if (meRes.status === 401) {
          localStorage.removeItem("admin_token");
          router.push("/login");
          return;
        }
        if (!meRes.ok) throw new Error("Could not load your account");
        const me = await meRes.json();
        setUserId(me.id);
        setUserRole(me.role);
      } catch (err: any) {
        setError(err.message || "Could not load your account");
        setLoading(false);
      }
    };
    boot();
  }, [router]);

  const loadLists = useCallback(
    async (uid: string, tok: string) => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${API}/users/${uid}/reading-lists`, {
          headers: { Authorization: `Bearer ${tok}` },
        });
        if (res.status === 401) {
          router.push("/login");
          return;
        }
        if (!res.ok) throw new Error(`Could not load reading lists (${res.status})`);
        const data = await res.json();
        const incoming: ReadingListSummary[] = data.reading_lists || [];
        setLists(incoming);
        setSelectedId((prev) =>
          prev && incoming.some((l) => l.id === prev) ? prev : incoming[0]?.id ?? null
        );
      } catch (err: any) {
        setError(err.message || "Could not load reading lists");
      } finally {
        setLoading(false);
      }
    },
    [router]
  );

  useEffect(() => {
    if (userId && token) loadLists(userId, token);
  }, [userId, token, loadLists]);

  const loadDetail = useCallback(
    async (listId: string) => {
      if (!token || !userId) return;
      setDetailLoading(true);
      try {
        const res = await fetch(`${API}/users/${userId}/reading-lists/${listId}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error(`Could not load list (${res.status})`);
        setDetail(await res.json());
      } catch (err: any) {
        setError(err.message || "Could not load list");
        setDetail(null);
      } finally {
        setDetailLoading(false);
      }
    },
    [token, userId]
  );

  useEffect(() => {
    if (selectedId) loadDetail(selectedId);
    else setDetail(null);
  }, [selectedId, loadDetail]);

  const handleCreateList = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !userId || creating) return;
    const name = newListName.trim();
    if (!name) {
      setCreateError("Name cannot be empty");
      return;
    }
    setCreating(true);
    setCreateError(null);
    try {
      const res = await fetch(`${API}/users/${userId}/reading-lists`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Could not create list");
      }
      const created: ReadingListSummary = await res.json();
      setNewListName("");
      setLists((prev) => [created, ...prev]);
      setSelectedId(created.id);
    } catch (err: any) {
      setCreateError(err.message || "Could not create list");
    } finally {
      setCreating(false);
    }
  };

  const handleRename = async () => {
    if (!token || !userId || !detail) return;
    const name = renameValue.trim();
    if (!name) return;
    setBusy(true);
    try {
      const res = await fetch(`${API}/users/${userId}/reading-lists/${detail.id}`, {
        method: "PUT",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Could not rename list");
      }
      const updated = await res.json();
      setLists((prev) => prev.map((l) => (l.id === updated.id ? { ...l, ...updated } : l)));
      setDetail((prev) => (prev ? { ...prev, name: updated.name } : prev));
      setRenaming(false);
    } catch (err: any) {
      setError(err.message || "Could not rename list");
    } finally {
      setBusy(false);
    }
  };

  const handleDeleteList = async () => {
    if (!token || !userId || !detail) return;
    if (!confirm(`Delete the reading list "${detail.name}"? This cannot be undone.`)) return;
    setBusy(true);
    try {
      const res = await fetch(`${API}/users/${userId}/reading-lists/${detail.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status !== 204 && !res.ok) throw new Error(`Delete failed (${res.status})`);
      // Cleanup when last list was removed.
      const remaining = lists.filter((l) => l.id !== detail.id);
      setLists(remaining);
      setDetail(null);
      setSelectedId(remaining[0]?.id ?? null);
    } catch (err: any) {
      setError(err.message || "Could not delete list");
    } finally {
      setBusy(false);
    }
  };

  const handleRemoveItem = async (itemId: string) => {
    if (!token || !userId || !detail) return;
    setBusy(true);
    try {
      const res = await fetch(
        `${API}/users/${userId}/reading-lists/${detail.id}/items/${itemId}`,
        { method: "DELETE", headers: { Authorization: `Bearer ${token}` } }
      );
      if (res.status !== 204 && !res.ok) throw new Error(`Remove failed (${res.status})`);
      setDetail((prev) =>
        prev
          ? { ...prev, items: prev.items.filter((i) => i.id !== itemId), item_count: prev.item_count - 1 }
          : prev
      );
      setLists((prev) =>
        prev.map((l) => (l.id === detail.id ? { ...l, item_count: Math.max(0, l.item_count - 1) } : l))
      );
    } catch (err: any) {
      setError(err.message || "Could not remove item");
    } finally {
      setBusy(false);
    }
  };

  const handleMove = async (index: number, direction: -1 | 1) => {
    if (!token || !userId || !detail) return;
    const target = index + direction;
    if (target < 0 || target >= detail.items.length) return;
    const next = [...detail.items];
    [next[index], next[target]] = [next[target], next[index]];
    // Optimistic reorder; revert if the request fails.
    const previous = detail.items;
    setDetail({ ...detail, items: next });
    setBusy(true);
    try {
      const res = await fetch(
        `${API}/users/${userId}/reading-lists/${detail.id}/items/reorder`,
        {
          method: "PUT",
          headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
          body: JSON.stringify({ item_ids: next.map((i) => i.id) }),
        }
      );
      if (!res.ok) throw new Error(`Reorder failed (${res.status})`);
    } catch (err: any) {
      setDetail((prev) => (prev ? { ...prev, items: previous } : prev));
      setError(err.message || "Could not reorder items");
    } finally {
      setBusy(false);
    }
  };

  const handleExport = async () => {
    if (!token || !userId || !detail) return;
    try {
      // Export needs the Authorization header, so fetch it and open the HTML
      // in a new window rather than navigating directly to the URL.
      const res = await fetch(`${API}/users/${userId}/reading-lists/${detail.id}/export`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      const html = await res.text();
      const win = window.open("", "_blank");
      if (!win) {
        setError("Pop-up blocked. Allow pop-ups to export.");
        return;
      }
      win.document.open();
      win.document.write(html);
      win.document.close();
    } catch (err: any) {
      setError(err.message || "Could not export list");
    }
  };

  const showAdmin = userRole === "ADMIN";

  return (
    <div className="bg-background text-on-background min-h-screen flex flex-col font-body-md relative overflow-x-hidden">
      <header className="flex justify-between items-center px-margin-desktop w-full h-16 sticky top-0 z-50 bg-[#080c16]/80 backdrop-blur-lg border-b border-indigo-950/40 flex-shrink-0">
        <PrimaryNav activeHref="/reading-lists" role={userRole} />
      </header>

      <div className="absolute inset-0 bg-[linear-gradient(to_right,rgba(69,70,77,0.06)_1px,transparent_1px),linear-gradient(to_bottom,rgba(69,70,77,0.06)_1px,transparent_1px)] bg-[size:40px_40px] pointer-events-none z-0"></div>

      <main className="flex-grow w-full max-w-6xl mx-auto px-margin-mobile md:px-margin-desktop py-stack-lg z-10 relative">
        <button
          onClick={() => router.push("/")}
          className="flex items-center gap-1.5 text-zinc-500 hover:text-primary transition-colors font-label-caps text-[10px] uppercase tracking-wider font-bold mb-6"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to Global Map
        </button>

        <div className="flex items-center gap-3 mb-8">
          <div className="w-8 h-8 rounded bg-primary/10 text-primary flex items-center justify-center">
            <BookOpen className="w-4 h-4" />
          </div>
          <div>
            <h1 className="font-display-lg text-[26px] md:text-display-lg text-on-surface leading-tight font-bold">
              Reading Lists
            </h1>
            <span className="font-label-caps text-label-caps text-on-surface-variant text-[10px] uppercase tracking-wider">
              Saved Intelligence, Organized
            </span>
          </div>
        </div>

        {error && (
          <div className="mb-6 p-3 rounded-xl bg-cyber-rose/10 border border-cyber-rose/30 text-cyber-rose text-xs font-mono-data uppercase tracking-wider flex items-center justify-between gap-3">
            <span>{error}</span>
            <button onClick={() => setError(null)} className="shrink-0 hover:text-white">
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-24 text-primary text-sm font-mono-data animate-pulse">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading reading lists…
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-gutter">
            {/* Sidebar: lists + create */}
            <aside className="lg:col-span-1 flex flex-col gap-4">
              <form
                onSubmit={handleCreateList}
                className="bg-surface-container border border-outline-variant rounded-lg p-4"
              >
                <label className="block font-mono-data text-[10px] text-zinc-400 uppercase tracking-widest font-bold mb-2">
                  New List
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={newListName}
                    onChange={(e) => {
                      setNewListName(e.target.value);
                      setCreateError(null);
                    }}
                    placeholder="e.g. Iran watch"
                    className="flex-1 bg-zinc-950/60 border border-outline-variant rounded-xl px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-primary transition-all"
                  />
                  <button
                    type="submit"
                    disabled={creating}
                    className="shrink-0 flex items-center justify-center gap-1.5 px-3 py-2 bg-primary/10 hover:bg-primary/20 border border-primary/30 text-primary font-mono-data text-[11px] font-bold tracking-widest uppercase rounded-xl transition-all disabled:opacity-60"
                  >
                    {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                    Add
                  </button>
                </div>
                {createError && (
                  <p className="mt-2 text-cyber-rose text-xs font-mono-data uppercase tracking-wider">
                    {createError}
                  </p>
                )}
              </form>

              <div className="bg-surface-container border border-outline-variant rounded-lg overflow-hidden">
                {lists.length === 0 ? (
                  <p className="p-4 text-xs text-zinc-500 leading-relaxed">
                    No lists yet. Create one, then use “Save to List” on any event dossier.
                  </p>
                ) : (
                  <ul>
                    {lists.map((l) => {
                      const active = l.id === selectedId;
                      return (
                        <li key={l.id}>
                          <button
                            onClick={() => setSelectedId(l.id)}
                            className={`w-full text-left px-4 py-3 border-l-2 transition-all flex items-center justify-between gap-2 ${
                              active
                                ? "border-primary bg-primary/10 text-on-surface"
                                : "border-transparent hover:bg-white/[0.03] text-zinc-400"
                            }`}
                          >
                            <span className="min-w-0">
                              <span className="block text-sm font-semibold truncate">{l.name}</span>
                              <span className="block font-mono-data text-[10px] uppercase tracking-wider text-zinc-500">
                                {l.item_count} {l.item_count === 1 ? "item" : "items"}
                                {l.is_public ? " · public" : ""}
                              </span>
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </aside>

            {/* Detail panel */}
            <section className="lg:col-span-2">
              {!detail ? (
                <div className="bg-surface-container border border-outline-variant rounded-lg p-10 text-center text-zinc-500 text-sm">
                  {lists.length === 0
                    ? "Create a reading list to get started."
                    : "Select a list to view its contents."}
                </div>
              ) : (
                <div className="bg-surface-container border border-outline-variant rounded-lg">
                  <div className="p-4 border-b border-outline-variant flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      {renaming ? (
                        <div className="flex items-center gap-2">
                          <input
                            autoFocus
                            value={renameValue}
                            onChange={(e) => setRenameValue(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") handleRename();
                              if (e.key === "Escape") setRenaming(false);
                            }}
                            className="flex-1 bg-zinc-950/60 border border-outline-variant rounded-lg px-3 py-1.5 text-sm text-zinc-200 focus:outline-none focus:border-primary"
                          />
                          <button
                            onClick={handleRename}
                            disabled={busy}
                            className="px-3 py-1.5 bg-primary/10 border border-primary/30 text-primary rounded-lg font-mono-data text-[11px] uppercase tracking-wider disabled:opacity-60"
                          >
                            Save
                          </button>
                          <button
                            onClick={() => setRenaming(false)}
                            className="px-3 py-1.5 border border-outline-variant text-zinc-400 rounded-lg font-mono-data text-[11px] uppercase tracking-wider"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <>
                          <h2 className="text-lg font-bold text-on-surface truncate">{detail.name}</h2>
                          {detail.description && (
                            <p className="text-xs text-zinc-500 mt-0.5">{detail.description}</p>
                          )}
                        </>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        onClick={() => {
                          setRenaming(true);
                          setRenameValue(detail.name);
                        }}
                        className="px-3 py-1.5 border border-outline-variant text-zinc-300 hover:border-primary hover:text-primary rounded-lg font-mono-data text-[11px] uppercase tracking-wider transition-all"
                      >
                        Rename
                      </button>
                      <button
                        onClick={handleExport}
                        className="flex items-center gap-1.5 px-3 py-1.5 border border-outline-variant text-zinc-300 hover:border-primary hover:text-primary rounded-lg font-mono-data text-[11px] uppercase tracking-wider transition-all"
                      >
                        <Printer className="w-3.5 h-3.5" />
                        Export
                      </button>
                      <button
                        onClick={handleDeleteList}
                        disabled={busy}
                        className="flex items-center gap-1.5 px-3 py-1.5 border border-cyber-rose/30 text-cyber-rose hover:bg-cyber-rose/10 rounded-lg font-mono-data text-[11px] uppercase tracking-wider transition-all disabled:opacity-60"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                        Delete
                      </button>
                    </div>
                  </div>

                  {detailLoading ? (
                    <div className="flex items-center justify-center gap-2 py-16 text-primary text-sm font-mono-data animate-pulse">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Loading…
                    </div>
                  ) : detail.items.length === 0 ? (
                    <p className="p-8 text-center text-zinc-500 text-sm">
                      This list is empty. Open an event dossier and choose “Save to List”.
                    </p>
                  ) : (
                    <ul>
                      {detail.items.map((item, index) => {
                        const target = item.target;
                        if (!target) return null;
                        const isEvent = item.type === "event";
                        const href = isEvent ? `/events/${target.id}` : `/dispatches/${target.id}`;
                        return (
                          <li
                            key={item.id}
                            className="p-4 border-b border-outline-variant/60 last:border-b-0 flex items-start gap-3 group"
                          >
                            <div className="flex flex-col items-center gap-1 pt-0.5">
                              <button
                                onClick={() => handleMove(index, -1)}
                                disabled={busy || index === 0}
                                title="Move up"
                                className="text-zinc-600 hover:text-primary disabled:opacity-30 transition-colors"
                              >
                                <ChevronUp className="w-4 h-4" />
                              </button>
                              <span className="font-mono-data text-[10px] text-zinc-600">
                                {String(index + 1).padStart(2, "0")}
                              </span>
                              <button
                                onClick={() => handleMove(index, 1)}
                                disabled={busy || index === detail.items.length - 1}
                                title="Move down"
                                className="text-zinc-600 hover:text-primary disabled:opacity-30 transition-colors"
                              >
                                <ChevronDown className="w-4 h-4" />
                              </button>
                            </div>

                            <div className="min-w-0 flex-1">
                              <a
                                href={href}
                                className="block text-sm font-semibold text-on-surface hover:text-primary transition-colors leading-snug"
                              >
                                {target.title}
                              </a>
                              <div className="flex items-center gap-2 mt-1 flex-wrap">
                                <span className="inline-flex items-center gap-1 font-mono-data text-[10px] uppercase tracking-wider text-cyber-cyan">
                                  {isEvent ? <Globe className="w-3 h-3" /> : <FileText className="w-3 h-3" />}
                                  {isEvent ? target.topic || "WORLD" : "Dispatch"}
                                </span>
                                {isEvent && target.country && (
                                  <span className="font-mono-data text-[10px] uppercase tracking-wider text-zinc-500">
                                    {target.country}
                                  </span>
                                )}
                              </div>
                              {item.note && (
                                <p className="mt-1 text-xs text-zinc-500 italic">{item.note}</p>
                              )}
                            </div>

                            <button
                              onClick={() => handleRemoveItem(item.id)}
                              disabled={busy}
                              title="Remove from list"
                              className="shrink-0 text-zinc-600 hover:text-cyber-rose transition-colors disabled:opacity-40"
                            >
                              <X className="w-4 h-4" />
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              )}
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
