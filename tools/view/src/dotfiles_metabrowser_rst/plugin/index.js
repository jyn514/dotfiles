(() => {
  const mb = window.metabrowser;
  if (!mb) {
    console.error("metabrowser rst plugin: window.metabrowser missing");
    return;
  }

  const externalSchemes = new Set(["http", "https", "mailto", "tel"]);
  const resourceAttributes = [
    ["img[src]", "src"],
    ["audio[src]", "src"],
    ["video[src]", "src"],
    ["source[src]", "src"],
    ["object[data]", "data"],
  ];

  function rawData(ctx) {
    return ctx.raw && typeof ctx.raw === "object" ? ctx.raw : {};
  }

  function renderSource(container, ctx) {
    mb.perf.measure("renderRst:source", () => {
      mb.renderSourceView(container, rawData(ctx));
    });
  }

  function renderError(container, error) {
    const detail = error instanceof Error ? error.message : String(error);
    container.innerHTML =
      '<div class="notice mb-rst-error" data-severity="error" role="alert">' +
      "<strong>Could not render this document.</strong>" +
      `<pre>${mb.escapeHtml(detail)}</pre>` +
      "</div>";
  }

  function splitTarget(target) {
    const fragmentIndex = target.indexOf("#");
    const beforeFragment = fragmentIndex === -1 ? target : target.slice(0, fragmentIndex);
    const fragment = fragmentIndex === -1 ? undefined : target.slice(fragmentIndex + 1);
    const queryIndex = beforeFragment.indexOf("?");
    return {
      path: queryIndex === -1 ? beforeFragment : beforeFragment.slice(0, queryIndex),
      query: queryIndex === -1 ? undefined : beforeFragment.slice(queryIndex + 1),
      fragment,
    };
  }

  function safeDecode(value) {
    try {
      return decodeURIComponent(value);
    } catch (_error) {
      return null;
    }
  }

  function inventoryName(value) {
    return value.replaceAll("%", "%25").replaceAll("\\", "%5C");
  }

  function resolvePath(sourcePath, authoredPath) {
    const rooted = authoredPath.startsWith("/");
    const relative = rooted ? authoredPath.slice(1) : authoredPath;
    if (!relative) {
      return rooted ? "" : sourcePath;
    }
    const trailingSlash = relative.endsWith("/");
    const segments = rooted ? [] : sourcePath.split("/").slice(0, -1);
    const authoredSegments = relative.split("/");
    for (const [index, rawSegment] of authoredSegments.entries()) {
      if (!rawSegment) {
        if (trailingSlash && index === authoredSegments.length - 1) {
          continue;
        }
        return null;
      }
      const segment = safeDecode(rawSegment);
      if (
        segment === null ||
        segment.includes("/") ||
        segment.includes("\\") ||
        segment.includes("\0")
      ) {
        return null;
      }
      if (segment === ".") {
        continue;
      }
      if (segment === "..") {
        if (!segments.length) {
          return null;
        }
        segments.pop();
        continue;
      }
      segments.push(inventoryName(segment));
    }
    const path = segments.join("/");
    return trailingSlash && path ? `${path}/` : path;
  }

  function resolveTarget(sourcePath, authoredTarget) {
    if (
      typeof authoredTarget !== "string" ||
      authoredTarget.includes("\\") ||
      authoredTarget.includes("\0")
    ) {
      return { blocked: true };
    }
    const compact = authoredTarget.trimStart();
    if (compact.startsWith("//")) {
      return { external: true };
    }
    const scheme = /^([A-Za-z][A-Za-z0-9+.-]*):/.exec(compact);
    if (scheme) {
      return externalSchemes.has(scheme[1].toLowerCase())
        ? { external: true }
        : { blocked: true };
    }
    const parts = splitTarget(authoredTarget);
    const path = resolvePath(sourcePath, parts.path);
    if (path === null) {
      return { blocked: true };
    }
    const target = { path };
    if (parts.query) {
      target.query = parts.query;
    }
    if (parts.fragment) {
      const fragment = safeDecode(parts.fragment);
      if (fragment === null || fragment.includes("\0")) {
        return { blocked: true };
      }
      target.fragment = fragment;
    }
    return { target };
  }

  function rawHref(target) {
    const fragment = target.fragment ? `#${encodeURIComponent(target.fragment)}` : "";
    return `/raw?path=${encodeURIComponent(target.path)}${fragment}`;
  }

  function disableTarget(element, attribute) {
    element.removeAttribute(attribute);
    element.setAttribute("aria-disabled", "true");
    element.setAttribute("title", "Metabrowser blocked this destination.");
  }

  function isPlainPrimaryClick(event) {
    return (
      !event.defaultPrevented &&
      event.button === 0 &&
      !event.altKey &&
      !event.ctrlKey &&
      !event.metaKey &&
      !event.shiftKey
    );
  }

  function enhanceLinks(container, sourcePath) {
    const internalTargets = new WeakMap();
    for (const anchor of container.querySelectorAll("a[href]")) {
      const resolved = resolveTarget(sourcePath, anchor.getAttribute("href"));
      if (resolved.target) {
        anchor.setAttribute("href", mb.navigation.href(resolved.target));
        internalTargets.set(anchor, resolved.target);
      } else if (resolved.blocked) {
        disableTarget(anchor, "href");
      }
    }
    for (const [selector, attribute] of resourceAttributes) {
      for (const resource of container.querySelectorAll(selector)) {
        const resolved = resolveTarget(sourcePath, resource.getAttribute(attribute));
        if (resolved.target) {
          resource.setAttribute(attribute, rawHref(resolved.target));
        } else if (resolved.blocked) {
          disableTarget(resource, attribute);
        }
      }
    }

    function handleClick(event) {
      if (!isPlainPrimaryClick(event)) {
        return;
      }
      let element = event.target;
      while (element && element !== container) {
        if (element instanceof Element) {
          const target = internalTargets.get(element);
          if (target) {
            event.preventDefault();
            void mb.navigation.open(target).catch((error) => {
              console.warn("Could not open reStructuredText link", error);
            });
            return;
          }
          element = element.parentElement;
        } else {
          return;
        }
      }
    }

    container.addEventListener("click", handleClick);
    return () => container.removeEventListener("click", handleClick);
  }

  function renderDocument(container, ctx) {
    const controller = new AbortController();
    let disposed = false;
    let disposeLinks = null;
    container.innerHTML =
      '<div class="loading mb-delayed-loading"><div class="spinner"></div>' +
      '<span class="sr-only">Loading document...</span></div>';
    const ready = mb.perf.measureAsync("renderRst:document", async () => {
      try {
        const data = await mb.fetchPluginData(
          "rst",
          "rendered",
          { path: ctx.path },
          { signal: controller.signal },
        );
        if (disposed || !container.isConnected) {
          return;
        }
        if (data.truncated) {
          renderSource(container, ctx);
          return;
        }
        const article = document.createElement("article");
        article.className = "mb-rst-document";
        article.innerHTML = typeof data.html === "string" ? data.html : "";
        container.replaceChildren(article);
        disposeLinks = enhanceLinks(article, String(ctx.path || ""));
      } catch (error) {
        if (!disposed && !mb.errors.isAbortError(error)) {
          renderError(container, error);
        }
      }
    });
    return {
      ready,
      dispose() {
        if (disposed) {
          return;
        }
        disposed = true;
        controller.abort();
        disposeLinks?.();
      },
    };
  }

  mb.registerView("rst", "rendered", { render: renderDocument });
  mb.registerView("rst", "source", { render: renderSource });
})();
