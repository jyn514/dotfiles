import type { ExtensionAPI, ExtensionFactory } from "@earendil-works/pi-coding-agent";

export interface StartupSession {
  event: any;
  ctx: any;
}

type DeferredExtensionFactory = (
  pi: ExtensionAPI,
  startup?: StartupSession,
) => void | Promise<void>;

type ExtensionModule = { default: DeferredExtensionFactory };

export function createDeferredStartupExtension(
  load: () => Promise<ExtensionModule> = () => import("./implementation.js"),
): ExtensionFactory {
  return (pi: ExtensionAPI) => {
    let initialization: Promise<void> | undefined;
    let initialized = false;

    pi.on("session_start", async (event, ctx) => {
      if (initialized) return;
      if (!initialization) {
        initialization = load()
          .then((extension) => extension.default(pi, { event, ctx }))
          .then(() => { initialized = true; });
      }
      await initialization;
    });
  };
}

export default createDeferredStartupExtension();
