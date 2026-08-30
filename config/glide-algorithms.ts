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

function repository_from_url(current_url: string) {
	const url = new URL(current_url);
	let path = url.pathname.split("/").filter(Boolean);
	if (url.hostname === "github.com") {
		path = path.slice(0, 2);
	} else if (url.hostname === "gitlab.com") {
		const route_separator = path.indexOf("-");
		if (route_separator >= 0) path = path.slice(0, route_separator);
	} else {
		throw new Error("current URL is not a GitHub or GitLab repository");
	}
	if (path.length < 2)
		throw new Error("current URL is not a GitHub or GitLab repository");

	url.pathname = "/" + path.join("/");
	url.search = "";
	url.hash = "";
	return { url, repo: path[path.length - 1].replace(/\.git$/, "") };
}

function shorten_unique_prefixes(haystack: string[]) {
	const seen = new Set<string>();
	const duplicates = new Set<string>();
	for (const text of haystack) {
		if (seen.has(text)) duplicates.add(text);
		else seen.add(text);
	}

	return haystack.map((needle, pos) => {
		if (duplicates.has(needle)) return needle;
		for (let i = 1; i <= needle.length; i++) {
			const prefix = needle.slice(0, i);
			if (haystack.every((word, index) => pos === index || !word.startsWith(prefix)))
				return prefix;
		}
		return needle;
	});
}

function strip_hint_text(text: string | null) {
	return (text ?? "").replace(/[0-9]+/g, "").replace(/[^a-zA-Z0-9-]/g, "").toLowerCase();
}

function labels(texts: string[]) {
	const haystack = shorten_unique_prefixes(texts);
	let nums_used = 0;
	const result = new Array<string>(haystack.length);
	const used = new Set<string>();

	outer: for (const [index, prefix] of haystack.entries()) {
		if (prefix === "") {
			result[index] = String(nums_used++);
		} else if (prefix.length > 3 || used.has(prefix)) {
			const base = prefix.substring(0, 2);
			for (const character of texts[index].substring(2)) {
				const candidate = base + character;
				if (!used.has(candidate)) {
					result[index] = candidate;
					used.add(candidate);
					continue outer;
				}
			}
			result[index] = String(nums_used++);
		} else {
			result[index] = prefix;
			used.add(prefix);
		}
	}

	return shorten_unique_prefixes(result);
}

function hint_labels(elements: Array<{ textContent: string | null; ariaLabel: string | null }>) {
	const texts = elements.map(element => strip_hint_text(element.textContent) || strip_hint_text(element.ariaLabel));
	return labels(texts);
}

async function hint_labels_from_content(content: {
	map<T>(callback: (element: { textContent: string | null; ariaLabel: string | null }) => T): Promise<T[]>;
}) {
	const elements = await content.map(element => ({
		textContent: element.textContent,
		ariaLabel: element.ariaLabel,
	}));
	return hint_labels(elements);
}

glide.g.dotfiles_algorithms = { repository_from_url, hint_labels, hint_labels_from_content };
