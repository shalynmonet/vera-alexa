// Caregiver dashboard: daily summary, "almost there" nudges with copyable
// record links, and the family list. Standalone page, reached via
// /caregiver/<user_id> from the elder's own Progress screen.

const userId = window.location.pathname.split("/").filter(Boolean).pop();
const el = (id) => document.getElementById(id);

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

async function api(name, args = {}) {
  const res = await fetch(`/api/tool/${name}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...args, user_id: userId }),
  });
  if (!res.ok) throw new Error(`${name} failed`);
  return res.json();
}

function copyToClipboard(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    const original = btn.textContent;
    btn.textContent = "Copied!";
    setTimeout(() => { btn.textContent = original; }, 1500);
  }).catch(() => {
    btn.textContent = "Couldn't copy";
  });
}

async function loadSummary() {
  try {
    const summary = await api("get_daily_summary");
    el("dash-summary").textContent = summary.summary || "No activity yet today.";
  } catch {
    el("dash-summary").textContent = "Couldn't reach Vera's server.";
  }
}

async function loadEngagement() {
  let trends = [];
  try {
    trends = (await api("get_engagement_trends")).trends || [];
  } catch {
    el("dash-engagement").innerHTML = "";
    return;
  }
  el("dash-engagement").innerHTML = trends.length
    ? trends.map((t) => `<p class="say-text">${escapeHtml(t.label)}${t.response_note ? " " + escapeHtml(t.response_note) : ""}</p>`).join("")
    : `<p class="say-text">No games played this month yet.</p>`;
}

async function loadNudgesAndFamily() {
  let nudges = [];
  let family = [];
  try {
    const [nudgesRes, familyRes] = await Promise.all([api("upcoming_milestones"), api("list_family")]);
    nudges = nudgesRes.upcoming || [];
    family = familyRes.family || [];
  } catch {
    el("dash-nudges").innerHTML = `<p class="say-text">Couldn't reach Vera's server.</p>`;
    el("dash-family").innerHTML = "";
    return;
  }

  el("dash-nudges").innerHTML = nudges.length
    ? nudges.map((n) => `<div class="result-box nudge-card"><p>${escapeHtml(n.nudge)}</p><div class="action-row" data-milestone="${escapeHtml(n.id)}"></div></div>`).join("")
    : `<p class="say-text">Nothing close right now -- check back soon!</p>`;

  nudges.forEach((n) => {
    const row = document.querySelector(`[data-milestone="${n.id}"]`);
    if (!row) return;
    if (!family.length) {
      row.innerHTML = `<span class="say-text">Add a family member below to get a link.</span>`;
      return;
    }
    family.forEach((m) => {
      const btn = document.createElement("button");
      btn.className = "secondary-btn";
      btn.textContent = `Copy link for ${m.name}`;
      const link = `${window.location.origin}/cheer/${m.token}?milestone=${encodeURIComponent(n.id)}`;
      btn.addEventListener("click", () => copyToClipboard(link, btn));
      row.appendChild(btn);
    });
  });

  el("dash-family").innerHTML = family.length
    ? family.map((m) => `
      <div class="result-box family-card">
        <p><strong>${escapeHtml(m.name)}</strong> — ${escapeHtml(m.relationship)}${m.email ? ` — ${escapeHtml(m.email)}` : ""}</p>
        <div class="action-row">
          <button class="secondary-btn copy-general-btn" data-token="${escapeHtml(m.token)}">Copy Link</button>
          <button class="secondary-btn remove-family-btn" data-id="${escapeHtml(m.id)}">Remove</button>
        </div>
      </div>
    `).join("")
    : `<p class="say-text">No family members yet -- add one below.</p>`;

  document.querySelectorAll(".copy-general-btn").forEach((btn) => {
    btn.addEventListener("click", () => copyToClipboard(`${window.location.origin}/cheer/${btn.dataset.token}`, btn));
  });
  document.querySelectorAll(".remove-family-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!window.confirm("Remove this family member? Their link will stop working.")) return;
      await api("remove_family_member", { family_id: btn.dataset.id });
      loadNudgesAndFamily();
    });
  });
}

el("fam-add-btn").addEventListener("click", async () => {
  const name = el("fam-name").value.trim();
  const relationship = el("fam-relationship").value.trim();
  const email = el("fam-email").value.trim();
  if (!name || !relationship) return;
  await api("add_family_member", { name, relationship, email: email || undefined });
  el("fam-name").value = "";
  el("fam-relationship").value = "";
  el("fam-email").value = "";
  loadNudgesAndFamily();
});

(async function initDashboard() {
  try {
    const profile = await api("get_profile");
    el("dash-title").textContent = `${profile.name}'s Caregiver Dashboard`;
  } catch {
    el("dash-title").textContent = "Caregiver Dashboard";
  }
  await Promise.all([loadSummary(), loadEngagement(), loadNudgesAndFamily()]);
})();
