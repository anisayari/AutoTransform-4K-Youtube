const bootstrap = window.APP_BOOTSTRAP || {};

const state = {
  videos: [],
  channel: null,
  busyVideoId: null,
  selectedVideoIds: new Set(),
  batchRunning: false,
};

const $ = (sel) => document.querySelector(sel);
const videosGrid = $("#videosGrid");
const promptInput = $("#promptInput");
const refreshButton = $("#refreshButton");
const disconnectButton = $("#disconnectButton");
const channelTitle = $("#channelTitle");
const mainSubtitle = $("#mainSubtitle");
const videoCount = $("#videoCount");
const transformBtn = $("#transformSelectionButton");
const selectVisibleBtn = $("#selectVisibleButton");
const clearSelectionBtn = $("#clearSelectionButton");
const selectionCount = $("#selectionCount");
const batchProgress = $("#batchProgress");
const batchProgressFill = $("#batchProgressFill");
const batchProgressLabel = $("#batchProgressLabel");
const toastContainer = $("#toastContainer");

function showToast(message, type = "info", duration = 4000) {
  const icons = {
    success: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
    error: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    info: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
  };

  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.innerHTML = `
    <span class="toast-icon">${icons[type] || icons.info}</span>
    <span class="toast-msg">${escapeHtml(message)}</span>
    <button class="toast-close" aria-label="Close">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
    </button>
  `;

  const remove = () => {
    el.classList.add("toast-out");
    el.addEventListener("animationend", () => el.remove());
  };

  el.querySelector(".toast-close").addEventListener("click", remove);
  toastContainer.appendChild(el);

  if (duration > 0) setTimeout(remove, duration);
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(value) {
  if (!value) return "Unknown date";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function formatVideoCount(count) {
  return `${count} video${count === 1 ? "" : "s"}`;
}

function updateSelection() {
  const count = state.selectedVideoIds.size;
  selectionCount.textContent = count;
  transformBtn.disabled = !count || state.batchRunning;

  document.querySelectorAll(".video-card").forEach((card) => {
    const id = card.dataset.videoId;
    card.classList.toggle("selected", state.selectedVideoIds.has(id));
  });
}

function renderVideos() {
  const channelName = state.channel?.title || "Connection required";
  channelTitle.textContent = channelName;

  if (state.channel) {
    mainSubtitle.textContent = "Pick the videos you want to upgrade, then run the 4K transform.";
  }

  videoCount.textContent = formatVideoCount(state.videos.length);

  if (!bootstrap.connected) {
    videosGrid.innerHTML = `
      <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2"/><path d="m10 8 6 4-6 4V8z"/></svg>
        <div class="empty-state-title">YouTube is not connected</div>
        <div class="empty-state-desc">Connect your YouTube account from the top bar to load your videos.</div>
      </div>
    `;
    return;
  }

  if (!state.videos.length) {
    videosGrid.innerHTML = `
      <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
        <div class="empty-state-title">No videos yet</div>
        <div class="empty-state-desc">Click "Refresh" to load your latest uploads.</div>
      </div>
    `;
    return;
  }

  videosGrid.innerHTML = state.videos
    .map((video) => {
      const busy = state.batchRunning || state.busyVideoId === video.id;
      const checked = state.selectedVideoIds.has(video.id) ? "checked" : "";

      let resultHtml = "";
      if (video.latestResult) {
        resultHtml = `
          <div class="card-result">
            <div class="card-result-label">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 4 12 14.01 9 11.01"/></svg>
              Transformed with ${escapeHtml(video.latestResult.model)}
            </div>
            <img src="${escapeHtml(video.latestResult.uploadReadyUrl)}" alt="Transformed thumbnail">
            <div class="card-result-meta">Source: ${escapeHtml(video.latestResult.sourceUsed)}</div>
          </div>
        `;
      }

      let statusHtml = "";
      if (busy) {
        statusHtml = '<div class="card-status processing"><span class="spinner spinner-sm"></span> Processing...</div>';
      }

      return `
        <article class="video-card ${checked ? "selected" : ""}" data-video-id="${escapeHtml(video.id)}">
          <div class="card-thumb">
            <img src="${escapeHtml(video.current_thumbnail_url || "")}" alt="${escapeHtml(video.title)}" loading="lazy">
            <label class="card-checkbox">
              <input type="checkbox" data-select-id="${escapeHtml(video.id)}" ${checked} ${state.batchRunning ? "disabled" : ""}>
            </label>
            <span class="card-privacy">${escapeHtml(video.privacy_status)}</span>
          </div>
          <div class="card-body">
            <h3 class="card-title">${escapeHtml(video.title)}</h3>
            <div class="card-date">${escapeHtml(formatDate(video.published_at))}</div>
            <div class="card-footer">
              <button class="btn btn-primary btn-sm flex-1" type="button" data-video-id="${escapeHtml(video.id)}" ${busy ? "disabled" : ""}>
                ${busy ? '<span class="spinner spinner-sm"></span>' : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>'}
                ${busy ? "Working..." : "Transform"}
              </button>
              <a class="btn btn-ghost btn-sm" href="${escapeHtml(video.watch_url)}" target="_blank" rel="noreferrer">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
              </a>
            </div>
          </div>
          ${statusHtml}
          ${resultHtml}
        </article>
      `;
    })
    .join("");

  updateSelection();
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok || !data.ok) {
    throw new Error(data.message || "Request failed.");
  }
  return data;
}

async function loadVideos() {
  if (!bootstrap.connected) {
    renderVideos();
    return;
  }

  showToast("Loading videos...", "info", 2000);
  refreshButton.disabled = true;

  try {
    const payload = await fetchJson("/api/videos");
    state.channel = payload.channel;
    state.videos = payload.videos;
    const availableIds = new Set(state.videos.map((video) => video.id));
    state.selectedVideoIds = new Set(
      [...state.selectedVideoIds].filter((id) => availableIds.has(id)),
    );
    renderVideos();
    showToast(`${formatVideoCount(state.videos.length)} loaded.`, "success");
  } catch (error) {
    state.videos = [];
    state.selectedVideoIds = new Set();
    renderVideos();
    showToast(error.message, "error", 6000);
  } finally {
    refreshButton.disabled = false;
  }
}

async function transformVideo(videoId) {
  if (!bootstrap.geminiConfigured) {
    showToast("Add GEMINI_API_KEY in Setup before you start a transform.", "error");
    return;
  }

  const video = state.videos.find((item) => item.id === videoId);
  if (!video) return;

  state.busyVideoId = videoId;
  renderVideos();
  showToast(`Transforming "${video.title}"...`, "info", 0);

  try {
    const payload = await fetchJson(`/api/videos/${videoId}/transform`, {
      method: "POST",
      body: JSON.stringify({
        prompt: promptInput.value,
        officialThumbnailUrl: video.official_thumbnail_url,
        pytubeThumbnailUrl: video.pytube_thumbnail_url,
      }),
    });

    video.current_thumbnail_url = payload.uploadReadyUrl;
    video.latestResult = payload;
    showToast("4K thumbnail uploaded to YouTube.", "success");
  } catch (error) {
    showToast(error.message, "error", 6000);
  } finally {
    state.busyVideoId = null;
    renderVideos();
  }
}

async function transformSelection() {
  const selected = state.videos.filter((video) => state.selectedVideoIds.has(video.id));
  if (!selected.length) {
    showToast("Select at least one video.", "error");
    return;
  }
  if (!bootstrap.geminiConfigured) {
    showToast("Add GEMINI_API_KEY in Setup before you start a batch.", "error");
    return;
  }

  state.batchRunning = true;
  batchProgress.style.display = "block";
  batchProgressFill.style.width = "0%";
  batchProgressLabel.textContent = `0 / ${selected.length}`;
  renderVideos();
  showToast(`Processing ${formatVideoCount(selected.length)}...`, "info", 0);

  try {
    const payload = await fetchJson("/api/videos/batch-transform", {
      method: "POST",
      body: JSON.stringify({
        prompt: promptInput.value,
        videos: selected.map((video) => ({
          id: video.id,
          officialThumbnailUrl: video.official_thumbnail_url,
          pytubeThumbnailUrl: video.pytube_thumbnail_url,
        })),
      }),
    });

    const processedById = new Map(payload.processed.map((result) => [result.videoId, result]));
    state.videos = state.videos.map((video) => {
      const result = processedById.get(video.id);
      if (!result) return video;
      return {
        ...video,
        current_thumbnail_url: result.uploadReadyUrl,
        latestResult: result,
      };
    });

    batchProgressFill.style.width = "100%";
    batchProgressLabel.textContent = `${payload.successCount} / ${selected.length}`;

    if (payload.successCount) state.selectedVideoIds = new Set();

    if (payload.hasFailures) {
      const failedIds = payload.failed.map((item) => item.videoId).filter(Boolean).join(", ");
      showToast(`${payload.message}${failedIds ? ` Failed IDs: ${failedIds}` : ""}`, "error", 8000);
    } else {
      showToast(payload.message, "success");
    }
  } catch (error) {
    showToast(error.message, "error", 6000);
  } finally {
    state.batchRunning = false;
    renderVideos();
    setTimeout(() => {
      batchProgress.style.display = "none";
    }, 2000);
  }
}

videosGrid.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-video-id]:not(.video-card)");
  if (!button) return;
  await transformVideo(button.dataset.videoId);
});

videosGrid.addEventListener("change", (event) => {
  const checkbox = event.target.closest("[data-select-id]");
  if (!checkbox) return;

  if (checkbox.checked) {
    state.selectedVideoIds.add(checkbox.dataset.selectId);
  } else {
    state.selectedVideoIds.delete(checkbox.dataset.selectId);
  }
  updateSelection();
});

refreshButton.addEventListener("click", () => loadVideos());
transformBtn.addEventListener("click", () => transformSelection());

selectVisibleBtn.addEventListener("click", () => {
  state.selectedVideoIds = new Set(state.videos.map((video) => video.id));
  renderVideos();
});

clearSelectionBtn.addEventListener("click", () => {
  state.selectedVideoIds = new Set();
  renderVideos();
});

if (disconnectButton) {
  disconnectButton.addEventListener("click", async () => {
    try {
      await fetchJson("/auth/google/disconnect", { method: "POST", body: "{}" });
      bootstrap.connected = false;
      state.channel = null;
      state.videos = [];
      state.selectedVideoIds = new Set();
      renderVideos();
      showToast("YouTube session cleared.", "success");
    } catch (error) {
      showToast(error.message, "error");
    }
  });
}

renderVideos();
void loadVideos();
