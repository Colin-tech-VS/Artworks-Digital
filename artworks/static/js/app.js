document.documentElement.classList.add("js");

// Menu mobile — la barre se replie sous 860px, ce bouton la rouvre.
const navToggle = document.querySelector(".nav-toggle");
const siteNav = document.getElementById("site-nav");
if (navToggle && siteNav) {
  const closeNav = () => {
    siteNav.classList.remove("is-open");
    navToggle.setAttribute("aria-expanded", "false");
    navToggle.setAttribute("aria-label", "Ouvrir le menu");
  };
  navToggle.addEventListener("click", () => {
    const open = siteNav.classList.toggle("is-open");
    navToggle.setAttribute("aria-expanded", String(open));
    navToggle.setAttribute("aria-label", open ? "Fermer le menu" : "Ouvrir le menu");
    if (open) siteNav.querySelector("a")?.focus();
  });
  siteNav.addEventListener("click", (event) => {
    if (event.target.tagName === "A") closeNav();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeNav();
  });
  window.addEventListener("resize", () => {
    if (window.innerWidth > 860) closeNav();
  });
}

// Barre latérale de l’atelier et de l’admin : même repli sur petit écran.
const shellToggle = document.querySelector(".shell-toggle");
const shellSide = document.querySelector(".atelier-side, .admin-side");
if (shellToggle && shellSide) {
  shellToggle.addEventListener("click", () => {
    const open = shellSide.classList.toggle("is-open");
    shellToggle.setAttribute("aria-expanded", String(open));
  });
  shellSide.addEventListener("click", (event) => {
    if (event.target.tagName === "A") {
      shellSide.classList.remove("is-open");
      shellToggle.setAttribute("aria-expanded", "false");
    }
  });
}

const gateDot = document.getElementById("gate-dot");
const gate = document.getElementById("gate");
if (gateDot && gate) {
  gateDot.addEventListener("click", () => {
    gate.hidden = false;
    const field = gate.querySelector("input[name='key']");
    if (field) field.focus();
  });
  gate.addEventListener("keydown", (event) => {
    if (event.key === "Enter") gate.submit();
  });
}

const flashes = document.querySelectorAll(".flash");
flashes.forEach((el) => {
  window.setTimeout(() => {
    el.style.opacity = "0";
    el.style.transform = "translateY(-8px)";
    window.setTimeout(() => el.remove(), 400);
  }, 4200);
});

const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";

const filter = document.getElementById("studio-filter");
const board = document.getElementById("studio-board");
if (filter && board) {
  filter.addEventListener("input", () => {
    const q = filter.value.trim().toLowerCase();
    board.querySelectorAll("li[data-title]").forEach((item) => {
      item.hidden = q ? !item.dataset.title.includes(q) : false;
    });
  });
}

if (board) {
  let dragged = null;
  board.querySelectorAll("li[data-id]").forEach((item) => {
    const handle = item.querySelector(".drag-handle");
    if (!handle) return;
    handle.addEventListener("pointerdown", () => {
      item.draggable = true;
    });
    item.addEventListener("dragstart", (event) => {
      dragged = item;
      item.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
    });
    item.addEventListener("dragend", () => {
      item.draggable = false;
      item.classList.remove("is-dragging");
      persistOrder();
    });
    item.addEventListener("dragover", (event) => {
      event.preventDefault();
      const target = event.currentTarget;
      if (!dragged || dragged === target) return;
      const rect = target.getBoundingClientRect();
      const before = event.clientY < rect.top + rect.height / 2;
      target.parentNode.insertBefore(dragged, before ? target : target.nextSibling);
    });
  });

  function persistOrder() {
    const ids = [...board.querySelectorAll("li[data-id]")].map((item) => item.dataset.id);
    fetch(board.dataset.reorder, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrf,
      },
      body: JSON.stringify({ ids }),
    });
  }
}

const imageField = document.querySelector("input[type='file'][name='image'], input[type='file'][name='cover']");
if (imageField) {
  imageField.addEventListener("change", () => {
    const file = imageField.files && imageField.files[0];
    if (!file) return;
    const preview = document.querySelector(".preview img") || document.createElement("img");
    preview.src = URL.createObjectURL(file);
    if (!preview.parentElement) {
      const figure = document.createElement("figure");
      figure.className = "preview";
      figure.appendChild(preview);
      imageField.closest("form")?.before(figure);
    }
  });
}

document.addEventListener("keydown", (event) => {
  if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
  if (event.key === "n" && document.body.classList.contains("atelier-app")) {
    const link = document.querySelector('a[href*="/atelier/oeuvres/nouvelle"]');
    if (link) {
      event.preventDefault();
      link.click();
    }
  }
});

// Copier l’adresse d’une œuvre — Instagram ne prend pas de lien cliquable.
document.querySelectorAll(".link-copy").forEach((button) => {
  button.addEventListener("click", async () => {
    const url = button.dataset.copy;
    const said = button.textContent;
    try {
      await navigator.clipboard.writeText(url);
      button.textContent = "Lien copié";
    } catch {
      window.prompt("Copiez ce lien :", url);
      return;
    }
    window.setTimeout(() => { button.textContent = said; }, 2200);
  });
});

/* ------------------------------------------------------------------
   K.A.E.L. — le panneau. Il ne pense pas ici : il appelle le serveur,
   qui parle à K.A.E.L. ou déclenche un outil. Aucun jeton côté page.
   ------------------------------------------------------------------ */
