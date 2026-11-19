(function () {
  var EMPTY_START = "開始記錄中，下一輪抓價後會出現第一個點。";
  var EMPTY_FAIL = "圖表元件載入失敗";
  var script = document.currentScript;
  var pageUrl = (script && script.getAttribute("data-url")) || "history/victory.json";
  var CURVES = {
    "勝利女神雅典娜": { title: "勝利女神雅典娜 價格曲線（每 30 分鐘）", url: "../history/victory.json" },
    "牛人彌諾陶洛斯": { title: "牛人彌諾陶洛斯 價格曲線（每 30 分鐘）", url: "../history/niuren.json" }
  };

  function $(sel, root) { return (root || document).querySelector(sel); }

  function fmtLabel(ts, tsMs) {
    var d = null;
    if (typeof tsMs === "number") d = new Date(tsMs);
    else if (ts) d = new Date(String(ts).replace(" +0800", "+08:00"));
    if (!d || isNaN(d.getTime())) return String(ts || "");
    var mo = d.toLocaleString("sv-SE", { timeZone: "Asia/Taipei", month: "2-digit" });
    var day = d.toLocaleString("sv-SE", { timeZone: "Asia/Taipei", day: "2-digit" });
    var hm = d.toLocaleString("sv-SE", { timeZone: "Asia/Taipei", hour: "2-digit", minute: "2-digit", hour12: false });
    return mo + "/" + day + " " + hm;
  }

  function fmtListTime(ts, tsMs) {
    var d = null;
    if (typeof tsMs === "number") d = new Date(tsMs);
    else if (ts) d = new Date(String(ts).replace(" +0800", "+08:00"));
    if (!d || isNaN(d.getTime())) return String(ts || "");
    return d.toLocaleString("sv-SE", {
      timeZone: "Asia/Taipei",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    }).replace("T", " ");
  }

  // 成本 人民幣/萬金 = 10000 ÷ (金/台幣 × 匯率)，與頁面「均價」同一套 5 萬台幣掃單平均。
  // 僅顯示用，不改寫歷史檔。缺匯率或金/台幣時該點留空（線會中斷）。
  function rmbPerWan(p) {
    var gold = p && p.pdd373, rate = p && p.rate;
    if (typeof gold !== "number" || gold <= 0 || typeof rate !== "number" || !(3 < rate && rate < 7)) return null;
    return 10000 / (gold * rate);
  }
  function twdPerWan(p) {
    var gold = p && p.pdd373;
    if (typeof gold !== "number" || gold <= 0) return null;
    return 10000 / gold;
  }
  function fmtRmb(v) {
    if (typeof v !== "number") return "無資料";
    return v.toLocaleString("zh-TW", { minimumFractionDigits: 2, maximumFractionDigits: 4 }) + " 人民幣／萬";
  }
  function fmtGold(v) {
    if (typeof v !== "number") return "";
    return v.toLocaleString("zh-TW", { maximumFractionDigits: 2 }) + " 金／台幣";
  }
  function fmtTwd(v) {
    if (typeof v !== "number") return "";
    return v.toLocaleString("zh-TW", { minimumFractionDigits: 2, maximumFractionDigits: 4 }) + " 台幣／萬";
  }

  function showEmpty(box, msg) {
    var empty = $(".chart-empty", box);
    var wrap = $(".chart-wrap", box);
    var note = $(".chart-note", box);
    var list = $(".chart-list", box);
    if (empty) { empty.hidden = false; empty.textContent = msg || EMPTY_START; }
    if (wrap) wrap.hidden = true;
    if (note) note.hidden = true;
    if (list) { list.hidden = true; list.innerHTML = ""; }
  }

  function renderList(box, points) {
    var list = $(".chart-list", box);
    if (!list) return;
    if (!points.length) { list.hidden = true; list.innerHTML = ""; return; }
    var rows = points.slice().reverse().map(function (p) {
      var rmb = rmbPerWan(p);
      var gold = typeof p.pdd373 === "number" ? fmtGold(p.pdd373) : "";
      var price = rmb == null ? "無資料" : (fmtRmb(rmb) + (gold ? "<span class=\"sub\">" + gold + "</span>" : ""));
      return "<li><span class=\"t\">" + fmtListTime(p.ts, p.ts_ms) + "</span><span class=\"p\">" + price + "</span></li>";
    }).join("");
    list.innerHTML = "<div class=\"chart-list-head\"><span>時間（台北）</span><span>成本 人民幣／萬</span></div>" + rows;
    list.hidden = false;
  }

  var WINDOW_MS = 7 * 24 * 3600 * 1000;

  function pointMs(p) {
    if (typeof p.ts_ms === "number") return p.ts_ms;
    if (!p || !p.ts) return 0;
    var d = new Date(String(p.ts).replace(" +0800", "+08:00"));
    return isNaN(d.getTime()) ? 0 : d.getTime();
  }

  function recentPoints(points) {
    var now = Date.now();
    var kept = points.filter(function (p) {
      var ms = pointMs(p);
      return ms && (now - ms) <= WINDOW_MS;
    });
    return kept;
  }

  function render(box, hist) {
    var points = recentPoints(hist && Array.isArray(hist.points) ? hist.points : []);
    var empty = $(".chart-empty", box);
    var wrap = $(".chart-wrap", box);
    var canvas = $("canvas", box);
    var note = $(".chart-note", box);
    if (!points.length || typeof Chart === "undefined" || !canvas) {
      showEmpty(box, typeof Chart === "undefined" ? EMPTY_FAIL : EMPTY_START);
      return;
    }
    if (empty) empty.hidden = true;
    if (wrap) wrap.hidden = false;
    if (note) note.hidden = false;
    renderList(box, points);
    var labels = points.map(function (p) { return fmtLabel(p.ts, p.ts_ms); });
    var cdd = points.map(function (p) { return rmbPerWan(p); });
    if (box._chart) box._chart.destroy();
    box._chart = new Chart(canvas.getContext("2d"), {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: "成本 人民幣／萬",
            data: cdd,
            borderColor: "#b45309",
            backgroundColor: "rgba(180,83,9,.12)",
            borderWidth: 2,
            pointRadius: 1.5,
            pointHoverRadius: 4,
            tension: 0.15,
            spanGaps: false
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { boxWidth: 12, font: { size: 11 } } },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var i = ctx.dataIndex;
                var p = points[i] || {};
                var rmb = ctx.parsed.y;
                if (rmb == null) return "成本：無資料";
                var lines = ["成本：" + fmtRmb(rmb)];
                var twd = twdPerWan(p);
                if (twd != null) lines.push(fmtTwd(twd));
                if (typeof p.pdd373 === "number") lines.push(fmtGold(p.pdd373));
                return lines;
              }
            }
          }
        },
        scales: {
          x: {
            ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 12, font: { size: 10 } },
            grid: { color: "rgba(0,0,0,.05)" }
          },
          y: {
            title: { display: true, text: "成本 人民幣/萬", font: { size: 11 } },
            reverse: false,
            ticks: {
              font: { size: 10 },
              callback: function (v) {
                return Number(v).toLocaleString("zh-TW", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
              }
            },
            grid: { color: "rgba(0,0,0,.06)" }
          }
        }
      }
    });
  }

  function loadInto(box, url) {
    if (!box) return;
    fetch(url + (url.indexOf("?") >= 0 ? "&" : "?") + "t=" + Date.now(), { cache: "no-store" })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (hist) { render(box, hist); })
      .catch(function () { showEmpty(box, EMPTY_START); });
  }

  function closeModal() {
    var modal = document.getElementById("curveModal");
    if (!modal) return;
    modal.hidden = true;
    document.body.classList.remove("curve-open");
  }

  function openModal(server) {
    var conf = CURVES[server];
    var modal = document.getElementById("curveModal");
    var box = document.getElementById("curveModalBox");
    var title = document.getElementById("curveModalTitle");
    if (!conf || !modal || !box) return;
    if (title) title.textContent = conf.title;
    modal.hidden = false;
    document.body.classList.add("curve-open");
    showEmpty(box, "載入中…");
    loadInto(box, conf.url);
    var closeBtn = $(".cmodal-close", modal);
    if (closeBtn) closeBtn.focus();
  }

  function onDocClick(e) {
    var btn = e.target.closest && e.target.closest(".curve-btn");
    if (btn) {
      e.preventDefault();
      openModal(btn.getAttribute("data-server"));
      return;
    }
    if (e.target.closest && e.target.closest("[data-curve-close]")) {
      closeModal();
    }
  }

  function onKey(e) {
    if (e.key === "Escape") closeModal();
  }

  function init() {
    var box = document.getElementById("victoryChartBox");
    if (box) loadInto(box, pageUrl);
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onKey);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
