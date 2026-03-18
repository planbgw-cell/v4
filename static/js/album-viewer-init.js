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

  function zoomOriginStyle(styles) {
    if (!styles || !styles.focus_offset) return "";
    var x = styles.focus_offset.x;
    var y = styles.focus_offset.y;
    if (x == null || y == null) return "";
    return " --zoom-origin-x:" + String(x).trim() + "; --zoom-origin-y:" + String(y).trim() + ";";
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
      ? '<video class="slot-blur-video" src="' + url + '" muted autoplay playsinline loop preload="auto" aria-hidden="true" tabindex="-1"></video>'
      : '<img class="slot-blur" src="' + url + '" alt="" loading="lazy" />';
    var posStyle = objectPositionStyle(styles || {});
    var mediaPart = isVideo
      ? '<video class="slot-video" src="' + url + '" controls playsinline loop muted preload="auto"></video>'
      : '<img class="slot-img contain" src="' + url + '" alt="" loading="lazy"' + posStyle + " />";
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
    var zoomOrigin = zoomOriginStyle(styles || {});
    var zoompanCls = isVideo ? "" : " zoompan-ready";
    return (
      '<div class="media-frame album-media-container' + zoompanCls + '"' + (zoomOrigin ? ' style="' + zoomOrigin + '"' : '') + '>' +
      blurPart +
      mediaPart +
      captionPart +
      "</div>"
    );
  }

  function coverSlotHtml(mediaPath, fileType, title) {
    var url = toRawUrl(mediaPath);
    var isVideo = (fileType && fileType.toLowerCase() === "video") || isVideoPath(mediaPath);
    var mediaPart = isVideo
      ? '<video class="slot-video" src="' + url + '" controls playsinline loop muted preload="auto"></video>'
      : '<img class="slot-img contain" src="' + url + '" alt="" loading="lazy" />';
    var overlayPart = '<div class="cover-title-overlay">' + escapeHtml(title || "") + "</div>";
    return (
      '<div class="media-frame album-media-container">' +
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

        // 가로(landscape) 영상만 상/하 블러(움직이는 배경) 재생
        var blurV = frame.querySelector("video.slot-blur-video");
        if (blurV) {
          if (w > h) {
            blurV.play().catch(function () {});
          } else {
            blurV.pause();
          }
        }
      }, { once: true });

      if (!albumVideoObserver) {
        albumVideoObserver = new IntersectionObserver(
          function (entries) {
            entries.forEach(function (entry) {
              var v = entry.target;
              var frame = v.closest(".media-frame");
              var blurV = frame ? frame.querySelector("video.slot-blur-video") : null;
              if (entry.isIntersecting) {
                v.play().catch(function () {});
                if (blurV && !(frame && frame.classList.contains("is-portrait"))) blurV.play().catch(function () {});
              } else {
                v.pause();
                if (blurV) blurV.pause();
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

  function isDesktop() {
    return typeof window !== "undefined" && window.innerWidth >= 768;
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
      leaf.className = "leaf";
      leaf.dataset.leafIndex = String(i);
      leaf.innerHTML =
        '<div class="leaf-inner">' +
        '<div class="leaf-face front" ' + frontFaceStyle + '>' +
        '<div class="leaf-spine-shadow" aria-hidden="true"></div>' +
        '<div class="leaf-face-content">' + frontHtml + "</div>" +
        "</div>" +
        '<div class="leaf-face back" ' + backFaceStyle + '>' +
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
    var totalLeaves = layout.pages.length - 1;
    if (totalLeaves <= 0) return;
    var leaves = document.querySelectorAll("#bookBody .leaf");
    for (var i = 0; i < leaves.length; i++) {
      var leaf = leaves[i];
      var isFlipped = i < currentIndex;
      leaf.classList.toggle("flipped", isFlipped);
      leaf.classList.toggle("active-zoom", i === currentIndex);
      leaf.style.zIndex = isFlipped ? String(i) : String(totalLeaves - i);
    }
  }

  function updateIndicatorAndThumb(index) {
    if (!layout || !layout.pages) return;
    var page = layout.pages[index];
    var total = layout.pages.length;
    var pageIndicator = document.getElementById("pageIndicator");
    if (pageIndicator) pageIndicator.textContent =
      getPageLabel(page, index, total) + " (" + (index + 1) + " / " + total + ")";
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
    var pages = layout.pages;
    currentIndex = Math.max(0, Math.min(index, pages.length - 1));
    var page = pages[currentIndex];
    updateIndicatorAndThumb(currentIndex);
    if (isDesktop()) {
      syncLeavesState();
    } else {
      var display = document.getElementById("pageDisplay");
      if (display) {
        disconnectVideoObserver();
        display.innerHTML = renderPageContent(page, currentIndex, pages.length);
        setupVideoInPage(display);
      }
    }
  }

  function playPageFlipSound(direction) {
    try {
      pageFlipAudio.currentTime = 0;
      pageFlipAudio.volume = direction === "next" ? 0.4 : 0.35;
      pageFlipAudio.play().catch(function () {});
    } catch (e) {}
  }

  function goNext() {
    if (!layout || !layout.pages || currentIndex >= layout.pages.length - 1) return;
    playPageFlipSound("next");
    showPage(currentIndex + 1);
  }

  function goPrev() {
    if (!layout || !layout.pages || currentIndex <= 0) return;
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
      '<img src="' + url + '" alt="" loading="lazy" />' + '</div>';
  }

  function isVideoType(ft) {
    return (ft && ft.toLowerCase() === "video") || false;
  }

  function buildThumbnailBar() {
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
      console.log("[Album] buildThumbnailBar + buildLeaves + showPage(0)");
      buildThumbnailBar();
      buildLeaves();
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
    if (!layout || !layout.pages) return;
    showPage(currentIndex);
  });

  /* 검증용: .book-container 높이 확인 후 제거 가능 */
  setTimeout(function () {
    var el = document.querySelector(".book-container");
    if (el) {
      console.log("[Album] .book-container height (getBoundingClientRect):", el.getBoundingClientRect().height);
    }
  }, 150);
};
