document.documentElement.classList.add("js");

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
