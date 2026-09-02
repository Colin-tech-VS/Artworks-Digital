document.documentElement.classList.add("js");

/* Le seuil de repli est défini une seule fois, ici et dans app.css : deux
   valeurs qui se répondent finissent toujours par diverger. */
const COMPACT = window.matchMedia("(max-width: 960px)");
const SHELL_COMPACT = window.matchMedia("(max-width: 860px)");

// Ouvre et referme un panneau replié (barre du site, tiroir de l’atelier).
function foldablePanel(button, panel, query, labels) {
  if (!button || !panel) return;

  const setState = (open) => {
    panel.classList.toggle("is-open", open);
    button.setAttribute("aria-expanded", String(open));
    if (labels) button.setAttribute("aria-label", open ? labels.close : labels.open);
  };
  const close = () => setState(false);
  const isOpen = () => panel.classList.contains("is-open");

  button.addEventListener("click", () => {
    const open = !isOpen();
    setState(open);
    if (open) panel.querySelector("a, button")?.focus();
  });

  // Un lien suivi referme le panneau : la page d’arrivée ne doit pas
  // s’ouvrir derrière un menu resté déplié.
  panel.addEventListener("click", (event) => {
    if (event.target.closest("a")) close();
  });

  // Un clic à côté referme aussi — sur un téléphone, c’est le geste attendu.
  document.addEventListener("click", (event) => {
    if (!isOpen()) return;
    if (panel.contains(event.target) || button.contains(event.target)) return;
    close();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !isOpen()) return;
    close();
    button.focus();
  });

  // Rotation de l’écran ou fenêtre élargie : le panneau replié n’a plus
  // lieu d’être, et la barre reprend sa forme longue.
  const onChange = (event) => {
    if (!event.matches) close();
  };
  if (query.addEventListener) query.addEventListener("change", onChange);
  else query.addListener(onChange);

  close();
}

// Menu du site — la barre se replie sous 960px, ce bouton la rouvre.
foldablePanel(
  document.querySelector(".nav-toggle"),
  document.getElementById("site-nav"),
  COMPACT,
  { open: "Ouvrir le menu", close: "Fermer le menu" }
);

// Barre latérale de l’atelier et de l’admin : même repli sur petit écran.
foldablePanel(
  document.querySelector(".shell-toggle"),
  document.querySelector(".atelier-side, .admin-side"),
  SHELL_COMPACT,
  null
);

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

(function () {
  const LIFE = 4200;
  const FADE = 400;

  function host() {
    let tray = document.querySelector(".flashes");
    if (tray) return tray;
    tray = document.createElement("ul");
    tray.className = "flashes";
    tray.setAttribute("aria-live", "polite");
    document.body.appendChild(tray);
    return tray;
  }

  function collect() {
    document.querySelectorAll(".flash").forEach((el) => {
      if (el.closest(".flashes")) return;
      const item = document.createElement("li");
      item.className = el.className;
      item.setAttribute("role", el.classList.contains("flash-error") ? "alert" : "status");
      item.textContent = el.textContent;
      el.remove();
      host().appendChild(item);
    });
  }

  function arm(el) {
    let timer;
    const hide = () => {
      el.classList.add("is-out");
      window.setTimeout(() => {
        const tray = el.closest(".flashes");
        el.remove();
        if (tray && !tray.querySelector(".flash")) tray.remove();
      }, FADE);
    };
    const start = () => {
      timer = window.setTimeout(hide, LIFE);
    };
    el.addEventListener("mouseenter", () => window.clearTimeout(timer));
    el.addEventListener("mouseleave", start);
    start();
  }

  collect();
  document.querySelectorAll(".flash").forEach(arm);
})();

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

  /* L'attente a sa forme : trois points. Une bulle vide se lirait comme
     une réponse que K.A.E.L. n'a pas donnée. */
  const waitingBubble = () => {
    const line = document.createElement("div");
    line.className = "kael-line kael-kael kael-typing";
    const body = document.createElement("p");
    body.append(...[0, 1, 2].map(() => document.createElement("i")));
    line.appendChild(body);
    line.setAttribute("aria-label", "K.A.E.L. répond…");
    stream.appendChild(line);
    stream.scrollTop = stream.scrollHeight;
    return line;
  };

  const form = panel.querySelector(".kael-form");
  const field = form?.querySelector("textarea");
  const send = form?.querySelector(".kael-send");
  const tools = panel.querySelectorAll(".kael-actions button");

  /* Tant qu'une réponse est en route, rien d'autre ne part. Le bouton
     d'envoi obéit en plus au champ : vide, il reste éteint. */
  const setBusy = (value) => {
    busy = value;
    tools.forEach((tool) => { tool.disabled = value; });
    if (send) send.disabled = value || !field.value.trim();
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
    setBusy(true);
    const waiting = waitingBubble();
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
      setBusy(false);
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

  /* Le champ grandit avec le texte, jusqu'à la limite posée en CSS : on
     relit ce qu'on écrit sans faire défiler deux lignes à la fois. */
  const fitField = () => {
    field.style.height = "auto";
    field.style.height = `${field.scrollHeight}px`;
  };
  if (field) {
    fitField();
    field.addEventListener("input", () => { fitField(); setBusy(busy); });
    // Entrée envoie, Maj+Entrée passe à la ligne — l'usage d'une messagerie.
    field.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        form.requestSubmit();
      }
    });
    setBusy(false);
  }

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = field.value.trim();
    if (!message || busy) return;
    bubble("me", message);
    field.value = "";
    fitField();
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

