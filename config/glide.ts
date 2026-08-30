// Config docs:
//
//   https://glide-browser.app/config
//
// API reference:
//
//   https://glide-browser.app/api
//
// Default config files can be found here:
//
//   https://github.com/glide-browser/glide/tree/main/src/glide/browser/base/content/plugins
//
// Most default keymappings are defined here:
//
//   https://github.com/glide-browser/glide/blob/main/src/glide/browser/base/content/plugins/keymaps.mts
//
// Try typing `glide.` and see what you can do!
//
// NOTE: vim LSP integration requires that you open this file from ~/.config/glide, not from the dotfiles repo.

declare global {
	interface GlideGlobals {
		dotfiles_algorithms: {
			repository_from_url(current_url: string): { url: URL; repo: string };
			hint_labels(elements: Array<{ textContent: string | null; ariaLabel: string | null }>): string[];
			hint_labels_from_content(content: {
				map<T>(callback: (element: { textContent: string | null; ariaLabel: string | null }) => T): Promise<T[]>;
			}): Promise<string[]>;
		};
	}
}

glide.g.mapleader = ","
glide.buf.keymaps.set("normal", ",.", async() => {
  await glide.commandline.show();
});

// breaks search on many docs sites
glide.buf.keymaps.del("normal", "s");
// breaks bookmarks and fastmail code highlighting, and I can just use pageUp/Down
glide.keymaps.del("insert", "<C-d>");
// breaks keybinds on many sites
glide.buf.keymaps.del(["normal", "insert"], "<C-k>");
// break View Source
glide.keymaps.del(["normal", "insert"], "<C-u>");

async function disable_shortcuts() {
  await glide.excmds.execute("mode_change ignore");
  return () => glide.excmds.execute("mode_change normal");
}

const disabled_sites = [
  "configure.zsa.io",
  "linear.app",
  "kumo.io",
];

for (const hostname of disabled_sites) {
  glide.autocmds.create("UrlEnter", { hostname }, disable_shortcuts);
}

glide.autocmds.create("UrlEnter", {hostname: "app.fastmail.com"}, async () => {
	glide.buf.keymaps.del("normal", "gi");
	glide.buf.keymaps.del("normal", "j");
	glide.buf.keymaps.del("normal", "k");
	glide.buf.keymaps.del("normal", "u");
	glide.buf.keymaps.del("normal", "x");
	glide.buf.keymaps.del("insert", "<C-i>");

  // obsidian-like keyboard shortcuts

  // quote text
  glide.buf.keymaps.set(['normal', 'insert'], "<C-'>", 'keys <C-]>');
  glide.buf.keymaps.set(['normal', 'insert'], '<C-">', 'keys <C-[>');
  // code formatting
  glide.buf.keymaps.set(['normal', 'insert'], "<C-`>", 'keys <C-d>');
  // strikethrough
  glide.buf.keymaps.set(['normal', 'insert'], "<C-S-s>", 'keys <C-S-7>');
  // bulleted list
  glide.buf.keymaps.set(['normal', 'insert'], "<C-.>", 'keys <C-S-8>');
  // numbered list
  glide.buf.keymaps.set(['normal', 'insert'], "<C-/>", 'keys <C-S-9>');
});
glide.autocmds.create("UrlEnter", {hostname: "discord.com",}, async () => {
	glide.buf.keymaps.del(["insert", "normal"], "<C-k>");
	glide.buf.keymaps.del("normal", "e");
	glide.buf.keymaps.del("normal", "r");
	glide.buf.keymaps.set("normal", ":", async() => {
		glide.keys.send('a:');
	});
});
glide.autocmds.create("UrlEnter", /.*\.zulipchat.com/, async () => {
	glide.buf.keymaps.del("normal", "d");
	glide.buf.keymaps.del("normal", "e");
	glide.buf.keymaps.del("normal", "r");
	glide.buf.keymaps.del("normal", "t");
	glide.buf.keymaps.del("normal", "U");
	glide.buf.keymaps.del("normal", ":");
});

// pin tab
glide.keymaps.set("normal", "p", async() => {
	const tab = await glide.tabs.active();
	if (tab?.id == null) return;
	await browser.tabs.update(tab.id, { pinned: !tab.pinned });
});

// undo
glide.keymaps.set("normal", "U", async () => {
	const { os } = await browser.runtime.getPlatformInfo();
	await glide.keys.send(os === "mac" ? "<D-S-z>" : "<C-S-z>");
});

// help
// https://github.com/glide-browser/glide/discussions/155
glide.keymaps.set("normal", "<C-?>",
	"tab_new resource://glide-docs/index.html#default-keymappings"
);
// workaround for vim indent bug
;

glide.keymaps.set("normal", "<D-/>",
	"tab_new resource://glide-docs/index.html#default-keymappings"
);
// workaround for vim indent bug
;

// move tab to new window
glide.keymaps.set("normal", "W", async() => {
	const [currentTab] = await browser.tabs.query({ active: true, currentWindow: true });
	if (currentTab?.id == null) return;
	await browser.windows.create({ tabId: currentTab.id });
});
// move tab into existing window
glide.keymaps.set("normal", "<A-w>", async() => {
	const [currentTab] = await browser.tabs.query({ active: true, currentWindow: true });
	if (currentTab?.id == null) return;
	const windows = await browser.windows.getAll({ windowTypes: ["normal"] });
	const next = windows.find(w => w.id != currentTab.windowId);
	if (next?.id == null) return;

	await browser.tabs.move(currentTab.id, { windowId: next.id, index: -1 });
	await browser.tabs.update(currentTab.id, { active: true });
	await browser.windows.update(next.id, { focused: true });
});

glide.include("glide-algorithms.ts").then(() => {
	const { repository_from_url, hint_labels_from_content } = glide.g.dotfiles_algorithms;

	// clone repo
	glide.keymaps.set("normal", "gC", async () => {
		const { url, repo } = repository_from_url(glide.ctx.url);
		const repo_path = glide.path.join(glide.path.home_dir, "src", repo);
		await glide.process.execute("fork-github", [url.toString(), repo_path]);
		await glide.process.execute("hx-hax", [repo_path]);
	}, { description: "open the GitHub repo in the focused tab in Neovim" });

	glide.o.hint_label_generator = ({ content }) => hint_labels_from_content(content);
});

// text editing works like linux
// glide.keymaps.set("insert", "<C-Left>", "execute_motion b");
// glide.keymaps.set("insert", "<C-Right>", "motion w");
// glide.keymaps.set(["normal", "insert"], "<C-Left>", "motion b");
// glide.keymaps.set(["normal", "insert"], "<C-Right>", "motion w");
glide.keymaps.set(["normal", "insert"], "<C-Right>", async() => {
	const selection = window.getSelection();
	if (selection == null) return;
	selection.modify("move", "forward", "word");
});
// gi acts like gI
glide.keymaps.set('normal', 'gi', 'keys gI');

// edit config
glide.keymaps.set('normal', 'ge', async() => {
	const dir = glide.path.join(glide.path.home_dir, ".config", "glide");
	const config = glide.path.join(dir, "glide.ts");
	await glide.process.spawn("hx-hax", [config], { cwd: dir });
});

// function partition(array, predicate) {
// 	let [yes, no] = [[], []];
// 	for ([i, elem] of array.entries()) {
// 		(predicate(elem, i) ? yes : no).push(elem);
// 	}
// 	return [yes, no];
// }
