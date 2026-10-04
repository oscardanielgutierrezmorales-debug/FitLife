import { createRoot } from "react-dom/client";
import { AuthProvider } from "./context/AuthContext";
import App from "./App";
import "./styles.css";
import "./chat.css";
createRoot(document.getElementById("root")).render(<AuthProvider><App /></AuthProvider>);
