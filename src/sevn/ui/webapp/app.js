// Phase 3 minimal SPA for sevn.bot webchat (specs/19-channel-webui.md §4.4).
// Hand-written: no bundler required. Chunk streaming + JWT refresh over HTTP.

"use strict";

(function () {
  const $ = (sel) => document.querySelector(sel);
  const statusEl = $("#status");
  const logEl = $("#log");
  const openUiHost = $("#openui-host");
  const composer = $("#composer");
  const textEl = $("#text");
  const bannerEl = $("#dev-banner");

  const GATEWAY_TOKEN_KEY = "sevn.gateway_token";
  const WEBCHAT_TOKEN_KEY = "sevn.webchat_token";

  let socket = null;
  let sessionId = null;
  let webchatToken = null;
  let streamingBubble = null;

  function setStatus(state, label) {
    statusEl.dataset.state = state;
    statusEl.textContent = label || state;
  }

  function appendBubble(text, role, metaExtra) {
    const who = role === "user" ? "user" : role === "error" ? "error" : "assistant";
    const msg = document.createElement("article");
    msg.className =
      "msg " + (who === "user" ? "msg--user" : who === "error" ? "msg--error" : "msg--assistant");
    const meta = document.createElement("div");
    meta.className = "msg__meta";
    const whoEl = document.createElement("span");
    whoEl.className = "who who--" + (who === "user" ? "user" : "assistant");
    whoEl.textContent = who === "user" ? "You" : who === "error" ? "Error" : "sevn";
    meta.appendChild(whoEl);
    const body = document.createElement("div");
    body.className = "msg__body";
    body.textContent = text;
    msg.appendChild(meta);
    msg.appendChild(body);
    if (metaExtra && typeof metaExtra === "object") {
      if (metaExtra.gateway_message_id != null) {
        msg.dataset.gatewayMessageId = String(metaExtra.gateway_message_id);
      }
      if (metaExtra.share_text) {
        msg.dataset.shareText = String(metaExtra.share_text);
      }
    }
    logEl.appendChild(msg);
    msg.scrollIntoView({ block: "end" });
    return msg;
  }

  function attachQaBar(article, shareText) {
    if (!article || !sessionId) {
      return;
    }
    const gwId = article.dataset.gatewayMessageId;
    if (!gwId) {
      return;
    }
    const bar = document.createElement("div");
    bar.className = "qa-bar";
    bar.style.display = "flex";
    bar.style.flexWrap = "wrap";
    bar.style.gap = "0.35rem";
    bar.style.marginTop = "0.35rem";
    const defs = [
      { label: "♻ Regen", action: "regen" },
      { label: "👍", action: "up" },
      { label: "👎", action: "down" },
      { label: "🔗 Share", action: "share" },
      { label: "📝 Feedback", action: "feedback" },
    ];
    defs.forEach(function (def) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = def.label;
      btn.className = "btn btn--ghost";
      btn.addEventListener("click", function () {
        if (def.action === "share") {
          const text = shareText || article.dataset.shareText || "";
          if (navigator.share) {
            navigator.share({ title: "sevn.bot", text: text }).catch(function () {});
          } else if (navigator.clipboard && text) {
            navigator.clipboard.writeText(text).catch(function () {});
          }
          return;
        }
        if (def.action === "feedback") {
          openFeedbackModal(gwId);
          return;
        }
        postQa(def.action, gwId);
      });
      bar.appendChild(btn);
    });
    article.appendChild(bar);
  }

  function postQa(action, gatewayMessageId) {
    if (!webchatToken) {
      return;
    }
    fetch("/api/webchat/qa", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + webchatToken,
      },
      body: JSON.stringify({
        action: action,
        session_id: sessionId,
        gateway_message_id: Number(gatewayMessageId),
        platform_message_id: 0,
      }),
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (body) {
        if (body && body.toast) {
          setStatus("connected", body.toast);
        }
      })
      .catch(function () {});
  }

  function openFeedbackModal(gatewayMessageId) {
    const overlay = document.createElement("div");
    overlay.style.position = "fixed";
    overlay.style.inset = "0";
    overlay.style.background = "rgba(0,0,0,0.45)";
    overlay.style.display = "flex";
    overlay.style.alignItems = "center";
    overlay.style.justifyContent = "center";
    const panel = document.createElement("form");
    panel.style.background = "var(--surface, #fff)";
    panel.style.padding = "1rem";
    panel.style.borderRadius = "8px";
    panel.style.maxWidth = "24rem";
    panel.style.width = "90%";
    panel.innerHTML =
      '<label>Severity<select name="severity"><option value="">—</option>' +
      '<option value="minor">Minor</option><option value="moderate">Moderate</option>' +
      '<option value="critical">Critical</option></select></label>' +
      '<label style="display:block;margin-top:0.5rem">Feedback<textarea name="body" rows="4" maxlength="2000"></textarea></label>' +
      '<button type="submit" class="btn" style="margin-top:0.5rem">Submit</button>' +
      '<button type="button" class="btn btn--ghost" data-cancel style="margin-top:0.25rem">Cancel</button>';
    panel.querySelector("[data-cancel]").addEventListener("click", function () {
      overlay.remove();
    });
    panel.addEventListener("submit", function (ev) {
      ev.preventDefault();
      const bodyText = panel.querySelector("[name=body]").value.trim();
      const severity = panel.querySelector("[name=severity]").value;
      if (!bodyText && !severity) {
        return;
      }
      fetch("/webapp/feedback/submit", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer " + webchatToken,
        },
        body: JSON.stringify({
          target_turn_id: String(gatewayMessageId),
          submission_key: "wc:" + gatewayMessageId + ":" + Date.now(),
          fields: { body_text: bodyText, severity: severity },
        }),
      })
        .then(function (r) {
          if (!r.ok) {
            throw new Error("fail");
          }
          overlay.remove();
          setStatus("connected", "Feedback logged.");
        })
        .catch(function () {
          setStatus("error", "Feedback failed.");
        });
    });
    overlay.appendChild(panel);
    document.body.appendChild(overlay);
  }

  function ensureStreamingBubble() {
    if (!streamingBubble) {
      streamingBubble = appendBubble("", "assistant", null).querySelector(".msg__body");
    }
    return streamingBubble;
  }

  function finishStreamingBubble() {
    streamingBubble = null;
  }

  function renderOpenUi(frame) {
    openUiHost.hidden = false;
    openUiHost.innerHTML = "";
    const iframe = document.createElement("iframe");
    iframe.setAttribute("sandbox", "allow-forms allow-same-origin");
    iframe.setAttribute(
      "csp",
      "default-src 'self'; script-src 'none'; style-src 'unsafe-inline'",
    );
    iframe.referrerPolicy = "no-referrer";
    if (typeof frame.iframe_src === "string" && frame.iframe_src) {
      iframe.src = frame.iframe_src;
    } else if (typeof frame.html === "string" && frame.html) {
      iframe.srcdoc = frame.html;
    } else {
      return;
    }
    if (frame.title) {
      iframe.title = frame.title;
    }
    openUiHost.appendChild(iframe);
  }

  function send(frame) {
    if (!socket || socket.readyState !== 1) {
      return false;
    }
    socket.send(JSON.stringify(frame));
    return true;
  }

  function gatewayAuthHeaders() {
    const tok = sessionStorage.getItem(GATEWAY_TOKEN_KEY);
    if (!tok) {
      return {};
    }
    return { Authorization: "Bearer " + tok };
  }

  async function loadPublicConfig() {
    try {
      const r = await fetch("/api/webchat/config");
      if (!r.ok) {
        return null;
      }
      return await r.json();
    } catch (_e) {
      return null;
    }
  }

  async function fetchToken() {
    const params = new URLSearchParams(location.search);
    const overrideToken = params.get("token");
    if (overrideToken) {
      return overrideToken;
    }
    const stored = sessionStorage.getItem(WEBCHAT_TOKEN_KEY);
    if (stored) {
      return stored;
    }
    try {
      const r = await fetch("/api/webchat/token", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...gatewayAuthHeaders(),
        },
        body: JSON.stringify({}),
      });
      if (r.status === 401) {
        location.href = "/login";
        return null;
      }
      if (!r.ok) {
        return null;
      }
      const body = await r.json();
      const tok =
        typeof body.access_token === "string" ? body.access_token : null;
      if (tok) {
        sessionStorage.setItem(WEBCHAT_TOKEN_KEY, tok);
      }
      return tok;
    } catch (_e) {
      return null;
    }
  }

  async function refreshToken() {
    if (!webchatToken) {
      return fetchToken();
    }
    try {
      const r = await fetch("/auth/refresh", {
        method: "POST",
        headers: { Authorization: "Bearer " + webchatToken },
      });
      if (!r.ok) {
        sessionStorage.removeItem(WEBCHAT_TOKEN_KEY);
        return fetchToken();
      }
      const body = await r.json();
      const tok =
        typeof body.access_token === "string" ? body.access_token : null;
      if (tok) {
        sessionStorage.setItem(WEBCHAT_TOKEN_KEY, tok);
        webchatToken = tok;
      }
      return tok;
    } catch (_e) {
      return fetchToken();
    }
  }

  function connect(token) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = proto + "://" + location.host + "/ws/webchat";
    socket = new WebSocket(url);
    setStatus("connecting", "connecting…");

    socket.addEventListener("open", () => {
      send({ type: "auth", token: token || "" });
    });

    socket.addEventListener("close", () => {
      setStatus("error", "disconnected");
      finishStreamingBubble();
    });

    socket.addEventListener("error", () => {
      setStatus("error", "error");
    });

    socket.addEventListener("message", (ev) => {
      let frame;
      try {
        frame = JSON.parse(ev.data);
      } catch (_err) {
        return;
      }
      if (!frame || typeof frame !== "object") {
        return;
      }
      switch (frame.type) {
        case "ready":
          sessionId = frame.session_id;
          setStatus("connected", "connected");
          break;
        case "message":
          finishStreamingBubble();
          {
            const art = appendBubble(frame.text || "", "assistant", {
              gateway_message_id: frame.gateway_message_id,
              share_text: frame.text || "",
            });
            attachQaBar(art, frame.text || "");
          }
          break;
        case "chunk":
          ensureStreamingBubble().textContent += frame.text || "";
          break;
        case "openui":
          renderOpenUi(frame);
          break;
        case "audio":
          if (frame.url) {
            const audio = new Audio(frame.url);
            audio.play().catch(() => undefined);
          }
          break;
        case "error":
          finishStreamingBubble();
          appendBubble(
            "error: " + (frame.code || "") + " " + (frame.message || ""),
            "error",
          );
          break;
        default:
          break;
      }
    });
  }

  composer.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const value = textEl.value.trim();
    if (!value || !sessionId) {
      return;
    }
    if (send({ type: "message", text: value, session_id: sessionId })) {
      appendBubble(value, "user");
      textEl.value = "";
    }
  });

  if (typeof initSevnTheme === "function") {
    initSevnTheme();
  }

  loadPublicConfig().then((cfg) => {
    if (cfg && cfg.public && bannerEl) {
      bannerEl.hidden = false;
      bannerEl.textContent =
        "Anonymous webchat (dev/testing only). Do not enable channels.webchat.public in production.";
    }
    if (cfg && cfg.gateway_auth_required && !sessionStorage.getItem(GATEWAY_TOKEN_KEY)) {
      const onLogin = location.pathname.startsWith("/login");
      if (!onLogin) {
        location.href = "/login";
        return;
      }
    }
    fetchToken().then((tok) => {
      if (!tok) {
        setStatus("error", "no token");
        return;
      }
      webchatToken = tok;
      connect(tok);
      window.setInterval(() => {
        refreshToken().then((next) => {
          if (next && socket && socket.readyState === 1) {
            send({ type: "auth", token: next });
          }
        });
      }, 45 * 60 * 1000);
    });
  });
})();
