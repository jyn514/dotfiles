export default function (pi: { registerFlag(name: string, options: { type: "boolean" }): void }) {
    pi.registerFlag("cache-invalidation-check", { type: "boolean" });
}
