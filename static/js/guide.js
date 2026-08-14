(function () {
  function showFallback(img) {
    var wrap = img.closest(".guide-screenshot-wrap");
    if (!wrap) return;

    img.classList.add("is-missing");
    var fallback = wrap.querySelector(".guide-img-fallback");
    if (!fallback) return;

    var label =
      img.getAttribute("data-fallback-label") ||
      img.getAttribute("alt") ||
      "이미지를 불러올 수 없습니다.";

    fallback.textContent = label;
    fallback.classList.remove("hidden");
    fallback.classList.add("is-visible");
    fallback.setAttribute("aria-hidden", "false");
  }

  function bindGuideScreenshot(img) {
    if (!img || img.dataset.guideFallbackBound === "1") return;
    img.dataset.guideFallbackBound = "1";

    img.addEventListener("error", function () {
      img.onerror = null;
      showFallback(img);
    });

    if (img.complete && img.naturalWidth === 0) {
      showFallback(img);
    }
  }

  function initGuideScreenshots() {
    document.querySelectorAll(".guide-screenshot").forEach(bindGuideScreenshot);
  }

  function initGuideStoryNav() {
    var navLinks = document.querySelectorAll(".guide-story-nav__link");
    var sections = document.querySelectorAll(".guide-story-section");
    if (!navLinks.length || !sections.length) return;

    function setActive(sectionId) {
      navLinks.forEach(function (link) {
        var isActive = link.getAttribute("data-guide-section") === sectionId;
        link.classList.toggle("is-active", isActive);
      });
    }

    if ("IntersectionObserver" in window) {
      var visible = {};
      var observer = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            visible[entry.target.id] = entry.isIntersecting ? entry.intersectionRatio : 0;
          });
          var bestId = null;
          var bestRatio = 0;
          sections.forEach(function (section) {
            var ratio = visible[section.id] || 0;
            if (ratio > bestRatio) {
              bestRatio = ratio;
              bestId = section.id;
            }
          });
          if (bestId) setActive(bestId);
        },
        { root: null, rootMargin: "-20% 0px -55% 0px", threshold: [0, 0.1, 0.25, 0.5, 0.75, 1] }
      );
      sections.forEach(function (section) {
        observer.observe(section);
      });
    }

    var firstSection = sections[0];
    if (firstSection) setActive(firstSection.id);

    navLinks.forEach(function (link) {
      link.addEventListener("click", function () {
        var id = link.getAttribute("data-guide-section");
        if (id) setActive(id);
      });
    });
  }

  function initGuidePage() {
    initGuideScreenshots();
    initGuideStoryNav();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initGuidePage);
  } else {
    initGuidePage();
  }
})();
