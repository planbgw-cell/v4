/**
 * 앨범 뷰어 초기화 — 단독 페이지 및 HTMX 마이페이지 공용.
 * #flipbookRoot 존재 시에만 동작하며, 재호출 시 기존 observer/DOM 정리 후 재생성.
 */
console.log("[Album] album-viewer-init.js loaded");
var albumVideoObserver = null;

window.initAlbumViewer = function () {
  console.log("!!! Album Engine: initAlbumViewer() called");
  if (!document.getElementById("flipbookRoot")) {
    console.warn("[Album] initAlbumViewer: flipbookRoot not found, exit");
    return;
  }
  var root = document.getElementById("viewerRoot");
  var projectId = root ? root.getAttribute("data-project-id") : null;
  console.log("!!! Album Engine Started with ID:", projectId);
  console.log("[Album] initAlbumViewer: projectId=" + (projectId || "(empty)"));
  if (!projectId) {
    var loadingState = document.getElementById("loadingState");
    var errorState = document.getElementById("errorState");
    if (loadingState) loadingState.classList.add("hidden");
    if (errorState) {
      errorState.classList.remove("hidden");
      errorState.textContent = "project_id가 없습니다.";
    }
    return;
  }

  projectId = String(projectId).trim();

  /** 앨범 뷰어: 좁은 뷰포트에서만 저해상도 이미지 API 사용 */
  var isMobileAlbum = typeof window.innerWidth === "number" && window.innerWidth < 768;

  if (albumVideoObserver) {
    albumVideoObserver.disconnect();
    albumVideoObserver = null;
  }
  var loadingState = document.getElementById("loadingState");
  var errorState = document.getElementById("errorState");
  var flipbookState = document.getElementById("flipbookState");
  if (loadingState) loadingState.classList.remove("hidden");
  if (errorState) {
    errorState.classList.add("hidden");
    errorState.textContent = "";
  }
  if (flipbookState) flipbookState.classList.add("hidden");
  var bookBody = document.getElementById("bookBody");
  if (bookBody) bookBody.innerHTML = "";
  var thumbBar = document.getElementById("thumbBar");
  if (thumbBar) thumbBar.innerHTML = "";

  var pageFlipAudio = new Audio("/static/audio/page-flip.mp3");

  function toRawUrl(path) {
    if (!path) return "";
    var match = path.match(/^storage\/raw\/[^/]+\/(.+)$/);
    if (match) return "/raw/" + projectId + "/" + match[1];
    return path.startsWith("/") ? path : "/raw/" + projectId + "/" + path;
  }

  var MOBILE_ALBUM_IMG_CAP = 1080;

  function rawFilenameFromStoragePath(path) {
    if (!path) return "";
    var match = path.match(/^storage\/raw\/[^/]+\/(.+)$/);
    if (match) return match[1];
    if (path.indexOf("/") === -1 && path.indexOf("\\") === -1) return path;
    return "";
  }

  function isRasterImageFilename(name) {
    var s = (name || "").split(/[\\/]/).pop() || "";
    var ext = (s.split(".").pop() || "").toLowerCase();
    return (
      ext === "jpg" ||
      ext === "jpeg" ||
      ext === "png" ||
      ext === "webp" ||
      ext === "heic" ||
      ext === "heif" ||
      ext === "bmp" ||
      ext === "tif" ||
      ext === "tiff"
    );
  }

  /**
   * 리사이즈 이미지 API URL. projectId·filename 모두 경로에 포함(각각 encodeURIComponent).
   * opts.thumb → w=320, opts.w → 해당 너비(1~1080), 없으면 DPR·뷰포트 기반 너비(최대 1080).
   */
  function toAlbumImageUrl(pid, filename, opts) {
    opts = opts || {};
    if (!filename || !pid) return "";
    var p = String(pid).trim();
    var w;
    if (opts.thumb) {
      w = 320;
    } else if (typeof opts.w === "number" && isFinite(opts.w)) {
      w = Math.min(MOBILE_ALBUM_IMG_CAP, Math.max(1, Math.round(opts.w)));
    } else {
      w = MOBILE_ALBUM_IMG_CAP;
    }
    return (
      "/api/media/image/" +
      encodeURIComponent(p) +
      "/" +
      encodeURIComponent(filename) +
      "?w=" +
      w
    );
  }

  /** storage 경로 또는 파일명만 → 모바일이면 API URL, 아니면 /raw */
  function toAlbumImageUrlFromStoragePath(path, opts) {
    if (!path || !isMobileAlbum || isVideoPath(path) || !projectId) return toRawUrl(path);
    var fn = rawFilenameFromStoragePath(path);
    if (!fn || !isRasterImageFilename(fn)) return toRawUrl(path);
    return toAlbumImageUrl(projectId, fn, opts);
  }

  function albumImageAttrsString(path, opts) {
    opts = opts || {};
    if (!path || !isMobileAlbum || isVideoPath(path) || !projectId) return { src: toRawUrl(path) };
    var fn = rawFilenameFromStoragePath(path);
    if (!fn || !isRasterImageFilename(fn)) return { src: toRawUrl(path) };
    if (opts.thumb) {
      return { src: toAlbumImageUrl(projectId, fn, { thumb: true }) };
    }
    var base =
      "/api/media/image/" +
      encodeURIComponent(projectId) +
      "/" +
      encodeURIComponent(fn);
    var srcset =
      base + "?w=640 640w, " + base + "?w=960 960w, " + base + "?w=1080 1080w";
    return { src: base + "?w=960", srcset: srcset, sizes: "100vw" };
  }

  function albumImgOpeningAttrs(path, opts) {
    var a = albumImageAttrsString(path, opts || {});
    var out = ' src="' + a.src + '"';
    if (a.srcset) {
      out += ' srcset="' + a.srcset + '" sizes="' + (a.sizes || "100vw") + '"';
    }
    return out;
  }

  function isVideoPath(path) {
    if (!path) return false;
    return /\.(mp4|webm|mov|m4v)(\?|$)/i.test(path);
  }

  function clamp(n, min, max) {
    return Math.max(min, Math.min(max, n));
  }

  function parsePct(v) {
    if (v == null) return null;
    var s = String(v).trim();
    var m = s.match(/^(-?\d+(?:\.\d+)?)%$/);
    if (!m) return null;
    var n = parseFloat(m[1]);
    return isNaN(n) ? null : n;
  }

  function focusXY(styles) {
    if (!styles || !styles.focus_offset) return null;
    var x = styles.focus_offset.x;
    var y = styles.focus_offset.y;
    if (x == null || y == null) return null;
    var xs = String(x).trim();
    var ys = String(y).trim();
    if (!xs || !ys) return null;
    return { x: xs, y: ys };
  }

  function focusStyleAttr(styles, opts) {
    var xy = focusXY(styles);
    if (!xy) return "";
    var includeOrigin = opts && opts.includeTransformOrigin;
    var yNudgePct = (opts && typeof opts.yNudgePct === "number") ? opts.yNudgePct : 0;
    var yNum = parsePct(xy.y);
    var yStr = xy.y;
    if (yNum != null && yNudgePct) {
      yStr = clamp(yNum + yNudgePct, 0, 100).toFixed(1) + "%";
    }
    var out = "object-position:" + xy.x + " " + yStr + ";";
    if (includeOrigin) out += "transform-origin:" + xy.x + " " + yStr + ";";
    return ' style="' + out + '"';
  }

  function contrastColorForHex(hex) {
    if (!hex || typeof hex !== "string") return "";
    var h = hex.replace(/^#/, "");
    if (!/^[0-9A-Fa-f]{6}$/.test(h)) return "";
    var r = parseInt(h.slice(0, 2), 16);
    var g = parseInt(h.slice(2, 4), 16);
    var b = parseInt(h.slice(4, 6), 16);
    var lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    return lum < 0.5 ? "#fff" : "#111";
  }

  function emotionClass(styles) {
    if (!styles || !styles.emotion) return "";
    var e = String(styles.emotion).trim().toLowerCase().replace(/\s+/g, "-");
    return e ? " caption-emotion-" + e : "";
  }

  function escapeHtml(s) {
    var div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function formatRuleBasedCoverTitle(title) {
    var t = String(title || "").trim();
    var limit = 10;
    if (t.length > limit) return t.slice(0, limit) + "...";
    return t;
  }

  function emotionalCaptionHtml(meta, styles) {
    if (!meta || !meta.text) return "";
    var pos = (meta.position === "top") ? "top" : "bottom";
    var delay = Number(meta.delay_ms || 0);
    if (!isFinite(delay) || delay < 0) delay = 0;
    var isLandscape = !!(styles && (styles.needs_blur || styles.background_blur));
    var text = String(meta.text || "").trim();
    if (!text) return "";
    var langCls = /[가-힣]/.test(text) ? "lang-ko" : "lang-en";
    var shapeCls = isLandscape ? "landscape" : "portrait";
    return (
      '<div class="emotional-caption ' +
      shapeCls + " " + pos + " " + langCls +
      '" style="animation-delay:' + delay + 'ms">' +
      escapeHtml(text) +
      "</div>"
    );
  }

  function slotHtml(mediaPath, styles, caption, fileType, emotionalMeta) {
    var url = toRawUrl(mediaPath);
    var isVideo = (fileType && fileType.toLowerCase() === "video") || isVideoPath(mediaPath);
    var hasFocus = !!focusXY(styles || {});
    var isBlurBg = !!(styles && (styles.needs_blur || styles.background_blur));
    // landscape blur은 살짝 위로 당겨 인물 상단 가림을 줄임(아주 미세)
    var blurY = (hasFocus && isBlurBg) ? -1.2 : 0;
    var blurPart = isVideo
      ? ""
      : '<img class="slot-blur"' +
        albumImgOpeningAttrs(mediaPath) +
        ' alt="" loading="lazy" decoding="async"' +
        focusStyleAttr(styles || {}, { yNudgePct: blurY }) +
        " />";
    var posStyle = hasFocus ? focusStyleAttr(styles || {}, { includeTransformOrigin: true, yNudgePct: (isBlurBg ? -0.6 : 0) }) : "";
    var fitCls = hasFocus ? "cover ai-subject" : "contain";
    var mediaPart = isVideo
      ? '<div class="slot-video-stack">' +
        '<img class="slot-blur-poster" src="" alt="" decoding="async" aria-hidden="true"' +
        focusStyleAttr(styles || {}, { yNudgePct: blurY }) +
        " />" +
        '<video class="slot-video" src="' + url + '" controls muted playsinline autoplay loop preload="auto"></video>' +
        "</div>"
      : '<img class="slot-img ' +
        fitCls +
        '"' +
        albumImgOpeningAttrs(mediaPath) +
        ' alt="" loading="lazy" decoding="async"' +
        posStyle +
        " />";
    var emotionalPart = emotionalCaptionHtml(emotionalMeta || null, styles || {});
    return (
      '<div class="media-frame album-media-container">' +
      blurPart +
      mediaPart +
      emotionalPart +
      "</div>"
    );
  }

  function coverSlotHtml(mediaPath, fileType, title, styles) {
    var url = toRawUrl(mediaPath);
    var isVideo = (fileType && fileType.toLowerCase() === "video") || isVideoPath(mediaPath);
    /* 앞표지만: 가로 이미지 시 상·하 검은 여백을 블러+확대 배경으로 채움 (내지 slotHtml과 별도) */
    var hasFocus = !!focusXY(styles || {});
    var isBlurBg = !!(styles && (styles.needs_blur || styles.background_blur));
    var blurY = (hasFocus && isBlurBg) ? -1.2 : 0;
    var blurPart = isVideo
      ? ""
      : '<img class="cover-bg-blur"' +
        albumImgOpeningAttrs(mediaPath) +
        ' alt="" loading="lazy" decoding="async" aria-hidden="true"' +
        focusStyleAttr(styles || {}, { yNudgePct: blurY }) +
        " />";
    var mediaPart = isVideo
      ? '<div class="slot-video-stack">' +
        '<img class="slot-blur-poster" src="" alt="" decoding="async" aria-hidden="true"' +
        focusStyleAttr(styles || {}, { yNudgePct: blurY }) +
        " />" +
        '<video class="slot-video" src="' + url + '" controls muted playsinline autoplay loop preload="auto"></video>' +
        "</div>"
      : '<img class="slot-img ' +
        (hasFocus ? "cover ai-subject" : "contain") +
        '"' +
        albumImgOpeningAttrs(mediaPath) +
        ' alt="" loading="lazy" decoding="async"' +
        (hasFocus ? focusStyleAttr(styles || {}, { includeTransformOrigin: true, yNudgePct: (isBlurBg ? -0.6 : 0) }) : "") +
        " />";
    var overlayTitle = formatRuleBasedCoverTitle(title);
    var overlayPart = '<div class="cover-title-overlay">' + escapeHtml(overlayTitle) + "</div>";
    return (
      '<div class="media-frame album-media-container cover-front">' +
      blurPart +
      mediaPart +
      overlayPart +
      "</div>"
    );
  }

  /** AI 콜라주 앞표지: 폴라로이드 3장 (cover_assets DOM 순서 = 하단→상단 z) */
  function coverCollageHtml(page) {
    var assets = page.cover_assets || [];
    var title = page.title || "";
    var overlayPart =
      '<div class="cover-title-overlay cover-title-collage">' +
      escapeHtml(formatRuleBasedCoverTitle(title)) +
      "</div>";
    var polaroids = "";
    for (var j = 0; j < assets.length; j++) {
      var a = assets[j];
      var styles = a.styles || {};
      var isLast = j === assets.length - 1;
      var hasFocus = !!focusXY(styles);
      var cls = "polaroid-img";
      if (isLast && hasFocus) cls += " slot-img cover ai-subject";
      var posStyle = hasFocus ? focusStyleAttr(styles, { includeTransformOrigin: true }) : "";
      polaroids +=
        '<figure class="polaroid polaroid-' +
        (j + 1) +
        '" data-z="' +
        (j + 1) +
        '">' +
        '<img class="' +
        cls +
        '"' +
        albumImgOpeningAttrs(a.path || "") +
        ' alt="" loading="lazy" decoding="async"' +
        posStyle +
        " />" +
        "</figure>";
    }
    return (
      '<div class="media-frame album-media-container cover-front cover-collage-wrap">' +
      '<div class="cover-polaroid-stack">' +
      polaroids +
      "</div>" +
      overlayPart +
      "</div>"
    );
  }

  function coverFooterHtml() {
    return '<div class="cover-footer"></div>';
  }

  function getCreatedDateForCover() {
    if (layout && layout.created_at) {
      try {
        var d = new Date(layout.created_at);
        if (!isNaN(d.getTime())) return d.toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric" });
      } catch (e) {}
    }
    return new Date().toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric" });
  }

  function backCoverHtml(projectIdVal, createdDate) {
    var shortId = (projectIdVal || "").toString().replace(/-/g, "").slice(-8) || "—";
    var featherSvg = '<svg class="cover-back-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3c-1.5 0-2.5 1.5-3 3L4 20l4-4 5-5 2-5c-1.5-.5-3 0-3 0z"/><path d="M12 8l4 4"/></svg>';
    var center = '<div class="cover-back-center">' + featherSvg + '<p class="cover-back-copy">우리의 이야기는 계속됩니다.</p></div>';
    var meta = '<div class="cover-back-meta">Created on: ' + escapeHtml(createdDate) + '<br>Project ID: ' + escapeHtml(shortId) + '</div>';
    var brand = '<div class="cover-back-brand">Flairy v4.0<span class="copyright">© 2026 Flairy. All rights reserved.</span></div>';
    return '<div class="cover-back">' + '<div class="cover-back-spine-shadow" aria-hidden="true"></div>' + center + meta + brand + '</div>';
  }

  /**
   * 가로 영상만: 재생 영상의 한 프레임을 캔버스로 그려 img.slot-blur-poster에 넣어 엠비언트 블러 배경으로 사용.
   * (이중 video 블러는 디코딩 전 검은 화면이 자주 보여 정적 썸네일 방식으로 통일)
   */
  function captureVideoFrameToAmbientPoster(frame, video) {
    var posterImg = frame.querySelector("img.slot-blur-poster");
    if (!posterImg || !frame.classList.contains("is-landscape")) return;
    // 모바일에서는 seek 기반 프레임 캡처를 비활성화해 재생 안정성을 우선한다.
    if (!isDesktop()) return;
    var maxDim = 960;
    function drawAndAssign() {
      try {
        var vw = video.videoWidth || 0;
        var vh = video.videoHeight || 0;
        if (!vw || !vh) return;
        var scale = Math.min(1, maxDim / vw, maxDim / vh);
        var cw = Math.max(1, Math.floor(vw * scale));
        var ch = Math.max(1, Math.floor(vh * scale));
        var canvas = document.createElement("canvas");
        canvas.width = cw;
        canvas.height = ch;
        var ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.drawImage(video, 0, 0, cw, ch);
        posterImg.src = canvas.toDataURL("image/jpeg", 0.82);
        posterImg.classList.add("slot-blur-poster--ready");
      } catch (err) {
        console.warn("[Album] ambient poster capture failed (CORS/보안)", err);
      }
    }
    try {
      var savedTime = video.currentTime;
      var dur = video.duration;
      var seekTo = 0.08;
      if (typeof dur === "number" && !isNaN(dur) && dur > 0) {
        seekTo = Math.min(0.15, Math.max(0.04, dur * 0.02));
      }
      function ensurePlayback() {
        try {
          video.muted = true;
          var p = video.play();
          if (p && typeof p.catch === "function") p.catch(function () {});
        } catch (e) {}
      }
      function afterSeek() {
        try {
          drawAndAssign();
        } finally {
          try {
            video.currentTime = savedTime;
          } catch (e) {}
          ensurePlayback();
        }
      }
      function runSeek() {
        try {
          video.currentTime = seekTo;
        } catch (e) {
          drawAndAssign();
          ensurePlayback();
          return;
        }
        video.addEventListener(
          "seeked",
          function onSeeked() {
            video.removeEventListener("seeked", onSeeked);
            afterSeek();
          },
          { once: true, passive: true }
        );
      }
      if (video.readyState >= 2) {
        runSeek();
      } else {
        video.addEventListener(
          "loadeddata",
          function onLd() {
            video.removeEventListener("loadeddata", onLd);
            runSeek();
          },
          { once: true, passive: true }
        );
      }
    } catch (err) {
      console.warn("[Album] ambient poster pipeline failed", err);
      try {
        video.muted = true;
        var pp = video.play();
        if (pp && typeof pp.catch === "function") pp.catch(function () {});
      } catch (e) {}
    }
  }

  function setupVideoInPage(container) {
    if (!container) return;

    container.querySelectorAll(".media-frame img.slot-img").forEach(function (img) {
      function apply() {
        var w = img.naturalWidth || 0;
        var h = img.naturalHeight || 0;
        if (!w || !h) return;
        var frame = img.closest(".media-frame");
        if (!frame) return;
        if (frame.classList.contains("cover-collage-wrap")) return;
        frame.classList.toggle("is-portrait", h >= w);
        frame.classList.toggle("is-landscape", w > h);
      }
      if (img.complete) apply();
      else img.addEventListener("load", apply, { once: true, passive: true });
    });

    container.querySelectorAll(".media-frame video.slot-video").forEach(function (video) {
      video.addEventListener("click", function (e) { e.stopPropagation(); }, { passive: true });
      video.closest(".media-frame").addEventListener("click", function (e) { e.stopPropagation(); }, { passive: true });

      video.addEventListener("loadedmetadata", function () {
        var w = video.videoWidth || 0;
        var h = video.videoHeight || 0;
        if (!w || !h) return;
        var frame = video.closest(".media-frame");
        if (!frame) return;
        frame.classList.toggle("is-portrait", h >= w);
        frame.classList.toggle("is-landscape", w > h);
        if (w > h) {
          captureVideoFrameToAmbientPoster(frame, video);
        }
      }, { once: true, passive: true });

      if (!albumVideoObserver) {
        albumVideoObserver = new IntersectionObserver(
          function (entries) {
            entries.forEach(function (entry) {
              var v = entry.target;
              if (entry.isIntersecting) {
                v.play().catch(function () {});
              } else {
                v.pause();
              }
            });
          },
          { threshold: 0.5, root: null }
        );
      }
      albumVideoObserver.observe(video);
    });
  }

  function disconnectVideoObserver() {
    if (albumVideoObserver) {
      albumVideoObserver.disconnect();
    }
  }

  function playVisibleVideos(scopeNode) {
    var root = scopeNode || document;
    var videos = root.querySelectorAll("video.slot-video");
    videos.forEach(function (video) {
      try {
        video.muted = true;
        video.setAttribute("muted", "");
        video.setAttribute("playsinline", "");
        video.setAttribute("autoplay", "");
        video.setAttribute("loop", "");
        var p = video.play();
        if (p && typeof p.catch === "function") {
          p.catch(function (err) {
            console.log("[Album] autoplay safeguard:", err);
          });
        }
      } catch (e) {
        console.log("[Album] autoplay safeguard:", e);
      }
    });
  }

  function getPageLabel(page, index, total) {
    if (!page) return "";
    if (index === 0 || page.type === "front") return "앞표지";
    if (index === total - 1 || page.type === "back") return "뒷표지";
    if (page.type === "spread") {
      var leftPage = 2 * (index - 1) + 1;
      var rightPage = leftPage + 1;
      return leftPage + " / " + rightPage;
    }
    return String(index);
  }

  function getMobileSlotLabel(slot, slotIndex, totalSlots) {
    if (!slot) return "";
    if (slotIndex === 0 || slot.kind === "front") return "앞표지";
    if (slotIndex === totalSlots - 1 || slot.kind === "back") return "뒷표지";
    if (slot.kind === "half") {
      // PC spread의 좌/우 페이지 번호와 모바일 싱글 번호를 동일하게 맞춘다.
      var leftPage = 2 * (slot.pageIndex - 1) + 1;
      return String(slot.side === "left" ? leftPage : (leftPage + 1));
    }
    return String(slotIndex);
  }

  function renderPageContent(page, index, total) {
    if (page.type === "front") {
      var leftBg = (page.styles && page.styles.left && page.styles.left.bg_color_hex) ? page.styles.left.bg_color_hex : "";
      var rightBg = (page.styles && page.styles.right && page.styles.right.bg_color_hex) ? page.styles.right.bg_color_hex : "";
      var leftStyle = leftBg ? ' style="background-color:' + leftBg + '"' : "";
      var rightStyle = rightBg ? ' style="background-color:' + rightBg + '"' : "";
      var leftHtml =
        '<div class="spread-half spread-half-blank"' + leftStyle + ">" +
        '<div class="page-content">' +
        '<div class="media-frame media-frame-placeholder"></div>' +
        "</div></div>";
      var rightHtmlInner =
        page.layout_type === "collage" && page.cover_assets && page.cover_assets.length
          ? coverCollageHtml(page)
          : page.right
            ? coverSlotHtml(page.right, (page.file_types && page.file_types.right) || "", page.title || "", (page.styles && page.styles.right) || {})
            : '<div class="media-frame media-frame-placeholder"></div>';
      var rightHtml =
        '<div class="spread-half spread-half-cover-right"' + rightStyle + ">" +
        '<div class="page-content page-content-cover-right">' +
        rightHtmlInner +
        "</div></div>";
      return '<div class="spread-row">' + leftHtml + rightHtml + "</div>";
    }
    if (page.type === "back") {
      var createdDate = getCreatedDateForCover();
      var leftHtml =
        '<div class="spread-half spread-half-back-cover">' +
        '<div class="cover-back" style="border-radius: 4px 0 0 4px;"></div></div>';
      var rightHtml =
        '<div class="spread-half spread-half-back-cover">' +
        backCoverHtml(projectId, createdDate) +
        "</div>";
      return '<div class="spread-row">' + leftHtml + rightHtml + "</div>";
    }
    if (page.type === "spread") {
      var leftBg = (page.styles && page.styles.left && page.styles.left.bg_color_hex) ? page.styles.left.bg_color_hex : "";
      var rightBg = (page.styles && page.styles.right && page.styles.right.bg_color_hex) ? page.styles.right.bg_color_hex : "";
      var leftStyle = leftBg ? ' style="background-color:' + leftBg + '"' : "";
      var rightStyle = rightBg ? ' style="background-color:' + rightBg + '"' : "";
      var leftHtml =
        '<div class="spread-half"' + leftStyle + ">" +
        '<div class="page-content">' +
        (page.left
          ? slotHtml(
              page.left,
              (page.styles && page.styles.left) || {},
              (page.captions && page.captions.left) || "",
              (page.file_types && page.file_types.left) || "",
              (page.emotional_captions && page.emotional_captions.left) || null
            )
          : '<div class="media-frame media-frame-placeholder">빈 페이지</div>') +
        "</div></div>";
      var rightHtml =
        '<div class="spread-half"' + rightStyle + ">" +
        '<div class="page-content">' +
        (page.right
          ? slotHtml(
              page.right,
              (page.styles && page.styles.right) || {},
              (page.captions && page.captions.right) || "",
              (page.file_types && page.file_types.right) || "",
              (page.emotional_captions && page.emotional_captions.right) || null
            )
          : '<div class="media-frame media-frame-placeholder">빈 페이지</div>') +
        "</div></div>";
      return '<div class="spread-row">' + leftHtml + rightHtml + "</div>";
    }
    return "";
  }

  var layout = null;
  var currentIndex = 0;
  var mobileSlots = [];
  var MOBILE_BUFFER_RADIUS = 3;
  var MOBILE_BREAKPOINT = 1024;
  var lastWidth = typeof window !== "undefined" ? window.innerWidth : 0;
  var lastDesktopMode = null;
  var resizeTimeout = null;
  var lastDebugIndex = -1;
  var cachedPageDisplayMidX = null;
  var cachedBookContainerMidX = null;
  var FLIP_ANIM_MS = 1200;
  var flipTokenSeed = 0;

  function isDesktop() {
    return typeof window !== "undefined" && window.innerWidth >= MOBILE_BREAKPOINT;
  }

  function refreshClickZoneMidXs() {
    cachedPageDisplayMidX = null;
    cachedBookContainerMidX = null;
    var pd = document.getElementById("pageDisplay");
    var bc = document.getElementById("bookContainer");
    if (pd) {
      var r = pd.getBoundingClientRect();
      cachedPageDisplayMidX = r.left + r.width / 2;
    }
    if (bc) {
      var r2 = bc.getBoundingClientRect();
      cachedBookContainerMidX = r2.left + r2.width / 2;
    }
  }

  function slotFromPageHalf(page, side) {
    var path, styles, caption, ft, emotional;
    if (side === "right") {
      path = page.right;
      styles = (page.styles && page.styles.right) || {};
      caption = (page.captions && page.captions.right) || (page.title || "") || "";
      ft = (page.file_types && page.file_types.right) || "";
      emotional = (page.emotional_captions && page.emotional_captions.right) || null;
    } else {
      path = page.left;
      styles = (page.styles && page.styles.left) || {};
      caption = (page.captions && page.captions.left) || (page.caption || "") || "";
      ft = (page.file_types && page.file_types.left) || "";
      emotional = (page.emotional_captions && page.emotional_captions.left) || null;
    }
    var media = path
      ? slotHtml(path, styles, "", ft, emotional)
      : '<div class="media-frame media-frame-placeholder"></div>';
    var emotion = (styles && styles.emotion) ? String(styles.emotion).trim().toLowerCase().replace(/\s+/g, "-") : "";
    var bgColorHex = (styles && styles.bg_color_hex) ? styles.bg_color_hex : null;
    var accentColorHex = (styles && styles.accent_color_hex) ? styles.accent_color_hex : null;
    return { media: media, caption: caption || "", emotion: emotion, bgColorHex: bgColorHex, accentColorHex: accentColorHex };
  }

  function spineColorForHex(hex) {
    if (!hex || typeof hex !== "string") return "";
    var cc = contrastColorForHex(hex);
    if (cc === "#fff" || cc === "#ffffff") return "rgba(255,255,255,0.25)";
    return "rgba(0,0,0,0.25)";
  }

  function buildLeafCaptionBar(caption, pageNum, emotion, bgColorHex, accentColorHex) {
    // 하단 감성 자막/페이지 번호는 임시 비활성화(추후 고도화 예정).
    return "";
  }

  function buildMobileSlots(pages) {
    var slots = [];
    if (!pages || !pages.length) return slots;
    for (var i = 0; i < pages.length; i++) {
      var p = pages[i];
      if (!p) continue;
      if (p.type === "front") {
        if (p.right) slots.push({ kind: "front", page: p, pageIndex: i });
        continue;
      }
      if (p.type === "back") {
        slots.push({ kind: "back", page: p, pageIndex: i });
        continue;
      }
      if (p.type === "spread") {
        if (p.left) slots.push({ kind: "half", side: "left", page: p, pageIndex: i });
        if (p.right) slots.push({ kind: "half", side: "right", page: p, pageIndex: i });
      }
    }
    return slots;
  }

  function renderMobileSlot(slot, index) {
    var pageNum = index + 1;
    if (!slot) return '<div class="media-frame media-frame-placeholder"></div>';
    if (slot.kind === "front") {
      var fp = slot.page;
      if (fp.layout_type === "collage" && fp.cover_assets && fp.cover_assets.length) {
        return coverCollageHtml(fp) + coverFooterHtml();
      }
      return fp.right
        ? coverSlotHtml(fp.right, (fp.file_types && fp.file_types.right) || "", fp.title || "", (fp.styles && fp.styles.right) || {}) + coverFooterHtml()
        : '<div class="media-frame media-frame-placeholder"></div>' + coverFooterHtml();
    }
    if (slot.kind === "back") {
      return backCoverHtml(projectId, getCreatedDateForCover());
    }
    var half = slotFromPageHalf(slot.page, slot.side);
    return half.media + buildLeafCaptionBar(half.caption, pageNum, half.emotion, half.bgColorHex, half.accentColorHex);
  }

  function createMobileLeaf(index, totalLeaves) {
    var leaf = document.createElement("div");
    leaf.className = "leaf leaf-mobile";
    leaf.dataset.leafIndex = String(index);
    leaf.style.zIndex = String(totalLeaves - index);
    var frontHtml = renderMobileSlot(mobileSlots[index], index);
    frontHtml = frontHtml.replace(/(<img\b[^>]*?)\ssrc="([^"]*)"/g, "$1 data-src=\"$2\"");
    leaf.innerHTML =
      '<div class="leaf-inner">' +
      '<div class="leaf-face front" style="background-color:#f0f0f0">' +
      '<div class="shadow-overlay" aria-hidden="true"></div>' +
      '<div class="leaf-spine-shadow" aria-hidden="true"></div>' +
      '<div class="leaf-face-content">' + frontHtml + "</div>" +
      "</div>" +
      '<div class="leaf-face back" style="background-color:#f0f0f0">' +
      '<div class="shadow-overlay" aria-hidden="true"></div>' +
      '<div class="leaf-spine-shadow" aria-hidden="true"></div>' +
      '<div class="leaf-face-content leaf-face-content--paper-back" aria-hidden="true"></div>' +
      "</div>" +
      "</div>";
    leaf.querySelectorAll("img").forEach(function (img) {
      img.setAttribute("decoding", "async");
      img.setAttribute("loading", "lazy");
    });
    // 가상화 purge/inject를 위해 비디오 원본 src를 data-src에 보관한다.
    leaf.querySelectorAll("video").forEach(function (v) {
      var s = v.getAttribute("src");
      if (s && !v.getAttribute("data-src")) {
        v.setAttribute("data-src", s);
      }
    });
    return leaf;
  }

  function injectLeafMedia(leaf, centerIndex) {
    if (!leaf) return;
    var idx = Number(leaf.dataset.leafIndex || "-1");
    var isVisibleNow = idx === centerIndex;
    leaf.querySelectorAll(".leaf-face-content").forEach(function (content) {
      var backup = content.getAttribute("data-media-backup");
      if (!backup) return;
      if (content.querySelector("img,video")) return;
      try {
        content.innerHTML = decodeURIComponent(backup);
      } catch (e) {
        console.warn("[Album] media backup restore failed", e);
      }
    });
    leaf.querySelectorAll("img[data-src]").forEach(function (img) {
      var ds = img.getAttribute("data-src");
      if (!ds) return;
      if (!img.getAttribute("src")) {
        if (isMobileAlbum) {
          var pid = "";
          var fn = "";
          var rmRaw = ds.match(/^\/raw\/([^/]+)\/([^?#]+)$/);
          if (rmRaw) {
            pid = String(rmRaw[1]).trim();
            fn = decodeURIComponent(rmRaw[2]);
          } else {
            var rmApi = ds.match(/^\/api\/media\/image\/([^/]+)\/([^?#]+)/);
            if (rmApi) {
              pid = decodeURIComponent(rmApi[1]).trim();
              fn = decodeURIComponent(rmApi[2]);
            }
          }
          if (pid && fn && isRasterImageFilename(fn)) {
            img.setAttribute("src", toAlbumImageUrl(pid, fn, { w: 960 }));
            img.setAttribute(
              "srcset",
              toAlbumImageUrl(pid, fn, { w: 640 }) +
                " 640w, " +
                toAlbumImageUrl(pid, fn, { w: 960 }) +
                " 960w, " +
                toAlbumImageUrl(pid, fn, { w: 1080 }) +
                " 1080w"
            );
            img.setAttribute("sizes", "100vw");
          } else {
            img.setAttribute("src", ds);
          }
        } else {
          img.removeAttribute("srcset");
          img.removeAttribute("sizes");
          img.setAttribute("src", ds);
        }
      }
      img.setAttribute("decoding", "async");
      img.setAttribute("loading", isVisibleNow ? "eager" : "lazy");
    });
    leaf.querySelectorAll("video").forEach(function (v) {
      var originalSrc = v.getAttribute("data-src");
      if (originalSrc && !v.getAttribute("src")) {
        v.setAttribute("src", originalSrc);
        try {
          v.load(); // src 복구 후 미디어 파이프라인 재초기화
        } catch (e) {}
      }
    });
    leaf.style.willChange = "transform";
  }

  function purgeLeafMedia(leaf) {
    if (!leaf) return;
    leaf.querySelectorAll(".leaf-face-content").forEach(function (content) {
      if (!content.getAttribute("data-media-backup")) {
        content.setAttribute("data-media-backup", encodeURIComponent(content.innerHTML));
      }
      content.setAttribute("data-media-kind", "img-video");
    });
    leaf.querySelectorAll("video, img").forEach(function (el) {
      var tag = (el.tagName || "").toLowerCase();
      var src = el.getAttribute("src");
      if (src && !el.getAttribute("data-src")) {
        el.setAttribute("data-src", src);
      }
      if (!el.getAttribute("data-type")) {
        el.setAttribute("data-type", tag);
      }
      if (!el.getAttribute("data-class")) {
        el.setAttribute("data-class", el.className || "");
      }
      try {
        if (tag === "video" && typeof el.pause === "function") el.pause();
      } catch (e) {}
      try {
        el.setAttribute("src", "");
      } catch (e) {}
      try {
        if (tag === "video" && typeof el.load === "function") {
          el.load();
        }
      } catch (e) {}
      try {
        el.remove();
      } catch (e) {}
    });
    leaf.style.display = "none";
    leaf.style.visibility = "hidden";
    leaf.style.opacity = "0";
    leaf.style.pointerEvents = "none";
    leaf.style.willChange = "auto";
  }

  function countLeafMediaNodes(leaf) {
    if (!leaf) return 0;
    var c = 0;
    leaf.querySelectorAll(".leaf-face-content").forEach(function (content) {
      var backup = content.getAttribute("data-media-backup");
      if (!backup) return;
      try {
        var html = decodeURIComponent(backup);
        var matches = html.match(/<(img|video)\b/gi);
        if (matches) c += matches.length;
      } catch (e) {}
    });
    return c;
  }

  function renderMobileWindow(centerIndex) {
    var bookBodyEl = document.getElementById("bookBody");
    if (!bookBodyEl || !mobileSlots.length) return;
    var total = mobileSlots.length;
    var dbgInject = 0;
    var dbgRemovedNodes = 0;
    for (var i = 0; i < total; i++) {
      var leaf = bookBodyEl.querySelector('.leaf-mobile[data-leaf-index="' + i + '"]');
      if (!leaf) continue;
      var inBuf = i >= centerIndex - MOBILE_BUFFER_RADIUS && i <= centerIndex + MOBILE_BUFFER_RADIUS;
      if (inBuf) {
        leaf.style.display = "";
        leaf.style.visibility = "visible";
        leaf.style.opacity = "1";
        leaf.style.pointerEvents = "";
        injectLeafMedia(leaf, centerIndex);
        dbgInject++;
      } else {
        dbgRemovedNodes += countLeafMediaNodes(leaf);
        purgeLeafMedia(leaf);
      }
    }
    if (window.__ALBUM_DEBUG__) {
      console.log(
        "[DEBUG] renderMobileWindow center=%s inject=%s removedMediaNodes=%s",
        centerIndex,
        dbgInject,
        dbgRemovedNodes
      );
    }
  }

  function clearTouchAreas(bookBodyEl) {
    if (!bookBodyEl) return;
    bookBodyEl.querySelectorAll(".touch-area").forEach(function (el) {
      el.remove();
    });
  }

  function attachTouchAreas(bookBodyEl) {
    if (!bookBodyEl || isDesktop()) return;
    clearTouchAreas(bookBodyEl);
    var left = document.createElement("div");
    left.className = "touch-area touch-area-left";
    left.setAttribute("aria-hidden", "true");
    left.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      goPrev();
    });
    var right = document.createElement("div");
    right.className = "touch-area touch-area-right";
    right.setAttribute("aria-hidden", "true");
    right.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      goNext();
    });
    bookBodyEl.appendChild(left);
    bookBodyEl.appendChild(right);
  }

  function buildMobileLeaves() {
    var bookBodyEl = document.getElementById("bookBody");
    if (!bookBodyEl || !mobileSlots.length) return;
    bookBodyEl.innerHTML = "";
    var total = mobileSlots.length;
    for (var i = 0; i < total; i++) {
      bookBodyEl.appendChild(createMobileLeaf(i, total));
    }
    console.log("[DEBUG] buildMobileLeaves count:", bookBodyEl.querySelectorAll(".leaf-mobile").length);
    renderMobileWindow(currentIndex);
    attachTouchAreas(bookBodyEl);
    setupVideoInPage(bookBodyEl);
  }

  function maxIndexForMode() {
    if (isDesktop()) return Math.max(0, (layout && layout.pages && layout.pages.length) ? layout.pages.length - 1 : 0);
    return Math.max(0, (mobileSlots && mobileSlots.length) ? mobileSlots.length - 1 : 0);
  }

  function ensureAlbumImgDecodingAsync() {
    var root = document.getElementById("flipbookRoot");
    if (root) {
      root.querySelectorAll("img").forEach(function (img) {
        if (!img.getAttribute("decoding")) img.setAttribute("decoding", "async");
      });
    }
    var bar = document.getElementById("thumbBar");
    if (bar) {
      bar.querySelectorAll("img").forEach(function (img) {
        if (!img.getAttribute("decoding")) img.setAttribute("decoding", "async");
      });
    }
  }

  function checkLayout() {
    if (!layout || !layout.pages || !layout.pages.length) return;
    var nowDesktop = isDesktop();
    if (lastDesktopMode !== null && lastDesktopMode !== nowDesktop) {
      currentIndex = 0;
    }
    lastDesktopMode = nowDesktop;
    var bookBodyEl = document.getElementById("bookBody");
    if (bookBodyEl) {
      clearTouchAreas(bookBodyEl);
      bookBodyEl.innerHTML = "";
    }
    buildThumbnailBar();
    if (nowDesktop) buildLeaves();
    else buildMobileLeaves();
    syncLeavesState();
    updateShadowOverlays();
    ensureAlbumImgDecodingAsync();
    requestAnimationFrame(function () {
      refreshClickZoneMidXs();
    });
  }

  function buildLeaves() {
    console.log("[Album] buildLeaves() entered, layout.pages length=" + (layout && layout.pages ? layout.pages.length : 0));
    if (!layout || !layout.pages || layout.pages.length < 2) {
      console.warn("[Album] buildLeaves early exit: need at least 2 pages");
      return;
    }
    var pages = layout.pages;
    var totalLeaves = pages.length - 1;
    var bookBodyEl = document.getElementById("bookBody");
    if (!bookBodyEl) {
      console.warn("[Album] buildLeaves: bookBody not found");
      return;
    }
    bookBodyEl.innerHTML = "";
    for (var i = 0; i < totalLeaves; i++) {
      var front = slotFromPageHalf(pages[i], "right");
      var back = slotFromPageHalf(pages[i + 1], "left");
      var frontPageNum = 2 * i + 2;
      var backPageNum = 2 * i + 3;
      var frontHtml;
      if (i === 0 && pages[i].type === "front") {
        if (pages[i].layout_type === "collage" && pages[i].cover_assets && pages[i].cover_assets.length) {
          frontHtml = coverCollageHtml(pages[i]) + coverFooterHtml();
        } else {
          frontHtml = pages[i].right
            ? coverSlotHtml(pages[i].right, (pages[i].file_types && pages[i].file_types.right) || "", pages[i].title || "", (pages[i].styles && pages[i].styles.right) || {}) + coverFooterHtml()
            : '<div class="media-frame media-frame-placeholder"></div>' + coverFooterHtml();
        }
      } else {
        frontHtml = front.media + buildLeafCaptionBar(front.caption, frontPageNum, front.emotion, front.bgColorHex, front.accentColorHex);
      }
      var backHtml;
      if (i === totalLeaves - 1 && pages[i + 1].type === "back") {
        backHtml = backCoverHtml(projectId, getCreatedDateForCover());
      } else {
        backHtml = back.media + buildLeafCaptionBar(back.caption, backPageNum, back.emotion, back.bgColorHex, back.accentColorHex);
      }
      var frontBg = (front.bgColorHex && front.bgColorHex.trim()) ? front.bgColorHex.trim() : "#f0f0f0";
      var backBg = (back.bgColorHex && back.bgColorHex.trim()) ? back.bgColorHex.trim() : "#f0f0f0";
      var frontSpine = spineColorForHex(front.bgColorHex);
      var backSpine = spineColorForHex(back.bgColorHex);
      var frontFaceStyle = 'style="background-color:' + frontBg + (frontSpine ? ";--spine-color:" + frontSpine : "") + '"';
      var backFaceStyle = 'style="background-color:' + backBg + (backSpine ? ";--spine-color:" + backSpine : "") + '"';
      var leaf = document.createElement("div");
      leaf.className = "leaf leaf-pc";
      leaf.dataset.leafIndex = String(i);
      leaf.innerHTML =
        '<div class="leaf-inner">' +
        '<div class="leaf-face front" ' + frontFaceStyle + '>' +
        '<div class="shadow-overlay" aria-hidden="true"></div>' +
        '<div class="leaf-spine-shadow" aria-hidden="true"></div>' +
        '<div class="leaf-face-content">' + frontHtml + "</div>" +
        "</div>" +
        '<div class="leaf-face back" ' + backFaceStyle + '>' +
        '<div class="shadow-overlay" aria-hidden="true"></div>' +
        '<div class="leaf-spine-shadow" aria-hidden="true"></div>' +
        '<div class="leaf-face-content">' + backHtml + "</div>" +
        "</div>" +
        "</div>";
      bookBodyEl.appendChild(leaf);
    }
    console.log("[Album] buildLeaves: appended " + totalLeaves + " leaves to #bookBody");
    setupVideoInPage(bookBodyEl);
  }

  function syncLeavesState() {
    if (!layout || !layout.pages) return;
    if (isDesktop()) {
      var leaves = document.querySelectorAll("#bookBody .leaf-pc");
      var totalLeaves = leaves.length;
      if (totalLeaves <= 0) return;
      for (var i = 0; i < leaves.length; i++) {
        var leaf = leaves[i];
        var leafIndex = Number(leaf.dataset.leafIndex || i);
        var isFlipped = leafIndex < currentIndex;
        leaf.classList.toggle("flipped", isFlipped);
        if (leaf.classList.contains("is-flipping")) {
          continue;
        }
        // 레이어 대역 분리: flipped(낮은 대역), non-flipped(높은 대역)
        leaf.style.zIndex = isFlipped
          ? String(leafIndex)
          : String((totalLeaves * 2) - leafIndex);
      }
    } else {
      var mobileLeaves = document.querySelectorAll("#bookBody .leaf-mobile");
      var totalMobile = mobileLeaves.length;
      if (totalMobile <= 0) return;
      for (var m = 0; m < mobileLeaves.length; m++) {
        var mLeaf = mobileLeaves[m];
        var idx = Number(mLeaf.dataset.leafIndex || "-1");
        if (idx < 0) continue;
        var mFlipped = idx < currentIndex;
        mLeaf.classList.toggle("flipped", mFlipped);
        if (mLeaf.classList.contains("is-flipping")) {
          continue;
        }
        // 레이어 대역 분리: flipped(낮은 대역), non-flipped(높은 대역)
        mLeaf.style.zIndex = mFlipped
          ? String(idx)
          : String((totalMobile * 2) - idx);
      }
    }

    // GPU 예약 최소화: 현재/인접 리프만 will-change 유지
    var activeWindow = {};
    activeWindow[currentIndex] = true;
    activeWindow[currentIndex + 1] = true;
    activeWindow[currentIndex - 1] = true;
    document.querySelectorAll("#bookBody .leaf").forEach(function (leafEl) {
      var idxVal = Number(leafEl.dataset.leafIndex || "-1");
      if (activeWindow[idxVal]) {
        leafEl.style.willChange = "transform";
      } else {
        leafEl.style.willChange = "auto";
      }
    });

    if (window.__ALBUM_DEBUG__) {
      if (currentIndex !== lastDebugIndex) {
        lastDebugIndex = currentIndex;
        var allLeaves = document.querySelectorAll("#bookBody .leaf");
        console.table(Array.from(allLeaves).map(function (leaf) {
          return {
            index: leaf.dataset.leafIndex,
            zIndex: window.getComputedStyle(leaf).zIndex,
            transform: window.getComputedStyle(leaf).transform,
            isFlipped: leaf.classList.contains("flipped"),
            opacity: window.getComputedStyle(leaf).opacity,
            width: window.getComputedStyle(leaf).width
          };
        }));
        console.log("[DEBUG] CurrentStep:", currentIndex);
        document.querySelectorAll("#bookBody .leaf").forEach(function (l) {
          console.log(
            "Leaf " + l.dataset.leafIndex +
            " | Flipped: " + l.classList.contains("flipped") +
            " | zIndex: " + l.style.zIndex
          );
        });
      }
    }
  }

  function updateShadowOverlays() {
    document.querySelectorAll("#bookBody .leaf").forEach(function (leaf) {
      leaf.classList.remove("shadow-next");
    });
    var nextIdx = currentIndex + 1;
    var sel = isDesktop()
      ? '#bookBody .leaf-pc[data-leaf-index="' + nextIdx + '"]'
      : '#bookBody .leaf-mobile[data-leaf-index="' + nextIdx + '"]';
    var nextLeaf = document.querySelector(sel);
    if (nextLeaf) nextLeaf.classList.add("shadow-next");
  }

  function updateIndicatorAndThumb(index) {
    if (!layout || !layout.pages) return;
    var pageIndicator = document.getElementById("pageIndicator");
    if (isDesktop()) {
      var page = layout.pages[index];
      var total = layout.pages.length;
      if (pageIndicator) pageIndicator.textContent =
        getPageLabel(page, index, total) + " (" + (index + 1) + " / " + total + ")";
    } else {
      var mobileTotal = mobileSlots.length || 1;
      if (pageIndicator) pageIndicator.textContent = getMobileSlotLabel(mobileSlots[index], index, mobileTotal);
    }
    document.querySelectorAll(".thumb-item").forEach(function (el, i) {
      el.classList.toggle("active", i === index);
    });
    var bar = document.getElementById("thumbBar");
    var activeThumb = bar && bar.querySelector(".thumb-item.active");
    if (activeThumb) {
      activeThumb.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
    }
  }

  function showPage(index) {
    console.log("[Album] showPage(" + index + ")");
    if (!layout || !layout.pages || !layout.pages.length) return;
    var maxIdx = maxIndexForMode();
    currentIndex = Math.max(0, Math.min(index, maxIdx));
    updateIndicatorAndThumb(currentIndex);
    applyKenBurnsForCurrent();
    if (isDesktop()) {
      syncLeavesState();
      updateShadowOverlays();
      playVisibleVideos(document.getElementById("bookBody"));
    } else {
      var bookBodyEl = document.getElementById("bookBody");
      renderMobileWindow(currentIndex);
      attachTouchAreas(bookBodyEl);
      setupVideoInPage(bookBodyEl);
      syncLeavesState();
      updateShadowOverlays();
      playVisibleVideos(bookBodyEl);
    }
    requestAnimationFrame(function () {
      refreshClickZoneMidXs();
    });
  }

  function applyKenBurnsForCurrent() {
    // 비디오는 제외. AI focus_offset이 있는 이미지만 대상(.ai-subject)
    try {
      document.querySelectorAll("img.slot-img.ai-subject").forEach(function (img) {
        img.style.animation = "none";
      });
    } catch (e) {}

    if (!layout || !layout.pages) return;

    var targets = [];
    if (isDesktop()) {
      var leftLeaf = getLeafByIndex(currentIndex - 1);
      var rightLeaf = getLeafByIndex(currentIndex);
      if (leftLeaf) {
        leftLeaf.querySelectorAll(".leaf-face.back img.slot-img.ai-subject").forEach(function (img) {
          targets.push(img);
        });
      }
      if (rightLeaf) {
        rightLeaf.querySelectorAll(".leaf-face.front img.slot-img.ai-subject").forEach(function (img) {
          targets.push(img);
        });
      }
    } else {
      var curLeaf = getLeafByIndex(currentIndex);
      if (curLeaf) {
        curLeaf.querySelectorAll(".leaf-face.front img.slot-img.ai-subject").forEach(function (img) {
          targets.push(img);
        });
      }
    }
    if (!targets.length) return;
    requestAnimationFrame(function () {
      targets.forEach(function (img) {
        try {
          void img.offsetHeight;
        } catch (e) {}
      });
      requestAnimationFrame(function () {
        targets.forEach(function (img) {
          try {
            var dur = 5 + Math.random() * 3;
            img.style.animation = "ai-motion-zoompan " + dur.toFixed(2) + "s ease-in-out 1 forwards";
          } catch (e) {}
        });
      });
    });
  }

  function playPageFlipSound(direction) {
    try {
      pageFlipAudio.currentTime = 0;
      pageFlipAudio.volume = direction === "next" ? 0.4 : 0.35;
      pageFlipAudio.play().catch(function () {});
    } catch (e) {}
  }

  function leafSelectorForMode(index) {
    var cls = isDesktop() ? "leaf-pc" : "leaf-mobile";
    return '#bookBody .' + cls + '[data-leaf-index="' + index + '"]';
  }

  function getLeafByIndex(index) {
    if (index == null || index < 0) return null;
    return document.querySelector(leafSelectorForMode(index));
  }

  function markLeafFlipping(leaf, direction) {
    if (!leaf) return;
    var token = String(++flipTokenSeed);
    leaf.dataset.flipToken = token;
    leaf.classList.add("is-flipping");
    if (window.__ALBUM_DEBUG__) {
      console.log(
        "[DEBUG] flip-start leaf=" + (leaf.dataset.leafIndex || "?") +
        " dir=" + direction + " z=" + window.getComputedStyle(leaf).zIndex
      );
    }
    var settled = false;
    var onDone = function () {
      if (settled) return;
      settled = true;
      if (leaf.dataset.flipToken !== token) return;
      leaf.classList.remove("is-flipping");
      leaf.removeEventListener("transitionend", onTransitionEnd);
      if (window.__ALBUM_DEBUG__) {
        console.log(
          "[DEBUG] flip-end leaf=" + (leaf.dataset.leafIndex || "?") +
          " dir=" + direction + " z=" + window.getComputedStyle(leaf).zIndex
        );
      }
      syncLeavesState();
      updateShadowOverlays();
    };
    var onTransitionEnd = function (evt) {
      if (!evt || evt.propertyName === "transform") {
        onDone();
      }
    };
    leaf.addEventListener("transitionend", onTransitionEnd, { passive: true });
    setTimeout(onDone, FLIP_ANIM_MS + 80);
  }

  function goNext() {
    if (!layout || !layout.pages || currentIndex >= maxIndexForMode()) return;
    var flippingLeaf = getLeafByIndex(currentIndex);
    markLeafFlipping(flippingLeaf, "next");
    playPageFlipSound("next");
    showPage(currentIndex + 1);
  }

  function goPrev() {
    if (!layout || !layout.pages || currentIndex <= 0) return;
    var flippingLeaf = getLeafByIndex(currentIndex - 1);
    markLeafFlipping(flippingLeaf, "prev");
    playPageFlipSound("prev");
    showPage(currentIndex - 1);
  }

  function thumbHalfFilled(url, isVideo) {
    if (isVideo) {
      return '<div class="thumb-spread-half filled thumb-video-wrap">' +
        '<video class="thumb-video-preview" src="' + url + '" muted playsinline preload="metadata"></video>' +
        '<span class="thumb-play-icon">&#9654;</span></div>';
    }
    return '<div class="thumb-spread-half filled">' +
      '<img src="' + url + '" alt="" loading="lazy" decoding="async" />' + '</div>';
  }

  function isVideoType(ft) {
    return (ft && ft.toLowerCase() === "video") || false;
  }

  function thumbUrlFromMobileSlot(slot) {
    if (!slot) return "";
    if (slot.kind === "front") {
      var pr = slot.page.right;
      if (!pr) return "";
      var ftr = slot.page.file_types && slot.page.file_types.right;
      if (isVideoType(ftr) || isVideoPath(pr)) return toRawUrl(pr);
      return toAlbumImageUrlFromStoragePath(pr, { thumb: true });
    }
    if (slot.kind === "half") {
      var p = slot.side === "left" ? slot.page.left : slot.page.right;
      if (!p) return "";
      var ft = slot.side === "left"
        ? (slot.page.file_types && slot.page.file_types.left)
        : (slot.page.file_types && slot.page.file_types.right);
      if (isVideoType(ft) || isVideoPath(p)) return toRawUrl(p);
      return toAlbumImageUrlFromStoragePath(p, { thumb: true });
    }
    return "";
  }

  function buildThumbnailBarMobile() {
    var bar = document.getElementById("thumbBar");
    if (!bar) return;
    bar.innerHTML = "";
    var total = mobileSlots.length;
    mobileSlots.forEach(function (slot, i) {
      var label = getMobileSlotLabel(slot, i, total);
      var url = thumbUrlFromMobileSlot(slot);
      var isVid = false;
      if (slot.kind === "half") {
        var ft = slot.side === "left"
          ? (slot.page.file_types && slot.page.file_types.left)
          : (slot.page.file_types && slot.page.file_types.right);
        var p = slot.side === "left" ? slot.page.left : slot.page.right;
        isVid = isVideoType(ft) || isVideoPath(p);
      } else if (slot.kind === "front") {
        isVid = isVideoType((slot.page.file_types && slot.page.file_types.right)) || isVideoPath(slot.page.right);
      }
      var thumbInner =
        '<div class="thumb-spread thumb-spread-mobile-single">' +
        (url ? thumbHalfFilled(url, isVid) : '<div class="thumb-spread-half blank"></div>') +
        "</div>";
      var div = document.createElement("div");
      div.className = "thumb-item" + (i === currentIndex ? " active" : "");
      div.dataset.mobileIndex = String(i);
      div.innerHTML = thumbInner + '<div class="thumb-label">' + escapeHtml(label) + "</div>";
      div.addEventListener(
        "click",
        function () {
          if (i === currentIndex) return;
          showPage(i);
        },
        { passive: true }
      );
      bar.appendChild(div);
    });
  }

  function buildThumbnailBar() {
    if (!isDesktop()) {
      buildThumbnailBarMobile();
      return;
    }
    var bar = document.getElementById("thumbBar");
    if (!bar) return;
    bar.innerHTML = "";
    var pages = layout.pages;
    pages.forEach(function (page, i) {
      var label = getPageLabel(page, i, pages.length);
      var thumbInner = "";
      if (page.type === "front") {
        var r = page.right ? toRawUrl(page.right) : "";
        var rVideo = isVideoType((page.file_types && page.file_types.right)) || isVideoPath(page.right);
        thumbInner =
          '<div class="thumb-spread">' +
          '<div class="thumb-spread-half blank"></div>' +
          (r ? thumbHalfFilled(r, rVideo) : '<div class="thumb-spread-half"></div>') +
          "</div>";
      } else if (page.type === "back") {
        var l = page.left ? toRawUrl(page.left) : "";
        var lVideo = isVideoType((page.file_types && page.file_types.left)) || isVideoPath(page.left);
        thumbInner =
          '<div class="thumb-spread">' +
          (l ? thumbHalfFilled(l, lVideo) : '<div class="thumb-spread-half"></div>') +
          '<div class="thumb-spread-half blank"></div>' +
          "</div>";
      } else {
        var lUrl = (page.type === "spread" && page.left) ? toRawUrl(page.left) : "";
        var rUrl = (page.type === "spread" && page.right) ? toRawUrl(page.right) : "";
        var lVideo = isVideoType((page.file_types && page.file_types.left)) || isVideoPath(page.left);
        var rVideo = isVideoType((page.file_types && page.file_types.right)) || isVideoPath(page.right);
        thumbInner =
          '<div class="thumb-spread">' +
          (lUrl ? thumbHalfFilled(lUrl, lVideo) : '<div class="thumb-spread-half blank"></div>') +
          (rUrl ? thumbHalfFilled(rUrl, rVideo) : '<div class="thumb-spread-half blank"></div>') +
          "</div>";
      }
      var div = document.createElement("div");
      div.className = "thumb-item" + (i === 0 ? " active" : "");
      div.dataset.index = String(i);
      div.innerHTML = thumbInner + '<div class="thumb-label">' + escapeHtml(label) + "</div>";
      div.addEventListener(
        "click",
        function () {
          if (i === currentIndex) return;
          showPage(i);
        },
        { passive: true }
      );
      bar.appendChild(div);
    });
  }

  var layoutUrl = "/outputs/" + encodeURIComponent(projectId) + "/album_layout.json";
  console.log("[Album] Fetching:", layoutUrl);
  fetch(layoutUrl)
    .then(function (r) {
      if (!r.ok) throw new Error(r.statusText);
      return r.json();
    })
    .then(function (data) {
      console.log("[Album] album_layout.json loaded, pages=" + (data.pages ? data.pages.length : 0));
      layout = data;
      var rawPages = data.pages || [];
      layout.pages = rawPages.filter(function (p) {
        if (!p) return false;
        if (p.type === "back") return true;
        var hasLeft = !!(p.left && String(p.left).trim());
        var hasRight = !!(p.right && String(p.right).trim());
        var hasCollage = !!(p.layout_type === "collage" && p.cover_assets && p.cover_assets.length);
        return hasLeft || hasRight || hasCollage;
      });

      // [DEBUG] 콜라주/AI spread의 left/right가 누락되어 특정 페이지(예: 2/3/6)가 빈 화면이 되는지 빠르게 확인
      if (window.__ALBUM_DEBUG__) {
        try {
          var targetPages = [2, 3, 6];
          var rows = [];
          for (var pi = 0; pi < layout.pages.length; pi++) {
            var pg = layout.pages[pi];
            if (!pg || pg.type !== "spread") continue;

            var leftPage = 2 * (pi - 1) + 1;
            var rightPage = leftPage + 1;
            var leftEmpty = !(pg.left && String(pg.left).trim());
            var rightEmpty = !(pg.right && String(pg.right).trim());

            if (targetPages.indexOf(leftPage) >= 0) {
              rows.push({
                targetPage: leftPage,
                spreadIndex: pi,
                side: "left",
                leftPresent: !leftEmpty,
                rightPresent: !rightEmpty,
              });
            }
            if (targetPages.indexOf(rightPage) >= 0) {
              rows.push({
                targetPage: rightPage,
                spreadIndex: pi,
                side: "right",
                leftPresent: !leftEmpty,
                rightPresent: !rightEmpty,
              });
            }
          }
          if (rows.length) console.table(rows);
        } catch (e) {}
      }

      var loadingStateEl = document.getElementById("loadingState");
      if (loadingStateEl) loadingStateEl.classList.add("hidden");
      if (!layout.pages.length) {
        var errorStateEl = document.getElementById("errorState");
        if (errorStateEl) {
          errorStateEl.classList.remove("hidden");
          errorStateEl.textContent = "앨범 페이지가 비어 있습니다.";
        }
        console.warn("[Album] No pages in layout, stopping");
        return;
      }
      var firstPath = null;
      for (var pi = 0; pi < layout.pages.length; pi++) {
        var p = layout.pages[pi];
        if (p && (p.left || p.right)) {
          firstPath = p.left || p.right;
          break;
        }
      }
      if (firstPath) {
        var segment = firstPath.replace(/^storage\/raw\/[^/]+\//, "");
        var sampleUrl = segment ? "/raw/" + projectId + "/" + segment : firstPath;
        console.log("[Album] First image URL sample (check Network for 200):", sampleUrl);
      }
      console.log("[Album] mobileSlots + checkLayout + showPage(0)");
      mobileSlots = buildMobileSlots(layout.pages);
      lastDesktopMode = null;
      checkLayout();
      showPage(0);
      var flipbookStateEl = document.getElementById("flipbookState");
      // 첫 leaf/media 주입 프레임 이후 노출해 초기 깜빡임을 줄인다.
      if (flipbookStateEl) {
        requestAnimationFrame(function () {
          requestAnimationFrame(function () {
            flipbookStateEl.classList.remove("hidden");
          });
        });
      }
      console.log("[Album] Init complete (last log) — if you see this, engine ran to the end.");
    })
    .catch(function (err) {
      var loadingStateEl = document.getElementById("loadingState");
      if (loadingStateEl) loadingStateEl.classList.add("hidden");
      var errorStateEl = document.getElementById("errorState");
      if (errorStateEl) {
        errorStateEl.classList.remove("hidden");
        errorStateEl.textContent = "앨범을 불러올 수 없습니다.";
      }
      console.warn("album_layout.json load failed:", err);
    });

  var clickNext = document.getElementById("clickNext");
  var clickPrev = document.getElementById("clickPrev");
  var bookContainer = document.getElementById("bookContainer");
  var pageDisplay = document.getElementById("pageDisplay");

  if (clickNext) {
    clickNext.addEventListener("click", function (e) {
      e.preventDefault();
      goNext();
    });
  }
  if (clickPrev) {
    clickPrev.addEventListener("click", function (e) {
      e.preventDefault();
      goPrev();
    });
  }

  if (bookContainer && clickPrev) {
    clickPrev.addEventListener(
      "mouseenter",
      function () {
        bookContainer.classList.remove("peek-right");
        bookContainer.classList.add("peek-left");
      },
      { passive: true }
    );
    clickPrev.addEventListener(
      "mouseleave",
      function () {
        bookContainer.classList.remove("peek-left");
      },
      { passive: true }
    );
  }
  if (bookContainer && clickNext) {
    clickNext.addEventListener(
      "mouseenter",
      function () {
        bookContainer.classList.remove("peek-left");
        bookContainer.classList.add("peek-right");
      },
      { passive: true }
    );
    clickNext.addEventListener(
      "mouseleave",
      function () {
        bookContainer.classList.remove("peek-right");
      },
      { passive: true }
    );
  }

  if (pageDisplay) {
    pageDisplay.addEventListener(
      "click",
      function (e) {
        if (e.target.closest("video") || (e.target.closest(".media-frame") && e.target.closest(".media-frame").querySelector("video"))) return;
        var mid = cachedPageDisplayMidX;
        if (mid == null) {
          refreshClickZoneMidXs();
          mid = cachedPageDisplayMidX;
        }
        if (mid == null) return;
        if (e.clientX < mid) goPrev();
        else goNext();
      },
      { passive: true }
    );
  }

  if (bookContainer) {
    bookContainer.addEventListener(
      "click",
      function (e) {
        if (!isDesktop()) return;
        if (e.target.closest("video") || (e.target.closest(".media-frame") && e.target.closest(".media-frame").querySelector("video"))) return;
        var mid = cachedBookContainerMidX;
        if (mid == null) {
          refreshClickZoneMidXs();
          mid = cachedBookContainerMidX;
        }
        if (mid == null) return;
        if (e.clientX < mid) goPrev();
        else goNext();
      },
      { passive: true }
    );
  }

  window.addEventListener(
    "resize",
    function () {
      clearTimeout(resizeTimeout);
      resizeTimeout = setTimeout(function () {
        if (!layout || !layout.pages) return;
        var newWidth = window.innerWidth;
        if (newWidth === lastWidth) return;
        lastWidth = newWidth;
        var nowDesktop = isDesktop();
        if (lastDesktopMode !== null && lastDesktopMode !== nowDesktop) {
          checkLayout();
        }
        showPage(currentIndex);
      }, 250);
    },
    { passive: true }
  );

  requestAnimationFrame(function () {
    refreshClickZoneMidXs();
  });
};
