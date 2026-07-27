import { pageMetadata } from "@/lib/seo";
import ChatClient from "./ChatClient";

export const metadata = pageMetadata({
  title: "Ask Pal",
  description:
    "Ask Pal anything about your FPL team — an AI assistant grounded in a statistical engine that quotes real projections and never invents a number.",
  path: "/chat",
});

export default function ChatPage() {
  return <ChatClient />;
}
