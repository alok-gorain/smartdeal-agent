"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";

import ChatWindow from "@/components/ChatWindow";
import { newId } from "@/lib/format";

function ChatPageInner() {
  const params = useSearchParams();
  const router = useRouter();
  const session = params.get("session");

  // Each conversation lives at /chat?session=<id>, so a reload or shared link restores it
  useEffect(() => {
    if (!session) router.replace(`/chat?session=${newId().replace(/-/g, "").slice(0, 20)}`);
  }, [session, router]);

  return (
    <ChatWindow
      sessionId={session}
      onNewChat={() => router.push(`/chat?session=${newId().replace(/-/g, "").slice(0, 20)}`)}
    />
  );
}

export default function ChatPage() {
  return (
    <Suspense fallback={<div className="h-dvh bg-bg" />}>
      <ChatPageInner />
    </Suspense>
  );
}
