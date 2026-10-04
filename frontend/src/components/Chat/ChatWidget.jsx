import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { markdownBlocks } from "./chatMarkdown";

function InlineMarkdown({ value }) {
  return <>{value.split(/(\*\*[^*]+\*\*)/g).map((part, index) => part.startsWith("**") && part.endsWith("**") ? <strong key={index}>{part.slice(2, -2)}</strong> : part)}</>;
}

function ChatContent({ value }) {
  return <div className="message-content">{markdownBlocks(value).map((block, index) => {
    if (block.type === "heading") return <h4 key={index}><InlineMarkdown value={block.text} /></h4>;
    if (block.type === "ordered-list") return <ol key={index}>{block.items.map((item, itemIndex) => <li key={itemIndex}><InlineMarkdown value={item} /></li>)}</ol>;
    if (block.type === "unordered-list") return <ul key={index}>{block.items.map((item, itemIndex) => <li key={itemIndex}><InlineMarkdown value={item} /></li>)}</ul>;
    return <p key={index}><InlineMarkdown value={block.text} /></p>;
  })}</div>;
}

export function ChatWidget({ entries, onSend, loading }) {
  const [message, setMessage] = useState("");
  const [showLatest, setShowLatest] = useState(false);
  const messagesRef = useRef(null);
  const nearBottomRef = useRef(true);
  const previousCountRef = useRef(0);
  const safeEntries = Array.isArray(entries) ? entries : [];
  const scrollToLatest = (behavior = "smooth") => {
    const node = messagesRef.current;
    if (!node) return;
    node.scrollTo({ top: node.scrollHeight, behavior });
    nearBottomRef.current = true;
    setShowLatest(false);
  };
  useLayoutEffect(() => {
    const last = safeEntries[safeEntries.length - 1];
    const firstLoad = previousCountRef.current === 0;
    const userJustSent = last?.role === "user" && safeEntries.length > previousCountRef.current;
    if (firstLoad || userJustSent || nearBottomRef.current) scrollToLatest(firstLoad ? "auto" : "smooth");
    else if (safeEntries.length > previousCountRef.current) setShowLatest(true);
    previousCountRef.current = safeEntries.length;
  }, [safeEntries.length, loading]);
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return undefined;
    const updateViewport = () => {
      document.documentElement.style.setProperty("--visual-viewport-height", `${viewport.height}px`);
      document.documentElement.style.setProperty("--visual-viewport-bottom", `${Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop)}px`);
    };
    updateViewport();
    viewport.addEventListener("resize", updateViewport);
    viewport.addEventListener("scroll", updateViewport);
    return () => {
      viewport.removeEventListener("resize", updateViewport);
      viewport.removeEventListener("scroll", updateViewport);
    };
  }, []);
  const handleScroll = () => {
    const node = messagesRef.current;
    if (!node) return;
    const nearBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 72;
    nearBottomRef.current = nearBottom;
    setShowLatest(!nearBottom);
  };
  const send = () => {
    const question = message.trim();
    if (!question || loading) return;
    nearBottomRef.current = true;
    setShowLatest(false);
    setMessage("");
    void onSend(question);
  };
  const submit = (event) => { event.preventDefault(); send(); };
  return <aside className="chat"><header><strong>FitLife AI</strong><small>Chat con tu equipo FitLife</small></header><div className="messages" ref={messagesRef} onScroll={handleScroll} aria-live="polite">{safeEntries.length === 0 && <p>Pregunta sobre tu plan, entrenamiento o nutrición.</p>}{safeEntries.map((entry) => <article key={entry.id} className={entry.role === "user" ? "user" : "assistant"}><strong>{entry.role === "user" ? "Tú" : "FitLife AI"}</strong><ChatContent value={entry.content} /></article>)}{loading && <article className="assistant pending"><strong>FitLife AI</strong><span>Estoy preparando la respuesta…</span></article>}</div>{showLatest && <button className="latest" type="button" onClick={() => scrollToLatest()}>↓ Mensaje más reciente</button>}<form className="compose" onSubmit={submit}><input value={message} disabled={loading} onChange={(e) => setMessage(e.target.value)} placeholder="Pregunta sobre tu plan…" aria-label="Mensaje para FitLife AI" /><button className="primary" type="submit" disabled={loading || !message.trim()}>Enviar</button></form></aside>;
}
