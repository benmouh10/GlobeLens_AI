// Client helpers for Web Push: VAPID key fetch, subscription lifecycle and
// preference persistence. Browser APIs are guarded so the module can be
// imported on the server without throwing.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const API = `${API_BASE_URL}/api/v1`;

export interface PushPreferences {
  breaking_news: boolean;
  followed_events: boolean;
  daily_briefing: boolean;
  briefing_hour_utc: number;
  timezone: string;
}

export interface PushDelivery {
  sent: number;
  failed: number;
  pruned: number;
  skipped: number;
}

export function pushSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

// VAPID keys are URL-safe base64 without padding; PushManager wants bytes.
function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const output = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) output[i] = raw.charCodeAt(i);
  return output;
}

async function readError(res: Response, fallback: string): Promise<string> {
  const data = await res.json().catch(() => ({}));
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map((d: any) => d.msg).join(", ");
  return fallback;
}

export async function getVapidKey(): Promise<{ public_key: string; enabled: boolean }> {
  const res = await fetch(`${API}/push/vapid-public-key`);
  if (!res.ok) throw new Error("Could not load push configuration");
  return res.json();
}

export async function getPreferences(token: string): Promise<PushPreferences> {
  const res = await fetch(`${API}/push/preferences`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res, "Could not load notification settings"));
  return res.json();
}

export async function updatePreferences(
  token: string,
  patch: Partial<PushPreferences>
): Promise<PushPreferences> {
  const res = await fetch(`${API}/push/preferences`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(await readError(res, "Could not save notification settings"));
  return res.json();
}

export async function getExistingSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null;
  const reg = await navigator.serviceWorker.getRegistration();
  if (!reg) return null;
  return reg.pushManager.getSubscription();
}

export async function enablePush(token: string): Promise<void> {
  if (!pushSupported()) throw new Error("This browser does not support push notifications.");

  const { public_key, enabled } = await getVapidKey();
  if (!enabled || !public_key) {
    throw new Error("Push is not configured on the server.");
  }

  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error("Notification permission was not granted.");
  }

  await navigator.serviceWorker.register("/sw.js");
  const reg = await navigator.serviceWorker.ready;

  const existing = await reg.pushManager.getSubscription();
  const subscription =
    existing ||
    (await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(public_key) as unknown as BufferSource,
    }));

  const json = subscription.toJSON();
  const res = await fetch(`${API}/push/subscribe`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      endpoint: subscription.endpoint,
      keys: { p256dh: json.keys?.p256dh, auth: json.keys?.auth },
    }),
  });
  if (!res.ok) {
    throw new Error(await readError(res, "Could not register this device for notifications"));
  }
}

export async function disablePush(token: string): Promise<void> {
  if (!pushSupported()) return;
  const reg = await navigator.serviceWorker.getRegistration();
  const subscription = reg ? await reg.pushManager.getSubscription() : null;
  if (!subscription) return;
  try {
    await fetch(`${API}/push/unsubscribe`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint: subscription.endpoint }),
    });
  } finally {
    // Local unsubscribe is the source of truth for the browser even if the
    // server call failed; a stale row will be pruned on the next send (410).
    await subscription.unsubscribe().catch(() => {});
  }
}

export async function sendTestPush(token: string): Promise<PushDelivery> {
  const res = await fetch(`${API}/push/test`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res, "Could not send a test notification"));
  return res.json();
}
