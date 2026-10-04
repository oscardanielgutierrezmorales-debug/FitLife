import { Component } from "react";

export class ChatErrorBoundary extends Component {
  constructor(props) { super(props); this.state = { failed: false }; }
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <aside className="chat"><header><strong>FitLife AI</strong><small>Chat con tu equipo FitLife</small></header><div className="messages"><article className="assistant"><strong>FitLife AI</strong><span>El chat encontró un problema de visualización. Tu perfil y plan siguen disponibles; recarga la página para reabrir la conversación.</span></article></div></aside>;
    return this.props.children;
  }
}
