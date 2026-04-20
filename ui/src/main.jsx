import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "../../frontend/styles.css";
import "katex/dist/katex.min.css";

class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { error: null };
    }
    static getDerivedStateFromError(error) {
        return { error };
    }
    render() {
        if (this.state.error) {
            return (
                <div style={{ padding: "2rem", color: "#f87171", fontFamily: "monospace", background: "#0a0a0a", minHeight: "100vh" }}>
                    <h2 style={{ color: "#f87171" }}>App crashed</h2>
                    <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{String(this.state.error)}</pre>
                    <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-all", color: "#9ca3af", fontSize: "0.8em" }}>{this.state.error?.stack}</pre>
                    <button style={{ marginTop: "1rem", padding: "0.5rem 1rem", cursor: "pointer" }} onClick={() => { localStorage.clear(); window.location.reload(); }}>Clear storage &amp; reload</button>
                </div>
            );
        }
        return this.props.children;
    }
}

ReactDOM.createRoot(document.getElementById("root")).render(
    <React.StrictMode>
        <ErrorBoundary>
            <App />
        </ErrorBoundary>
    </React.StrictMode>
);
