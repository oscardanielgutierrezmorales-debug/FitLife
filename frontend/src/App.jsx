import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { LoginForm } from "./components/Auth/LoginForm";
import { UserProfileForm } from "./components/Profile/UserProfileForm";
import { CalendarView } from "./components/Plan/CalendarView";
import { DayPlan } from "./components/Plan/DayPlan";
import { ChatWidget } from "./components/Chat/ChatWidget";
import { ChatErrorBoundary } from "./components/Chat/ChatErrorBoundary";
import { chatVisualReducer, initialChatVisualState } from "./components/Chat/chatVisualState";
import { useAuth } from "./context/AuthContext";
import { login, signUp } from "./services/authService";
import { generatePlan, getPlan, getProfile, saveProfile, saveProgress } from "./services/planService";
import { getChatContext, getChatHistory, sendChat } from "./services/chatService";
import { validateProfile } from "./validation/profileRules";
import { toProfilePayload } from "./services/profileContract";
import { chatEntry, chatRequestPayload, parseChatResponse } from "./services/chatContract";

const blankProfile = { language: "es", sex: "", age: null, height_cm: null, weight_kg: null, workout_hours_per_week: null, goal: "general_fitness", dietary_restrictions: [], available_days: [] };

function Dashboard() {
  const { auth, logout: clearAuth } = useAuth();
  const [tab, setTab] = useState("profile");
  const [profile, setProfile] = useState(blankProfile);
  const [plan, setPlan] = useState(null);
  const [selectedDate, setSelectedDate] = useState(null);
  const [week, setWeek] = useState(1);
  const [entries, setEntries] = useState([]);
  const [chatContext, setChatContext] = useState(null);
  const [sessionId, setSessionId] = useState(() => sessionStorage.getItem("fitlife.chatSession.v1"));
  const [busy, setBusy] = useState(false);
  const [chatLoading, setChatLoading] = useState(false);
  const chatRequestRef = useRef(false);
  const requestAbortRef = useRef(null);
  const mountedRef = useRef(true);
  const [chatVisual, dispatchChatVisual] = useReducer(chatVisualReducer, sessionStorage.getItem("fitlife.chatMinimized.v1"), initialChatVisualState);
  const [message, setMessage] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const token = auth.access_token;
  const load = async () => {
    try { setProfile(toProfilePayload(await getProfile(token))); } catch (error) { setMessage(error.message); return; }
    try { const next = await getPlan(token); setPlan(next); setSelectedDate(next.days[0]?.date || null); } catch (error) { if (!String(error.message).includes("Aún no tienes")) setMessage(error.message); }
    try { setChatContext(await getChatContext(token)); } catch { setChatContext(null); }
  };
  useEffect(() => { load(); }, []);
  useEffect(() => () => { mountedRef.current = false; requestAbortRef.current?.abort(); }, []);
  useEffect(() => { if (!sessionId) return; getChatHistory(token, sessionId).then((result) => setEntries(Array.isArray(result.messages) ? result.messages.map((item) => chatEntry(item.role, item.content, item.id)) : [])).catch(() => { sessionStorage.removeItem("fitlife.chatSession.v1"); setSessionId(null); }); }, [sessionId, token]);
  const selected = useMemo(() => plan?.days.find((day) => day.date === selectedDate) || plan?.days[0], [plan, selectedDate]);
  const weekDays = useMemo(() => plan?.days.filter((day) => day.week === week) || [], [plan, week]);
  const setSafeProfile = (next) => { setFieldErrors({}); setProfile(toProfilePayload(next)); };
  const validateBeforeSubmit = () => { const errors = validateProfile(profile); setFieldErrors(errors); if (Object.keys(errors).length) { setMessage("Revisa los campos marcados antes de continuar."); return false; } return true; };
  async function save() { if (!validateBeforeSubmit()) return false; setBusy(true); setMessage(""); try { setSafeProfile(await saveProfile(token, toProfilePayload(profile))); setMessage("Perfil guardado. Si cambió, genera un plan nuevo cuando quieras aplicarlo."); return true; } catch (error) { setFieldErrors(error.fieldErrors || {}); setMessage(error.message); return false; } finally { setBusy(false); } }
  async function buildPlan() { if (!validateBeforeSubmit()) return; setBusy(true); setMessage(""); try { setSafeProfile(await saveProfile(token, toProfilePayload(profile))); const next = await generatePlan(token); setPlan(next); setSelectedDate(next.days[0]?.date || null); setWeek(1); setTab("plan"); } catch (error) { setFieldErrors(error.fieldErrors || {}); setMessage(error.message); } finally { setBusy(false); } }
  async function toggleDay() { if (!selected) return; try { const next = await saveProgress(token, { date: selected.date, completed: !plan.completed_days.includes(selected.date) }); setPlan({ ...plan, completed_days: next.completed_days }); } catch (error) { setMessage(error.message); } }
  async function chat(question) {
    if (chatRequestRef.current) return;
    chatRequestRef.current = true;
    const controller = new AbortController();
    requestAbortRef.current = controller;
    const requestPlanDate = selectedDate;
    setChatLoading(true);
    setEntries((items) => [...items, chatEntry("user", question)]);
    try {
      const next = parseChatResponse(await sendChat(token, chatRequestPayload(question, sessionId, requestPlanDate), controller.signal));
      if (next.sessionId) {
        setSessionId(next.sessionId);
        sessionStorage.setItem("fitlife.chatSession.v1", next.sessionId);
      }
      setEntries((items) => [...items, chatEntry("assistant", next.message)]);
      dispatchChatVisual({ type: "response_received" });
    } catch (error) {
      if (mountedRef.current && error?.message !== "La solicitud fue cancelada.") {
        setEntries((items) => [...items, chatEntry("assistant", error instanceof Error ? error.message : "No pude completar la respuesta. Intenta nuevamente.")]);
        dispatchChatVisual({ type: "response_received" });
      }
    } finally {
      chatRequestRef.current = false;
      requestAbortRef.current = null;
      if (mountedRef.current) setChatLoading(false);
    }
  }
  const setChatVisualState = (minimized) => {
    dispatchChatVisual({ type: minimized ? "minimize" : "restore" });
    sessionStorage.setItem("fitlife.chatMinimized.v1", String(minimized));
  };
  const logout = () => { requestAbortRef.current?.abort(); sessionStorage.removeItem("fitlife.chatSession.v1"); setSessionId(null); setEntries([]); setChatContext(null); clearAuth(); };
  return <main className="shell"><section className="card wide"><header className="top"><div><p className="eyebrow">FITLIFE AI · PERFIL SEGURO</p><h1>{tab === "profile" ? "Mi perfil" : "Mi plan"}</h1></div><button className="link" onClick={logout}>Cerrar sesión</button></header><nav><button className={tab === "profile" ? "active" : ""} onClick={() => setTab("profile")}>Mi perfil</button><button className={tab === "plan" ? "active" : ""} onClick={() => setTab("plan")}>Mi plan</button></nav>{tab === "profile" ? <UserProfileForm profile={profile} setProfile={setSafeProfile} onSave={save} onGenerate={buildPlan} busy={busy} message={message} serverErrors={fieldErrors} /> : <>{message && <p className="error">{message}</p>}{!plan ? <section className="empty"><h2>Aún no tienes un plan</h2><p>Completa tu perfil y genera un plan personalizado de 28 días.</p><button className="primary" onClick={() => setTab("profile")}>Ir a mi perfil</button></section> : <><div className="plan-intro"><div><h2>Tu calendario está listo</h2><p>28 días con progresión, variedad y días de recuperación según tu disponibilidad.</p></div><strong>{plan.completed_days.length}/28 completado</strong></div><div className="week-nav"><button className="secondary" disabled={week === 1} onClick={() => setWeek(week - 1)}>←</button><strong>Semana {week}</strong><button className="secondary" disabled={week === 4} onClick={() => setWeek(week + 1)}>→</button></div><CalendarView days={weekDays} selectedDate={selectedDate} onSelect={setSelectedDate} completed={plan.completed_days} />{selected && <DayPlan day={selected} complete={plan.completed_days.includes(selected.date)} onToggle={toggleDay} />}</>}</>} {plan && <ChatErrorBoundary><ChatWidget entries={entries} onSend={chat} loading={chatLoading} minimized={chatVisual.minimized} unread={chatVisual.unread} onMinimize={() => setChatVisualState(true)} onRestore={() => setChatVisualState(false)} /></ChatErrorBoundary>}</section></main>;
}

export default function App() { const { auth, setAuth } = useAuth(); const [mode, setMode] = useState("signup"); const [values, setValues] = useState({ username: "", password: "" }); const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const submit = async () => { setBusy(true); setError(""); try { setAuth(await (mode === "signup" ? signUp(values) : login(values))); } catch (err) { setError(err.message); } finally { setBusy(false); } }; return auth ? <Dashboard /> : <LoginForm values={values} onChange={(key, value) => setValues({ ...values, [key]: value })} onSubmit={submit} busy={busy} error={error} mode={mode} setMode={setMode} />; }
