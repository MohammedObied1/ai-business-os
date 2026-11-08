"use client";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { getPlatformToken, getToken } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  useEffect(() => { router.replace(getToken() ? "/command-center" : getPlatformToken() ? "/admin" : "/login"); }, [router]);
  return null;
}
