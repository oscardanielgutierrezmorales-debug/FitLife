import { useEffect, useRef, useState } from "react";

function safeText(value) { return typeof value === "string" ? value : "No fue posible mostrar esta respuesta."; }
function ChatContent({ value }) { return <>{safeText(value).split(/(\*\*[^*]+\*\*)/g).map((part, index) => part.startsWith("**") && part.endsWith("**") ? <strong key={index}>{part.slice(2, -2)}</strong> : part)}</>; }

export function ChatWidget({ entries, onSend, loading }) {
  const [message, setMessage] = useState("");
  const ref = useRef(null);
  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [entries, loading]);
  const send = () => { const question = message.trim(); if (!question || loading) return; setMessage(""); void onSend(question); };
  const submit = (event) => { event.preventDefault(); send(); };
  const safeEntries = Array.isArray(entries) ? entries : [];
  return <aside className="chat"><header><strong>FitLife AI</strong><small>Chat con tu equipo FitLife</small></header><div className="messages" ref={ref}>{safeEntries.length === 0 && <p>Pregunta sobre tu plan, entrenamiento o nutrición.</p>}{safeEntries.map((entry, index) => <article key={`${entry.role}-${index}`} className={entry.role === "user" ? "user" : "assistant"}><strong>{entry.role === "user" ? "Tú" : "FitLife AI"}</strong><span><ChatContent value={entry.content} /></span></article>)}{loading && <article className="assistant"><strong>FitLife AI</strong><span>Procesando…</span></article>}</div><form className="compose" onSubmit={submit}><input value={message} disabled={loading} onChange={(e) => setMessage(e.target.value)} placeholder="Pregunta sobre tu plan…" /><button className="primary" type="submit" disabled={loading || !message.trim()}>Enviar</button></form></aside>;
}
