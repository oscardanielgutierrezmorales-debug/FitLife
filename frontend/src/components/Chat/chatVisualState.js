export function initialChatVisualState(storedValue = null) {
  return { minimized: storedValue === "true", unread: 0 };
}

export function chatVisualReducer(state, action) {
  if (action.type === "minimize") return { ...state, minimized: true };
  if (action.type === "restore") return { minimized: false, unread: 0 };
  if (action.type === "response_received" && state.minimized) return { ...state, unread: state.unread + 1 };
  return state;
}
