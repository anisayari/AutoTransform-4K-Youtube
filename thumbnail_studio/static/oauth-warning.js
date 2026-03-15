(() => {
  const modal = document.querySelector("[data-oauth-warning-modal]");
  if (!modal) return;

  const continueButton = modal.querySelector("[data-oauth-warning-continue]");
  const cancelButtons = modal.querySelectorAll("[data-oauth-warning-cancel]");
  let pendingHref = "";

  const closeModal = () => {
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    pendingHref = "";
  };

  const openModal = (href) => {
    pendingHref = href;
    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
    continueButton?.focus();
  };

  document.querySelectorAll("[data-oauth-warning-link]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const href = link.getAttribute("href");
      if (!href) return;
      openModal(href);
    });
  });

  continueButton?.addEventListener("click", () => {
    if (!pendingHref) return;
    window.location.href = pendingHref;
  });

  cancelButtons.forEach((button) => {
    button.addEventListener("click", closeModal);
  });

  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeModal();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal.classList.contains("is-open")) {
      closeModal();
    }
  });
})();
