document.addEventListener("click", (event) => {
  const navButton = event.target.closest?.(".history-calendar-nav");
  if (!navButton) return;

  // The calendar rebuilds itself during the nav click. Re-open it after the
  // existing document-level outside-click handler runs so the newly-rendered
  // month remains visible.
  const picker = navButton.closest(".history-date-picker");
  if (!picker) return;

  window.setTimeout(() => {
    const popover = picker.querySelector(".history-calendar");
    const control = picker.querySelector(".history-control-button");
    if (!popover || !control) return;
    popover.classList.add("open");
    control.setAttribute("aria-expanded", "true");
  }, 0);
}, true);
