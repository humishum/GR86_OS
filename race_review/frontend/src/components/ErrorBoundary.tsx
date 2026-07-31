import { Component, type ErrorInfo, type ReactNode } from "react";
import { ActionableError } from "./ActionableError";

type State = { error: Error | null };

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Race Review rendering failed", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="fatal-error">
        <div className="wordmark"><span>GR86</span> / RACE REVIEW</div>
        <ActionableError
          title="Race Review stopped unexpectedly"
          message="Your session data is safe. Reload the interface to recover."
          primaryAction={{ label: "Reload interface", onClick: () => window.location.reload() }}
        />
      </main>
    );
  }
}
