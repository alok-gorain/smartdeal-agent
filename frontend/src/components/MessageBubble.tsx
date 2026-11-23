import { AlertCircle } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import BuyTimingCard from "@/components/BuyTimingCard";
import ComparisonTable from "@/components/ComparisonTable";
import CouponList from "@/components/CouponList";
import FakeDiscountBadge from "@/components/FakeDiscountBadge";
import PriceHistoryChart from "@/components/PriceHistoryChart";
import ProductResults from "@/components/ProductResults";
import type { Block, ChatMessage } from "@/lib/types";

function BlockView({ block }: { block: Block }) {
  switch (block.kind) {
    case "products":
      return <ProductResults data={block.data} />;
    case "comparison":
      return <ComparisonTable data={block.data} />;
    case "history":
      return <PriceHistoryChart data={block.data} />;
    case "discount":
      return <FakeDiscountBadge data={block.data} />;
    case "timing":
      return <BuyTimingCard data={block.data} />;
    case "coupons":
      return <CouponList data={block.data} />;
    default:
      return null;
  }
}

export default function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex animate-fadeIn justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tr-sm bg-blue-600 px-4 py-2.5 text-sm text-white">
          {message.content}
        </div>
      </div>
    );
  }

  if (message.role === "error") {
    return (
      <div className="flex animate-fadeIn justify-start">
        <div className="flex max-w-[85%] items-start gap-2 rounded-2xl rounded-tl-sm border border-bad/40 bg-bad/10 px-4 py-2.5 text-sm">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-bad" aria-hidden />
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex animate-fadeIn justify-start">
      <div className="w-full max-w-3xl space-y-3">
        {message.content && (
          <div className="chat-markdown prose prose-sm max-w-none rounded-2xl rounded-tl-sm border border-line bg-card px-4 py-3 text-ink prose-headings:mb-2 prose-headings:mt-1 prose-headings:text-ink prose-p:my-1.5 prose-a:text-highlight prose-strong:text-ink prose-li:my-0.5 prose-table:my-2 prose-th:text-ink prose-td:text-ink">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ href, children }) => (
                  <a href={href} target="_blank" rel="noopener noreferrer">
                    {children}
                  </a>
                ),
                table: ({ children }) => (
                  <div className="scrollbar-thin overflow-x-auto">
                    <table>{children}</table>
                  </div>
                ),
              }}
            >
              {message.content}
            </ReactMarkdown>
          </div>
        )}
        {message.blocks?.map((block, i) => <BlockView key={`${block.kind}-${i}`} block={block} />)}
      </div>
    </div>
  );
}
