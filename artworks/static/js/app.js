document.documentElement.classList.add("js");

const flashes = document.querySelectorAll(".flash");
flashes.forEach((el) => {
  window.setTimeout(() => {
    el.style.opacity = "0";
    el.style.transform = "translateY(-8px)";
    window.setTimeout(() => el.remove(), 400);
  }, 4200);
});
