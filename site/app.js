"use strict";

const $ = (sel) => document.querySelector(sel);

const els = {
  search: $("#search"),
  venue: $("#venue"),
  from: $("#from"),
  to: $("#to"),
  reset: $("#reset"),
  ical: $("#ical"),
  list: $("#shows"),
  count: $("#count"),
  empty: $("#empty"),
  meta: $("#meta"),
  generated: $("#generated"),
  errors: $("#errors"),
};

let DATA = { shows: [], venues: [], generated_at: null, errors: [] };

const fmtDate = (() => {
  const fmt = new Intl.DateTimeFormat("nb-NO", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
  return (iso) => {
    if (!iso) return "";
    try {
      return fmt.format(new Date(iso));
    } catch {
      return iso;
    }
  };
})();

const fmtTime = (iso) => {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("nb-NO", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
};

const fmtRange = (s) => {
  const start = fmtDate(s.start);
  const t = fmtTime(s.start);
  const hasTime = t && t !== "00:00";
  if (s.end && s.end !== s.start) {
    const sd = (s.start || "").slice(0, 10);
    const ed = s.end.slice(0, 10);
    if (sd === ed) {
      return hasTime ? `${start} kl. ${t}` : start;
    }
    return `${start} – ${fmtDate(s.end)}`;
  }
  return hasTime ? `${start} kl. ${t}` : start;
};

function escapeHTML(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function venueDisplay(slug) {
  const v = DATA.venues.find((v) => v.slug === slug);
  return v ? v.name : slug;
}

function render() {
  const q = els.search.value.trim().toLowerCase();
  const venue = els.venue.value;
  const from = els.from.value ? new Date(els.from.value) : null;
  const to = els.to.value ? new Date(els.to.value + "T23:59:59") : null;

  // Implicit cutoff: hide shows that have already played (before today's midnight)
  // unless the user explicitly sets an earlier "from" date.
  const todayStart = new Date();
  todayStart.setHours(0, 0, 0, 0);
  const cutoff = from && from < todayStart ? from : todayStart;

  const filtered = DATA.shows.filter((s) => {
    if (venue && s.venue_slug !== venue) return false;
    const start = new Date(s.start);
    const end = s.end ? new Date(s.end) : start;
    if (end < cutoff) return false;
    if (from && end < from) return false;
    if (to && start > to) return false;
    if (q) {
      const blob = `${s.title} ${s.description || ""} ${s.venue} ${s.stage || ""} ${s.genre || ""}`.toLowerCase();
      if (!blob.includes(q)) return false;
    }
    return true;
  });

  els.count.textContent = `${filtered.length} ${filtered.length === 1 ? "forestilling" : "forestillinger"}`;
  els.empty.classList.toggle("hidden", filtered.length > 0);
  els.list.innerHTML = filtered.map(renderShow).join("");
  els.list.dataset.filteredIds = filtered.map((s) => s.id).join(",");
}

function renderShow(s) {
  const img = s.image_url
    ? `<div class="show__image" style="background-image:url('${escapeHTML(s.image_url)}')"></div>`
    : `<div class="show__image show__image--placeholder">🎭</div>`;
  const ticket = s.ticket_url
    ? `<a class="primary" href="${escapeHTML(s.ticket_url)}" target="_blank" rel="noopener">Kjøp billett ↗</a>`
    : "";
  const detail = s.detail_url && s.detail_url !== s.ticket_url
    ? `<a class="secondary" href="${escapeHTML(s.detail_url)}" target="_blank" rel="noopener">Les mer</a>`
    : "";
  const stage = s.stage ? `<span class="show__stage">${escapeHTML(s.stage)}</span>` : "";
  return `
    <li class="show">
      ${img}
      <div class="show__body">
        <div class="show__venue">${escapeHTML(s.venue)}</div>
        <h2 class="show__title">${escapeHTML(s.title)}</h2>
        <div class="show__meta">
          ${stage}
          <span class="show__when">${escapeHTML(fmtRange(s))}</span>
        </div>
        ${s.description ? `<p class="show__desc">${escapeHTML(s.description)}</p>` : ""}
        <div class="show__actions">${ticket}${detail}</div>
      </div>
    </li>`;
}

function populateVenues() {
  const seen = new Map();
  for (const s of DATA.shows) seen.set(s.venue_slug, s.venue);
  for (const v of DATA.venues) if (!seen.has(v.slug) && v.show_count > 0) seen.set(v.slug, v.name);
  const opts = ['<option value="">Alle teatre</option>'];
  for (const [slug, name] of [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1], "nb"))) {
    opts.push(`<option value="${escapeHTML(slug)}">${escapeHTML(name)}</option>`);
  }
  els.venue.innerHTML = opts.join("");
}

function buildIcs() {
  const ids = (els.list.dataset.filteredIds || "").split(",").filter(Boolean);
  const shows = DATA.shows.filter((s) => ids.includes(s.id));
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//oslo-teater//NONSGML v1//NO", "CALSCALE:GREGORIAN"];
  for (const s of shows) {
    const dtStart = toIcsDate(s.start);
    const dtEnd = toIcsDate(s.end || addHours(s.start, 2));
    lines.push("BEGIN:VEVENT");
    lines.push(`UID:${s.id}@oslo-teater`);
    lines.push(`DTSTAMP:${toIcsDate(new Date().toISOString())}`);
    lines.push(`DTSTART:${dtStart}`);
    lines.push(`DTEND:${dtEnd}`);
    lines.push(`SUMMARY:${icsEscape(s.title)}`);
    lines.push(`LOCATION:${icsEscape(s.venue + (s.stage ? " — " + s.stage : ""))}`);
    if (s.description) lines.push(`DESCRIPTION:${icsEscape(s.description)}`);
    if (s.ticket_url) lines.push(`URL:${s.ticket_url}`);
    lines.push("END:VEVENT");
  }
  lines.push("END:VCALENDAR");
  return lines.join("\r\n");
}

function icsEscape(s) {
  return String(s).replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
}
function toIcsDate(iso) {
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return (
    d.getUTCFullYear().toString() +
    pad(d.getUTCMonth() + 1) +
    pad(d.getUTCDate()) + "T" +
    pad(d.getUTCHours()) +
    pad(d.getUTCMinutes()) +
    pad(d.getUTCSeconds()) + "Z"
  );
}
function addHours(iso, h) {
  const d = new Date(iso);
  d.setHours(d.getHours() + h);
  return d.toISOString();
}

function downloadIcs() {
  const blob = new Blob([buildIcs()], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "oslo-teater.ics";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function attach() {
  els.search.addEventListener("input", render);
  els.venue.addEventListener("change", render);
  els.from.addEventListener("change", render);
  els.to.addEventListener("change", render);
  els.reset.addEventListener("click", () => {
    els.search.value = "";
    els.venue.value = "";
    els.from.value = "";
    els.to.value = "";
    render();
  });
  els.ical.addEventListener("click", downloadIcs);
}

async function init() {
  try {
    const r = await fetch("shows.json", { cache: "no-cache" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    DATA = await r.json();
  } catch (e) {
    els.list.innerHTML = "";
    els.empty.classList.remove("hidden");
    els.empty.textContent = "Klarte ikke laste data: " + e.message;
    return;
  }
  els.generated.textContent = DATA.generated_at ? fmtDate(DATA.generated_at) : "";
  els.meta.textContent = `${DATA.show_count} forestillinger fra ${DATA.venues.filter((v) => v.show_count > 0).length} teatre`;
  if (DATA.errors && DATA.errors.length) {
    els.errors.textContent = `${DATA.errors.length} scraper(e) feilet — sjekk loggen.`;
  }
  populateVenues();
  attach();
  render();
}

init();
