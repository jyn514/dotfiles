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

glide.autocmds.create("ConfigLoaded", async () => {
	// tests and debugging go here
	console.assert(labels(["a", "b", "c"]) == ["a", "b", "c"]);
	console.assert(labels(["", "", ""]) == ["0", "1", "2"]);
	console.assert(labels(["abcdefg", "ac"]) == ["ab", "ac"]);
	console.assert(labels(["abcdefg", "abcdfff"]) == ["abe", "abf"]);

	// Additional test cases
	console.assert(labels(["apple", "application"]) == ["app", "appl"]);
	console.assert(labels(["test", "test", "testing"]) == ["te", "0", "tes"]);
	console.assert(labels(["", "a", ""]) == ["0", "a", "1"]);

	const a = ["new", "notifications", "0", "1"];
	console.assert(shortest_unique_prefix("new", a), "ne");
});

glide.buf.keymaps.del("normal", "s");

// breaks bookmarks and fastmail code highlighting, and I can just use pageUp/Down
glide.keymaps.del("insert", "<C-d>");
// break View Source
glide.keymaps.del(["normal", "insert"], "<C-u>");

glide.autocmds.create("UrlEnter", {hostname: "app.fastmail.com"}, async () => {
	glide.buf.keymaps.del("normal", "gi");
	glide.buf.keymaps.del("normal", "j");
	glide.buf.keymaps.del("normal", "k");
	glide.buf.keymaps.del("normal", "u");
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
	glide.buf.keymaps.set("normal", ":", async() => {
		glide.keys.send('a:');
	});
});

// pin tab
glide.keymaps.set("normal", "p", async() => {
	const tab = await glide.tabs.active();
	browser.tabs.update(tab.id, { pinned: !tab.pinned });
});

// undo
glide.keymaps.set("normal", "U", "keys <C-S-z>");
glide.keymaps.set("normal", "U", "keys <D-S-z>");

// forward/back arrows
glide.keymaps.set(["insert", "normal"], "<A-Right>", "forward");
glide.keymaps.set(["insert", "normal"], "<A-Left>", "back");

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
	browser.windows.create({ tabId: currentTab.id });
});
// move tab into existing window
glide.keymaps.set("normal", "<A-w>", async() => {
	const [currentTab] = await browser.tabs.query({ active: true, currentWindow: true });
	const windows = await browser.windows.getAll({ windowTypes: ["normal"] });
	const next = windows.find(w => w.id != currentTab.windowId);

	await browser.tabs.move(currentTab.id, { windowId: next.id, index: -1 });
	await browser.tabs.update(currentTab.id, { active: true });
	await browser.windows.update(next.id, { focused: true });
});

// clone repo
// https://blog.craigie.dev/introducing-glide/
glide.keymaps.set("normal", "gC", async () => {
  // extract the owner and repo from a url like 'https://github.com/glide-browser/glide'
	let url = glide.ctx.url;
	const path = url.pathname.split("/").slice(1, 3);
	const repo = path[1];
	url.pathname = '/' + path.join('/');
	if (!["github.com", "gitlab.com"].includes(url.hostname) || !repo)
		throw new Error("current URL is not a github repo");

	// * clone the current github repo to ~/src/$repo
	// * start kitty with neovim open at the cloned repo
	const repo_path = glide.path.join(glide.path.home_dir, "src", repo);
	await glide.process.execute("fork-github", [url.toString(), repo_path]);
	await glide.process.execute("hx-hax", [repo_path]);
	// await glide.process.execute("kitty", ["-d", repo_path, "nvim"], { cwd: repo_path });
}, { description: "open the GitHub repo in the focused tab in Neovim" });

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

function shortest_unique_prefix(needle, haystack) {
	let i = 0;
	// while all words have the same character at position i, increment i
	for (let i in needle) {
		const prefix = needle.slice(0, i);
		const is_unique = !haystack.some(w => w !== needle && w.startsWith(prefix));
		if (is_unique) {
			return prefix;
		}
	}
	return needle;
}

function labels(texts) {
	// strip numbers, non-ascii text, and annoying-to-type characters
	let haystack = texts.map((text) => {
		return text.replace(/[0-9]+/g, '').replace(/[^a-zA-Z0-9-]/g, '').toLowerCase();
	});
	// now shorten as much as we can without losing info
	haystack = haystack.map(text => shortest_unique_prefix(text, haystack));

	let nums_used = 0;
	const result = new Array(haystack.length);
	const labelIndices = new Map();

	// record the original order so we don't have to keep them in order while calculating.
	for (const [index, label] of haystack.entries()) {
		if (label === "") {
			result[index] = String(nums_used++);
		} else {
			labelIndices.getOrInsert(label, []).push(index);
		}
	}

	// assign numbers to duplicates and remove them from the haystack.
	const unique = [];
	for (const [label, indices] of labelIndices) {
		// first occurrence gets processed normally, rest get numbers
		unique.push({ label, index: indices[0] });
		for (let i = 1; i < indices.length; i++) {
			result[indices[i]] = String(nums_used++);
		}
	}

	// trim prefixes longer than 3 characters by using letters that occur later in the label.
	const used = new Set();
	outer: for (const {label, index} of unique) {
		if (label.length > 3) {
			const base = label.substring(0, 2);
			// try each character after the 3rd in turn.
			for (const c of label.substring(2)) {
				const candidate = base + c;
				if (!used.has(candidate)) {
					result[index] = candidate;
					used.add(candidate);
					continue outer;
				}
			}
			// we couldn't shorten it. use a number.
			result[index] = String(nums_used++);
		} else {
			// already short enough, use it as-is.
			result[index] = label;
			used.add(label);
		}
	}

	// try one last time to shorten prefixes—if we gave up earlier, we might have freed up a spot.
	return result.map(text => shortest_unique_prefix(text, result));
}

glide.o.hint_label_generator = async ({ content }) => {
	const texts = await content.map((element) => element.textContent);
	return labels(texts);
};

