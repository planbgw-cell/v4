(function (window, document) {
  // Kakao Web 플랫폼 등록 도메인과 동일한 기본값(필요 시 init({siteDomain})로 덮어쓰기).
  var SITE_DOMAIN = "http://121.133.47.184:8000";

  function getOrigin() {
    return window.location.origin;
  }

  function getSiteDomain(options) {
    var configured = options && options.siteDomain ? String(options.siteDomain).trim() : "";
    var base = configured || SITE_DOMAIN || getOrigin();
    return base.replace(/\/+$/, "");
  }

  function normalizeAbsoluteUrl(url) {
    if (!url) return "";
    var s = String(url).trim();
    if (!s) return "";
    if (/^https?:\/\//i.test(s)) return s;
    if (s.startsWith("//")) return window.location.protocol + s;
    if (s.startsWith("/")) return getOrigin() + s;
    return getOrigin() + "/" + s;
  }

  function buildViewerUrl(projectType, projectId, options) {
    var base = getSiteDomain(options);
    var type = (projectType === "album") ? "album" : "video";
    return base + "/viewer/" + type + "/" + encodeURIComponent(projectId || "");
  }

  function buildShareUrl(projectType, projectId, options) {
    var base = getSiteDomain(options);
    var type = (projectType === "album") ? "album" : "video";
    return base + "/share/" + type + "/" + encodeURIComponent(projectId || "");
  }

  function buildDefaultShareImage(projectType, projectId, imageUrl, options) {
    var normalized = normalizeAbsoluteUrl(imageUrl || "");
    if (normalized) return normalized;
    return "";
  }

  function legacyCopy(text) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "readonly");
    ta.style.position = "fixed";
    ta.style.top = "-9999px";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    var copied = false;
    try {
      copied = document.execCommand("copy");
    } catch (e) {
      copied = false;
    }
    document.body.removeChild(ta);
    return copied;
  }

  function copyShareUrl(url) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(url).catch(function () {
        if (!legacyCopy(url)) {
          throw new Error("copy failed");
        }
      });
    }
    if (!legacyCopy(url)) {
      return Promise.reject(new Error("copy failed"));
    }
    return Promise.resolve();
  }

  function showToast(text) {
    var toast = document.getElementById("shareToast");
    if (!toast) return;
    toast.textContent = text || "완료되었습니다.";
    toast.classList.remove("hidden");
    window.clearTimeout(showToast._timer);
    showToast._timer = window.setTimeout(function () {
      toast.classList.add("hidden");
    }, 1800);
  }

  function ensureKakaoInitialized(key) {
    if (!window.Kakao || !key) return false;
    if (!window.Kakao.isInitialized()) {
      window.Kakao.init(key);
    }
    return true;
  }

  function sendKakao(payload) {
    if (!window.Kakao || !window.Kakao.Share) return false;
    window.Kakao.Share.sendDefault({
      objectType: "feed",
      content: {
        title: payload.title || "Flairy 공유",
        description: payload.description || "Flairy에서 만든 콘텐츠를 확인해보세요.",
        imageUrl: payload.imageUrl || payload.fallbackImageUrl || "",
        link: {
          mobileWebUrl: payload.url,
          webUrl: payload.url
        }
      },
      buttons: [
        {
          title: "콘텐츠 보기",
          link: { mobileWebUrl: payload.url, webUrl: payload.url }
        }
      ]
    });
    return true;
  }

  function renderQrCode(url) {
    var wrap = document.getElementById("shareQrWrap");
    var canvas = document.getElementById("shareQrCanvas");
    if (!wrap || !canvas || !window.QRCode || !window.QRCode.toCanvas) {
      showToast("QR 라이브러리를 불러올 수 없습니다.");
      return;
    }
    wrap.classList.remove("hidden");
    try {
      window.QRCode.toCanvas(canvas, url, { width: 220, margin: 1 }, function (err) {
        if (err) {
          console.warn("[Sharing] QRCode.toCanvas callback error:", err);
          wrap.classList.add("hidden");
          showToast("QR을 만들 수 없습니다.");
        }
      });
    } catch (err) {
      console.warn("[Sharing] QRCode.toCanvas failed:", err);
      wrap.classList.add("hidden");
      showToast("QR을 만들 수 없습니다.");
    }
  }

  function init(options) {
    options = options || {};
    var kakaoJsKey = options.kakaoJsKey || "";
    var fallbackImageUrl = options.fallbackImageUrl || "";
    var siteDomain = getSiteDomain(options);

    var modal = document.getElementById("shareModal");
    var backdrop = document.getElementById("shareModalBackdrop");
    var closeBtn = document.getElementById("shareModalClose");
    var copyBtn = document.getElementById("btnShareCopy");
    var kakaoBtn = document.getElementById("btnShareKakao");
    var qrBtn = document.getElementById("btnShareQr");
    var titleEl = document.getElementById("shareModalTitle");
    var urlEl = document.getElementById("shareModalUrl");
    var qrWrap = document.getElementById("shareQrWrap");
    var root = document.getElementById("viewerRoot");

    if (!modal) return;
    if (modal.getAttribute("data-sharing-init") === "true") return;
    modal.setAttribute("data-sharing-init", "true");

    var state = {
      projectId: "",
      projectType: "video",
      title: "Flairy",
      url: siteDomain + "/",
      imageUrl: normalizeAbsoluteUrl(fallbackImageUrl)
    };

    function closeModal() {
      modal.classList.add("hidden");
      modal.setAttribute("aria-hidden", "true");
      if (qrWrap) qrWrap.classList.add("hidden");
    }

    function openModalByButton(btn) {
      var pid = (btn && btn.getAttribute("data-project-id")) || (root && root.getAttribute("data-project-id")) || "";
      var ptype = (btn && btn.getAttribute("data-project-type")) || (root && root.getAttribute("data-project-type")) || "video";
      var ptitle = (btn && btn.getAttribute("data-project-title")) || document.title || "Flairy";
      state.projectId = pid;
      state.projectType = ptype;
      state.title = ptitle;
      state.url = buildShareUrl(ptype, pid, { siteDomain: siteDomain });
      state.imageUrl = buildDefaultShareImage(
        ptype,
        pid,
        (btn && btn.getAttribute("data-share-image")) || fallbackImageUrl || "",
        { siteDomain: siteDomain }
      );

      console.log("[Sharing] generated share URL:", state.url);
      console.log("[Sharing] generated image URL:", state.imageUrl);

      if (titleEl) titleEl.textContent = ptitle;
      if (urlEl) urlEl.textContent = state.url;
      if (qrWrap) qrWrap.classList.add("hidden");
      modal.classList.remove("hidden");
      modal.setAttribute("aria-hidden", "false");
    }

    if (copyBtn) {
      copyBtn.addEventListener("click", function () {
        copyShareUrl(state.url).then(function () {
          showToast("링크가 복사되었습니다.");
        }).catch(function () {
          window.prompt("아래 링크를 복사해 주세요.", state.url);
        });
      });
    }

    if (qrBtn) {
      qrBtn.addEventListener("click", function () {
        renderQrCode(state.url);
      });
    }

    if (kakaoBtn) {
      kakaoBtn.addEventListener("click", function () {
        var ready = ensureKakaoInitialized(kakaoJsKey);
        if (!ready) {
          showToast("카카오 공유 설정이 없습니다.");
          return;
        }
        sendKakao({
          title: state.title,
          description: "Flairy에서 생성된 디지털 앨범입니다.",
          imageUrl: normalizeAbsoluteUrl(state.imageUrl),
          fallbackImageUrl: normalizeAbsoluteUrl(fallbackImageUrl),
          url: normalizeAbsoluteUrl(state.url)
        });
      });
    }

    if (closeBtn) closeBtn.addEventListener("click", closeModal);
    if (backdrop) backdrop.addEventListener("click", closeModal);

    document.addEventListener("click", function (event) {
      var trigger = event.target.closest("[data-share-trigger='true']");
      if (!trigger) return;
      event.preventDefault();
      openModalByButton(trigger);
    });
  }

  window.FlairySharing = {
    init: init,
    buildShareUrl: buildShareUrl,
    copyShareUrl: copyShareUrl
  };
})(window, document);
