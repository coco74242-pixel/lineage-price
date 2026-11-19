(function () {
  var EMPTY = "尚無資料，抓到價格後開始記錄";
  var script = document.currentScript;
  var url = (script && script.getAttribute("data-url")) || "history/victory.json";

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

  function showEmpty(box, msg) {
    var empty = $(".chart-empty", box);
    var wrap = $(".chart-wrap", box);
    var note = $(".chart-note", box);
    if (empty) { empty.hidden = false; empty.textContent = msg || EMPTY; }
    if (wrap) wrap.hidden = true;
    if (note) note.hidden = true;
  }

  function render(box, hist) {
    var points = hist && Array.isArray(hist.points) ? hist.points : [];
    var empty = $(".chart-empty", box);
    var wrap = $(".chart-wrap", box);
    var canvas = $("canvas", box);
    var note = $(".chart-note", box);
    if (!points.length || typeof Chart === "undefined" || !canvas) {
      showEmpty(box, typeof Chart === "undefined" ? "圖表元件載入失敗" : EMPTY);
      return;
    }
    if (empty) empty.hidden = true;
    if (wrap) wrap.hidden = false;
    if (note) note.hidden = false;
    var labels = points.map(function (p) { return fmtLabel(p.ts, p.ts_ms); });
    var cdd = points.map(function (p) { return typeof p.pdd373 === "number" ? p.pdd373 : null; });
    if (box._chart) box._chart.destroy();
    box._chart = new Chart(canvas.getContext("2d"), {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: "DD373 成本",
            data: cdd,
            borderColor: "#b45309",
            backgroundColor: "rgba(180,83,9,.12)",
            borderWidth: 2,
            pointRadius: 2,
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
                var v = ctx.parsed.y;
                return ctx.dataset.label + "：" + (v == null ? "無資料" : v.toLocaleString("zh-TW") + " 金／台幣");
              }
            }
          }
        },
        scales: {
          x: {
            ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8, font: { size: 10 } },
            grid: { color: "rgba(0,0,0,.05)" }
          },
          y: {
            title: { display: true, text: "金／1台幣", font: { size: 11 } },
            ticks: { font: { size: 10 } },
            grid: { color: "rgba(0,0,0,.06)" }
          }
        }
      }
    });
  }

  function init() {
    var box = document.getElementById("victoryChartBox");
    if (!box) return;
    fetch(url + "?t=" + Date.now(), { cache: "no-store" })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (hist) { render(box, hist); })
      .catch(function () { showEmpty(box, EMPTY); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
