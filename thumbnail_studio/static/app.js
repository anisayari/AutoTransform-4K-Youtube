const bootstrap = window.APP_BOOTSTRAP || {};
const VIDEO_CACHE_KEY = "thumbnailStudio.videoCache.v1";
const SKELETON_CARD_COUNT = 6;
const JOB_POLL_INTERVAL_MS = 1200;
const GEMINI_COST_PER_IMAGE_USD = Number(bootstrap.geminiCostPerImageUsd || 0);
const DEFAULT_PROMPT = String(bootstrap.defaultPrompt || "").trim();
const LEGACY_DEFAULT_PROMPTS = new Set([
  "Transform this YouTube thumbnail into a sharper, premium, high-click-through version. Preserve the main composition, keep text readable, improve contrast, color grading, subject separation, and face detail. Keep it clean, cinematic, and optimized for a 16:9 YouTube thumbnail. No watermarks, no borders, no layout changes that break the original idea.",
  "Take the provided YouTube thumbnail exactly as it is and regenerate the same image in clean 4K. Preserve the original composition, text, layout, colors, subjects, framing, and overall design. Do not redesign, restyle, add, remove, or move elements. Only improve resolution, sharpness, and fidelity for a 16:9 4K YouTube thumbnail. Return only the generated image.",
]);

const state = {
  videos: [],
  channel: null,
  selectedVideoIds: new Set(),
  batchRunning: false,
  loadingVideos: false,
  activeJobId: null,
  activeJobVideoIds: new Set(),
  activeJobPollTimer: null,
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
const costPerImage = $("#costPerImage");
const selectionCost = $("#selectionCost");
const toastContainer = $("#toastContainer");
const logModal = $("[data-log-modal]");
const logModalTitle = $("#jobLogTitle");
const logModalMeta = $("#jobLogMeta");
const logModalBody = $("#jobLogBody");
const logModalCloseButtons = document.querySelectorAll("[data-log-close]");

if (promptInput) {
  const currentPrompt = promptInput.value.trim();
  if (!currentPrompt || LEGACY_DEFAULT_PROMPTS.has(currentPrompt)) {
    promptInput.value = DEFAULT_PROMPT;
  }
}

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
    el.addEventListener("animationend", () => el.remove(), { once: true });
  };

  el.querySelector(".toast-close").addEventListener("click", remove);
  toastContainer.appendChild(el);

  if (duration > 0) {
    window.setTimeout(remove, duration);
  }
}

function openLogModal(title, meta, body) {
  if (!logModal || !logModalTitle || !logModalMeta || !logModalBody) return;

  logModalTitle.textContent = title || "Transform log";
  logModalMeta.textContent = meta || "";
  logModalBody.textContent = body || "No log available.";
  logModal.classList.add("is-open");
  logModal.setAttribute("aria-hidden", "false");
}

function closeLogModal() {
  if (!logModal) return;
  logModal.classList.remove("is-open");
  logModal.setAttribute("aria-hidden", "true");
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
    : date.toLocaleDateString(undefined, {
        day: "numeric",
        month: "short",
        year: "numeric",
      });
}

function formatVideoCount(count) {
  return `${count} video${count === 1 ? "" : "s"}`;
}

function formatUsd(value) {
  if (!Number.isFinite(value)) return "Unavailable";

  const minimumFractionDigits = value >= 1 ? 2 : 3;
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits,
    maximumFractionDigits: 3,
  }).format(value);
}

function normalizeVideo(video) {
  const originalThumbnailUrl = video.original_thumbnail_url || video.current_thumbnail_url || null;
  const comparePosition = Number(video.comparePosition);

  return {
    ...video,
    original_thumbnail_url: originalThumbnailUrl,
    latestResult: video.latestResult || null,
    comparePosition: Number.isFinite(comparePosition) ? comparePosition : 50,
    jobState: video.jobState || null,
    jobMessage: video.jobMessage || "",
    jobLog: video.jobLog || "",
  };
}

