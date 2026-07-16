import type { ComponentType as ReactComponentType } from "react";

// Next.js 15.5 generated validator types reference React.ComponentType globally.
declare global {
  namespace React {
    type ComponentType<P = {}> = ReactComponentType<P>;
  }
}