document.querySelectorAll("form[data-busy]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (form.classList.contains("is-busy")) {
      event.preventDefault();
      return;
    }
    form.classList.add("is-busy");
    const submitter = event.submitter;
    if (submitter && submitter.name) {
      const carry = document.createElement("input");
      carry.type = "hidden";
      carry.name = submitter.name;
      carry.value = submitter.value;
      form.appendChild(carry);
    }
    const label = (submitter && submitter.dataset.busy) || form.dataset.busy || "Chargement…";
    form.querySelectorAll("button[type=submit], input[type=submit]").forEach((el) => {
      el.disabled = true;
    });
    const veil = document.createElement("div");
    veil.className = "busy-veil";
    veil.setAttribute("role", "status");
    veil.innerHTML = `<div class="busy-card"><span class="busy-spin" aria-hidden="true"></span><p></p></div>`;
    veil.querySelector("p").textContent = label;
    document.body.appendChild(veil);
    document.body.classList.add("is-busy");
  });
});

(function () {
  const caption = document.getElementById("preview-caption");
  const image = document.getElementById("preview-image");
  const blank = document.getElementById("preview-blank");
  if (!caption || !image) return;
  const message = document.getElementById("message");
  const imageUrl = document.getElementById("image_url");
  const imageName = document.getElementById("image_name");

  const showImage = (src) => {
    if (src) {
      image.src = src;
      image.hidden = false;
      if (blank) blank.hidden = true;
    } else {
      image.removeAttribute("src");
      image.hidden = true;
      if (blank) blank.hidden = false;
    }
  };

  const refresh = () => {
    caption.textContent = (message?.value || "").trim() || "La légende se compose ici, comme sur le réseau.";
    const name = (imageName?.value || "").trim();
    const url = (imageUrl?.value || "").trim();
    showImage(name ? `/media/${encodeURIComponent(name)}` : url);
  };

  message?.addEventListener("input", refresh);
  imageUrl?.addEventListener("input", refresh);
})();

(function () {
  const root = document.querySelector("[data-live]");
  if (!root) return;
  const url = root.getAttribute("data-live");
  const activeEl = root.querySelector("[data-live-active]");
  const viewsEl = root.querySelector("[data-live-views]");
  const lamp = root.querySelector("[data-live-lamp]");
  const feed = root.querySelector("[data-live-feed]");

  const ago = (iso) => {
    if (!iso) return "";
    const seconds = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
    if (Number.isNaN(seconds) || seconds < 8) return "à l’instant";
    if (seconds < 60) return `il y a ${seconds} s`;
    if (seconds < 3600) return `il y a ${Math.round(seconds / 60)} min`;
    return `il y a ${Math.round(seconds / 60 / 60)} h`;
  };

  const stamp = () => {
    feed?.querySelectorAll("[data-at]").forEach((el) => {
      el.textContent = ago(el.getAttribute("data-at"));
    });
  };

  const paint = (data) => {
    if (activeEl) activeEl.textContent = String(data.active ?? 0);
    if (viewsEl) viewsEl.textContent = String(data.views ?? 0);
    lamp?.classList.toggle("is-up", Boolean(data.active));
    if (!feed) return;
    const hits = data.feed || [];
    feed.replaceChildren();
    if (!hits.length) {
      const empty = document.createElement("li");
      empty.className = "is-empty";
      empty.textContent = "Personne sur le site pour l’instant.";
      feed.appendChild(empty);
      return;
    }
    hits.forEach((hit) => {
      const item = document.createElement("li");
      const name = document.createElement("strong");
      name.textContent = hit.place || "Lieu inconnu";
      const meta = document.createElement("span");
      meta.textContent = [hit.channel, hit.device, hit.title || hit.path].filter(Boolean).join(" · ");
      const when = document.createElement("em");
      when.setAttribute("data-at", hit.at || "");
      when.textContent = ago(hit.at);
      item.append(name, meta, when);
      feed.appendChild(item);
    });
  };

  const tick = async () => {
    if (document.hidden) return;
    try {
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      if (!response.ok) return;
      paint(await response.json());
    } catch (_) {
      stamp();
    }
  };

  stamp();
  setInterval(stamp, 8000);
  setInterval(tick, 10000);
})();
