(() => {
  const mb = window.metabrowser;
  if (!mb) {
    console.error("metabrowser markdown mermaid plugin: window.metabrowser missing");
    return;
  }

  const builtin = mb.getRegisteredView("markdown", "rendered");
  if (!builtin || typeof builtin.render !== "function") {
    console.error("metabrowser markdown mermaid plugin: built-in markdown renderer missing");
    return;
  }

  const mermaid = window.mermaid;
  if (!mermaid || typeof mermaid.initialize !== "function" || typeof mermaid.render !== "function") {
    console.error("metabrowser markdown mermaid plugin: Mermaid bundle missing");
    return;
  }

  const mermaidSelector = "pre > code.language-mermaid, pre > code.lang-mermaid";
  let diagramSequence = 0;

  function resolvedTheme() {
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "default";
  }

  function configureMermaid() {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: resolvedTheme(),
    });
  }

  function createFigure() {
    const figure = document.createElement("figure");
    figure.className = "mb-mermaid-diagram";
    return figure;
  }

  function renderError(pre, error) {
    if (pre.nextElementSibling?.classList.contains("mb-mermaid-error")) {
      return;
    }
    const notice = document.createElement("div");
    notice.className = "notice mb-mermaid-error";
    notice.dataset.severity = "error";
    notice.setAttribute("role", "alert");

    const title = document.createElement("strong");
    title.textContent = "Could not render this Mermaid diagram.";
    notice.append(title);

    const detail = document.createElement("pre");
    detail.textContent = error instanceof Error ? error.message : String(error);
    notice.append(detail);
    pre.after(notice);
  }

  async function renderDiagram(figure, source) {
    configureMermaid();
    const id = `mb-mermaid-${++diagramSequence}`;
    const result = await mermaid.render(id, source);
    figure.innerHTML = typeof result.svg === "string" ? result.svg : "";
    if (typeof result.bindFunctions === "function") {
      result.bindFunctions(figure);
    }
  }

  function mountMermaid(container) {
    const article = container.querySelector("article.kpress");
    if (!article || article.classList.contains("kpress-inert")) {
      return Object.freeze({ ready: Promise.resolve(), dispose() {} });
    }

    const diagrams = [];
    let disposed = false;
    let renderVersion = 0;
    let unsubscribeTheme = null;

    async function renderInitialBlocks() {
      const version = renderVersion;
      const blocks = Array.from(article.querySelectorAll(mermaidSelector))
        .map((code) => ({
          pre: code.parentElement,
          source: code.textContent || "",
        }))
        .filter((block) => block.pre instanceof HTMLElement);

      for (const block of blocks) {
        if (disposed || version !== renderVersion || !block.pre.isConnected) {
          return;
        }
        const figure = createFigure();
        try {
          await renderDiagram(figure, block.source);
        } catch (error) {
          if (!disposed && version === renderVersion && block.pre.isConnected) {
            renderError(block.pre, error);
          }
          continue;
        }
        if (disposed || version !== renderVersion || !block.pre.isConnected) {
          return;
        }
        block.pre.replaceWith(figure);
        diagrams.push({ figure, source: block.source });
      }
    }

    async function rerenderForTheme() {
      const version = ++renderVersion;
      for (const diagram of diagrams) {
        if (disposed || version !== renderVersion || !diagram.figure.isConnected) {
          return;
        }
        const figure = createFigure();
        try {
          await renderDiagram(figure, diagram.source);
        } catch (error) {
          console.warn("Could not rerender Mermaid diagram for theme change", error);
          continue;
        }
        if (disposed || version !== renderVersion || !diagram.figure.isConnected) {
          return;
        }
        diagram.figure.replaceWith(figure);
        diagram.figure = figure;
      }
    }

    const ready = renderInitialBlocks().then(() => {
      if (!disposed && typeof window.MetabrowserTheme?.subscribe === "function") {
        unsubscribeTheme = window.MetabrowserTheme.subscribe(() => {
          void rerenderForTheme();
        });
      }
    });

    return Object.freeze({
      ready,
      dispose() {
        if (disposed) {
          return;
        }
        disposed = true;
        renderVersion += 1;
        unsubscribeTheme?.();
      },
    });
  }

  function renderDocument(container, ctx) {
    const rendered = builtin.render(container, ctx);
    let disposed = false;
    let disposeMermaid = null;
    const ready = Promise.resolve(rendered?.ready).then(() => {
      if (disposed) {
        return;
      }
      const mounted = mountMermaid(container);
      disposeMermaid = mounted.dispose;
      return mounted.ready;
    });

    return Object.freeze({
      ready,
      dispose() {
        if (disposed) {
          return;
        }
        disposed = true;
        disposeMermaid?.();
        rendered?.dispose?.();
      },
    });
  }

  mb.registerView("markdown", "rendered", { render: renderDocument });
})();
