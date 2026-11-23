"use client";

import { Plus, SendHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { AskContext } from "@/components/AskContext";
import LoadingAnimation from "@/components/LoadingAnimation";
import MessageBubble from "@/components/MessageBubble";
import ThemeToggle from "@/components/ThemeToggle";
import { useChat } from "@/hooks/useChat";

const QUICK_ACTIONS = [
  { label: "🔍 Compare prices", prompt: "Compare prices for the top pick", starter: "Compare prices for " },
  { label: "📊 Price history", prompt: "Show the price history", starter: "Show price history for " },
  { label: "🧾 Fake discount?", prompt: "Is the discount real?", starter: "Is the discount real on " },
  { label: "🏷️ Find coupons", prompt: "Find coupons and bank offers", starter: "Bank offers on " },
];

const EXAMPLES = [
  "Best ANC earbuds under ₹3000",
  "iPhone 16 128GB — where is it cheapest?",
  "Samsung 55 inch 4K TV",
  "Nike running shoes",
  "HDFC card offers on Flipkart",
];

export default function ChatWindow({ sessionId, onNewChat }: { sessionId: string | null; onNewChat: () => void }) {
  const { messages, thinking, busy, connection, send } = useChat(sessionId);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, thinking]);

  const submit = (text: string) => {
    if (!text.trim() || busy) return;
    send(text);
    setInput("");
  };

  const statusColor = connection === "open" ? "bg-good" : connection === "connecting" ? "bg-warn" : "bg-bad";
  // "Live" while the chat connection is up; only says otherwise when it really isn't
  const statusText = connection === "open" ? "Live" : connection === "connecting" ? "Connecting…" : "Offline";

  return (
    <AskContext.Provider value={submit}>
      <div className="flex h-dvh flex-col bg-bg">
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-line bg-card/80 px-4 py-2.5 backdrop-blur">
          <div className="flex min-w-0 items-center gap-2.5">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/logo.svg" alt="" className="h-8 w-8" />
            <div className="min-w-0">
              <h1 className="text-sm font-bold leading-tight">
                SmartDeal <span className="text-highlight">Agent</span>
              </h1>
              <p className="flex items-center gap-1.5 truncate text-[11px] text-muted" role="status">
                <span className={`inline-block h-1.5 w-1.5 rounded-full ${statusColor}`} aria-hidden />
                {statusText}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <ThemeToggle />
            <button
              onClick={onNewChat}
              className="inline-flex items-center gap-1 rounded-lg px-2.5 py-2 text-xs font-medium text-muted hover:bg-raised hover:text-ink"
            >
              <Plus className="h-4 w-4" aria-hidden /> <span className="hidden sm:inline">New chat</span>
            </button>
          </div>
        </header>

        <main ref={scrollRef} className="scrollbar-thin flex-1 overflow-y-auto">
          <div className="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-6">
            {messages.length === 0 && !busy && (
              <div className="mt-[8vh] text-center">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src="/logo.svg" alt="" className="mx-auto h-14 w-14" />
                <h2 className="mt-4 text-2xl font-bold">Find the real best deal</h2>
                <p className="mx-auto mt-2 max-w-md text-sm text-muted">
                  I compare prices across Amazon, Flipkart, Myntra, Croma, Reliance Digital and more, check if a discount is
                  real, and tell you whether to buy now or wait for the next sale.
                </p>
                <div className="mt-6 flex flex-wrap justify-center gap-2">
                  {EXAMPLES.map((e) => (
                    <button
                      key={e}
                      onClick={() => submit(e)}
                      className="rounded-full border border-line bg-card px-3.5 py-1.5 text-sm hover:border-highlight hover:text-highlight"
                    >
                      {e}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} />
            ))}
            {busy && <LoadingAnimation steps={thinking} />}
          </div>
        </main>

        <footer className="shrink-0 border-t border-line bg-card/80 px-4 pb-4 pt-2 backdrop-blur">
          <div className="mx-auto max-w-3xl">
            <div className="scrollbar-thin mb-2 flex gap-2 overflow-x-auto pb-1">
              {QUICK_ACTIONS.map((a) => (
                <button
                  key={a.label}
                  disabled={busy}
                  onClick={() => {
                    if (messages.length) submit(a.prompt);
                    else {
                      setInput(a.starter);
                      inputRef.current?.focus();
                    }
                  }}
                  className="shrink-0 rounded-full border border-line bg-raised px-3 py-1 text-xs hover:border-highlight disabled:opacity-50"
                >
                  {a.label}
                </button>
              ))}
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                submit(input);
              }}
              className="flex items-end gap-2 rounded-2xl border border-line bg-bg px-3 py-2 focus-within:border-highlight"
            >
              <label htmlFor="chat-input" className="sr-only">
                Message
              </label>
              <textarea
                id="chat-input"
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    submit(input);
                  }
                }}
                rows={1}
                maxLength={1000}
                placeholder="Ask for a product, budget or store…"
                className="max-h-32 flex-1 resize-none bg-transparent py-1.5 text-sm outline-none placeholder:text-muted"
              />
              <button
                type="submit"
                disabled={!input.trim() || busy}
                className="rounded-xl bg-highlight p-2 text-bg transition hover:brightness-110 disabled:opacity-40"
                aria-label="Send"
              >
                <SendHorizontal className="h-4 w-4" />
              </button>
            </form>
          </div>
        </footer>
      </div>
    </AskContext.Provider>
  );
}