function normalizeVideos(videos) {
  return videos.map((video) => normalizeVideo(video));
}

function clearVideoCache() {
  try {
    window.localStorage.removeItem(VIDEO_CACHE_KEY);
  } catch {}
}

function persistVideoCache() {
  if (!bootstrap.connected) return;

  const cacheVideos = state.videos.map(({ jobState, jobMessage, jobLog, ...video }) => ({
    ...video,
  }));

  try {
    window.localStorage.setItem(
      VIDEO_CACHE_KEY,
      JSON.stringify({
        channel: state.channel,
        videos: cacheVideos,
      }),
    );
  } catch {}
}

function restoreVideoCache() {
  if (!bootstrap.connected) return false;

  try {
    const raw = window.localStorage.getItem(VIDEO_CACHE_KEY);
    if (!raw) return false;

    const parsed = JSON.parse(raw);
    if (!parsed || !Array.isArray(parsed.videos)) return false;

    state.channel = parsed.channel && typeof parsed.channel === "object" ? parsed.channel : null;
    state.videos = normalizeVideos(parsed.videos);
    state.selectedVideoIds = new Set();
    return true;
  } catch {
    clearVideoCache();
    return false;
  }
}

function mergeIncomingVideos(incomingVideos) {
  const previousById = new Map(state.videos.map((video) => [video.id, normalizeVideo(video)]));

  return normalizeVideos(incomingVideos).map((incoming) => {
    const previous = previousById.get(incoming.id);
    if (!previous) return incoming;

    return {
      ...incoming,
      original_thumbnail_url:
        previous.original_thumbnail_url ||
        previous.current_thumbnail_url ||
        incoming.original_thumbnail_url ||
        incoming.current_thumbnail_url,
      latestResult: previous.latestResult || null,
      comparePosition: previous.comparePosition ?? 50,
      jobState: null,
      jobMessage: "",
      jobLog: "",
    };
  });
}

function updateCostEstimate() {
  const count = state.selectedVideoIds.size;
  costPerImage.textContent = formatUsd(GEMINI_COST_PER_IMAGE_USD);
  selectionCost.textContent = formatUsd(GEMINI_COST_PER_IMAGE_USD * count);
}

function updateSelection() {
  const count = state.selectedVideoIds.size;
  selectionCount.textContent = count;
  transformBtn.disabled = !count || state.batchRunning || state.loadingVideos;
  refreshButton.disabled = state.loadingVideos || state.batchRunning;
  selectVisibleBtn.disabled = !state.videos.length || state.batchRunning || state.loadingVideos;
  clearSelectionBtn.disabled = !count || state.batchRunning || state.loadingVideos;

  document.querySelectorAll(".video-card").forEach((card) => {
    const id = card.dataset.videoId;
    card.classList.toggle("selected", state.selectedVideoIds.has(id));
  });

  document.querySelectorAll("[data-select-id]").forEach((checkbox) => {
    checkbox.checked = state.selectedVideoIds.has(checkbox.dataset.selectId);
  });

  updateCostEstimate();
}

function toggleVideoSelection(videoId) {
  if (!videoId || state.batchRunning || state.loadingVideos) return;

  if (state.selectedVideoIds.has(videoId)) {
    state.selectedVideoIds.delete(videoId);
  } else {
    state.selectedVideoIds.add(videoId);
  }

  updateSelection();
}

