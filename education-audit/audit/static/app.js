"use strict";
const all = document.getElementById("select-all");
if (all) all.addEventListener("change", () => {
  document.querySelectorAll('input[name="org_ids"]').forEach(input => { input.checked = all.checked; });
});
const printButton = document.getElementById("print-report");
if (printButton) printButton.addEventListener("click", () => {
  const evidence = [...document.querySelectorAll("details.evidence")];
  const previous = evidence.map(item => item.open);
  evidence.forEach(item => { item.open = true; });
  window.addEventListener("afterprint", () => evidence.forEach((item,i) => { item.open = previous[i]; }), { once:true });
  window.print();
});
const activeRun = document.querySelector("[data-poll-run]");
let polling = false;
if (activeRun) {
  const timer = setInterval(async () => {
    if (polling || document.hidden) return;
    polling = true;
    try {
      const response = await fetch(`/runs/${activeRun.dataset.pollRun}/progress`);
      if (!response.ok) return;
      const result = await response.json();
      const count = document.getElementById("pages-done");
      if (count) count.textContent = String(result.pages);
      if (!["queued","running"].includes(result.status)) { clearInterval(timer); location.reload(); }
    } catch (_) { /* Retry on the next interval after a temporary network failure. */ }
    finally { polling = false; }
  }, 3000);
}
if (document.querySelector("[data-poll-history]")) setInterval(() => { if (!document.hidden) location.reload(); }, 10000);
