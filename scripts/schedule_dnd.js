/**
 * 往診リスト: 行ドラッグ並び替え・別日移動・正本 overrides 書き出し
 * build_august_schedule_html.py から HTML に埋め込まれる
 */
(function () {
  var STORAGE_KEY = "ousehin-schedule-overrides-v1";
  var dirty = false;
  var dragRow = null;
  var moveTargetRow = null;
  var selectedInsertIndex = null; // 0..n : そのインデックスの前に挿入（n=末尾）

  function constraints() {
    return window.OUSEHIN_CONSTRAINTS || { patients: {}, capacity: {}, day_capacity: {} };
  }

  function patientConstraint(id) {
    var c = constraints();
    return (c.patients && c.patients[id]) || null;
  }

  function capacityFor(day, doctor) {
    var c = constraints();
    var dayCap = (c.day_capacity && c.day_capacity[day] && c.day_capacity[day][doctor]);
    if (dayCap) return dayCap;
    return (c.capacity && c.capacity[doctor]) || 99;
  }

  function doctorPrefLabel(pref) {
    var labels = (constraints().doctor_pref_labels) || {};
    return labels[pref] || pref;
  }

  function findDayCard(day) {
    return qsa("article.day-card").find(function (c) {
      return c.dataset.day === day;
    });
  }

  function findDoctorBlock(day, doctor) {
    var card = findDayCard(day);
    if (!card) return null;
    return qsa(".doctor-block", card).find(function (b) {
      return b.dataset.doctor === doctor;
    });
  }

  function countVisitsOnDay(day, patientId, excludeRow) {
    var card = findDayCard(day);
    if (!card) return 0;
    return qsa("tbody tr", card).filter(function (tr) {
      return tr !== excludeRow && tr.dataset.patientId === patientId;
    }).length;
  }

  function validateMove(opts) {
    var warnings = [];
    var pid = opts.patientId;
    var toDay = opts.toDay;
    var toDoctor = opts.toDoctor;
    var fromDay = opts.fromDay;
    var fromDoctor = opts.fromDoctor;
    var excludeRow = opts.excludeRow;
    var pc = patientConstraint(pid);

    if (pc && Array.isArray(pc.eligible_days) && pc.eligible_days.length) {
      if (pc.eligible_days.indexOf(toDay) < 0) {
        warnings.push("希望・候補日の範囲外です（eligible に " + toDay + " がありません）");
      }
    }

    var destBlock = findDoctorBlock(toDay, toDoctor);
    if (destBlock) {
      var n = qsa("tbody tr", destBlock).filter(function (tr) {
        return tr !== excludeRow;
      }).length;
      // 別枠からの移動なら +1
      if (!(fromDay === toDay && fromDoctor === toDoctor)) n += 1;
      var cap = capacityFor(toDay, toDoctor);
      if (n > cap) {
        warnings.push(toDoctor + " の定員目安" + cap + "を超えます（移動後 " + n + "件）");
      }
    }

    if (pc && pc.doctor_pref && pc.doctor_pref !== "auto") {
      var want = doctorPrefLabel(pc.doctor_pref);
      if (want && want !== "auto" && want !== toDoctor) {
        warnings.push("医師希望は「" + want + "」ですが「" + toDoctor + "」へ移動します");
      }
    }

    if (toDay !== fromDay && countVisitsOnDay(toDay, pid, excludeRow) > 0) {
      warnings.push("この日に既に同じ患者の割当があります");
    }

    if (pc && pc.insurance === "医療" && pc.deadline) {
      var m = /^(\d+)\/(\d+)/.exec(toDay);
      var dlNum = null;
      var dlMatch = String(pc.deadline).match(/(\d+)\s*\/\s*(\d+)/);
      var iso = String(pc.deadline).match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
      if (dlMatch) {
        dlNum = parseInt(dlMatch[1], 10) * 100 + parseInt(dlMatch[2], 10);
      } else if (iso) {
        dlNum = parseInt(iso[2], 10) * 100 + parseInt(iso[3], 10);
      }
      if (m && dlNum !== null) {
        var toNum = parseInt(m[1], 10) * 100 + parseInt(m[2], 10);
        var otherBefore = false;
        qsa("article.day-card").forEach(function (card) {
          if (card.dataset.day === toDay) return;
          qsa("tbody tr", card).forEach(function (tr) {
            if (tr === excludeRow) return;
            if (tr.dataset.patientId !== pid) return;
            var om = /^(\d+)\/(\d+)/.exec(card.dataset.day);
            if (!om) return;
            var on = parseInt(om[1], 10) * 100 + parseInt(om[2], 10);
            if (on <= dlNum) otherBefore = true;
          });
        });
        if (toNum > dlNum && !otherBefore) {
          warnings.push(
            "医療・期限 " + pc.deadline + " より後の日へ移します（期限前必達の確認）"
          );
        }
      }
    }

    if (pc && pc.pair_with) {
      var mateOnDest = countVisitsOnDay(toDay, pc.pair_with, null) > 0;
      var mateOnFrom = fromDay ? countVisitsOnDay(fromDay, pc.pair_with, null) > 0 : false;
      if (mateOnFrom && !mateOnDest && toDay !== fromDay) {
        warnings.push("ペア患者（" + pc.pair_with + "）と同日でなくなります");
      }
    }

    return warnings;
  }

  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }
  function qsa(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function formatUpdatedAtJst(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    var parts = new Intl.DateTimeFormat("ja-JP", {
      timeZone: "Asia/Tokyo",
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).formatToParts(d);
    var y = "";
    var mo = "";
    var da = "";
    var h = "";
    var mi = "";
    parts.forEach(function (p) {
      if (p.type === "year") y = p.value;
      if (p.type === "month") mo = p.value;
      if (p.type === "day") da = p.value;
      if (p.type === "hour") h = p.value;
      if (p.type === "minute") mi = p.value;
    });
    return y + "/" + mo + "/" + da + " " + h + ":" + mi;
  }

  function updateLastUpdatedDisplay(iso) {
    var label = formatUpdatedAtJst(iso);
    if (!label) return;
    qsa(".last-updated-label").forEach(function (el) {
      el.textContent = "最終更新: " + label;
    });
    qsa(".print-updated-at").forEach(function (el) {
      el.textContent = "最終更新: " + label;
    });
    var root = qs("#last-updated-at");
    if (root) root.setAttribute("data-updated-at", iso);
  }

  function setDirty(on) {
    dirty = !!on;
    var banner = qs("#edit-dirty-banner");
    if (banner) banner.hidden = !dirty;
    qsa(".print-btn, [data-print-day]").forEach(function (btn) {
      btn.disabled = dirty;
      btn.title = dirty
        ? "未保存の並び替えがあります。正本再生成後に印刷してください"
        : "";
    });
    qsa("td.eta").forEach(function (td) {
      if (dirty) td.classList.add("eta-stale");
      else td.classList.remove("eta-stale");
    });
    try {
      if (dirty) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(collectRoutesPayload()));
      }
    } catch (e) {}
  }

  function cellText(tr, cls) {
    var el = tr.querySelector("td." + cls);
    if (!el) return "";
    return (el.textContent || "").replace(/\s+/g, " ").trim();
  }

  function visitFromRow(tr) {
    var nameEl = tr.querySelector("td.name strong");
    var idEl = tr.querySelector("td.name .id");
    var tds = tr.querySelectorAll("td");
    // tools, order, name, type, deadline, eta, time-ng, flags, addr, note
    return {
      order: cellText(tr, "order"),
      name: nameEl ? nameEl.textContent.trim() : "",
      id: idEl ? idEl.textContent.trim() : tr.dataset.patientId || "",
      type: (tds[3] && tds[3].textContent.trim()) || "",
      deadline: cellText(tr, "deadline"),
      eta: cellText(tr, "eta"),
      time_ng: cellText(tr, "time-ng") || "—",
      flags: cellText(tr, "flags") || "—",
      address: cellText(tr, "addr"),
      note: cellText(tr, "note"),
    };
  }

  function renumberBlock(block) {
    var rows = qsa("tbody tr", block);
    rows.forEach(function (tr, i) {
      var orderTd = tr.querySelector("td.order");
      if (orderTd) orderTd.textContent = String(i + 1);
    });
  }

  function tsvEscape(cell) {
    return String(cell || "")
      .replace(/\t/g, " ")
      .replace(/\r/g, " ")
      .replace(/\n/g, " ");
  }

  function visitsToTsv(visits, day, doctor) {
    var header = [
      "日付",
      "医師",
      "順",
      "氏名",
      "ID",
      "区分",
      "期限",
      "予定時間",
      "時間NG",
      "特記",
      "住所",
      "備考",
    ];
    var lines = [header.join("\t")];
    visits.forEach(function (v) {
      lines.push(
        [
          day,
          doctor,
          v.order,
          v.name,
          v.id,
          v.type,
          v.deadline,
          v.eta,
          v.time_ng || "—",
          v.flags || "—",
          v.address,
          v.note,
        ]
          .map(tsvEscape)
          .join("\t")
      );
    });
    return lines.join("\n");
  }

  function syncBlockTsv(block) {
    var day = block.dataset.day;
    var doctor = block.dataset.doctor;
    var tsvId = block.dataset.tsvId;
    var visits = qsa("tbody tr", block).map(visitFromRow);
    var el = document.getElementById(tsvId);
    if (el) el.value = visitsToTsv(visits, day, doctor);
  }

  function syncDayChips(dayCard) {
    var chipRow = qs(".chip-row", dayCard);
    if (!chipRow) return;
    var chips = [];
    qsa(".doctor-block", dayCard).forEach(function (block) {
      var doctor = block.dataset.doctor;
      var dc = block.classList.contains("hanawa")
        ? "hanawa"
        : block.classList.contains("katayama")
          ? "katayama"
          : "torikoe";
      qsa("tbody tr", block).forEach(function (tr) {
        var v = visitFromRow(tr);
        chips.push(
          '<span class="chip ' +
            dc +
            '" title="' +
            escapeAttr(v.id) +
            '">' +
            escapeHtml(v.name) +
            " <small>" +
            escapeHtml(doctor) +
            "</small></span>"
        );
      });
    });
    chipRow.innerHTML = chips.join("");
  }

  function syncDayTsv(dayCard) {
    var dayId = dayCard.id.replace(/^day-/, "");
    var parts = [];
    var first = true;
    qsa(".doctor-block", dayCard).forEach(function (block) {
      var el = document.getElementById(block.dataset.tsvId);
      if (!el || !el.value) return;
      if (first) {
        parts.push(el.value);
        first = false;
      } else {
        var lines = el.value.split("\n");
        parts.push(lines.slice(1).join("\n"));
      }
    });
    var dayTsv = document.getElementById("tsv-day-" + dayId);
    if (dayTsv) dayTsv.value = parts.filter(Boolean).join("\n");
  }

  function syncAllTsv() {
    var allParts = [];
    var header =
      [
        "日付",
        "医師",
        "順",
        "氏名",
        "ID",
        "区分",
        "期限",
        "予定時間",
        "時間NG",
        "特記",
        "住所",
        "備考",
      ].join("\t");
    allParts.push(header);
    qsa("article.day-card").forEach(function (dayCard) {
      qsa(".doctor-block", dayCard).forEach(function (block) {
        var visits = qsa("tbody tr", block).map(visitFromRow);
        visits.forEach(function (v) {
          allParts.push(
            [
              block.dataset.day,
              block.dataset.doctor,
              v.order,
              v.name,
              v.id,
              v.type,
              v.deadline,
              v.eta,
              v.time_ng || "—",
              v.flags || "—",
              v.address,
              v.note,
            ]
              .map(tsvEscape)
              .join("\t")
          );
        });
      });
    });
    var allEl = document.getElementById("tsv-all");
    if (allEl) allEl.value = allParts.join("\n");

    // 患者別一覧
    var byPatient = {};
    qsa("article.day-card").forEach(function (dayCard) {
      qsa(".doctor-block", dayCard).forEach(function (block) {
        qsa("tbody tr", block).forEach(function (tr) {
          var v = visitFromRow(tr);
          if (!byPatient[v.id]) {
            byPatient[v.id] = {
              name: v.name,
              id: v.id,
              type: v.type,
              deadline: v.deadline,
              days: [],
              doctors: {},
            };
          }
          byPatient[v.id].days.push(block.dataset.day + "（" + block.dataset.doctor + "）");
          byPatient[v.id].doctors[block.dataset.doctor] = true;
        });
      });
    });
    var pHeader = ["氏名", "ID", "区分", "期限", "往診日", "医師", "回数"].join("\t");
    var pLines = [pHeader];
    Object.keys(byPatient)
      .sort(function (a, b) {
        return byPatient[a].name.localeCompare(byPatient[b].name, "ja");
      })
      .forEach(function (id) {
        var p = byPatient[id];
        var docs = Object.keys(p.doctors);
        pLines.push(
          [
            p.name,
            p.id,
            p.type,
            p.deadline,
            p.days.join("、"),
            docs.length > 1 ? "複数" : docs[0] || "",
            String(p.days.length),
          ]
            .map(tsvEscape)
            .join("\t")
        );
      });
    var pEl = document.getElementById("tsv-patients");
    if (pEl) pEl.value = pLines.join("\n");
  }

  function syncSummary() {
    var counts = {};
    qsa("article.day-card").forEach(function (dayCard) {
      var day = dayCard.dataset.day;
      counts[day] = { 花輪: 0, 片山: 0, 鳥越: 0 };
      qsa(".doctor-block", dayCard).forEach(function (block) {
        var n = qsa("tbody tr", block).length;
        var d = block.dataset.doctor;
        if (counts[day][d] !== undefined) counts[day][d] = n;
      });
    });
    qsa("table.summary tbody tr").forEach(function (tr) {
      var day = (tr.cells[0] && tr.cells[0].textContent.trim()) || "";
      var c = counts[day];
      if (!c) return;
      function num(n) {
        return n ? String(n) : "—";
      }
      if (tr.cells[1]) tr.cells[1].textContent = num(c["花輪"]);
      if (tr.cells[2]) tr.cells[2].textContent = num(c["片山"]);
      if (tr.cells[3]) tr.cells[3].textContent = num(c["鳥越"]);
      if (tr.cells[4]) {
        var total = c["花輪"] + c["片山"] + c["鳥越"];
        tr.cells[4].innerHTML = "<strong>" + total + "</strong>";
      }
    });
  }

  function afterStructureChange(affectedDayCards) {
    var seen = {};
    (affectedDayCards || []).forEach(function (card) {
      if (!card || seen[card.id]) return;
      seen[card.id] = true;
      qsa(".doctor-block", card).forEach(function (block) {
        renumberBlock(block);
        syncBlockTsv(block);
      });
      syncDayChips(card);
      syncDayTsv(card);
      updateDayMeta(card);
    });
    syncAllTsv();
    syncSummary();
    setDirty(true);
  }

  function updateDayMeta(dayCard) {
    var labels = [];
    var total = 0;
    qsa(".doctor-block", dayCard).forEach(function (block) {
      var n = qsa("tbody tr", block).length;
      total += n;
      labels.push(block.dataset.doctor + n + "件");
    });
    var meta = qs(".print-meta", dayCard);
    if (meta) meta.textContent = labels.join(" / ") + " ・ 合計" + total + "件";
    dayCard.classList.remove("dense", "medium", "normal");
    if (total >= 10) dayCard.classList.add("dense");
    else if (total >= 7) dayCard.classList.add("medium");
    else dayCard.classList.add("normal");
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, "&#39;");
  }

  function collectRoutes() {
    var routes = {};
    qsa("article.day-card").forEach(function (dayCard) {
      var day = dayCard.dataset.day;
      routes[day] = {};
      qsa(".doctor-block", dayCard).forEach(function (block) {
        var doctor = block.dataset.doctor;
        var ids = qsa("tbody tr", block).map(function (tr) {
          return tr.dataset.patientId;
        });
        if (ids.length) routes[day][doctor] = ids;
      });
    });
    return routes;
  }

  function collectRoutesPayload() {
    return {
      version: 1,
      period_key: window.OUSEHIN_PERIOD_KEY || "2026-08",
      updated_at: new Date().toISOString(),
      routes: collectRoutes(),
    };
  }

  var API_BASE = window.OUSEHIN_API_BASE || "http://127.0.0.1:8765";

  function apiAvailable() {
    return fetch(API_BASE + "/api/health", { method: "GET" })
      .then(function (r) {
        return r.ok;
      })
      .catch(function () {
        return false;
      });
  }

  async function saveOverridesToApi() {
    var payload = collectRoutesPayload();
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    } catch (e) {}
    var period = payload.period_key || "2026-08";
    var url =
      API_BASE +
      "/api/schedule/" +
      encodeURIComponent(period) +
      "?regenerate=1";
    var res = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    var data = {};
    try {
      data = await res.json();
    } catch (e) {}
    if (!res.ok) {
      var msg = (data && data.detail) || (data && data.error) || res.statusText;
      throw new Error(msg || "保存に失敗しました");
    }
    setDirty(false);
    var pending = qs("#edit-pending-apply");
    if (pending) pending.hidden = true;
    var hint = qs("#save-hint");
    if (hint) hint.hidden = true;
    updateLastUpdatedDisplay(payload.updated_at);
    if (window.showToast) {
      window.showToast(
        "DBに保存し、リストを再生成しました。予定時間を反映するには再読み込みしてください"
      );
    }
    return data;
  }

  function clearDropHints() {
    qsa(".drop-target, .drop-before, .drag-over-block").forEach(function (el) {
      el.classList.remove("drop-target", "drop-before", "drag-over-block");
    });
  }

  function dayCardOf(el) {
    return el.closest("article.day-card");
  }

  function bindRowDrag(tr) {
    tr.setAttribute("draggable", "false");
    var handle = tr.querySelector(".drag-handle");
    if (handle) {
      handle.addEventListener("mousedown", function () {
        tr.setAttribute("draggable", "true");
      });
      handle.addEventListener("touchstart", function () {
        tr.setAttribute("draggable", "true");
      }, { passive: true });
    }
    tr.addEventListener("dragstart", function (e) {
      if (!tr.getAttribute("draggable") || tr.getAttribute("draggable") === "false") {
        e.preventDefault();
        return;
      }
      dragRow = tr;
      tr.classList.add("dragging");
      try {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", tr.dataset.patientId || "");
      } catch (err) {}
    });
    tr.addEventListener("dragend", function () {
      tr.classList.remove("dragging");
      tr.setAttribute("draggable", "false");
      clearDropHints();
      dragRow = null;
    });
  }

  function bindTableDnD(tbody) {
    tbody.addEventListener("dragover", function (e) {
      if (!dragRow) return;
      e.preventDefault();
      var tr = e.target.closest("tr");
      clearDropHints();
      if (tr && tr !== dragRow && tbody.contains(tr)) {
        var rect = tr.getBoundingClientRect();
        var before = e.clientY < rect.top + rect.height / 2;
        tr.classList.add(before ? "drop-before" : "drop-target");
      } else {
        tbody.closest(".doctor-block").classList.add("drag-over-block");
      }
    });
    tbody.addEventListener("drop", function (e) {
      if (!dragRow) return;
      e.preventDefault();
      var destBlock = tbody.closest(".doctor-block");
      var srcBlock = dragRow.closest(".doctor-block");
      var tr = e.target.closest("tr");
      var affected = [dayCardOf(srcBlock), dayCardOf(destBlock)];

      if (srcBlock !== destBlock) {
        var warnings = validateMove({
          patientId: dragRow.dataset.patientId,
          fromDay: srcBlock.dataset.day,
          fromDoctor: srcBlock.dataset.doctor,
          toDay: destBlock.dataset.day,
          toDoctor: destBlock.dataset.doctor,
          excludeRow: dragRow,
        });
        if (warnings.length) {
          var ok = window.confirm(
            "確認が必要な点があります:\n\n- " +
              warnings.join("\n- ") +
              "\n\nそれでも移動しますか？"
          );
          if (!ok) {
            clearDropHints();
            return;
          }
        }
      }

      if (tr && tr !== dragRow && tbody.contains(tr)) {
        var rect = tr.getBoundingClientRect();
        var before = e.clientY < rect.top + rect.height / 2;
        tbody.insertBefore(dragRow, before ? tr : tr.nextSibling);
      } else {
        tbody.appendChild(dragRow);
      }

      if (srcBlock !== destBlock) {
        warnCapacity(destBlock);
      }
      clearDropHints();
      afterStructureChange(affected);
      if (window.showToast) {
        window.showToast(
          srcBlock === destBlock ? "順番を変更しました" : "別の枠へ移動しました"
        );
      }
    });
  }

  function warnCapacity(block) {
    var n = qsa("tbody tr", block).length;
    var day = block.dataset.day;
    var doctor = block.dataset.doctor;
    var cap = capacityFor(day, doctor);
    if (n > cap && window.showToast) {
      window.showToast(
        "注意: " + doctor + " が定員目安" + cap + "を超えています（" + n + "件）"
      );
    }
  }

  function updateMoveWarningsUI() {
    var box = qs("#move-warnings");
    var list = qs("#move-warnings-list");
    var okBtn = qs("#move-modal-ok");
    if (!moveTargetRow || selectedInsertIndex === null) {
      if (box) box.hidden = true;
      if (okBtn) {
        okBtn.disabled = true;
        okBtn.textContent = "移動する";
        okBtn.classList.remove("warn");
      }
      return;
    }
    var srcBlock = moveTargetRow.closest(".doctor-block");
    var day = qs("#move-day-select").value;
    var doctor = qs("#move-doctor-select").value;
    var warnings = validateMove({
      patientId: moveTargetRow.dataset.patientId,
      fromDay: srcBlock && srcBlock.dataset.day,
      fromDoctor: srcBlock && srcBlock.dataset.doctor,
      toDay: day,
      toDoctor: doctor,
      excludeRow: moveTargetRow,
    });
    if (list) {
      list.innerHTML = warnings
        .map(function (w) {
          return "<li>" + escapeHtml(w) + "</li>";
        })
        .join("");
    }
    if (box) box.hidden = warnings.length === 0;
    if (okBtn) {
      okBtn.disabled = false;
      if (warnings.length) {
        okBtn.textContent = "警告ありでも移動";
        okBtn.classList.add("warn");
      } else {
        okBtn.textContent = "移動する";
        okBtn.classList.remove("warn");
      }
    }
  }

  function renderInsertList() {
    var list = qs("#move-insert-list");
    var heading = qs("#insert-list-heading");
    if (!list || !moveTargetRow) return;
    var day = qs("#move-day-select").value;
    var doctor = qs("#move-doctor-select").value;
    var block = findDoctorBlock(day, doctor);
    var moveId = moveTargetRow.dataset.patientId;
    var visits = block
      ? qsa("tbody tr", block).filter(function (tr) {
          return tr !== moveTargetRow;
        })
      : [];

    if (heading) {
      heading.textContent =
        day + " " + doctor + " の往診順（挿入位置を選択）";
    }

    var html = [];
    function slotBtn(idx, label) {
      var sel = selectedInsertIndex === idx ? " selected" : "";
      html.push(
        '<button type="button" class="insert-slot' +
          sel +
          '" data-insert-index="' +
          idx +
          '" role="option" aria-selected="' +
          (selectedInsertIndex === idx ? "true" : "false") +
          '">▶ ' +
          escapeHtml(label) +
          "</button>"
      );
    }

    if (!visits.length) {
      slotBtn(0, "ここに挿入（先頭・この枠は0件）");
    } else {
      slotBtn(0, "ここに挿入（先頭）");
      visits.forEach(function (tr, i) {
        var v = visitFromRow(tr);
        html.push(
          '<div class="insert-visit">' +
            "<strong>" +
            escapeHtml(String(i + 1)) +
            ". " +
            escapeHtml(v.name) +
            "</strong> " +
            '<span class="id">' +
            escapeHtml(v.id) +
            "</span>" +
            '<div class="meta">' +
            escapeHtml(v.eta || "—") +
            " ／ " +
            escapeHtml(v.flags || "—") +
            "</div></div>"
        );
        var isLast = i === visits.length - 1;
        slotBtn(
          i + 1,
          isLast ? "ここに挿入（末尾）" : "ここに挿入（" + (i + 1) + "番の後）"
        );
      });
    }
    // 移動対象が同じ枠にいる場合のヒントは不要
    void moveId;
    list.innerHTML = html.join("");
    if (selectedInsertIndex === null && visits.length === 0) {
      selectedInsertIndex = 0;
      renderInsertList();
      return;
    }
    updateMoveWarningsUI();
  }

  function openMoveModal(tr) {
    moveTargetRow = tr;
    selectedInsertIndex = null;
    var modal = qs("#move-day-modal");
    var sel = qs("#move-day-select");
    var docWrap = qs("#move-doctor-wrap");
    var docSel = qs("#move-doctor-select");
    var title = qs("#move-modal-title");
    var v = visitFromRow(tr);
    if (title) title.textContent = v.name + "（" + v.id + "）を移動";

    var currentDay = tr.closest("article.day-card").dataset.day;
    sel.innerHTML = "";
    qsa("article.day-card").forEach(function (card) {
      var opt = document.createElement("option");
      opt.value = card.dataset.day;
      opt.textContent = card.dataset.day;
      if (card.dataset.day === currentDay) opt.selected = true;
      sel.appendChild(opt);
    });

    function refreshDoctors() {
      var day = sel.value;
      var card = findDayCard(day);
      var docs = card
        ? qsa(".doctor-block", card).map(function (b) {
            return b.dataset.doctor;
          })
        : [];
      docSel.innerHTML = "";
      docs.forEach(function (d) {
        var opt = document.createElement("option");
        opt.value = d;
        opt.textContent = d + "先生";
        docSel.appendChild(opt);
      });
      docWrap.hidden = docs.length <= 1;
      if (docs.length === 1) docSel.value = docs[0];
      selectedInsertIndex = null;
      renderInsertList();
    }
    sel.onchange = refreshDoctors;
    docSel.onchange = function () {
      selectedInsertIndex = null;
      renderInsertList();
    };
    refreshDoctors();
    modal.hidden = false;
  }

  function closeMoveModal() {
    var modal = qs("#move-day-modal");
    if (modal) modal.hidden = true;
    moveTargetRow = null;
    selectedInsertIndex = null;
  }

  function insertRowAt(tbody, row, index) {
    var rows = qsa("tr", tbody).filter(function (tr) {
      return tr !== row;
    });
    if (index >= rows.length) {
      tbody.appendChild(row);
    } else {
      tbody.insertBefore(row, rows[index]);
    }
  }

  function confirmMove() {
    if (!moveTargetRow || selectedInsertIndex === null) return;
    var day = qs("#move-day-select").value;
    var doctor = qs("#move-doctor-select").value;
    var card = findDayCard(day);
    if (!card) return;
    var block = findDoctorBlock(day, doctor);
    if (!block) {
      if (window.showToast) window.showToast("移動先の医師枠が見つかりません");
      return;
    }
    var srcCard = dayCardOf(moveTargetRow);
    var tbody = qs("tbody", block);
    insertRowAt(tbody, moveTargetRow, selectedInsertIndex);
    warnCapacity(block);
    closeMoveModal();
    afterStructureChange([srcCard, card]);
    if (window.showToast) window.showToast(day + " " + doctor + " へ移動しました");
  }

  function downloadOverridesFallback() {
    var payload = collectRoutesPayload();
    var text = JSON.stringify(payload, null, 2);
    try {
      localStorage.setItem(STORAGE_KEY, text);
    } catch (e) {}
    var blob = new Blob([text], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "schedule_overrides.json";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () {
      URL.revokeObjectURL(a.href);
      a.remove();
    }, 500);
    try {
      navigator.clipboard.writeText(text);
    } catch (e) {}
    var pending = qs("#edit-pending-apply");
    if (pending) pending.hidden = false;
    updateLastUpdatedDisplay(payload.updated_at);
    if (window.showToast) {
      window.showToast(
        "API未接続のため JSON をダウンロードしました。apply またはサーバー起動後に保存してください"
      );
    }
    var hint = qs("#save-hint");
    if (hint) {
      hint.hidden = false;
      hint.textContent =
        "ローカル API: python3 scripts/schedule_server.py を起動するか、JSON を apply してください";
    }
  }

  async function saveOverrides() {
    var bannerBtn = qs("#save-overrides-btn-banner");
    if (bannerBtn) bannerBtn.disabled = true;
    try {
      if (await apiAvailable()) {
        await saveOverridesToApi();
        return;
      }
      downloadOverridesFallback();
    } catch (err) {
      if (window.showToast) {
        window.showToast("保存失敗: " + (err && err.message ? err.message : String(err)));
      }
    } finally {
      if (bannerBtn) bannerBtn.disabled = false;
    }
  }

  function initPatientSearch() {
    var input = qs("#patient-search-input");
    var panel = qs("#patient-search-results");
    if (!input || !panel) return;

    var index = window.OUSEHIN_SEARCH_INDEX || [];
    var activeIdx = -1;
    var currentMatches = [];

    function normalizeQuery(s) {
      return String(s || "")
        .replace(/\s+/g, "")
        .toLowerCase()
        .replace(/[ァ-ン]/g, function (ch) {
          return String.fromCharCode(ch.charCodeAt(0) - 0x60);
        });
    }

    function entryHaystack(entry) {
      return normalizeQuery(
        (entry.name || "") + (entry.kana || "") + (entry.id || "")
      );
    }

    function formatVisitLabel(v) {
      if (!v) return "";
      return v.day + " " + v.doctor + (v.order ? " #" + v.order : "");
    }

    function findMatches(q) {
      var nq = normalizeQuery(q);
      if (!nq) return [];
      var hits = [];
      index.forEach(function (entry) {
        if (entryHaystack(entry).indexOf(nq) >= 0) hits.push(entry);
      });
      return hits.slice(0, 20);
    }

    function clearHighlights() {
      qsa("tr.search-hit").forEach(function (tr) {
        tr.classList.remove("search-hit");
      });
    }

    function scrollToPatient(patientId, day, doctor) {
      clearHighlights();
      var rows = qsa('tr[data-patient-id="' + patientId + '"]');
      if (day) {
        var filtered = rows.filter(function (tr) {
          return tr.getAttribute("data-day") === day;
        });
        if (doctor) {
          var byDoc = filtered.filter(function (tr) {
            return tr.getAttribute("data-doctor") === doctor;
          });
          if (byDoc.length) filtered = byDoc;
        }
        if (filtered.length) rows = filtered;
      }
      if (!rows.length) {
        if (window.showToast) {
          window.showToast("割当行が見つかりません: " + patientId);
        }
        return;
      }
      var row = rows[0];
      row.classList.add("search-hit");
      row.scrollIntoView({ block: "center", behavior: "smooth" });
      setTimeout(function () {
        row.classList.remove("search-hit");
      }, 4500);
    }

    function closePanel() {
      panel.hidden = true;
      panel.innerHTML = "";
      activeIdx = -1;
      currentMatches = [];
    }

    function renderResults(matches) {
      currentMatches = matches;
      activeIdx = -1;
      if (!matches.length) {
        panel.innerHTML =
          '<div class="patient-search-empty">該当する患者がいません</div>';
        panel.hidden = false;
        return;
      }
      panel.innerHTML = matches
        .map(function (entry, i) {
          var visit = entry.visits && entry.visits[0];
          var meta =
            visit && visit.day
              ? formatVisitLabel(visit)
              : entry.schedule_note || "割当なし";
          if (entry.visits && entry.visits.length > 1) {
            meta +=
              " ほか" + (entry.visits.length - 1) + "枠（先頭へジャンプ）";
          }
          var kana = entry.kana ? "（" + entry.kana + "）" : "";
          return (
            '<button type="button" class="patient-search-item" data-idx="' +
            i +
            '" data-pid="' +
            entry.id +
            '" data-day="' +
            (visit && visit.day ? visit.day : "") +
            '" data-doctor="' +
            (visit && visit.doctor ? visit.doctor : "") +
            '"><strong>' +
            entry.name +
            "</strong>" +
            kana +
            ' <span class="meta">' +
            entry.id +
            " · " +
            meta +
            "</span></button>"
          );
        })
        .join("");
      panel.hidden = false;
    }

    function pickItem(btn) {
      if (!btn) return;
      scrollToPatient(
        btn.getAttribute("data-pid"),
        btn.getAttribute("data-day") || "",
        btn.getAttribute("data-doctor") || ""
      );
      input.value = btn.querySelector("strong")
        ? btn.querySelector("strong").textContent
        : "";
      closePanel();
    }

    function setActive(idx) {
      var items = qsa(".patient-search-item", panel);
      items.forEach(function (el, i) {
        el.classList.toggle("active", i === idx);
      });
      activeIdx = idx;
      if (idx >= 0 && items[idx]) {
        items[idx].scrollIntoView({ block: "nearest" });
      }
    }

    input.addEventListener("input", function () {
      var q = input.value.trim();
      if (q.length < 1) {
        closePanel();
        return;
      }
      renderResults(findMatches(q));
    });

    input.addEventListener("keydown", function (e) {
      if (panel.hidden) return;
      var items = qsa(".patient-search-item", panel);
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive(Math.min(activeIdx + 1, items.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive(Math.max(activeIdx - 1, 0));
      } else if (e.key === "Enter") {
        if (activeIdx >= 0 && items[activeIdx]) {
          e.preventDefault();
          pickItem(items[activeIdx]);
        } else if (items.length === 1) {
          e.preventDefault();
          pickItem(items[0]);
        }
      } else if (e.key === "Escape") {
        closePanel();
      }
    });

    panel.addEventListener("click", function (e) {
      var btn = e.target.closest(".patient-search-item");
      if (btn) pickItem(btn);
    });

    document.addEventListener("click", function (e) {
      if (!e.target.closest(".patient-search")) closePanel();
    });
  }

  function init() {
    qsa(".doctor-block").forEach(function (block) {
      var tbody = qs("tbody", block);
      if (!tbody) return;
      bindTableDnD(tbody);
      qsa("tr", tbody).forEach(bindRowDrag);
    });

    document.addEventListener("click", function (e) {
      var btn = e.target.closest(".move-day-btn");
      if (btn) {
        var tr = btn.closest("tr");
        if (tr) openMoveModal(tr);
      }
      var slot = e.target.closest(".insert-slot");
      if (slot && qs("#move-day-modal") && !qs("#move-day-modal").hidden) {
        selectedInsertIndex = parseInt(slot.getAttribute("data-insert-index"), 10);
        renderInsertList();
      }
      if (e.target.closest("#move-modal-cancel")) closeMoveModal();
      if (e.target.closest("#move-modal-ok")) confirmMove();
      if (e.target.closest("#save-overrides-btn-banner")) saveOverrides();
      if (e.target.closest("#move-modal-backdrop")) closeMoveModal();
    });

    window.addEventListener("beforeunload", function (e) {
      if (!dirty) return;
      e.preventDefault();
      e.returnValue = "";
    });

    apiAvailable().then(function (ok) {
      var el = qs("#api-status");
      if (!el) return;
      if (ok) {
        el.textContent = "ローカルAPI接続済み";
        el.hidden = false;
      } else {
        el.hidden = true;
      }
    });

    initPatientSearch();

    var updatedRoot = qs("#last-updated-at");
    if (updatedRoot) {
      var iso = updatedRoot.getAttribute("data-updated-at");
      if (iso) updateLastUpdatedDisplay(iso);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
