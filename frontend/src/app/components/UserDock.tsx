"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { LogOut, HardDriveDownload } from "lucide-react";
import { createPortal } from "react-dom";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * Bottom-left dock shared by every page via PrimaryNav. It hosts the Offline
 * library shortcut next to the Logout control so the top bar (and the search
 * field beside it) stays uncluttered. Admins keep their Logout in the header.
 */
export default function UserDock() {
  const router = useRouter();
  const pathname = usePathname();
  const [authed, setAuthed] = useState(false);
  const [role, setRole] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const token = localStorage.getItem("admin_token");
    if (!token) return;
    setAuthed(true);
    fetch(`${API_BASE_URL}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((me) => setRole(me?.role ?? "AUTH_USER"))
      .catch(() => setRole("AUTH_USER"));
  }, []);

  const handleLogout = async () => {
    const token = localStorage.getItem("admin_token");
    try {
      if (token) {
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

  const showOffline = pathname !== "/offline";
  const showLogout =
    authed && role !== null && role !== "ADMIN" && pathname !== "/profile";

  if (!mounted) return null;

  return createPortal(
    <div className="fixed bottom-6 left-6 z-40 flex items-center gap-3">
      {showOffline && (
        <Link
          href="/offline"
          title="Open your offline library"
          className="flex items-center gap-2 bg-cyber-cyan/10 backdrop-blur-md border border-cyber-cyan/30 hover:bg-cyber-cyan/20 text-cyber-cyan text-[11px] font-bold tracking-wider uppercase font-mono-data px-3 py-2 rounded-xl shadow-[0_4px_20px_rgba(6,182,212,0.25)] transition-all hover:scale-[1.02] active:scale-[0.98]"
        >
          <HardDriveDownload className="w-4 h-4" />
          Offline
        </Link>
      )}
      {showLogout && (
        <button
          onClick={handleLogout}
          className="flex items-center gap-2 bg-cyber-rose/10 backdrop-blur-md border border-cyber-rose/30 hover:bg-cyber-rose/20 text-cyber-rose text-[11px] font-bold tracking-wider uppercase font-mono-data px-3 py-2 rounded-xl shadow-[0_4px_20px_rgba(244,63,94,0.25)] transition-all hover:scale-[1.02] active:scale-[0.98]"
        >
          <LogOut className="w-4 h-4" />
          Logout
        </button>
      )}
    </div>,
    document.body
  );
}
