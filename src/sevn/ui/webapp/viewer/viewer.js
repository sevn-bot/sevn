(function () {
  const params = new URLSearchParams(location.search);
  const token = params.get("token") || "";
  const statusEl = document.getElementById("viewer-status");
  const rootEl = document.getElementById("viewer-root");
  const titleEl = document.getElementById("viewer-title");
  const actionsEl = document.getElementById("viewer-actions");
  const shareStoryBtn = document.getElementById("viewer-share-story");
  const tg = window.Telegram && window.Telegram.WebApp;
  let shareStoryEnabled = false;
  let shareStoryMediaUrl = "";

  function applyTheme() {
    if (!tg || !tg.themeParams) {
      return;
    }
    const tp = tg.themeParams;
    const root = document.documentElement;
    Object.keys(tp).forEach(function (key) {
      if (tp[key]) {
        root.style.setProperty("--tg-theme-" + key.replace(/_/g, "-"), tp[key]);
      }
    });
    if (typeof tg.ready === "function") {
      tg.ready();
    }
    if (typeof tg.expand === "function") {
      tg.expand();
    }
  }

  function clearRoot() {
    while (rootEl.firstChild) {
      rootEl.removeChild(rootEl.firstChild);
    }
  }

  function maybeShowShareToStory(mediaUrl, caption) {
    shareStoryMediaUrl = mediaUrl || "";
    if (
      !shareStoryEnabled ||
      !shareStoryMediaUrl ||
      !tg ||
      typeof tg.shareToStory !== "function" ||
      !actionsEl ||
      !shareStoryBtn
    ) {
      return;
    }
    actionsEl.hidden = false;
    shareStoryBtn.hidden = false;
    shareStoryBtn.onclick = function () {
      try {
        tg.shareToStory(shareStoryMediaUrl, {
          text: caption || "",
        });
      } catch (_err) {
        statusEl.textContent = "Share to Story unavailable.";
      }
    };
  }

  function renderTable(data) {
    clearRoot();
    const headers = Array.isArray(data.headers) ? data.headers : [];
    const rows = Array.isArray(data.rows) ? data.rows : [];
    const table = document.createElement("table");
    table.className = "viewer-table";
    if (headers.length) {
      const thead = document.createElement("thead");
      const tr = document.createElement("tr");
      headers.forEach(function (h) {
        const th = document.createElement("th");
        th.textContent = String(h);
        tr.appendChild(th);
      });
      thead.appendChild(tr);
      table.appendChild(thead);
    }
    const tbody = document.createElement("tbody");
    rows.forEach(function (row) {
      const tr = document.createElement("tr");
      (Array.isArray(row) ? row : []).forEach(function (cell) {
        const td = document.createElement("td");
        td.textContent = String(cell);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    rootEl.appendChild(table);
    if (data.caption) {
      const cap = document.createElement("p");
      cap.className = "viewer-caption";
      cap.textContent = String(data.caption);
      rootEl.appendChild(cap);
    }
    titleEl.textContent = "Table";
  }

  function renderGallery(data) {
    clearRoot();
    const grid = document.createElement("div");
    grid.className = "viewer-gallery";
    const images = Array.isArray(data.images) ? data.images : [];
    images.forEach(function (src) {
      const img = document.createElement("img");
      img.src = String(src);
      img.alt = "";
      img.loading = "lazy";
      grid.appendChild(img);
    });
    rootEl.appendChild(grid);
    titleEl.textContent = "Gallery";
    if (images.length) {
      maybeShowShareToStory(String(images[0]), data.caption || "");
    }
  }

  function renderSlideshow(data) {
    clearRoot();
    const slides = Array.isArray(data.slides) ? data.slides : [];
    if (!slides.length) {
      statusEl.textContent = "No slides.";
      return;
    }
    let index = 0;
    const wrap = document.createElement("div");
    wrap.className = "viewer-slideshow";
    const slideBox = document.createElement("div");
    slideBox.className = "viewer-slide";
    const img = document.createElement("img");
    const caption = document.createElement("p");
    caption.className = "viewer-slide-caption";
    slideBox.appendChild(img);
    slideBox.appendChild(caption);
    const nav = document.createElement("div");
    nav.className = "viewer-nav";
    const prev = document.createElement("button");
    prev.type = "button";
    prev.textContent = "Previous";
    const next = document.createElement("button");
    next.type = "button";
    next.textContent = "Next";
    nav.appendChild(prev);
    nav.appendChild(next);
    wrap.appendChild(slideBox);
    wrap.appendChild(nav);
    rootEl.appendChild(wrap);

    function show(i) {
      index = (i + slides.length) % slides.length;
      const slide = slides[index] || {};
      const url = String(slide.url || slide.image || "");
      img.src = url;
      caption.textContent = String(slide.caption || "");
      maybeShowShareToStory(url, slide.caption || "");
    }
    prev.addEventListener("click", function () {
      show(index - 1);
    });
    next.addEventListener("click", function () {
      show(index + 1);
    });
    show(0);
    titleEl.textContent = "Slideshow";
  }

  function renderStream(streamId, initData) {
    clearRoot();
    const pre = document.createElement("pre");
    pre.className = "viewer-stream";
    rootEl.appendChild(pre);
    titleEl.textContent = "Stream";
    let offset = 0;
    let closed = false;

    function appendChunks(chunks) {
      chunks.forEach(function (chunk) {
        pre.textContent += String(chunk);
      });
    }

    function poll() {
      if (closed) {
        return;
      }
      const url =
        "/webapp/viewer/stream/" +
        encodeURIComponent(streamId) +
        "/poll?token=" +
        encodeURIComponent(token) +
        "&offset=" +
        String(offset) +
        "&init_data=" +
        encodeURIComponent(initData);
      fetch(url)
        .then(function (r) {
          if (!r.ok) {
            throw new Error("poll_failed");
          }
          return r.json();
        })
        .then(function (snap) {
          appendChunks(Array.isArray(snap.chunks) ? snap.chunks : []);
          offset = Number(snap.next_offset) || offset;
          if (snap.done) {
            closed = true;
            return;
          }
          setTimeout(poll, 400);
        })
        .catch(function () {
          statusEl.textContent = "Stream unavailable.";
        });
    }
    poll();
  }

  applyTheme();
  const initData =
    tg && typeof tg.initData === "string" && tg.initData ? tg.initData : "";
  if (!initData) {
    statusEl.textContent = "Missing Telegram initData.";
    return;
  }
  if (!token) {
    statusEl.textContent = "Open an artifact from inline results or assistant replies.";
    return;
  }

  fetch("/webapp/viewer/payload", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: token, init_data: initData }),
  })
    .then(function (r) {
      if (!r.ok) {
        throw new Error("payload_failed");
      }
      return r.json();
    })
    .then(function (payload) {
      statusEl.textContent = "";
      shareStoryEnabled = payload.share_to_story === true;
      const view = String(payload.view || "");
      const data = payload.view_data && typeof payload.view_data === "object" ? payload.view_data : {};
      if (view === "table") {
        renderTable(data);
        return;
      }
      if (view === "gallery") {
        renderGallery(data);
        return;
      }
      if (view === "slideshow") {
        renderSlideshow(data);
        return;
      }
      if (view === "stream") {
        const streamId = String(payload.stream_id || "");
        if (!streamId) {
          statusEl.textContent = "Missing stream id.";
          return;
        }
        renderStream(streamId, initData);
        return;
      }
      statusEl.textContent = "Unknown view: " + view;
    })
    .catch(function () {
      statusEl.textContent = "Could not load viewer payload.";
    });
})();
