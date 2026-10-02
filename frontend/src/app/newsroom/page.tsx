"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  Calendar,
  ExternalLink,
  FileText,
  Lock,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Send,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import PillNav from "../components/PillNav";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const API = `${API_BASE_URL}/api/v1`;

interface Article {
  id: string;
  title: string;
  content: string;
  url: string | null;
  published_at: string | null;
  created_at: string | null;
  origin: string;
  publication_status: string;
  author: { id: string; name: string } | null;
}

interface Me {
  id: string;
  name: string;
  role: string;
}

const EDITOR_ROLES = ["ADMIN", "JOURNALIST"];

export default function NewsroomPage() {
  const router = useRouter();

  const [token, setToken] = useState<string | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [articles, setArticles] = useState<Article[]>([]);
  const [listLoading, setListLoading] = useState(false);

  // Editor state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [url, setUrl] = useState("");
  const [saving, setSaving] = useState<"draft" | "publish" | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const clearSession = useCallback(() => {
    localStorage.removeItem("admin_token");
    document.cookie = "admin_token=; path=/; expires=Thu, 01 Jan 1970 00:00:01 GMT;";
    router.push("/login");
  }, [router]);

  const authFetch = useCallback(
    async (path: string, init?: RequestInit) => {
      if (!token) throw new Error("No active session");
      const res = await fetch(`${API}${path}`, {
        ...init,
        headers: {
          Authorization: `Bearer ${token}`,
          ...(init?.body ? { "Content-Type": "application/json" } : {}),
          ...(init?.headers || {}),
        },
      });
      if (res.status === 401) {
        clearSession();
        throw new Error("Your session expired");
      }
      return res;
    },
    [token, clearSession]
  );

  const loadMine = useCallback(async () => {
    setListLoading(true);
    try {
      const res = await authFetch("/articles/mine");
      if (!res.ok) throw new Error(`Could not load your articles (${res.status})`);
      const data = await res.json();
      setArticles(data.articles || []);
    } catch (err: any) {
      setNotice({ kind: "err", text: err.message || "Could not load your articles" });
    } finally {
      setListLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    const saved = localStorage.getItem("admin_token");
    if (!saved) {
      router.push("/login");
      return;
    }
    setToken(saved);

    const boot = async () => {
      try {
        const res = await fetch(`${API}/auth/me`, {
          headers: { Authorization: `Bearer ${saved}` },
        });
        if (res.status === 401) {
          clearSession();
          return;
        }
        if (!res.ok) throw new Error("Could not verify your clearance");
        const profile: Me = await res.json();
        setMe(profile);
      } catch (err: any) {
        setError(err.message || "Could not verify your clearance");
      } finally {
        setLoading(false);
      }
    };

    boot();
  }, [router, clearSession]);

  useEffect(() => {
    if (token && me && EDITOR_ROLES.includes(me.role)) {
      loadMine();
    }
  }, [token, me, loadMine]);

  const resetEditor = () => {
    setEditingId(null);
    setTitle("");
    setContent("");
    setUrl("");
  };

  const startEdit = (article: Article) => {
    setNotice(null);
    setEditingId(article.id);
    setTitle(article.title);
    setContent(article.content);
    setUrl(article.url || "");
    if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleSave = async (publish: boolean) => {
    if (saving) return;
    const cleanTitle = title.trim();
    const cleanContent = content.trim();
    if (!cleanTitle || !cleanContent) {
      setNotice({ kind: "err", text: "Title and body are both required" });
      return;
    }

    setSaving(publish ? "publish" : "draft");
    setNotice(null);
    try {
      let id = editingId;
      const payload = JSON.stringify({ title: cleanTitle, content: cleanContent, url: url.trim() });

      if (id) {
        const res = await authFetch(`/articles/${id}`, { method: "PUT", body: payload });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || "Could not save the article");
        }
      } else {
        const res = await authFetch("/articles", { method: "POST", body: payload });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || "Could not create the article");
        }
        const created: Article = await res.json();
        id = created.id;
      }

      if (publish && id) {
        const res = await authFetch(`/articles/${id}/publish`, { method: "POST" });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || "Could not publish the article");
        }
      }

      setNotice({ kind: "ok", text: publish ? "Article published" : "Draft saved" });
      resetEditor();
      await loadMine();
    } catch (err: any) {
      setNotice({ kind: "err", text: err.message || "Could not save the article" });
    } finally {
      setSaving(null);
    }
  };

  const togglePublication = async (article: Article) => {
    setBusyId(article.id);
    setNotice(null);
    const publish = article.publication_status !== "PUBLISHED";
    try {
      const res = await authFetch(
        `/articles/${article.id}/${publish ? "publish" : "unpublish"}`,
        { method: "POST" }
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Could not update publication status");
      }
      setNotice({ kind: "ok", text: publish ? "Article published" : "Article unpublished" });
      await loadMine();
    } catch (err: any) {
      setNotice({ kind: "err", text: err.message || "Could not update publication status" });
    } finally {
      setBusyId(null);
    }
  };

  const removeArticle = async (article: Article) => {
    if (typeof window !== "undefined" && !window.confirm(`Delete "${article.title}" permanently?`)) {
      return;
    }
    setBusyId(article.id);
    setNotice(null);
    try {
      const res = await authFetch(`/articles/${article.id}`, { method: "DELETE" });
      if (!res.ok && res.status !== 204) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Could not delete the article");
      }
      if (editingId === article.id) resetEditor();
      setNotice({ kind: "ok", text: "Article deleted" });
      await loadMine();
    } catch (err: any) {
      setNotice({ kind: "err", text: err.message || "Could not delete the article" });
    } finally {
      setBusyId(null);
    }
  };

  const isEditor = !!me && EDITOR_ROLES.includes(me.role);
  const editingArticle = articles.find((a) => a.id === editingId) || null;

  return (
    <div className="bg-background text-on-background min-h-screen flex flex-col font-body-md relative overflow-x-hidden">
      {/* TopNavBar — PillNav (same header as the rest of the app) */}
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
            { label: "Profile", href: "/profile" },
            ...(me?.role === "ADMIN" ? [{ label: "Admin", href: "/admin/dashboard" }] : []),
            { label: "Fact Checker", href: "/fact-checker" },
          ]}
          activeHref="/newsroom"
          baseColor="#080c16"
          pillColor="#0c101b"
          hoveredPillTextColor="#22d3ee"
          pillTextColor="#94a3b8"
          initialLoadAnimation={false}
        />
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
            <FileText className="w-4 h-4" />
          </div>
          <div>
            <h1 className="font-display-lg text-[26px] md:text-display-lg text-on-surface leading-tight font-bold">
              Newsroom
            </h1>
            <span className="font-label-caps text-label-caps text-on-surface-variant text-[10px] uppercase tracking-wider">
              Authoring Desk
            </span>
          </div>
        </div>

        {loading && (
          <div className="flex items-center justify-center gap-2 py-24 text-primary text-sm font-mono-data animate-pulse">
            <RefreshCw className="w-4 h-4 animate-spin" /> Verifying clearance...
          </div>
        )}

        {!loading && error && (
          <div className="p-4 rounded border border-cyber-rose/30 bg-cyber-rose/10 text-cyber-rose text-sm font-mono-data">
            {error}
          </div>
        )}

        {!loading && !error && !isEditor && (
          <div className="max-w-lg mx-auto text-center bg-surface-container border border-outline-variant rounded-lg p-8 mt-8">
            <div className="w-12 h-12 mx-auto rounded-full bg-zinc-900 border border-outline-variant flex items-center justify-center mb-4">
              <Lock className="w-5 h-5 text-cyber-amber" />
            </div>
            <h2 className="font-headline-lg text-[20px] text-on-surface font-bold">Clearance Required</h2>
            <p className="text-on-surface-variant text-sm mt-2 leading-relaxed">
              The newsroom is available to editors and administrators only. Your account can read
              published dispatches, but cannot author new ones.
            </p>
            <button
              onClick={() => router.push("/dispatches")}
              className="mt-6 inline-flex items-center gap-2 px-5 py-2.5 bg-primary/10 hover:bg-primary/20 border border-primary/30 text-primary font-mono-data text-xs font-bold tracking-widest uppercase rounded-xl transition-all"
            >
              Browse Dispatches
            </button>
          </div>
        )}

        {!loading && !error && isEditor && (
          <div className="grid grid-cols-1 lg:grid-cols-[380px_1fr] gap-stack-md">
            {/* Left: my articles */}
            <section className="bg-surface-container border border-outline-variant rounded-lg p-stack-md flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <h3 className="font-label-caps text-label-caps text-zinc-400 uppercase tracking-widest text-[10px] flex items-center gap-2">
                  <ShieldAlert className="w-3.5 h-3.5 text-primary" />
                  My Articles
                </h3>
                <button
                  onClick={resetEditor}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-primary/10 hover:bg-primary/20 border border-primary/30 text-primary font-mono-data text-[10px] font-bold tracking-widest uppercase rounded-lg transition-all"
                >
                  <Plus className="w-3.5 h-3.5" />
                  New
                </button>
              </div>

              {listLoading && (
                <div className="flex items-center gap-2 text-zinc-500 text-xs font-mono-data py-6 justify-center">
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Loading...
                </div>
              )}

              {!listLoading && articles.length === 0 && (
                <p className="text-zinc-500 text-xs font-mono-data py-6 text-center">
                  No articles yet. Start your first dispatch.
                </p>
              )}

              {!listLoading && articles.length > 0 && (
                <ul className="flex flex-col gap-2 max-h-[60vh] overflow-y-auto pr-1">
                  {articles.map((a) => {
                    const published = a.publication_status === "PUBLISHED";
                    const busy = busyId === a.id;
                    return (
                      <li
                        key={a.id}
                        className={`border rounded-xl p-3 transition-all ${
                          editingId === a.id
                            ? "border-primary/40 bg-primary/5"
                            : "border-zinc-900 bg-zinc-950/40 hover:border-zinc-800"
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <button
                            onClick={() => startEdit(a)}
                            className="text-left min-w-0 flex-grow"
                          >
                            <p className="text-sm text-zinc-100 font-semibold truncate">{a.title}</p>
                            <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                              <span
                                className={`inline-flex items-center px-2 py-0.5 rounded-full font-mono-data text-[9px] uppercase tracking-wider border ${
                                  published
                                    ? "bg-cyber-emerald/10 text-cyber-emerald border-cyber-emerald/30"
                                    : "bg-cyber-amber/10 text-cyber-amber border-cyber-amber/30"
                                }`}
                              >
                                {published ? "Published" : "Draft"}
                              </span>
                              {a.created_at && (
                                <span className="inline-flex items-center gap-1 text-[9px] text-zinc-500 font-mono-data">
                                  <Calendar className="w-3 h-3" />
                                  {new Date(a.created_at).toLocaleDateString("en-GB", {
                                    day: "2-digit",
                                    month: "short",
                                    year: "numeric",
                                  })}
                                </span>
                              )}
                            </div>
                          </button>
                          {busy && <RefreshCw className="w-4 h-4 text-primary animate-spin flex-shrink-0" />}
                        </div>

                        <div className="flex items-center gap-1.5 mt-3">
                          <button
                            onClick={() => startEdit(a)}
                            disabled={busy}
                            className="flex items-center gap-1 px-2 py-1 rounded-lg text-zinc-400 hover:text-primary hover:bg-primary/10 font-mono-data text-[9px] uppercase tracking-wider transition-all disabled:opacity-50"
                          >
                            <Pencil className="w-3 h-3" /> Edit
                          </button>
                          <button
                            onClick={() => togglePublication(a)}
                            disabled={busy}
                            className={`flex items-center gap-1 px-2 py-1 rounded-lg font-mono-data text-[9px] uppercase tracking-wider transition-all disabled:opacity-50 ${
                              published
                                ? "text-cyber-amber hover:bg-cyber-amber/10"
                                : "text-cyber-emerald hover:bg-cyber-emerald/10"
                            }`}
                          >
                            {published ? (
                              <>
                                <Lock className="w-3 h-3" /> Unpublish
                              </>
                            ) : (
                              <>
                                <Send className="w-3 h-3" /> Publish
                              </>
                            )}
                          </button>
                          <button
                            onClick={() => removeArticle(a)}
                            disabled={busy}
                            className="flex items-center gap-1 px-2 py-1 rounded-lg text-zinc-500 hover:text-cyber-rose hover:bg-cyber-rose/10 font-mono-data text-[9px] uppercase tracking-wider transition-all disabled:opacity-50 ml-auto"
                          >
                            <Trash2 className="w-3 h-3" /> Delete
                          </button>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>

            {/* Right: editor */}
            <section className="bg-surface-container border border-outline-variant rounded-lg p-stack-md">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-label-caps text-label-caps text-zinc-400 uppercase tracking-widest text-[10px] flex items-center gap-2">
                  <Pencil className="w-3.5 h-3.5 text-primary" />
                  {editingId ? "Edit Article" : "New Article"}
                </h3>
                {editingId && (
                  <span
                    className={`inline-flex items-center px-2 py-0.5 rounded-full font-mono-data text-[9px] uppercase tracking-wider border ${
                      editingArticle?.publication_status === "PUBLISHED"
                        ? "bg-cyber-emerald/10 text-cyber-emerald border-cyber-emerald/30"
                        : "bg-cyber-amber/10 text-cyber-amber border-cyber-amber/30"
                    }`}
                  >
                    {editingArticle?.publication_status === "PUBLISHED" ? "Published" : "Draft"}
                  </span>
                )}
              </div>

              <div className="space-y-4">
                <div className="space-y-1.5">
                  <label
                    className="block font-mono-data text-[10px] text-zinc-400 uppercase tracking-widest font-bold"
                    htmlFor="article-title"
                  >
                    Headline
                  </label>
                  <input
                    id="article-title"
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="A concise, factual headline"
                    className="w-full bg-zinc-950/60 border border-outline-variant rounded-xl px-4 py-2.5 text-sm text-zinc-200 focus:outline-none focus:border-primary transition-all placeholder:text-zinc-700"
                  />
                </div>

                <div className="space-y-1.5">
                  <label
                    className="block font-mono-data text-[10px] text-zinc-400 uppercase tracking-widest font-bold"
                    htmlFor="article-body"
                  >
                    Dispatch Body
                  </label>
                  <textarea
                    id="article-body"
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    rows={16}
                    placeholder="Write the full story..."
                    className="w-full bg-zinc-950/60 border border-outline-variant rounded-xl px-4 py-3 text-sm text-zinc-200 focus:outline-none focus:border-primary transition-all placeholder:text-zinc-700 resize-y leading-relaxed"
                  />
                </div>

                <div className="space-y-1.5">
                  <label
                    className="block font-mono-data text-[10px] text-zinc-400 uppercase tracking-widest font-bold"
                    htmlFor="article-url"
                  >
                    Source URL <span className="text-zinc-600">(optional)</span>
                  </label>
                  <div className="relative">
                    <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-zinc-500">
                      <ExternalLink className="w-4 h-4" />
                    </span>
                    <input
                      id="article-url"
                      type="url"
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                      placeholder="https://..."
                      className="w-full bg-zinc-950/60 border border-outline-variant rounded-xl pl-10 pr-4 py-2.5 text-sm text-zinc-200 focus:outline-none focus:border-primary transition-all placeholder:text-zinc-700"
                    />
                  </div>
                </div>

                {notice && (
                  <div
                    className={`p-3 rounded-xl border text-xs font-mono-data uppercase tracking-wider ${
                      notice.kind === "ok"
                        ? "bg-primary/10 border-primary/30 text-primary"
                        : "bg-cyber-rose/10 border-cyber-rose/30 text-cyber-rose"
                    }`}
                  >
                    {notice.text}
                  </div>
                )}

                <div className="flex flex-wrap items-center gap-3 pt-1">
                  <button
                    onClick={() => handleSave(false)}
                    disabled={!!saving}
                    className="flex items-center justify-center gap-2 px-5 py-2.5 bg-primary/10 hover:bg-primary/20 border border-primary/30 text-primary font-mono-data text-xs font-bold tracking-widest uppercase rounded-xl transition-all disabled:opacity-60"
                  >
                    {saving === "draft" ? (
                      <RefreshCw className="w-4 h-4 animate-spin" />
                    ) : (
                      <Save className="w-4 h-4" />
                    )}
                    {editingId ? "Save Changes" : "Save Draft"}
                  </button>

                  {editingArticle?.publication_status !== "PUBLISHED" ? (
                    <button
                      onClick={() => handleSave(true)}
                      disabled={!!saving}
                      className="flex items-center justify-center gap-2 px-5 py-2.5 bg-cyber-emerald/10 hover:bg-cyber-emerald/20 border border-cyber-emerald/30 text-cyber-emerald font-mono-data text-xs font-bold tracking-widest uppercase rounded-xl transition-all disabled:opacity-60"
                    >
                      {saving === "publish" ? (
                        <RefreshCw className="w-4 h-4 animate-spin" />
                      ) : (
                        <Send className="w-4 h-4" />
                      )}
                      Publish
                    </button>
                  ) : (
                    <button
                      onClick={() => editingArticle && togglePublication(editingArticle)}
                      disabled={!!saving || !!busyId}
                      className="flex items-center justify-center gap-2 px-5 py-2.5 bg-cyber-amber/10 hover:bg-cyber-amber/20 border border-cyber-amber/30 text-cyber-amber font-mono-data text-xs font-bold tracking-widest uppercase rounded-xl transition-all disabled:opacity-60"
                    >
                      <Lock className="w-4 h-4" />
                      Unpublish
                    </button>
                  )}

                  {editingId && (
                    <button
                      onClick={resetEditor}
                      className="px-4 py-2.5 text-zinc-400 hover:text-zinc-200 font-mono-data text-xs uppercase tracking-wider transition-all"
                    >
                      Discard
                    </button>
                  )}
                </div>
              </div>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
