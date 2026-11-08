"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";

/** Unread count (checked every minute). New unread items also pop up as a browser notification when allowed. */
export function NotificationBell({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useT();
  const [count, setCount] = useState(0);
  const lastId = useRef<number | null>(null);

  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const r = await api<{ count: number; latest: any }>("/api/notifications/unread-count");
        if (!alive) return;
        setCount(r.count);
        const latest = r.latest;
        if (latest && lastId.current !== null && latest.id > lastId.current && typeof Notification !== "undefined" && Notification.permission === "granted"
            && document.visibilityState !== "visible") {
          new Notification(latest.title, { body: latest.message ?? "", icon: "/icons/icon-192.png", tag: `bizos-${latest.id}` });
        }
        if (latest) lastId.current = Math.max(lastId.current ?? 0, latest.id);
        else if (lastId.current === null) lastId.current = 0;
      } catch { /* offline: try again next time */ }
    };
    check();
    const h = setInterval(check, 60000);
    return () => { alive = false; clearInterval(h); };
  }, []);

  return (
    <Link href="/notifications" onClick={onNavigate} className="relative rounded-lg p-2 text-slate hover:bg-paper hover:text-ink" aria-label={t("Notifications")} title={t("Notifications")}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 01-3.4 0" /></svg>
      {count > 0 && <span className="absolute -end-0.5 -top-0.5 min-w-[1.1rem] rounded-full bg-rust px-1 text-center text-[10px] font-bold leading-[1.1rem] text-white">{count > 99 ? "99+" : count}</span>}
    </Link>
  );
}
