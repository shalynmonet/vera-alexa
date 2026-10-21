// Caregiver dashboard: daily summary, engagement trends, "almost there"
// nudges with copyable record links, the family list (with a one-tap SMS
// invite), and cheer management. Standalone page, reached via
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

function inviteMessage(member, recipientFirstName) {
  const called = member.nickname || recipientFirstName;
  const familyFirstName = member.name.split(" ")[0];
  const link = `${window.location.origin}/cheer/${member.token}`;
  // Only prefix with a nickname when one was actually given -- otherwise
  // "I added you to Rose Rose's Vera app" duplicates the name.
  const whoFor = member.nickname ? `${called} ${recipientFirstName}` : recipientFirstName;
  return {
    link,
    text: `Hi ${familyFirstName}! I added you to ${whoFor}'s Vera app \u{1F49C} Vera is her wellness companion, and you can send her short voice or video cheers that play when she hits milestones. Tap your link anytime to send one: ${link}`,
  };
}

let recipientFirstName = "";

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
      btn.textContent = `Copy link for ${m.nickname || m.name}`;
      const link = `${window.location.origin}/cheer/${m.token}?milestone=${encodeURIComponent(n.id)}`;
      btn.addEventListener("click", () => copyToClipboard(link, btn));
      row.appendChild(btn);
    });
  });

  el("dash-family").innerHTML = family.length
    ? family.map((m) => `
      <div class="result-box family-card">
        <p><strong>${escapeHtml(m.name)}</strong>${m.relationship ? ` — ${escapeHtml(m.relationship)}` : " — setup pending"}
          ${m.unplayed_count ? ` — ${m.unplayed_count} cheer${m.unplayed_count === 1 ? "" : "s"} waiting to play` : ""}</p>
        <div class="action-row">
          <a class="secondary-btn" href="sms:${escapeHtml(m.phone)}?body=${encodeURIComponent(inviteMessage(m, recipientFirstName).text)}">💬 Text Invite</a>
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

async function loadCheers() {
  let cheers = [];
  try {
    cheers = (await api("list_cheers")).cheers || [];
  } catch {
    el("dash-cheers").innerHTML = `<p class="say-text">Couldn't reach Vera's server.</p>`;
    return;
  }
  if (!cheers.length) {
    el("dash-cheers").innerHTML = `<p class="say-text">No cheers recorded yet.</p>`;
    return;
  }
  const statusLabel = { locked: "🔒 Locked", unlocked: "💜 Ready to play", played: "✔ Played" };
  el("dash-cheers").innerHTML = cheers
    .sort((a, b) => (a.recorded_on < b.recorded_on ? 1 : -1))
    .map((c) => `
      <div class="result-box nudge-card">
        <p><strong>${escapeHtml(c.family_name)}</strong> — ${escapeHtml(statusLabel[c.status] || c.status)}
          — ${escapeHtml(c.cheer_type)}${c.target ? ` (${escapeHtml(c.target)})` : ""} — ${escapeHtml(c.recorded_on)}</p>
        <div class="action-row">
          <button class="secondary-btn delete-cheer-btn" data-id="${escapeHtml(c.id)}">Delete</button>
        </div>
      </div>
    `).join("");
  document.querySelectorAll(".delete-cheer-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!window.confirm("Delete this cheer? This can't be undone.")) return;
      await api("delete_cheer", { cheer_id: btn.dataset.id });
      loadCheers();
      loadNudgesAndFamily();
    });
  });
}

el("fam-add-btn").addEventListener("click", async () => {
  const name = el("fam-name").value.trim();
  const phone = el("fam-phone").value.trim();
  const nickname = el("fam-nickname").value.trim();
  if (!name || !phone) return;
  const { member } = await api("add_family_member", { name, phone, nickname: nickname || undefined });
  el("fam-name").value = "";
  el("fam-phone").value = "";
  el("fam-nickname").value = "";

  const invite = inviteMessage(member, recipientFirstName);
  el("fam-invite-row").classList.remove("hidden");
  el("fam-invite-intro").textContent = `${member.name} is ready! Send them their invite:`;
  el("fam-invite-sms").href = `sms:${phone}?body=${encodeURIComponent(invite.text)}`;
  el("fam-invite-copy").onclick = () => copyToClipboard(invite.link, el("fam-invite-copy"));

  loadNudgesAndFamily();
});

(async function initDashboard() {
  try {
    const profile = await api("get_profile");
    recipientFirstName = profile.name.split(" ")[0];
    el("dash-title").textContent = `${profile.name}'s Caregiver Dashboard`;
  } catch {
    el("dash-title").textContent = "Caregiver Dashboard";
  }
  await Promise.all([loadSummary(), loadEngagement(), loadNudgesAndFamily(), loadCheers()]);
  // Running-low email nudges: this app has no background job runner, so
  // this is the opportunistic trigger point -- best-effort, never blocks
  // the rest of the dashboard.
  fetch("/api/family/check_alerts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId }),
  }).catch(() => {});
})();
