"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, wsUrl } from "@/lib/api";
import { newId } from "@/lib/format";
import type { ChatMessage, ServerEvent } from "@/lib/types";
import { ChatSocket, type ConnectionState } from "@/lib/websocket";

export function useChat(sessionId: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [thinking, setThinking] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const socket = useRef<ChatSocket | null>(null);
  const busyRef = useRef(false);

  const onEvent = useCallback((event: ServerEvent) => {
    if (event.type === "thinking") {
      setThinking((steps) => (steps.includes(event.content) ? steps : [...steps, event.content]));
      return;
    }
    setThinking([]);
    busyRef.current = false;
    setBusy(false);
    setMessages((prev) => [
      ...prev,
      event.type === "response"
        ? { id: newId(), role: "assistant", content: event.content, blocks: event.blocks }
        : { id: newId(), role: "error", content: event.content },
    ]);
  }, []);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    setMessages([]);
    api
      .chatHistory(sessionId)
      .then((items) => {
        if (cancelled || !items.length) return;
        setMessages(items.map((m) => ({ id: newId(), role: m.role, content: m.content, blocks: m.blocks })));
      })
      .catch(() => {
        /* new session or API offline */
      });

    const onStateChange = (state: ConnectionState) => {
      setConnection(state);
      // A dropped connection loses the in-flight answer: tell the user instead of spinning forever
      if (state === "closed" && busyRef.current) {
        busyRef.current = false;
        setBusy(false);
        setThinking([]);
        setMessages((prev) => [
          ...prev,
          { id: newId(), role: "error", content: "Connection lost while answering. Please send that again." },
        ]);
      }
    };
    const s = new ChatSocket(wsUrl(sessionId), { onEvent, onStateChange });
    s.connect();
    socket.current = s;
    return () => {
      cancelled = true;
      s.close();
      socket.current = null;
    };
  }, [sessionId, onEvent]);

  const send = useCallback(
    (text: string) => {
      const message = text.trim();
      if (!message || busy) return;
      setMessages((prev) => [...prev, { id: newId(), role: "user", content: message }]);
      setThinking([]);
      busyRef.current = true;
      setBusy(true);
      socket.current?.send(message);
    },
    [busy],
  );

  return { messages, thinking, busy, connection, send };
}
