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
