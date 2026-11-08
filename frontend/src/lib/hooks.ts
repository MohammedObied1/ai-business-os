"use client";
import { useCallback, useEffect, useState } from "react";
import { api, apiPage } from "./api";

export function useApi<T = any>(path: string | null, deps: unknown[] = [], opts: { platform?: boolean } = {}) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!!path);
  const reload = useCallback(() => {
    if (!path) return;
    setLoading(true);
    api<T>(path, { platform: opts.platform }).then((d) => { setData(d); setError(null); }).catch((e) => setError(e.message)).finally(() => setLoading(false));
  }, [path, opts.platform, ...deps]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { reload(); }, [reload]);
  return { data, error, loading, reload, setData };
}

/** Server-side paging: first `size` rows, then loadMore() appends the next page. `path` must not contain offset/limit. */
export function usePaged<T = any>(path: string | null, deps: unknown[] = [], size = 50, opts: { platform?: boolean } = {}) {
  const [rows, setRows] = useState<T[] | null>(null);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const sep = path?.includes("?") ? "&" : "?";
  const fetchPage = useCallback(async (offset: number) => {
    if (!path) return;
    setLoading(true);
    try {
      const r = await apiPage<T>(`${path}${sep}offset=${offset}&limit=${size}`, opts);
      setTotal(r.total);
      setRows((prev) => (offset === 0 ? r.rows : [...(prev ?? []), ...r.rows]));
    } finally { setLoading(false); }
  }, [path, size, opts.platform, ...deps]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { fetchPage(0); }, [fetchPage]);
  return { rows, total, loading, reload: () => fetchPage(0), loadMore: () => fetchPage(rows?.length ?? 0), hasMore: (rows?.length ?? 0) < total };
}
