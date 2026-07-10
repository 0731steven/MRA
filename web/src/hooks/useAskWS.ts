import { useCallback, useEffect, useRef, useState } from "react";

export type WsMsg =
  | { type: "clarify"; question_id: number; message: string }
  | { type: "keywords"; question_id: number; sub_questions: SubQuestion[]; keywords: string[]; tier: string }
  | { type: "mra_params"; question_id: number; report_type: ReportType; research_params: Record<string, unknown>; sub_questions: SubQuestion[]; keywords: string[]; tier: string }
  | { type: "progress"; question_id: number; task_id: number; step: string; message: string }
  | { type: "done"; question_id: number; task_id: number; report_id: number | null }
  | { type: "invalid"; message: string }
  | { type: "error"; question_id?: number; message: string };

export interface SubQuestion {
  id: string;
  text: string;
  coverage?: string;
}

export type ReportType = "market" | "product" | "competitive" | "technology";

type SendMsg =
  | { type: "ask"; text: string; tier?: string }
  | { type: "clarify_reply"; question_id: number; text: string }
  | { type: "confirm_keywords"; question_id: number; keywords: string[]; tier: string; sub_questions?: SubQuestion[]; report_type?: ReportType; research_params?: Record<string, unknown> }
  | { type: "revise_keywords"; question_id: number; keywords: string[]; tier: string; sub_questions?: SubQuestion[]; report_type?: ReportType; research_params?: Record<string, unknown> }
  | { type: "cancel"; question_id: number };

interface UseAskWS {
  connected: boolean;
  send: (msg: SendMsg) => void;
  lastMessage: WsMsg | null;
  messages: WsMsg[];
}

export function useAskWS(token: string | null): UseAskWS {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WsMsg | null>(null);
  const [messages, setMessages] = useState<WsMsg[]>([]);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!token) return;

    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const host = window.location.host;
    const url = `${proto}://${host}/api/ws/ask?token=${encodeURIComponent(token)}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (mountedRef.current) setConnected(true);
    };

    ws.onmessage = (ev) => {
      try {
        const msg: WsMsg = JSON.parse(ev.data);
        if (mountedRef.current) {
          setLastMessage(msg);
          setMessages((prev) => [...prev, msg]);
        }
      } catch {
        // ignore malformed
      }
    };

    ws.onclose = () => {
      if (mountedRef.current) setConnected(false);
    };

    ws.onerror = () => {
      if (mountedRef.current) setConnected(false);
    };

    return () => {
      ws.close();
    };
  }, [token]);

  const send = useCallback((msg: SendMsg) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  return { connected, send, lastMessage, messages };
}