function renderVideoSkeletons() {
  const count = Math.max(state.videos.length || 0, SKELETON_CARD_COUNT);
  const cards = Array.from(
    { length: count },
    () => `
      <article class="video-card skeleton-card" aria-hidden="true">
        <div class="card-thumb skeleton-block"></div>
        <div class="card-body">
          <div class="skeleton-line skeleton-line-lg"></div>
          <div class="skeleton-line skeleton-line-md"></div>
          <div class="skeleton-line skeleton-line-sm"></div>
          <div class="card-footer">
            <div class="skeleton-pill flex-1"></div>
            <div class="skeleton-pill skeleton-pill-icon"></div>
          </div>
        </div>
      </article>
    `,
  ).join("");

  channelTitle.textContent = state.channel?.title || "Loading videos";
  mainSubtitle.textContent = "Fetching your latest long-form videos.";
  videoCount.textContent = "Loading...";
  selectionCount.textContent = "0";
  transformBtn.disabled = true;
  refreshButton.disabled = true;
  videosGrid.innerHTML = cards;
}

function renderThumbnail(video) {
  const originalThumbnailUrl = video.original_thumbnail_url || video.current_thumbnail_url || "";
  const transformedThumbnailUrl = video.latestResult?.uploadReadyUrl || "";
  const comparePosition = Number.isFinite(Number(video.comparePosition))
    ? Number(video.comparePosition)
    : 50;

  if (originalThumbnailUrl && transformedThumbnailUrl) {
    return `
      <div class="card-compare" style="--compare-position: ${comparePosition}%;">
        <img class="compare-image compare-after" src="${escapeHtml(transformedThumbnailUrl)}" alt="${escapeHtml(video.title)} 4K thumbnail" loading="lazy">
        <div class="compare-before">
          <img class="compare-image compare-before-image" src="${escapeHtml(originalThumbnailUrl)}" alt="${escapeHtml(video.title)} original thumbnail" loading="lazy">
        </div>
        <div class="compare-divider"></div>
        <span class="compare-label compare-label-before">Before</span>
        <span class="compare-label compare-label-after">4K</span>
        <input
          class="compare-range"
          type="range"
          min="0"
          max="100"
          value="${comparePosition}"
          data-compare-id="${escapeHtml(video.id)}"
          aria-label="Compare original and 4K thumbnail for ${escapeHtml(video.title)}"
        >
      </div>
    `;
  }

  return `<img src="${escapeHtml(originalThumbnailUrl)}" alt="${escapeHtml(video.title)}" loading="lazy">`;
}

function renderCardStatus(video) {
  if (video.jobState === "processing") {
    return '<div class="card-status processing"><span class="spinner spinner-sm"></span> Generating 4K and uploading...</div>';
  }
  if (video.jobState === "queued") {
    return '<div class="card-status processing"><span class="spinner spinner-sm"></span> Queued for Gemini.</div>';
  }
  if (video.jobState === "success") {
    return '<div class="card-status success">4K thumbnail uploaded.</div>';
  }
  if (video.jobState === "error") {
    return `
      <div class="card-status error">
        <span class="card-status-message">${escapeHtml(video.jobMessage || "This thumbnail failed.")}</span>
        ${
          video.jobLog
            ? `<button class="btn btn-ghost btn-sm card-log-button" type="button" data-log-id="${escapeHtml(video.id)}">Log</button>`
            : ""
        }
      </div>
    `;
  }
  return "";
}

function renderResultMeta(video) {
  if (!video.latestResult) return "";

  return `
    <div class="card-result">
      <div class="card-result-label">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 4 12 14.01 9 11.01"/></svg>
        Compare original vs 4K
      </div>
      <div class="card-result-meta">
        Generated with ${escapeHtml(video.latestResult.model)} from the ${escapeHtml(video.latestResult.sourceUsed)} thumbnail source.
      </div>
      ${
        video.latestResult.notes
          ? `<div class="card-result-meta">${escapeHtml(video.latestResult.notes)}</div>`
          : ""
      }
    </div>
  `;
}

