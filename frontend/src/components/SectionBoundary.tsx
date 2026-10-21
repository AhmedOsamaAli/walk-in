import { Component, type ErrorInfo, type ReactNode } from "react";

interface SectionBoundaryProps {
  /** What the section shows, for the message that replaces it ("The gaps"). */
  label: string;
  children: ReactNode;
}

interface SectionBoundaryState {
  failed: boolean;
}

/** Keeps one section's render error from blanking the page: the rest of the survey stays readable. */
export class SectionBoundary extends Component<SectionBoundaryProps, SectionBoundaryState> {
  override state: SectionBoundaryState = { failed: false };

  static getDerivedStateFromError(): SectionBoundaryState {
    return { failed: true };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`${this.props.label} failed to render`, error, info.componentStack);
  }

  override render(): ReactNode {
    if (this.state.failed) {
      return <p className="sec section-error mono">{this.props.label} could not be shown. Reload the page to try again.</p>;
    }
    return this.props.children;
  }
}
