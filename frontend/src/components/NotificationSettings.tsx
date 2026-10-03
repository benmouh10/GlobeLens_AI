"use client";

import React, { useEffect, useState } from "react";
import { Bell, BellOff, Loader2, Send, Sparkles } from "lucide-react";
import {
  disablePush,
  enablePush,
  getExistingSubscription,
  getPreferences,
  PushPreferences,
  pushSupported,
  sendTestPush,
  updatePreferences,
} from "../lib/push";

interface Props {
  token: string;
}

export default function NotificationSettings({ token }: Props) {
  const [supported, setSupported] = useState(false);
  const [hasSubscription, setHasSubscription] = useState<boolean | null>(null);
  const [prefs, setPrefs] = useState<PushPreferences | null>(null);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const ok = pushSupported();
    setSupported(ok);
    if (!ok) return;

    let cancelled = false;
    (async () => {
      try {
        const [sub, loaded] = await Promise.all([
          getExistingSubscription(),
          getPreferences(token),
        ]);
        if (cancelled) return;
        setHasSubscription(!!sub);
        setPrefs(loaded);
      } catch (err: any) {
        if (!cancelled) setError(err.message || "Could not load notification settings");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const handleToggleDevice = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      if (hasSubscription) {
        await disablePush(token);
        setHasSubscription(false);
        setMessage("Notifications disabled on this device.");
      } else {
        await enablePush(token);
        setHasSubscription(true);
        setMessage("Notifications enabled on this device.");
      }
    } catch (err: any) {
      setError(err.message || "Could not change notification permission");
    } finally {
      setBusy(false);
    }
  };

  const togglePref = async (key: "breaking_news" | "followed_events" | "daily_briefing") => {
    if (!prefs) return;
    const next = !prefs[key];
    setPrefs({ ...prefs, [key]: next });
    setError(null);
    try {
      const saved = await updatePreferences(token, { [key]: next });
      setPrefs(saved);
    } catch (err: any) {
      setPrefs((prev) => (prev ? { ...prev, [key]: !next } : prev));
      setError(err.message || "Could not save preference");
    }
  };

  const handleTest = async () => {
    if (testing) return;
    setTesting(true);
    setError(null);
    setMessage(null);
    try {
      const result = await sendTestPush(token);
      if (result.sent > 0) {
        setMessage(`Test sent to ${result.sent} device${result.sent === 1 ? "" : "s"}.`);
      } else if (result.skipped > 0) {
        setError("This category is turned off for your account.");
      } else {
        setError("No registered device received the test. Enable notifications first.");
      }
    } catch (err: any) {
      setError(err.message || "Could not send a test notification");
    } finally {
      setTesting(false);
    }
  };

  const PREF_ROWS: { key: "breaking_news" | "followed_events" | "daily_briefing"; label: string; desc: string }[] = [
    { key: "breaking_news", label: "Breaking news", desc: "Major developing stories as they are verified." },
    { key: "followed_events", label: "Followed events", desc: "Updates on dossiers you bookmark or follow." },
    { key: "daily_briefing", label: "Daily briefing", desc: "A once-a-day push with the top stories." },
  ];

  return (
    <section className="bg-surface-container border border-outline-variant rounded-lg p-stack-md">
      <h3 className="font-label-caps text-label-caps text-zinc-400 uppercase tracking-widest text-[10px] mb-4 flex items-center gap-2">
        <Bell className="w-3.5 h-3.5 text-primary" />
        Notifications
      </h3>

      {!supported ? (
        <p className="text-xs text-zinc-500 leading-relaxed">
          This browser does not support push notifications.
        </p>
      ) : (
        <>
          <div className="flex items-start justify-between gap-4 mb-4">
            <div className="min-w-0">
              <p className="text-sm text-on-surface font-semibold">This device</p>
              <p className="text-[11px] text-zinc-500 leading-relaxed mt-0.5">
                {hasSubscription
                  ? "Notifications are on for this browser."
                  : "Turn on to receive alerts on this browser."}
              </p>
            </div>
            <button
              onClick={handleToggleDevice}
              disabled={busy || hasSubscription === null}
              className={`shrink-0 flex items-center gap-2 px-4 py-2 border rounded-xl font-mono-data text-[11px] font-bold tracking-widest uppercase transition-all disabled:opacity-60 ${
                hasSubscription
                  ? "bg-cyber-rose/10 hover:bg-cyber-rose/20 border-cyber-rose/30 text-cyber-rose"
                  : "bg-primary/10 hover:bg-primary/20 border-primary/30 text-primary"
              }`}
            >
              {busy ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : hasSubscription ? (
                <BellOff className="w-3.5 h-3.5" />
              ) : (
                <Bell className="w-3.5 h-3.5" />
              )}
              {hasSubscription ? "Disable" : "Enable"}
            </button>
          </div>

          {prefs && (
            <div className="border-t border-outline-variant/60 pt-4 space-y-3">
              {PREF_ROWS.map((row) => {
                const on = prefs[row.key];
                return (
                  <button
                    key={row.key}
                    onClick={() => togglePref(row.key)}
                    className="w-full flex items-start justify-between gap-4 text-left group"
                  >
                    <span className="min-w-0">
                      <span className="block text-sm text-zinc-200">{row.label}</span>
                      <span className="block text-[11px] text-zinc-500 leading-relaxed">
                        {row.desc}
                      </span>
                    </span>
                    <span
                      className={`shrink-0 mt-0.5 w-9 h-5 rounded-full border transition-colors relative ${
                        on ? "bg-primary/30 border-primary/50" : "bg-zinc-900 border-outline-variant"
                      }`}
                    >
                      <span
                        className={`absolute top-0.5 w-3.5 h-3.5 rounded-full transition-all ${
                          on ? "left-[18px] bg-primary" : "left-0.5 bg-zinc-500"
                        }`}
                      />
                    </span>
                  </button>
                );
              })}

              <div className="flex items-center justify-between gap-4 pt-1">
                <span className="text-[11px] text-zinc-500">Briefing hour (UTC)</span>
                <select
                  value={prefs.briefing_hour_utc}
                  onChange={async (e) => {
                    const hour = Number(e.target.value);
                    setPrefs({ ...prefs, briefing_hour_utc: hour });
                    try {
                      setPrefs(await updatePreferences(token, { briefing_hour_utc: hour }));
                    } catch (err: any) {
                      setError(err.message || "Could not save briefing hour");
                    }
                  }}
                  className="bg-zinc-950/60 border border-outline-variant rounded-lg px-2 py-1 text-xs text-zinc-200 focus:outline-none focus:border-primary"
                >
                  {Array.from({ length: 24 }, (_, h) => (
                    <option key={h} value={h}>
                      {String(h).padStart(2, "0")}:00
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}

          <button
            onClick={handleTest}
            disabled={testing || !hasSubscription}
            className="mt-4 flex items-center justify-center gap-2 px-4 py-2 border border-outline-variant text-zinc-300 hover:border-primary hover:text-primary rounded-xl font-mono-data text-[11px] font-bold tracking-widest uppercase transition-all disabled:opacity-40"
          >
            {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
            Send test
          </button>

          {error && (
            <div className="mt-3 p-3 rounded-xl bg-cyber-rose/10 border border-cyber-rose/30 text-cyber-rose text-[11px] font-mono-data tracking-wide">
              {error}
            </div>
          )}
          {message && (
            <div className="mt-3 p-3 rounded-xl bg-cyber-emerald/10 border border-cyber-emerald/30 text-cyber-emerald text-[11px] font-mono-data tracking-wide flex items-center gap-2">
              <Sparkles className="w-3.5 h-3.5 shrink-0" />
              {message}
            </div>
          )}
        </>
      )}
    </section>
  );
}
