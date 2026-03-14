const bootstrap = window.APP_BOOTSTRAP || {};

const state = {
  videos: [],
  channel: null,
  busyVideoId: null,
  selectedVideoIds: new Set(),
  batchRunning: false,
};

const feedbackNode = document.getElementById("feedback");
const videosGrid = document.getElementById("videosGrid");
const promptInput = document.getElementById("promptInput");
const refreshButton = document.getElementById("refreshButton");
const disconnectButton = document.getElementById("disconnectButton");
const channelTitle = document.getElementById("channelTitle");
const videoCount = document.getElementById("videoCount");
const transformSelectionButton = document.getElementById("transformSelectionButton");
const selectVisibleButton = document.getElementById("selectVisibleButton");
const clearSelectionButton = document.getElementById("clearSelectionButton");
const selectionSummary = document.getElementById("selectionSummary");

function updateSelectionSummary() {
  const count = state.selectedVideoIds.size;
  selectionSummary.textContent = `${count} vidéo${count > 1 ? "s" : ""} sélectionnée${count > 1 ? "s" : ""}`;
  transformSelectionButton.disabled = !count || state.batchRunning;
}

function setFeedback(message, type = "") {
  feedbackNode.textContent = message || "";
  feedbackNode.className = `feedback ${type}`.trim();
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
  if (!value) {
    return "Date inconnue";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("fr-FR");
}

function renderVideos() {
  channelTitle.textContent = state.channel?.title || "Connexion requise";
  videoCount.textContent = `${state.videos.length} vidéo${state.videos.length > 1 ? "s" : ""}`;
  updateSelectionSummary();

  if (!bootstrap.connected) {
    videosGrid.innerHTML = "";
    setFeedback("Connecte d'abord YouTube puis recharge les vidéos.");
    return;
  }

  if (!state.videos.length) {
    videosGrid.innerHTML = "";
    setFeedback("Aucune vidéo récupérée pour le moment.");
    return;
  }

  setFeedback("");
  videosGrid.innerHTML = state.videos
    .map((video) => {
      const busy = state.batchRunning || state.busyVideoId === video.id;
      const checked = state.selectedVideoIds.has(video.id) ? "checked" : "";
      const preview = video.latestResult
        ? `
            <div class="result-preview">
              <div class="small-text">Dernier rendu via ${escapeHtml(video.latestResult.model)}</div>
              <img src="${escapeHtml(video.latestResult.uploadReadyUrl)}" alt="Thumbnail transformé de ${escapeHtml(video.title)}">
              <div class="small-text">Source téléchargée: ${escapeHtml(video.latestResult.sourceUsed)}</div>
            </div>
          `
        : "";

      return `
        <article class="video-card">
          <div class="video-thumb">
            <img src="${escapeHtml(video.current_thumbnail_url || "")}" alt="Thumbnail actuel de ${escapeHtml(video.title)}">
            <label class="selection-badge">
              <input type="checkbox" data-select-id="${escapeHtml(video.id)}" ${checked} ${state.batchRunning ? "disabled" : ""}>
              Sélectionner
            </label>
          </div>
          <div class="video-body">
            <h3 class="video-title">${escapeHtml(video.title)}</h3>
            <div class="video-meta">
              <span>${escapeHtml(formatDate(video.published_at))}</span>
              <span>${escapeHtml(video.privacy_status)}</span>
            </div>
            <div class="card-actions">
              <button class="action-button" type="button" data-video-id="${escapeHtml(video.id)}" ${busy ? "disabled" : ""}>
                ${busy ? "Traitement..." : "Transformer et réuploader"}
              </button>
              <a class="card-link" href="${escapeHtml(video.watch_url)}" target="_blank" rel="noreferrer">Voir sur YouTube</a>
            </div>
            ${preview}
          </div>
        </article>
      `;
    })
    .join("");
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
    },
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

  setFeedback("Chargement des vidéos...");
  try {
    const payload = await fetchJson("/api/videos");
    state.channel = payload.channel;
    state.videos = payload.videos;
    const availableIds = new Set(state.videos.map((video) => video.id));
    state.selectedVideoIds = new Set(
      [...state.selectedVideoIds].filter((videoId) => availableIds.has(videoId)),
    );
    renderVideos();
  } catch (error) {
    state.videos = [];
    state.selectedVideoIds = new Set();
    renderVideos();
    setFeedback(error.message, "error");
  }
}

