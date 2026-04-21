(function (window, document) {
  var STORAGE_KEY = "flairy_active_task";
  var POLL_INTERVAL_MS = 3000;
  var MAGIC_LINK_ORIGIN = "http://121.133.47.184:8000";
  var ACTIVE_STATUSES = { PENDING: true, ANALYZING: true, COMPOSING: true, GENERATING: true };
  var pollHandle = null;
  var lastMessage = "";
  var currentTaskId = "";

  function saveActiveTask(taskId) {
    if (!taskId) return;
    currentTaskId = String(taskId);
    try {
      window.localStorage.setItem(STORAGE_KEY, String(taskId));
    } catch (e) {
      console.warn("[WES] localStorage save failed:", e);
    }
  }

  function clearActiveTask() {
    currentTaskId = "";
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch (e) {
      console.warn("[WES] localStorage remove failed:", e);
    }
  }

  function getActiveTaskId() {
    try {
      return (window.localStorage.getItem(STORAGE_KEY) || "").trim();
    } catch (e) {
      return "";
    }
  }

  function getTaskIdFromQuery() {
    try {
      var u = new URL(window.location.href);
      return (u.searchParams.get("task_id") || "").trim();
    } catch (e) {
      return "";
    }
  }

  function getMagicLink(taskId) {
    return MAGIC_LINK_ORIGIN + "/?task_id=" + encodeURIComponent(taskId || "");
  }

  function showToast(message) {
    var prev = document.getElementById("wesToast");
    if (prev) prev.remove();
    var toast = document.createElement("div");
    toast.id = "wesToast";
    toast.className = "fixed left-1/2 bottom-6 -translate-x-1/2 z-[9999] rounded-lg bg-gray-900 text-white px-4 py-2 text-sm shadow-lg";
    toast.textContent = message;
    document.body.appendChild(toast);
    window.setTimeout(function () {
      if (toast && toast.parentNode) toast.parentNode.removeChild(toast);
    }, 2200);
  }

  function removeStatusCard() {
    var el = document.getElementById("wesLiveCard");
    if (el) el.remove();
  }

  function ensureStatusCard() {
    var card = document.getElementById("wesLiveCard");
    if (card) return card;

    card = document.createElement("section");
    card.id = "wesLiveCard";
    card.className = "mt-6 rounded-xl border border-indigo-200 bg-white p-4 shadow-sm";
    card.innerHTML =
      '<div class="flex items-center justify-between gap-3">' +
      '  <h3 class="text-sm font-semibold text-indigo-700">진행 중인 작업이 있습니다</h3>' +
      '  <a id="wesCheckLink" class="text-xs text-indigo-600 underline" href="/">확인하기</a>' +
      "</div>" +
      '<p id="wesStatusMsg" class="mt-2 text-sm text-gray-700 transition-opacity duration-300 opacity-100">작업 준비 중...</p>' +
      '<div class="mt-3 h-2 w-full rounded bg-gray-200 overflow-hidden">' +
      '  <div id="wesProgressBar" class="h-2 bg-indigo-500 transition-all duration-300" style="width:10%"></div>' +
      "</div>" +
      '<p id="wesStatusLabel" class="mt-1 text-xs text-gray-500">PENDING</p>' +
      '<div id="wesBestCutWrap" class="mt-3 hidden">' +
      '  <p class="text-xs font-medium text-gray-700 mb-2">AI가 고른 오늘의 베스트 컷!</p>' +
      '  <img id="wesBestCutImg" alt="best cut" class="w-full max-h-48 object-cover rounded-lg border border-gray-200" />' +
      "</div>" +
      '<div id="wesActionWrap" class="mt-3 flex gap-2">' +
      '  <a id="wesResultBtn" class="hidden px-3 py-2 rounded-lg bg-indigo-600 text-white text-sm" href="/">결과 확인하기</a>' +
      '  <button id="wesRetryBtn" type="button" class="hidden px-3 py-2 rounded-lg border border-gray-300 text-sm text-gray-700">다시 시도하기</button>' +
      "</div>" +
      '<div class="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-3">' +
      '  <p class="text-xs text-gray-700 font-medium">창을 닫으셔도 작업은 계속 진행됩니다!</p>' +
      '  <div class="mt-2 flex gap-2">' +
      '    <button id="wesCopyMagicBtn" type="button" class="px-3 py-2 rounded-lg border border-indigo-300 text-indigo-700 text-sm bg-white">매직 링크 복사</button>' +
      "  </div>" +
      '  <p class="mt-3 text-xs text-gray-600">완성되면 카톡으로 알려드려요</p>' +
      '  <div class="mt-2 flex gap-2">' +
      '    <input id="wesNotifyInput" type="tel" placeholder="전화번호 입력" class="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white" />' +
      '    <button id="wesNotifyBtn" type="button" class="px-3 py-2 rounded-lg bg-indigo-600 text-white text-sm">신청</button>' +
      "  </div>" +
      "</div>";
    var root = document.querySelector(".max-w-4xl") || document.body;
    root.appendChild(card);

    var retryBtn = card.querySelector("#wesRetryBtn");
    retryBtn.addEventListener("click", function () {
      var dropZone = document.getElementById("dropZone");
      if (dropZone && dropZone.scrollIntoView) {
        dropZone.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });

    var copyBtn = card.querySelector("#wesCopyMagicBtn");
    copyBtn.addEventListener("click", function () {
      if (!currentTaskId) return;
      var magic = getMagicLink(currentTaskId);
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard
          .writeText(magic)
          .then(function () {
            showToast("링크가 복사되었습니다! 메모장 등에 보관하세요.");
          })
          .catch(function () {
            showToast("링크 복사에 실패했습니다. 다시 시도해 주세요.");
          });
      } else {
        showToast("현재 브라우저에서는 클립보드 복사를 지원하지 않습니다.");
      }
    });

    var notifyBtn = card.querySelector("#wesNotifyBtn");
    notifyBtn.addEventListener("click", function () {
      if (!currentTaskId) return;
      var input = card.querySelector("#wesNotifyInput");
      var phone = String((input && input.value) || "").trim();
      if (!phone) {
        showToast("전화번호를 입력해 주세요.");
        return;
      }
      window
        .fetch("/api/tasks/" + encodeURIComponent(currentTaskId) + "/notify", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ notify_target: phone }),
        })
        .then(function (r) {
          if (!r.ok) {
            return r.json().then(function (d) {
              throw new Error((d && d.detail) || "알림 신청 실패");
            });
          }
          return r.json();
        })
        .then(function () {
          showToast("알림 신청이 완료되었습니다.");
        })
        .catch(function (e) {
          showToast(e.message || "알림 신청에 실패했습니다.");
        });
    });
    return card;
  }

  function setMessage(msg) {
    var msgEl = document.getElementById("wesStatusMsg");
    if (!msgEl) return;
    var next = msg || "작업 준비 중...";
    if (next === lastMessage) return;
    msgEl.style.opacity = "0";
    window.setTimeout(function () {
      msgEl.textContent = next;
      msgEl.style.opacity = "1";
    }, 150);
    lastMessage = next;
  }

  function stopPolling() {
    if (pollHandle) {
      window.clearInterval(pollHandle);
      pollHandle = null;
    }
  }

  function updateUi(task) {
    var card = ensureStatusCard();
    var status = String(task.status || "PENDING").toUpperCase();
    var progress = Math.max(0, Math.min(100, Number(task.progress_percent || 10)));
    var projectType = task.project_type === "album" ? "album" : "video";
    var progressUrl =
      task.project_id
        ? "/progress/" + projectType + "/" + encodeURIComponent(task.project_id)
        : "/";

    card.querySelector("#wesCheckLink").setAttribute("href", progressUrl);
    card.querySelector("#wesProgressBar").style.width = String(progress) + "%";
    card.querySelector("#wesStatusLabel").textContent = status + " · " + progress + "%";
    setMessage(task.current_msg);

    var bestWrap = card.querySelector("#wesBestCutWrap");
    var bestImg = card.querySelector("#wesBestCutImg");
    if (task.best_cut_image_url) {
      bestWrap.classList.remove("hidden");
      bestImg.setAttribute("src", task.best_cut_image_url);
    } else {
      bestWrap.classList.add("hidden");
      bestImg.removeAttribute("src");
    }

    var resultBtn = card.querySelector("#wesResultBtn");
    var retryBtn = card.querySelector("#wesRetryBtn");
    resultBtn.classList.add("hidden");
    retryBtn.classList.add("hidden");

    if (status === "COMPLETED") {
      resultBtn.classList.remove("hidden");
      resultBtn.setAttribute("href", task.result_url || progressUrl);
      stopPolling();
      clearActiveTask();
      if (task.result_url) {
        window.setTimeout(function () {
          window.location.href = task.result_url;
        }, 1200);
      }
      return;
    }
    if (status === "FAILED") {
      retryBtn.classList.remove("hidden");
      stopPolling();
      clearActiveTask();
    }
  }

  function fetchTask(taskId) {
    return window
      .fetch("/api/tasks/" + encodeURIComponent(taskId), { credentials: "include" })
      .then(function (r) {
        if (r.status === 404 || r.status === 410) {
          clearActiveTask();
          removeStatusCard();
          stopPolling();
          return null;
        }
        if (!r.ok) throw new Error("task fetch failed: " + r.status);
        return r.json();
      })
      .then(function (data) {
        if (!data) return null;
        updateUi(data);
        return data;
      })
      .catch(function (e) {
        console.warn("[WES] task polling failed:", e);
        return null;
      });
  }

  function checkActiveTask() {
    var taskId = getActiveTaskId();
    currentTaskId = taskId;
    if (!taskId) {
      removeStatusCard();
      stopPolling();
      return Promise.resolve(null);
    }
    return fetchTask(taskId).then(function (data) {
      if (!data) return null;
      var status = String(data.status || "").toUpperCase();
      if (ACTIVE_STATUSES[status] && !pollHandle) {
        pollHandle = window.setInterval(function () {
          fetchTask(taskId);
        }, POLL_INTERVAL_MS);
      }
      if (!ACTIVE_STATUSES[status]) {
        stopPolling();
      }
      return data;
    });
  }

  function initFromMagicLink() {
    var taskIdFromUrl = getTaskIdFromQuery();
    if (!taskIdFromUrl) return;
    saveActiveTask(taskIdFromUrl);
    try {
      var u = new URL(window.location.href);
      u.searchParams.delete("task_id");
      window.history.replaceState({}, "", u.toString());
    } catch (e) {
      // ignore URL cleanup failure
    }
  }

  window.FlairyWES = {
    saveActiveTask: saveActiveTask,
    clearActiveTask: clearActiveTask,
    checkActiveTask: checkActiveTask,
    stopPolling: stopPolling,
    initFromMagicLink: initFromMagicLink,
  };

  initFromMagicLink();
  currentTaskId = getActiveTaskId();
})(window, document);
