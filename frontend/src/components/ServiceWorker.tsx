"use client";
import { useEffect } from "react";

/** Registers /sw.js so the app can be installed on phones and desktops. Skipped in development to avoid stale pages. */
export default function ServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }, []);
  return null;
}