(() => {
  const panel = document.getElementById("kael-panel");
  const opener = document.querySelector(".kael-open");
  if (!panel || !opener) return;

  const stream = panel.querySelector(".kael-stream");
  const endpoint = panel.dataset.endpoint;
  const mode = panel.dataset.mode;
  let conversationId = null;
  let busy = false;

  const setOpen = (open) => {
    panel.hidden = !open;
    opener.setAttribute("aria-expanded", String(open));
    document.body.classList.toggle("kael-is-open", open);
    if (open) panel.querySelector("textarea, button:not(.kael-close)")?.focus();
  };
  opener.addEventListener("click", () => setOpen(panel.hidden));
  panel.querySelector(".kael-close")?.addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !panel.hidden) setOpen(false);
  });

  const bubble = (who, text, extra) => {
    const line = document.createElement("div");
    line.className = `kael-line kael-${who}`;
    const body = document.createElement("p");
    body.textContent = text;
    line.appendChild(body);
    if (extra) line.appendChild(extra);
    stream.appendChild(line);
    stream.scrollTop = stream.scrollHeight;
    return line;
  };

  const list = (items) => {
    const ul = document.createElement("ul");
    ul.className = "kael-list";
    items.slice(0, 8).forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item;
      ul.appendChild(li);
    });
    return ul;
  };

  /* Un résultat d'outil est une donnée, pas une phrase : on le raconte. */
  const tell = (tool, data) => {
    if (tool === "analyze_portfolio") {
      const weak = data.works_to_improve || [];
      const head = `J’ai regardé ${data.works_total} œuvre${data.works_total > 1 ? "s" : ""}. `
        + (weak.length
          ? `${weak.length} mériterai${weak.length > 1 ? "ent" : "t"} d’être reprise${weak.length > 1 ? "s" : ""}.`
          : "Les cartels sont complets.");
      const lines = weak.map((w) => `${w.title} — ${w.findings[0]}`).concat(data.remarks || []);
      return bubble("kael", head, lines.length ? list(lines) : null);
    }
    if (tool === "analyze_artwork") {
      const findings = (data.findings || []).map((f) => f.detail);
      return bubble(
        "kael",
        `« ${data.artwork.title} » — ${data.score}/100. ${data.verdict}`,
        findings.length ? list(findings) : null,
      );
    }
    if (tool === "get_artist_stats") {
      const top = (data.top_works || []).map((w) => `${w.title} — ${w.views} vue(s)`);
      return bubble(
        "kael",
        `${data.views_total_period} vue(s) sur ${data.days} jours, ${data.views_all_time} depuis l’ouverture.`,
        top.length ? list(top) : null,
      );
    }
    if (tool === "find_anomalies") {
      const rows = (data.anomalies || []).map((a) => a.detail);
      return bubble(
        "kael",
        rows.length ? `${data.count} anomalie(s) sur ${data.days} jours.` : "Rien à signaler.",
        rows.length ? list(rows) : null,
      );
    }
    if (tool === "get_platform_stats") {
      return bubble("kael", `${data.artists} atelier(s), ${data.published_rooms} salle(s) ouverte(s), `
        + `${data.works} œuvre(s), ${data.total_views} vue(s). Revenu récurrent : ${data.mrr_label}.`);
    }
    if (tool === "get_service_health") {
      const rows = Object.entries(data)
        .filter(([key]) => ["smtp", "imap", "stripe", "mistral"].includes(key))
        .map(([key, value]) => `${key} — ${value ? "branché" : "absent"}`);
      return bubble("kael", `Base ${data.database}.`, list(rows));
    }
    return bubble("kael", JSON.stringify(data).slice(0, 600));
  };

  const post = async (body) => {
    if (busy) return null;
    busy = true;
    const waiting = bubble("kael", "…");
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify(body),
      });
      const payload = await response.json();
      waiting.remove();
      return payload;
    } catch (error) {
      waiting.remove();
      bubble("kael", `Je n’ai pas pu joindre le serveur : ${error}`);
      return null;
    } finally {
      busy = false;
    }
  };

  panel.querySelectorAll(".kael-actions button").forEach((button) => {
    button.addEventListener("click", async () => {
      const tool = button.dataset.tool;
      bubble("me", button.textContent.trim());
      const params = button.dataset.params ? JSON.parse(button.dataset.params) : {};
      if (mode === "admin") {
        const payload = await post({ message: `Utilise l’outil ${tool} sur Artworks Digital et résume-moi le résultat.`, page: panel.dataset.page, conversation_id: conversationId });
        if (!payload) return;
        if (payload.ok) {
          conversationId = payload.conversation_id || conversationId;
          bubble("kael", payload.reply);
        } else {
          bubble("kael", payload.error);
        }
        return;
      }
      const payload = await post({ action: tool, params });
      if (!payload) return;
      if (payload.ok) tell(tool, payload.data);
      else bubble("kael", payload.error);
    });
  });

  const form = panel.querySelector(".kael-form");
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const field = form.querySelector("textarea");
    const message = field.value.trim();
    if (!message) return;
    bubble("me", message);
    field.value = "";
    const payload = await post({
      message,
      page: panel.dataset.page,
      work_id: panel.dataset.workId || null,
      conversation_id: conversationId,
    });
    if (!payload) return;
    if (payload.ok) {
      conversationId = payload.conversation_id || conversationId;
      bubble("kael", payload.reply);
    } else {
      bubble("kael", payload.error);
    }
  });
})();
