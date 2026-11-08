"use client";
import { createContext, useContext } from "react";

export type Session = { user: any; company: any; reloadCompany: () => void; can: (perm: string) => boolean };
export const SessionContext = createContext<Session | null>(null);
export const useSession = () => useContext(SessionContext)!;
