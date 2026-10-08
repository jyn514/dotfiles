/** Adapted from Pi's examples/extensions/custom-footer.ts (installed v0.85.1). */

import { isAbsolute, relative, resolve, sep } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";

export default function (pi: ExtensionAPI) {
  pi.on("session_start", (_event, ctx) => {
    if (!ctx.hasUI) return;
    ctx.ui.setFooter((tui, theme, footerData) => {
      const unsub = footerData.onBranchChange(() => tui.requestRender());
      return {
        dispose: unsub,
        invalidate() {},
        render(width: number): string[] {
          // Use all entries, like Pi's default footer, including tool and summary costs.
          let cost = 0;
          for (const e of ctx.sessionManager.getEntries()) {
            if (e.type === "message") {
              if (e.message.role === "assistant" || e.message.role === "toolResult") {
                cost += e.message.usage?.cost.total ?? 0;
              }
            } else if (e.type === "compaction" || e.type === "branch_summary") {
              cost += e.usage?.cost.total ?? 0;
            }
          }
          const fmt = (n: number) => n < 1000 ? `${n}`
            : n < 10000 ? `${(n / 1000).toFixed(1)}k`
            : n < 1000000 ? `${Math.round(n / 1000)}k`
            : `${(n / 1000000).toFixed(1)}M`;
          const usage = ctx.getContextUsage();
          const percent = usage?.percent;
          const capacity = usage?.contextWindow ?? ctx.model?.contextWindow ?? 0;
          const context = `${percent == null ? "?" : `${percent.toFixed(1)}%`}/${fmt(capacity)}`;
          const color = percent != null && percent > 90 ? "error" : percent != null && percent > 70 ? "warning" : "dim";
          const left = truncateToWidth(`${theme.fg(color, context)} ${theme.fg("dim", `$${cost.toFixed(3)}`)}`, width);
          const model = ctx.model;
          let right = model?.id || "no-model";
          if (model?.reasoning) {
            const thinking = pi.getThinkingLevel();
            right += ` • ${thinking === "off" ? "thinking off" : thinking}`;
          }
          if (model && footerData.getAvailableProviderCount() > 1) {
            const withProvider = `(${model.provider}) ${right}`;
            if (visibleWidth(left) + 2 + visibleWidth(withProvider) <= width) right = withProvider;
          }
          const available = width - visibleWidth(left) - 2;
          right = available > 0 ? truncateToWidth(right, available, "") : "";
          const pad = " ".repeat(Math.max(0, width - visibleWidth(left) - visibleWidth(right)));
          const stats = right ? left + pad + theme.fg("dim", right) : left;

          let pwd = ctx.sessionManager.getCwd();
          const home = process.env.HOME || process.env.USERPROFILE;
          if (home) {
            const inside = relative(resolve(home), resolve(pwd));
            if (inside === "" || (inside !== ".." && !inside.startsWith(`..${sep}`) && !isAbsolute(inside))) {
              pwd = inside ? `~${sep}${inside}` : "~";
            }
          }
          const branch = footerData.getGitBranch();
          if (branch) pwd += ` (${branch})`;
          const title = ctx.sessionManager.getSessionName();
          if (title) pwd += ` • ${title}`;
          const ellipsis = theme.fg("dim", "...");
          const lines = [truncateToWidth(theme.fg("dim", pwd), width, ellipsis), stats];
          const statuses = footerData.getExtensionStatuses();
          if (statuses.size) {
            const text = [...statuses].sort(([a], [b]) => a.localeCompare(b))
              .map(([, text]) => text.replace(/[\r\n\t]/g, " ").replace(/ +/g, " ").trim()).join(" ");
            lines.push(truncateToWidth(text, width, ellipsis));
          }
          return lines;
        },
      };
    });
  });
}