function renderVideos() {
  if (state.loadingVideos) {
    renderVideoSkeletons();
    return;
  }

  const channelName = state.channel?.title || "Connection required";
  channelTitle.textContent = channelName;
  mainSubtitle.textContent = state.channel
    ? "Pick the videos you want to upgrade, then queue the 4K transform."
    : "Connect your YouTube account to load your videos.";

  videoCount.textContent = formatVideoCount(state.videos.length);

  if (!bootstrap.connected) {
    videosGrid.innerHTML = `
      <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2"/><path d="m10 8 6 4-6 4V8z"/></svg>
        <div class="empty-state-title">YouTube is not connected</div>
        <div class="empty-state-desc">Connect your YouTube account from the top bar to load your videos.</div>
      </div>
    `;
    updateSelection();
    return;
  }

  if (!state.videos.length) {
    videosGrid.innerHTML = `
      <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
        <div class="empty-state-title">No cached videos yet</div>
        <div class="empty-state-desc">Click "Refresh" to fetch your latest long-form uploads.</div>
      </div>
    `;
    updateSelection();
    return;
  }

  videosGrid.innerHTML = state.videos
    .map((video) => {
      const busy = state.batchRunning;
      const checked = state.selectedVideoIds.has(video.id) ? "checked" : "";

      return `
        <article class="video-card ${checked ? "selected" : ""}" data-video-id="${escapeHtml(video.id)}">
          <div class="card-thumb">
            ${renderThumbnail(video)}
            <label class="card-checkbox">
              <input type="checkbox" data-select-id="${escapeHtml(video.id)}" ${checked} ${busy ? "disabled" : ""}>
            </label>
            <span class="card-privacy">${escapeHtml(video.privacy_status)}</span>
          </div>
          <div class="card-body">
            <h3 class="card-title">${escapeHtml(video.title)}</h3>
            <div class="card-date">${escapeHtml(formatDate(video.published_at))}</div>
            <div class="card-footer">
              <button class="btn btn-primary btn-sm flex-1" type="button" data-transform-id="${escapeHtml(video.id)}" ${busy ? "disabled" : ""}>
                ${busy ? '<span class="spinner spinner-sm"></span>' : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>'}
                ${busy ? "Job running..." : "Transform"}
              </button>
              <a class="btn btn-ghost btn-sm" href="${escapeHtml(video.watch_url)}" target="_blank" rel="noreferrer">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
              </a>
            </div>
          </div>
          ${renderCardStatus(video)}
          ${renderResultMeta(video)}
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

async function loadVideos({ showToast = true } = {}) {
  if (!bootstrap.connected) {
    renderVideos();
    return;
  }

  const previousChannel = state.channel;
  const previousVideos = state.videos.map((video) => ({ ...video }));
  const previousSelection = new Set(state.selectedVideoIds);

  state.loadingVideos = true;
  renderVideos();

  if (showToast) {
    showToast("Loading videos...", "info", 2000);
  }

  try {
    const payload = await fetchJson("/api/videos");
    state.channel = payload.channel;
    state.videos = mergeIncomingVideos(payload.videos);
    const availableIds = new Set(state.videos.map((video) => video.id));
    state.selectedVideoIds = new Set(
      [...state.selectedVideoIds].filter((id) => availableIds.has(id)),
    );
    persistVideoCache();
    showToast(`${formatVideoCount(state.videos.length)} loaded.`, "success");
  } catch (error) {
    state.channel = previousChannel;
    state.videos = previousVideos;
    state.selectedVideoIds = previousSelection;
    showToast(error.message, "error", 6000);
  } finally {
    state.loadingVideos = false;
    renderVideos();
  }
}

function updateVideoComparePosition(videoId, position) {
  const numericPosition = Math.max(0, Math.min(100, Number(position)));
  state.videos = state.videos.map((video) =>
    video.id === videoId
      ? {
          ...video,
          comparePosition: numericPosition,
        }
      : video,
  );
}

function stopJobPolling() {
  if (state.activeJobPollTimer) {
    window.clearTimeout(state.activeJobPollTimer);
    state.activeJobPollTimer = null;
  }
}

function applyJobSnapshot(snapshot) {
  const processedById = new Map(snapshot.processed.map((result) => [result.videoId, result]));
  const failedById = new Map(snapshot.failed.map((item) => [item.videoId, item]));
  const targetedIds = new Set(snapshot.videoIds || [...state.activeJobVideoIds]);

  state.videos = state.videos.map((video) => {
    if (!targetedIds.has(video.id)) return video;

    const processed = processedById.get(video.id);
    if (processed) {
      return {
        ...video,
        original_thumbnail_url:
          video.original_thumbnail_url || video.current_thumbnail_url || null,
        latestResult: processed,
        jobState: "success",
        jobMessage: "",
        jobLog: "",
      };
    }

    const failed = failedById.get(video.id);
    if (failed) {
      return {
        ...video,
        jobState: "error",
        jobMessage: failed.message || "This thumbnail failed.",
        jobLog: failed.log || "",
      };
    }

    if (snapshot.currentVideoId === video.id && snapshot.status === "running") {
      return {
        ...video,
        jobState: "processing",
        jobMessage: snapshot.message || "Processing...",
        jobLog: "",
      };
    }

    if (snapshot.status === "queued" || snapshot.status === "running") {
      return {
        ...video,
        jobState: "queued",
        jobMessage: "Queued for Gemini.",
        jobLog: "",
      };
    }

    return video;
  });

  const totalCount = snapshot.totalCount || 0;
  const completedCount = snapshot.completedCount || 0;
  const percent = totalCount ? Math.round((completedCount / totalCount) * 100) : 0;
  const detail = snapshot.currentVideoTitle
    ? `Processing "${snapshot.currentVideoTitle}"`
    : snapshot.message;

  batchProgress.style.display = "block";
  batchProgressFill.style.width = `${percent}%`;
  batchProgressLabel.textContent = totalCount
    ? `${completedCount} / ${totalCount} · ${detail}`
    : detail || "";

  persistVideoCache();
  renderVideos();
}

function finishJob(snapshot) {
  stopJobPolling();
  state.batchRunning = false;
  state.activeJobId = null;
  state.activeJobVideoIds = new Set();

  const failedIds = new Set(snapshot.failed.map((item) => item.videoId).filter(Boolean));
  state.selectedVideoIds = new Set(
    [...state.selectedVideoIds].filter((videoId) => failedIds.has(videoId)),
  );

  applyJobSnapshot(snapshot);
  showToast(snapshot.message, snapshot.hasFailures ? "error" : "success", 6000);

  window.setTimeout(() => {
    batchProgress.style.display = "none";
  }, 2500);
}

async function pollJob(jobId) {
  try {
    const snapshot = await fetchJson(`/api/transform-jobs/${jobId}`);
    applyJobSnapshot(snapshot);

    if (["completed", "partial", "failed"].includes(snapshot.status)) {
      finishJob(snapshot);
      return;
    }

    state.activeJobPollTimer = window.setTimeout(() => {
      void pollJob(jobId);
    }, JOB_POLL_INTERVAL_MS);
  } catch (error) {
    stopJobPolling();
    state.batchRunning = false;
    state.activeJobId = null;
    state.videos = state.videos.map((video) =>
      state.activeJobVideoIds.has(video.id)
        ? {
            ...video,
            jobState: "error",
            jobMessage: "Could not refresh the async job status.",
            jobLog: error.message || "",
          }
        : video,
    );
    state.activeJobVideoIds = new Set();
    batchProgress.style.display = "none";
    renderVideos();
    showToast(error.message, "error", 6000);
  }
}

async function queueTransformJob(targetVideos) {
  if (!targetVideos.length) {
    showToast("Select at least one video.", "error");
    return;
  }
  if (!bootstrap.geminiConfigured) {
    showToast("Add GEMINI_API_KEY in Setup before you start a batch.", "error");
    return;
  }
  if (state.batchRunning) {
    showToast("A transform job is already running.", "info");
    return;
  }

  try {
    const snapshot = await fetchJson("/api/transform-jobs", {
      method: "POST",
      body: JSON.stringify({
        prompt: promptInput.value,
        videos: targetVideos.map((video) => ({
          id: video.id,
          title: video.title,
          officialThumbnailUrl: video.official_thumbnail_url,
          pytubeThumbnailUrl: video.pytube_thumbnail_url,
        })),
      }),
    });

    state.batchRunning = true;
    state.activeJobId = snapshot.jobId;
    state.activeJobVideoIds = new Set(targetVideos.map((video) => video.id));

    state.videos = state.videos.map((video) =>
      state.activeJobVideoIds.has(video.id)
        ? {
          ...video,
          jobState: "queued",
          jobMessage: "Queued for Gemini.",
          jobLog: "",
        }
        : video,
    );

    applyJobSnapshot(snapshot);
    showToast(
      `${formatVideoCount(targetVideos.length)} queued. Estimated Gemini cost: ${formatUsd(snapshot.estimatedCostUsd)}.`,
      "info",
      5000,
    );
    void pollJob(snapshot.jobId);
  } catch (error) {
    showToast(error.message, "error", 6000);
  }
}

async function transformVideo(videoId) {
  const video = state.videos.find((item) => item.id === videoId);
  if (!video) return;
  await queueTransformJob([video]);
}

async function transformSelection() {
  const selected = state.videos.filter((video) => state.selectedVideoIds.has(video.id));
  await queueTransformJob(selected);
}

videosGrid.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-transform-id]");
  if (!button) return;
  await transformVideo(button.dataset.transformId);
});

videosGrid.addEventListener("click", (event) => {
  const button = event.target.closest("[data-log-id]");
  if (!button) return;

  const video = state.videos.find((item) => item.id === button.dataset.logId);
  if (!video) {
    showToast("No log found for this video.", "error");
    return;
  }

  openLogModal(
    "Transform log",
    video.title || button.dataset.logId,
    video.jobLog || video.jobMessage,
  );
});

videosGrid.addEventListener("click", (event) => {
  if (event.target.closest("button, a, [data-select-id], .card-checkbox, [data-compare-id]")) {
    return;
  }

  const thumb = event.target.closest(".card-thumb");
  if (!thumb) return;

  const card = thumb.closest(".video-card");
  if (!card) return;

  toggleVideoSelection(card.dataset.videoId);
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

videosGrid.addEventListener("input", (event) => {
  const compareRange = event.target.closest("[data-compare-id]");
  if (!compareRange) return;

  const compareCard = compareRange.closest(".card-compare");
  if (compareCard) {
    compareCard.style.setProperty("--compare-position", `${compareRange.value}%`);
  }

  updateVideoComparePosition(compareRange.dataset.compareId, compareRange.value);
});

videosGrid.addEventListener("change", (event) => {
  const compareRange = event.target.closest("[data-compare-id]");
  if (!compareRange) return;

  updateVideoComparePosition(compareRange.dataset.compareId, compareRange.value);
  persistVideoCache();
});

refreshButton.addEventListener("click", () => void loadVideos());
transformBtn.addEventListener("click", () => void transformSelection());

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
      stopJobPolling();
      clearVideoCache();
      bootstrap.connected = false;
      state.channel = null;
      state.videos = [];
      state.selectedVideoIds = new Set();
      state.batchRunning = false;
      state.activeJobId = null;
      state.activeJobVideoIds = new Set();
      batchProgress.style.display = "none";
      renderVideos();
      showToast("YouTube session cleared.", "success");
    } catch (error) {
      showToast(error.message, "error");
    }
  });
}

if (logModal) {
  logModal.addEventListener("click", (event) => {
    if (event.target === logModal) {
      closeLogModal();
    }
  });
}

logModalCloseButtons.forEach((button) => {
  button.addEventListener("click", closeLogModal);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeLogModal();
  }
});

renderVideos();
updateCostEstimate();
if (!restoreVideoCache()) {
  void loadVideos({ showToast: false });
} else {
  renderVideos();
}
