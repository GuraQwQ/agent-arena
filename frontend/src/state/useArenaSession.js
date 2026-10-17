import { useCallback, useEffect, useRef, useState } from "react";
import { arenaApi } from "../api/arenaClient.js";

export function useArenaSession() {
  const [access, setAccess] = useState(null);
  const [snapshot, setSnapshot] = useState(null);
  const [connected, setConnected] = useState(false);
  const [notice, setNotice] = useState(null);
  const source = useRef(null);

  const showNotice = useCallback((message, error = false) => {
    setNotice({ message, error });
    window.setTimeout(() => setNotice(current => current?.message === message ? null : current), 4200);
  }, []);

  const refreshAccess = useCallback(async () => {
    const data = await arenaApi.access();
    setAccess(data);
    return data;
  }, []);

  const closeStream = useCallback(() => {
    source.current?.close();
    source.current = null;
    setConnected(false);
  }, []);

  const connect = useCallback(() => {
    closeStream();
    const stream = new EventSource("/api/admin/stream");
    source.current = stream;
    stream.onopen = () => setConnected(true);
    stream.onmessage = event => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "SNAPSHOT") setSnapshot(payload.data);
        if (payload.type === "HOST_ACCESS") setAccess(current => ({ ...current, ...payload.data }));
        if (payload.type === "MOD_RELOAD") window.location.reload();
      } catch {
        showNotice("实时消息解析失败", true);
      }
    };
    stream.onerror = async () => {
      setConnected(false);
      try {
        const current = await refreshAccess();
        if (!current.authenticated) closeStream();
      } catch {
        // EventSource 会继续自动重连。
      }
    };
  }, [closeStream, refreshAccess, showNotice]);

  useEffect(() => {
    refreshAccess().then(current => current.authenticated && connect()).catch(error => showNotice(error.message, true));
    return closeStream;
  }, [closeStream, connect, refreshAccess, showNotice]);

  const join = useCallback(async password => {
    const data = await arenaApi.joinHost(password);
    setAccess({ ...data, authenticated: true });
    connect();
    return data;
  }, [connect]);

  return { access, snapshot, connected, notice, showNotice, refreshAccess, join };
}