async function transformVideo(videoId) {
  if (!bootstrap.geminiConfigured) {
    setFeedback("Ajoute GEMINI_API_KEY dans .env pour lancer la transformation.", "error");
    return;
  }

  const video = state.videos.find((entry) => entry.id === videoId);
  if (!video) {
    return;
  }

  state.busyVideoId = videoId;
  renderVideos();
  setFeedback(`Transformation en cours pour "${video.title}"...`);

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
    setFeedback(payload.message, "success");
  } catch (error) {
    setFeedback(error.message, "error");
  } finally {
    state.busyVideoId = null;
    renderVideos();
  }
}

async function transformSelection() {
  const selectedVideos = state.videos.filter((video) => state.selectedVideoIds.has(video.id));
  if (!selectedVideos.length) {
    setFeedback("Sélectionne au moins une vidéo.", "error");
    return;
  }
  if (!bootstrap.geminiConfigured) {
    setFeedback("Ajoute GEMINI_API_KEY dans .env pour lancer la transformation.", "error");
    return;
  }

  state.batchRunning = true;
  renderVideos();
  setFeedback(`Traitement de ${selectedVideos.length} vidéo${selectedVideos.length > 1 ? "s" : ""} en cours...`);

  try {
    const payload = await fetchJson("/api/videos/batch-transform", {
      method: "POST",
      body: JSON.stringify({
        prompt: promptInput.value,
        videos: selectedVideos.map((video) => ({
          id: video.id,
          officialThumbnailUrl: video.official_thumbnail_url,
          pytubeThumbnailUrl: video.pytube_thumbnail_url,
        })),
      }),
    });

    const processedById = new Map(payload.processed.map((result) => [result.videoId, result]));
    state.videos = state.videos.map((video) => {
      const result = processedById.get(video.id);
      if (!result) {
        return video;
      }
      return {
        ...video,
        current_thumbnail_url: result.uploadReadyUrl,
        latestResult: result,
      };
    });

    if (payload.successCount) {
      state.selectedVideoIds = new Set();
    }

    if (payload.hasFailures) {
      const failedIds = payload.failed.map((item) => item.videoId).filter(Boolean).join(", ");
      setFeedback(`${payload.message}${failedIds ? ` Échecs: ${failedIds}` : ""}`, "error");
    } else {
      setFeedback(payload.message, "success");
    }
  } catch (error) {
    setFeedback(error.message, "error");
  } finally {
    state.batchRunning = false;
    renderVideos();
  }
}

videosGrid.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-video-id]");
  if (!button) {
    return;
  }
  await transformVideo(button.dataset.videoId);
});

videosGrid.addEventListener("change", (event) => {
  const checkbox = event.target.closest("[data-select-id]");
  if (!checkbox) {
    return;
  }

  if (checkbox.checked) {
    state.selectedVideoIds.add(checkbox.dataset.selectId);
  } else {
    state.selectedVideoIds.delete(checkbox.dataset.selectId);
  }
  updateSelectionSummary();
});

refreshButton.addEventListener("click", async () => {
  await loadVideos();
});

transformSelectionButton.addEventListener("click", async () => {
  await transformSelection();
});

selectVisibleButton.addEventListener("click", () => {
  state.selectedVideoIds = new Set(state.videos.map((video) => video.id));
  renderVideos();
});

clearSelectionButton.addEventListener("click", () => {
  state.selectedVideoIds = new Set();
  renderVideos();
});

disconnectButton.addEventListener("click", async () => {
  try {
    await fetchJson("/auth/google/disconnect", { method: "POST", body: "{}" });
    bootstrap.connected = false;
    state.channel = null;
    state.videos = [];
    state.selectedVideoIds = new Set();
    renderVideos();
    setFeedback("Session YouTube supprimée.", "success");
  } catch (error) {
    setFeedback(error.message, "error");
  }
});

renderVideos();
void loadVideos();
