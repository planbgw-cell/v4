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

  function isVideoPath(path) {
    if (!path) return false;
    return /\.(mp4|webm|mov|m4v)(\?|$)/i.test(path);
  }

  function objectPositionStyle(styles) {
    if (!styles || !styles.focus_offset) return "";
    var x = styles.focus_offset.x;
    var y = styles.focus_offset.y;
    if (x == null || y == null) return "";
    return ' style="object-position:' + String(x).trim() + " " + String(y).trim() + ';"';
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

  function slotHtml(mediaPath, styles, caption, fileType) {
    var url = toRawUrl(mediaPath);
    var isVideo = (fileType && fileType.toLowerCase() === "video") || isVideoPath(mediaPath);
    var blurPart = isVideo
      ? ""
      : '<img class="slot-blur" src="' + url + '" alt="" loading="lazy" decoding="async" />';
    var posStyle = objectPositionStyle(styles || {});
    var fitCls = "contain";
    var mediaPart = isVideo
      ? '<div class="slot-video-stack">' +
        '<img class="slot-blur-poster" src="" alt="" decoding="async" aria-hidden="true" />' +
        '<video class="slot-video" src="' + url + '" controls playsinline loop muted preload="metadata"></video>' +
        "</div>"
      : '<img class="slot-img ' + fitCls + '" src="' + url + '" alt="" loading="lazy" decoding="async"' + posStyle + " />";
    var captionPart = "";
    if (caption) {
      var emotionCls = emotionClass(styles || {});
      var colorStyle = "";
      var bgHex = (styles && styles.bg_color_hex) ? styles.bg_color_hex : null;
      if (bgHex) {
        var cc = contrastColorForHex(bgHex);
        if (cc) colorStyle = ' style="color:' + cc + '"';
      }
      var accentHex = (styles && styles.accent_color_hex) ? styles.accent_color_hex : null;
      var dotPart = accentHex ? '<span class="caption-accent-dot" style="color:' + accentHex + '">·</span> ' : "";
      captionPart = '<div class="slot-caption' + emotionCls + '"' + colorStyle + ">" + dotPart + escapeHtml(caption) + "</div>";
    }
    return (
      '<div class="media-frame album-media-container">' +
      blurPart +
      mediaPart +
      captionPart +
      "</div>"
    );
  }

  function coverSlotHtml(mediaPath, fileType, title) {
    var url = toRawUrl(mediaPath);
    var isVideo = (fileType && fileType.toLowerCase() === "video") || isVideoPath(mediaPath);
    /* 앞표지만: 가로 이미지 시 상·하 검은 여백을 블러+확대 배경으로 채움 (내지 slotHtml과 별도) */
    var blurPart = isVideo
      ? ""
      : '<img class="cover-bg-blur" src="' + url + '" alt="" loading="lazy" decoding="async" aria-hidden="true" />';
    var mediaPart = isVideo
      ? '<div class="slot-video-stack">' +
        '<img class="slot-blur-poster" src="" alt="" decoding="async" aria-hidden="true" />' +
        '<video class="slot-video" src="' + url + '" controls playsinline loop muted preload="metadata"></video>' +
        "</div>"
      : '<img class="slot-img contain" src="' + url + '" alt="" loading="lazy" decoding="async" />';
    var overlayPart = '<div class="cover-title-overlay">' + escapeHtml(title || "") + "</div>";
    return (
      '<div class="media-frame album-media-container cover-front">' +
      blurPart +
      mediaPart +
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
    var savedTime = video.currentTime;
    var dur = video.duration;
    var seekTo = 0.08;
    if (typeof dur === "number" && !isNaN(dur) && dur > 0) {
      seekTo = Math.min(0.15, Math.max(0.04, dur * 0.02));
    }
    function afterSeek() {
      drawAndAssign();
      try {
        video.currentTime = savedTime;
      } catch (e) {}
    }
    function runSeek() {
      try {
        video.currentTime = seekTo;
      } catch (e) {
        drawAndAssign();
        return;
      }
      video.addEventListener(
        "seeked",
        function onSeeked() {
          video.removeEventListener("seeked", onSeeked);
          afterSeek();
        },
        { once: true }
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
        { once: true }
      );
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
        frame.classList.toggle("is-portrait", h >= w);
        frame.classList.toggle("is-landscape", w > h);
      }
      if (img.complete) apply();
      else img.addEventListener("load", apply, { once: true });
    });

    container.querySelectorAll(".media-frame video.slot-video").forEach(function (video) {
      video.addEventListener("click", function (e) { e.stopPropagation(); });
      video.closest(".media-frame").addEventListener("click", function (e) { e.stopPropagation(); });

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
      }, { once: true });

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

  function getPageLabel(page, index, total) {
    if (page.type === "front") return "앞표지";
    if (page.type === "back") return "뒷표지";
    if (page.type === "spread") {
      var leftPage = 2 * (index - 1) + 1;
      var rightPage = 2 * (index - 1) + 2;
      return leftPage + " / " + rightPage;
    }
    return (index + 1) + " / " + total;
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
      var rightHtml =
        '<div class="spread-half spread-half-cover-right"' + rightStyle + ">" +
        '<div class="page-content page-content-cover-right">' +
        (page.right
          ? coverSlotHtml(page.right, (page.file_types && page.file_types.right) || "", page.title || "")
          : '<div class="media-frame media-frame-placeholder"></div>') +
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
          ? slotHtml(page.left, (page.styles && page.styles.left) || {}, (page.captions && page.captions.left) || "", (page.file_types && page.file_types.left) || "")
          : '<div class="media-frame media-frame-placeholder">빈 페이지</div>') +
        "</div></div>";
      var rightHtml =
        '<div class="spread-half"' + rightStyle + ">" +
        '<div class="page-content">' +
        (page.right
          ? slotHtml(page.right, (page.styles && page.styles.right) || {}, (page.captions && page.captions.right) || "", (page.file_types && page.file_types.right) || "")
          : '<div class="media-frame media-frame-placeholder">빈 페이지</div>') +
        "</div></div>";
      return '<div class="spread-row">' + leftHtml + rightHtml + "</div>";
    }
    return "";
  }

  var layout = null;
  var currentIndex = 0;
  var mobileSlots = [];
  var MOBILE_BUFFER_RADIUS = 2;
  var MOBILE_BREAKPOINT = 1024;
  var lastWidth = typeof window !== "undefined" ? window.innerWidth : 0;
  var lastDesktopMode = null;
  var resizeTimeout = null;
  var lastDebugIndex = -1;
  var FLIP_ANIM_MS = 1200;
  var flipTokenSeed = 0;

  function isDesktop() {
    return typeof window !== "undefined" && window.innerWidth >= MOBILE_BREAKPOINT;
  }

  function slotFromPageHalf(page, side) {
    var path, styles, caption, ft;
    if (side === "right") {
      path = page.right;
      styles = (page.styles && page.styles.right) || {};
      caption = (page.captions && page.captions.right) || (page.title || "") || "";
      ft = (page.file_types && page.file_types.right) || "";
    } else {
      path = page.left;
      styles = (page.styles && page.styles.left) || {};
      caption = (page.captions && page.captions.left) || (page.caption || "") || "";
      ft = (page.file_types && page.file_types.left) || "";
    }
    var media = path
      ? slotHtml(path, styles, "", ft)
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
    var emotionCls = (emotion && String(emotion).trim()) ? " caption-emotion-" + String(emotion).trim().toLowerCase().replace(/\s+/g, "-") : "";
    var colorStyle = "";
    if (bgColorHex) {
      var cc = contrastColorForHex(bgColorHex);
      if (cc) colorStyle = ' style="color:' + cc + '"';
    }
    var dotPart = accentColorHex ? '<span class="caption-accent-dot" style="color:' + accentColorHex + '">·</span> ' : "";
    var pageNumStyle = "";
    if (accentColorHex) pageNumStyle = ' style="border-bottom:1px solid ' + accentColorHex + '"';
    return '<div class="slot-caption leaf-caption-bar' + emotionCls + '"' + colorStyle + ">" +
      (caption ? dotPart + escapeHtml(caption) : '') +
      '<span class="leaf-page-num"' + pageNumStyle + ">Page " + pageNum + "</span></div>";
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
      return slot.page.right
        ? coverSlotHtml(slot.page.right, (slot.page.file_types && slot.page.file_types.right) || "", slot.page.title || "") + coverFooterHtml()
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
      '<div class="leaf-face front" style="background-color:#F9F9F9">' +
      '<div class="shadow-overlay" aria-hidden="true"></div>' +
      '<div class="leaf-spine-shadow" aria-hidden="true"></div>' +
      '<div class="leaf-face-content">' + frontHtml + "</div>" +
      "</div>" +
      '<div class="leaf-face back" style="background-color:#F9F9F9">' +
      '<div class="shadow-overlay" aria-hidden="true"></div>' +
      '<div class="leaf-spine-shadow" aria-hidden="true"></div>' +
      '<div class="leaf-face-content leaf-face-content--paper-back" aria-hidden="true"></div>' +
      "</div>" +
      "</div>";
    leaf.querySelectorAll("img").forEach(function (img) {
      img.setAttribute("decoding", "async");
      img.setAttribute("loading", "lazy");
    });
    return leaf;
  }

  function injectLeafMedia(leaf, centerIndex) {
    if (!leaf) return;
    var idx = Number(leaf.dataset.leafIndex || "-1");
    var isVisibleNow = idx === centerIndex;
    leaf.querySelectorAll("img[data-src]").forEach(function (img) {
      if (!img.getAttribute("src")) {
        img.setAttribute("src", img.getAttribute("data-src"));
      }
      img.setAttribute("decoding", "async");
      img.setAttribute("loading", isVisibleNow ? "eager" : "lazy");
    });
  }

  function purgeLeafMedia(leaf) {
    if (!leaf) return;
    leaf.querySelectorAll("img").forEach(function (img) {
      img.removeAttribute("srcset");
      if (img.getAttribute("src")) {
        img.setAttribute("data-src", img.getAttribute("src"));
      }
      img.removeAttribute("src");
    });
    leaf.querySelectorAll("video").forEach(function (v) {
      try {
        v.pause();
      } catch (e) {}
      v.removeAttribute("src");
      v.load();
    });
  }

  function renderMobileWindow(centerIndex) {
    var bookBodyEl = document.getElementById("bookBody");
    if (!bookBodyEl || !mobileSlots.length) return;
    var total = mobileSlots.length;
    for (var i = 0; i < total; i++) {
      var leaf = bookBodyEl.querySelector('.leaf-mobile[data-leaf-index="' + i + '"]');
      if (!leaf) continue;
      var inBuf = i >= centerIndex - MOBILE_BUFFER_RADIUS && i <= centerIndex + MOBILE_BUFFER_RADIUS;
      if (inBuf) {
        leaf.style.display = "";
        injectLeafMedia(leaf, centerIndex);
      } else {
        leaf.style.display = "none";
        purgeLeafMedia(leaf);
      }
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
        frontHtml = pages[i].right
          ? coverSlotHtml(pages[i].right, (pages[i].file_types && pages[i].file_types.right) || "", pages[i].title || "") + coverFooterHtml()
          : '<div class="media-frame media-frame-placeholder"></div>' + coverFooterHtml();
      } else {
        frontHtml = front.media + buildLeafCaptionBar(front.caption, frontPageNum, front.emotion, front.bgColorHex, front.accentColorHex);
      }
      var backHtml;
      if (i === totalLeaves - 1 && pages[i + 1].type === "back") {
        backHtml = backCoverHtml(projectId, getCreatedDateForCover());
      } else {
        backHtml = back.media + buildLeafCaptionBar(back.caption, backPageNum, back.emotion, back.bgColorHex, back.accentColorHex);
      }
      var frontBg = (front.bgColorHex && front.bgColorHex.trim()) ? front.bgColorHex.trim() : "#F9F9F9";
      var backBg = (back.bgColorHex && back.bgColorHex.trim()) ? back.bgColorHex.trim() : "#F9F9F9";
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
      if (pageIndicator) pageIndicator.textContent = (index + 1) + " / " + mobileTotal;
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
    if (isDesktop()) {
      syncLeavesState();
      updateShadowOverlays();
    } else {
      var bookBodyEl = document.getElementById("bookBody");
      renderMobileWindow(currentIndex);
      attachTouchAreas(bookBodyEl);
      setupVideoInPage(bookBodyEl);
      syncLeavesState();
      updateShadowOverlays();
    }
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
    leaf.addEventListener("transitionend", onTransitionEnd);
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
    if (slot.kind === "front") return slot.page.right ? toRawUrl(slot.page.right) : "";
    if (slot.kind === "half") {
      var p = slot.side === "left" ? slot.page.left : slot.page.right;
      return p ? toRawUrl(p) : "";
    }
    return "";
  }

  function buildThumbnailBarMobile() {
    var bar = document.getElementById("thumbBar");
    if (!bar) return;
    bar.innerHTML = "";
    var total = mobileSlots.length;
    mobileSlots.forEach(function (slot, i) {
      var label = (i + 1) + " / " + total;
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
      div.addEventListener("click", function () {
        if (i === currentIndex) return;
        showPage(i);
      });
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
      div.addEventListener("click", function () {
        if (i === currentIndex) return;
        showPage(i);
      });
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
        var hasLeft = !!(p.left && String(p.left).trim());
        var hasRight = !!(p.right && String(p.right).trim());
        return hasLeft || hasRight;
      });
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
      var flipbookStateEl = document.getElementById("flipbookState");
      if (flipbookStateEl) flipbookStateEl.classList.remove("hidden");
      console.log("[Album] mobileSlots + checkLayout + showPage(0)");
      mobileSlots = buildMobileSlots(layout.pages);
      lastDesktopMode = null;
      checkLayout();
      showPage(0);
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
    clickPrev.addEventListener("mouseenter", function () {
      bookContainer.classList.remove("peek-right");
      bookContainer.classList.add("peek-left");
    });
    clickPrev.addEventListener("mouseleave", function () {
      bookContainer.classList.remove("peek-left");
    });
  }
  if (bookContainer && clickNext) {
    clickNext.addEventListener("mouseenter", function () {
      bookContainer.classList.remove("peek-left");
      bookContainer.classList.add("peek-right");
    });
    clickNext.addEventListener("mouseleave", function () {
      bookContainer.classList.remove("peek-right");
    });
  }

  if (pageDisplay) {
    pageDisplay.addEventListener("click", function (e) {
      if (e.target.closest("video") || (e.target.closest(".media-frame") && e.target.closest(".media-frame").querySelector("video"))) return;
      var rect = e.currentTarget.getBoundingClientRect();
      var mid = rect.left + rect.width / 2;
      if (e.clientX < mid) goPrev();
      else goNext();
    });
  }

  if (bookContainer) {
    bookContainer.addEventListener("click", function (e) {
      if (!isDesktop()) return;
      if (e.target.closest("video") || (e.target.closest(".media-frame") && e.target.closest(".media-frame").querySelector("video"))) return;
      var rect = e.currentTarget.getBoundingClientRect();
      var mid = rect.left + rect.width / 2;
      if (e.clientX < mid) goPrev();
      else goNext();
    });
  }

  window.addEventListener("resize", function () {
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
  });

  /* 검증용: .book-container 높이 확인 후 제거 가능 */
  setTimeout(function () {
    var el = document.querySelector(".book-container");
    if (el) {
      console.log("[Album] .book-container height (getBoundingClientRect):", el.getBoundingClientRect().height);
    }
  }, 150);
};
