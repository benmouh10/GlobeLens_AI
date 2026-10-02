"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  Mail,
  Shield,
  Calendar,
  LogOut,
  Save,
  RefreshCw,
  ArrowLeft,
  UserCircle,
  BadgeCheck,
  Newspaper,
} from "lucide-react";
import PillNav from "../components/PillNav";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Profile {
  id: string;
  name: string;
  email: string;
  role: string;
  preferred_topics?: string[];
  preferred_countries?: string[];
  created_at?: string | null;
}

const ROLE_LABEL: Record<string, string> = {
  ADMIN: "Administrator",
  JOURNALIST: "Editor / Author",
  AUTH_USER: "Reader",
  GUEST: "Guest",
};

export default function ProfilePage() {
  const router = useRouter();

  const [token, setToken] = useState<string | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [loggingOut, setLoggingOut] = useState(false);

  // Tokens live in localStorage, which cannot be read during render on a
  // client component without breaking SSR, so the lookup happens in an effect.
  useEffect(() => {
    const saved = localStorage.getItem("admin_token");
    if (!saved) {
      router.push("/login");
      return;
    }
    setToken(saved);

    const load = async () => {
      try {
        const meRes = await fetch(`${API_BASE_URL}/api/v1/auth/me`, {
          headers: { Authorization: `Bearer ${saved}` },
        });
        if (meRes.status === 401) {
          localStorage.removeItem("admin_token");
          router.push("/login");
          return;
        }
        if (!meRes.ok) throw new Error("Could not load your profile");
        const me = await meRes.json();

        // /auth/me returns the sanitized account; /users/{id} adds preferences
        // and the join date. Merge so a failure on the second call still shows
        // the core identity rather than an empty page.
        let detail: Partial<Profile> = {};
        try {
          const detailRes = await fetch(
            `${API_BASE_URL}/api/v1/users/${me.id}`,
            { headers: { Authorization: `Bearer ${saved}` } }
          );
          if (detailRes.ok) detail = await detailRes.json();
        } catch {
          /* profile detail is optional */
        }

        const merged: Profile = { ...me, ...detail };
        setProfile(merged);
        setName(merged.name || "");
      } catch (err: any) {
        setError(err.message || "Could not load your profile");
      } finally {
        setLoading(false);
      }
    };

    load();
  }, [router]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !profile || saving) return;

    const cleaned = name.trim();
    if (!cleaned) {
      setSaveError("Name cannot be empty");
      setSaveMessage(null);
      return;
    }

    setSaving(true);
    setSaveError(null);
    setSaveMessage(null);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/users/${profile.id}`, {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ name: cleaned }),
      });

      if (res.status === 401) {
        localStorage.removeItem("admin_token");
        router.push("/login");
        return;
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Could not save your changes");
      }

      const updated = await res.json();
      setProfile((prev) => (prev ? { ...prev, name: updated.name ?? cleaned } : prev));
      setSaveMessage("Profile updated");
    } catch (err: any) {
      setSaveError(err.message || "Could not save your changes");
    } finally {
      setSaving(false);
    }
  };

  const handleLogout = async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    try {
      if (token) {
        // Best effort: even if revocation fails the local session is cleared,
        // so the browser no longer presents the token.
        await fetch(`${API_BASE_URL}/api/v1/auth/logout`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        }).catch(() => {});
      }
    } finally {
      localStorage.removeItem("admin_token");
      document.cookie = "admin_token=; path=/; expires=Thu, 01 Jan 1970 00:00:01 GMT;";
      router.push("/login");
    }
  };

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
            { label: "Profile", href: "/profile" },
            ...(profile?.role === "ADMIN" ? [{ label: "Admin", href: "/admin/dashboard" }] : []),
            { label: "Dispatches", href: "/dispatches" },
            { label: "Fact Checker", href: "/fact-checker" },
          ]}
          activeHref="/profile"
          baseColor="#080c16"
          pillColor="#0c101b"
          hoveredPillTextColor="#22d3ee"
          pillTextColor="#94a3b8"
          initialLoadAnimation={false}
        />
      </header>

      <div className="absolute inset-0 bg-[linear-gradient(to_right,rgba(69,70,77,0.06)_1px,transparent_1px),linear-gradient(to_bottom,rgba(69,70,77,0.06)_1px,transparent_1px)] bg-[size:40px_40px] pointer-events-none z-0"></div>

      <main className="flex-grow w-full max-w-3xl mx-auto px-margin-mobile md:px-margin-desktop py-stack-lg z-10 relative">
        <button
          onClick={() => router.push("/")}
          className="flex items-center gap-1.5 text-zinc-500 hover:text-primary transition-colors font-label-caps text-[10px] uppercase tracking-wider font-bold mb-6"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to Global Map
        </button>

        <div className="flex items-center gap-3 mb-8">
          <div className="w-8 h-8 rounded bg-primary/10 text-primary flex items-center justify-center">
            <UserCircle className="w-4 h-4" />
          </div>
          <div>
            <h1 className="font-display-lg text-[26px] md:text-display-lg text-on-surface leading-tight font-bold">
              Account
            </h1>
            <span className="font-label-caps text-label-caps text-on-surface-variant text-[10px] uppercase tracking-wider">
              Identity & Session
            </span>
          </div>
        </div>

        {loading && (
          <div className="flex items-center justify-center gap-2 py-24 text-primary text-sm font-mono-data animate-pulse">
            <RefreshCw className="w-4 h-4 animate-spin" /> Loading secure profile...
          </div>
        )}

        {!loading && error && (
          <div className="p-4 rounded border border-cyber-rose/30 bg-cyber-rose/10 text-cyber-rose text-sm font-mono-data">
            {error}
          </div>
        )}

        {!loading && !error && profile && (
          <div className="flex flex-col gap-stack-md">
            {/* Identity card */}
            <section className="bg-surface-container border border-outline-variant rounded-lg p-stack-md">
              <div className="flex items-center gap-4">
                <div className="w-16 h-16 rounded-full bg-zinc-900 border border-outline-variant flex items-center justify-center font-mono-data text-xl text-primary font-bold">
                  {(profile.name || "?").slice(0, 2).toUpperCase()}
                </div>
                <div className="min-w-0">
                  <h2 className="font-headline-lg text-[22px] text-on-surface font-bold truncate">
                    {profile.name}
                  </h2>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-zinc-900 text-zinc-300 border border-zinc-800 font-mono-data text-[10px] uppercase tracking-wider">
                      <BadgeCheck className="w-3 h-3 text-primary" />
                      {ROLE_LABEL[profile.role] || profile.role}
                    </span>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-6">
                <div className="bg-zinc-950/40 border border-zinc-900 rounded-xl p-3 flex items-center gap-3">
                  <Mail className="w-4 h-4 text-primary flex-shrink-0" />
                  <div className="min-w-0">
                    <span className="text-[9px] text-zinc-500 uppercase tracking-wider font-mono-data block">
                      Email
                    </span>
                    <span className="text-xs text-zinc-200 truncate block">{profile.email}</span>
                  </div>
                </div>
                <div className="bg-zinc-950/40 border border-zinc-900 rounded-xl p-3 flex items-center gap-3">
                  <Calendar className="w-4 h-4 text-primary flex-shrink-0" />
                  <div className="min-w-0">
                    <span className="text-[9px] text-zinc-500 uppercase tracking-wider font-mono-data block">
                      Member Since
                    </span>
                    <span className="text-xs text-zinc-200 truncate block">
                      {profile.created_at
                        ? new Date(profile.created_at).toLocaleDateString("en-GB", {
                            day: "2-digit",
                            month: "short",
                            year: "numeric",
                          })
                        : "—"}
                    </span>
                  </div>
                </div>
              </div>
            </section>

            {/* Editable fields */}
            <section className="bg-surface-container border border-outline-variant rounded-lg p-stack-md">
              <h3 className="font-label-caps text-label-caps text-zinc-400 uppercase tracking-widest text-[10px] mb-4 flex items-center gap-2">
                <Shield className="w-3.5 h-3.5 text-primary" />
                Editable Profile
              </h3>

              <form onSubmit={handleSave} className="space-y-4">
                <div className="space-y-1.5">
                  <label
                    className="block font-mono-data text-[10px] text-zinc-400 uppercase tracking-widest font-bold"
                    htmlFor="display-name"
                  >
                    Display Name
                  </label>
                  <input
                    id="display-name"
                    type="text"
                    value={name}
                    onChange={(e) => {
                      setName(e.target.value);
                      setSaveMessage(null);
                      setSaveError(null);
                    }}
                    className="w-full bg-zinc-950/60 border border-outline-variant rounded-xl px-4 py-2.5 text-sm text-zinc-200 focus:outline-none focus:border-primary transition-all"
                  />
                </div>

                {saveError && (
                  <div className="p-3 rounded-xl bg-cyber-rose/10 border border-cyber-rose/30 text-cyber-rose text-xs font-mono-data uppercase tracking-wider">
                    {saveError}
                  </div>
                )}
                {saveMessage && (
                  <div className="p-3 rounded-xl bg-primary/10 border border-primary/30 text-primary text-xs font-mono-data uppercase tracking-wider">
                    {saveMessage}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={saving}
                  className="flex items-center justify-center gap-2 px-5 py-2.5 bg-primary/10 hover:bg-primary/20 border border-primary/30 text-primary font-mono-data text-xs font-bold tracking-widest uppercase rounded-xl transition-all disabled:opacity-60"
                >
                  {saving ? (
                    <RefreshCw className="w-4 h-4 animate-spin" />
                  ) : (
                    <Save className="w-4 h-4" />
                  )}
                  {saving ? "Saving..." : "Save Changes"}
                </button>
              </form>
            </section>

            {/* Editorial desk — journalists and admins only */}
            {(profile.role === "ADMIN" || profile.role === "JOURNALIST") && (
              <section className="bg-surface-container border border-outline-variant rounded-lg p-stack-md">
                <h3 className="font-label-caps text-label-caps text-zinc-400 uppercase tracking-widest text-[10px] mb-4 flex items-center gap-2">
                  <Newspaper className="w-3.5 h-3.5 text-primary" />
                  Editorial Desk
                </h3>
                <p className="text-on-surface-variant text-xs leading-relaxed mb-4">
                  Write, edit and publish your own dispatches from the newsroom.
                </p>
                <button
                  onClick={() => router.push("/newsroom")}
                  className="flex items-center justify-center gap-2 px-5 py-2.5 bg-primary/10 hover:bg-primary/20 border border-primary/30 text-primary font-mono-data text-xs font-bold tracking-widest uppercase rounded-xl transition-all"
                >
                  <Newspaper className="w-4 h-4" />
                  Open Newsroom
                </button>
              </section>
            )}

            {/* Session */}
            <section className="bg-surface-container border border-outline-variant rounded-lg p-stack-md">
              <h3 className="font-label-caps text-label-caps text-zinc-400 uppercase tracking-widest text-[10px] mb-4">
                Session
              </h3>
              <button
                onClick={handleLogout}
                disabled={loggingOut}
                className="flex items-center justify-center gap-2 px-5 py-2.5 bg-cyber-rose/10 hover:bg-cyber-rose/20 border border-cyber-rose/30 text-cyber-rose font-mono-data text-xs font-bold tracking-widest uppercase rounded-xl transition-all disabled:opacity-60"
              >
                <LogOut className="w-4 h-4" />
                {loggingOut ? "Signing out..." : "Sign Out"}
              </button>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
