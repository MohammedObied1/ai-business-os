import type { Metadata, Viewport } from "next";
import "./globals.css";
import { LangProvider } from "@/lib/i18n";
import { ToastHost } from "@/components/ui";
import ServiceWorker from "@/components/ServiceWorker";

export const metadata: Metadata = {
  title: "AI Business OS",
  description: "Your business has a database. Our AI turns that data into decisions and actions.",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icons/icon-192.png", apple: "/icons/apple-touch-icon.png" },
  appleWebApp: { capable: true, title: "Business OS", statusBarStyle: "default" },
};

export const viewport: Viewport = { themeColor: "#0F766E", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ar" dir="rtl" suppressHydrationWarning>
      <body><LangProvider>{children}<ToastHost /><ServiceWorker /></LangProvider></body>
    </html>
  );
}
