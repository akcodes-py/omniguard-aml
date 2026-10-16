import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

class Boundary extends React.Component {
  constructor(p) { super(p); this.state = { err: null }; }
  static getDerivedStateFromError(err) { return { err: String(err?.message || err) }; }
  render() {
    if (this.state.err)
      return <div style={{ background: "#000", color: "#f87171", padding: 24, fontFamily: "monospace" }}>
        UI crashed: {this.state.err}<br />Screenshot this and send it to the developer.</div>;
    return this.props.children;
  }
}

createRoot(document.getElementById("root")).render(<Boundary><App /></Boundary>);
