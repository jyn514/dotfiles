import { expect, test } from "bun:test";
import {
  registerChildExtensionChannel, EXTENSION_DISCOVER, type ChildEndpoint,
} from "./extension-channel.ts";

test("new helper rejects old manager immediately without emitting orphan notifications", async () => {
  const old = process.env.PI_SUBAGENT_EXTENSION_CHANNEL_VERSION;
  delete process.env.PI_SUBAGENT_EXTENSION_CHANNEL_VERSION;
  let endpoint: ChildEndpoint | undefined;
  const notifications: string[] = [];
  const hooks = new Map<string, (...args: any[]) => any>();
  const pi: any = {
    events: {
      on() {},
      emit(name: string, offer: any) {
        if (name === EXTENSION_DISCOVER) endpoint = offer.endpoint;
      },
    },
    on(name: string, handler: any) { hooks.set(name, handler); },
    registerCommand() {},
    getPauseState() { return "unpaused"; },
  };
  try {
    registerChildExtensionChannel(pi);
    hooks.get("session_start")!({}, {
      ui: { notify(message: string) { notifications.push(message); } },
    });
    await expect(endpoint!.request("test", { value: 1 })).rejects.toMatchObject({ code: "unsupported" });
    expect(notifications).toEqual([]);
  } finally {
    if (old === undefined) delete process.env.PI_SUBAGENT_EXTENSION_CHANNEL_VERSION;
    else process.env.PI_SUBAGENT_EXTENSION_CHANNEL_VERSION = old;
  }
});
