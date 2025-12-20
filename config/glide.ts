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

glide.buf.keymaps.del("normal", "s");

glide.autocmds.create("UrlEnter", {
	hostname: "discord.com",
}, async () => {
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
	await glide.process.spawn("hx-hax", ["~/.config/glide/glide.ts"]);
});

function shortest_unique_prefix(needle, haystack) {
	let i = 0;
	// while all words have the same character at position i, increment i
	while (needle[i] && haystack.some(w => w !== needle && w[i] === needle[i])) {
		i++;
	}

	// prefix is the substring from the beginning to the last successfully checked i
	return needle.slice(0, i+1);
}

glide.o.hint_label_generator = async ({ content }) => {
	const texts = await content.map((element) => element.textContent);
	const haystack = texts.map((text) => {
		// strip numbers, non-ascii text, and annoying-to-type characters
		return text.replace(/[0-9]+/g, '').replace(/[^a-zA-Z0-9-]/g, '').toLowerCase();
	});

	let abbrs = new Map();
	let labels = haystack.map((text, i) => {
		const prefix = shortest_unique_prefix(text, haystack);
		// no text at all, nothing we can do here.
		if (prefix === "") return "";

		// if there's more than one occurance of `needle`, there's no unique prefix.
		if (haystack.findIndex(w => w.startsWith(text)) != i) return "";

		// set a cap on how long a label can be.
		if (prefix.length > 3) {
			let short = prefix.slice(0, 2);
			// avoid returning duplicate labels
			let i = abbrs.getOrInsert(short, 0);
			abbrs.set(short, i+1);
			// first one gets the prime spot
			if (i == 0) {
				return prefix.slice(0, 3);
			// avoid mixing letters and numbers if there's too many numbers
			} else if (i > 9) {
				return "";
			} else {
				return short + i.toString();
			}
		}

		return prefix;
	});

	// If we have a bunch of numbers, see if there's any single-letter free spots
	const letters = Array(26).fill().map((_, i) => String.fromCharCode('a'.charCodeAt(0) + i));
	const prefixes = [...abbrs.keys()];
	let char_start = 0;
	let nums_used = 0;
	labels = labels.map(text => {
		if (text !== "") return text;
		const abbr = letters.slice(char_start).find(c => {
			!labels.includes(c) && !prefixes.some(prefix => prefix.startsWith(c))
		});
		if (abbr) {
			char_start = abbr.charCodeAt(0) - 'a'.charCodeAt(0) + 1;
			return abbr;
		}
		// out of characters, use numbers
		const last = nums_used.toString();
		nums_used++;
		return last;
	});

	return labels;
};
