(function (window, document) {
  function getOrigin() {
    return window.location.origin;
  }

  function buildShareUrl(projectType, projectId) {
    var type = (projectType === "album") ? "album" : "video";
    return getOrigin() + "/share/" + type + "/" + encodeURIComponent(projectId || "");
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
    if (!wrap || !canvas || !window.QRCode || !window.QRCode.toCanvas) return;
    wrap.classList.remove("hidden");
    window.QRCode.toCanvas(canvas, url, { width: 220, margin: 1 }, function () {});
  }

  function init(options) {
    options = options || {};
    var kakaoJsKey = options.kakaoJsKey || "";
    var fallbackImageUrl = options.fallbackImageUrl || "";

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
      url: window.location.href,
      imageUrl: fallbackImageUrl
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
      state.url = buildShareUrl(ptype, pid);
      state.imageUrl = (btn && btn.getAttribute("data-share-image")) || fallbackImageUrl || "";

      console.log("[Sharing] generated share URL:", state.url);

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
          description: "Flairy에서 생성된 콘텐츠를 확인해보세요.",
          imageUrl: state.imageUrl,
          fallbackImageUrl: fallbackImageUrl,
          url: state.url
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
