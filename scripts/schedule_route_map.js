/* 日別ルートを画面内の地図に描く（表の現在順。住所の外部共有はしない） */
(function () {
  var CLINIC = "東京都練馬区東大泉1-28-7 フォンターナ琴坂";
  var KATAYAMA_HOME = "東京都練馬区大泉学園町6-28-34";
  var TORIGOE_HOME = "東京都練馬区東大泉2-40-8";
  var MISSING = { "（住所未登録）": true, "—": true, "-": true, "": true };
  var geoCache = Object.create(null);
  var liveMap = null;
  var liveLayer = null;
  var ROUTE_COLORS = { 花輪: "#2563eb", 片山: "#c2410c", 鳥越: "#047857", 鳥越午前: "#0f766e" };

  function qsa(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function dowFromDayKey(dayKey) {
    var m = String(dayKey || "").match(/\(([月土])\)/);
    return m ? m[1] : "";
  }

  function addressForVisitDay(address, dow) {
    var text = String(address || "")
      .replace(/\n/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    if (text.indexOf("【月】") >= 0 && text.indexOf("【土】") >= 0) {
      if (dow === "月") {
        var mon = text.match(/【月】([^【]+)/);
        return mon ? mon[1].trim() : text;
      }
      if (dow === "土") {
        var sat = text.match(/【土】(.+)$/);
        return sat ? sat[1].trim() : text;
      }
    }
    if (text.indexOf("【自宅】") >= 0) {
      var parts = text.split("【自宅】");
      var facility = (parts[0] || "").trim();
      var home = (parts[1] || "").trim();
      var after = facility.match(/】\s*(.+)$/);
      var monAddr = after ? after[1].trim() : facility;
      if (dow === "土") return home;
      if (dow === "月") return monAddr;
    }
    return text;
  }

  function isMissingAddress(addr) {
    var s = String(addr || "").replace(/\s+/g, "").trim();
    return !s || MISSING[addr] || MISSING[s] || s.indexOf("住所未登録") >= 0;
  }

  function endpoints(doctor) {
    if (doctor === "片山") {
      return {
        origin: CLINIC,
        dest: KATAYAMA_HOME,
        originPlace: "ローソン前",
        originWhen: "13:15 お迎え・出発",
        originMapNote: "地図ピンはクリニック住所（ローソン前の目安）",
        destPlace: "片山先生ご自宅",
        destWhen: "往診後お送り",
        destMapNote: "",
      };
    }
    if (doctor === "鳥越" || doctor === "鳥越午前") {
      return {
        origin: TORIGOE_HOME,
        dest: TORIGOE_HOME,
        originPlace: "鳥越先生ご自宅",
        originWhen: "13:00 お迎え",
        originMapNote: "",
        destPlace: "鳥越先生ご自宅",
        destWhen: "お返し（帰宅目安 16:30）",
        destMapNote: "",
      };
    }
    return {
      origin: CLINIC,
      dest: CLINIC,
      originPlace: "榎本駐車場",
      originWhen: "10:15 集合・出発",
      originMapNote: "地図ピンはクリニック住所（榎本駐車場の目安）",
      destPlace: "クリニック（フォンターナ琴坂）",
      destWhen: "往診後お返し",
      destMapNote: "",
    };
  }

  function collectRoutes(dayCard) {
    var dayKey = dayCard.getAttribute("data-day") || "";
    var dow = dowFromDayKey(dayKey);
    var routes = [];
    qsa(".doctor-block", dayCard).forEach(function (block) {
      var doctor = block.getAttribute("data-doctor") || "";
      var ep = endpoints(doctor);
      var missingOrders = [];
      var patients = [];
      qsa("tbody tr", block).forEach(function (tr) {
        if (tr.getAttribute("data-cancelled") === "1") return;
        if (tr.classList.contains("visit-cancelled")) return;
        var nameEl = tr.querySelector("td.name strong");
        var name = nameEl ? nameEl.textContent.trim() : tr.getAttribute("data-patient-name") || "";
        var orderEl = tr.querySelector("td.order");
        var order = orderEl ? orderEl.textContent.trim() : "";
        var etaEl = tr.querySelector("td.eta");
        var eta = etaEl ? etaEl.textContent.replace(/\s+/g, " ").trim() : "";
        var raw = "";
        var addrTd = tr.querySelector("td.addr");
        if (addrTd) raw = (addrTd.textContent || "").replace(/\s+/g, " ").trim();
        var addr = addressForVisitDay(raw, dow);
        if (isMissingAddress(addr)) {
          missingOrders.push(order ? "#" + order : "不明");
          return;
        }
        patients.push({ name: name, addr: addr, order: order, eta: eta });
      });
      var points = [
        {
          kind: "start",
          place: ep.originPlace,
          when: ep.originWhen,
          mapNote: ep.originMapNote,
          addr: ep.origin,
        },
      ].concat(
        patients.map(function (p) {
          return {
            kind: "visit",
            place: p.name,
            when: p.eta,
            order: p.order,
            addr: p.addr,
            mapNote: "",
          };
        })
      );
      points.push({
        kind: "end",
        place: ep.destPlace,
        when: ep.destWhen,
        mapNote: ep.destMapNote,
        addr: ep.dest,
      });
      routes.push({
        doctor: doctor,
        missingOrders: missingOrders,
        points: points,
        visitCount: patients.length,
      });
    });
    return { dayKey: dayKey, routes: routes };
  }

  function esc(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function kindMeta(p) {
    if (p.kind === "start") return { badge: "出発", cls: "is-start" };
    if (p.kind === "end") return { badge: "帰宅", cls: "is-end" };
    var n = p.order ? String(p.order) : "";
    return { badge: n ? "往診 " + n : "往診", cls: "is-visit" };
  }

  function markerLabel(p) {
    if (p.kind === "start") return "出";
    if (p.kind === "end") return "帰";
    return p.order ? String(p.order) : "往";
  }

  function renderStop(p) {
    var meta = kindMeta(p);
    var when = p.when ? '<span class="map-stop-when">' + esc(p.when) + "</span>" : "";
    var note = p.mapNote ? '<p class="map-stop-note">' + esc(p.mapNote) + "</p>" : "";
    var addrLabel = p.kind === "visit" ? "訪問先" : "地図の検索位置";
    return (
      '<li class="map-stop ' +
      meta.cls +
      '">' +
      '<div class="map-stop-rail" aria-hidden="true"></div>' +
      '<span class="map-stop-badge">' +
      esc(meta.badge) +
      "</span>" +
      '<div class="map-stop-body">' +
      '<p class="map-stop-place">' +
      esc(p.place) +
      when +
      "</p>" +
      '<p class="map-stop-addr"><span class="map-addr-label">' +
      addrLabel +
      "</span> " +
      esc(p.addr) +
      "</p>" +
      note +
      "</div></li>"
    );
  }

  function privacyBanner(dayKey) {
    return (
      '<aside class="map-privacy" role="note">' +
      "<strong>取扱い注意（個人情報）</strong>" +
      "<p>院内の往診調整用です。氏名・住所の保存・転送・持ち出しはしないでください。" +
      "地図表示のため、住所を国土地理院の住所検索に送り、地図タイルはOpenStreetMapを使います。</p>" +
      "<p class=\"map-live-hint\">対象日: " +
      esc(dayKey) +
      " ／ この瞬間の表の順です。</p>" +
      "</aside>"
    );
  }

  function setStatus(text) {
    var el = document.getElementById("route-map-status");
    if (el) el.textContent = text || "";
  }

  function renderList(data) {
    var body = document.getElementById("route-map-modal-body");
    var title = document.getElementById("route-map-modal-title");
    if (!body) return;
    if (title) title.textContent = "今日の回り順（" + data.dayKey + "）";
    if (!data.routes.length) {
      body.innerHTML = privacyBanner(data.dayKey) + "<p>この日のルートがありません。</p>";
      return;
    }
    var routesHtml = data.routes
      .map(function (route) {
        var warn = "";
        if (!route.visitCount) {
          warn = '<p class="map-warn">往診先の住所がありません。</p>';
        } else if (route.missingOrders.length) {
          warn =
            '<p class="map-warn">住所なしのため地図から外した枠: ' +
            esc(route.missingOrders.join("、")) +
            "</p>";
        }
        return (
          '<section class="map-route" data-doctor="' +
          esc(route.doctor) +
          '">' +
          "<h4>" +
          esc(route.doctor) +
          "先生ルート<span>（往診 " +
          route.visitCount +
          "件）</span></h4>" +
          warn +
          '<ol class="map-stops">' +
          route.points.map(renderStop).join("") +
          "</ol>" +
          "</section>"
        );
      })
      .join("");
    body.innerHTML = privacyBanner(data.dayKey) + routesHtml;
  }

  var KNOWN_COORDS = {
    "東京都練馬区東大泉1-28-7 フォンターナ琴坂": { lat: 35.749924, lon: 139.587158 },
    "東京都練馬区東大泉1-28-7": { lat: 35.749924, lon: 139.587158 },
    "東京都練馬区大泉学園町6-28-34": { lat: 35.773266, lon: 139.58551 },
    "東京都練馬区東大泉2-40-8": { lat: 35.753834, lon: 139.592896 },
  };

  function normalizeQuery(addr) {
    return String(addr || "")
      .replace(/〒\s*\d{3}-?\d{4}/g, "")
      .replace(/フォンターナ琴坂.*$/g, "")
      .replace(/\s*[0-9０-９]+号室.*$/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function queryVariants(addr) {
    var q = normalizeQuery(addr);
    var out = [];
    function add(v) {
      if (v && out.indexOf(v) < 0) out.push(v);
    }
    add(q);
    add(q.replace(/[\s　].+$/, ""));
    if (q && q.indexOf("区") < 0 && q.indexOf("都") < 0 && q.indexOf("市") < 0) {
      add("東京都練馬区" + q);
    }
    return out;
  }

  function parseGsi(data) {
    if (!data || !data[0] || !data[0].geometry || !data[0].geometry.coordinates) {
      return null;
    }
    var c = data[0].geometry.coordinates;
    var lon = Number(c[0]);
    var lat = Number(c[1]);
    if (!isFinite(lat) || !isFinite(lon)) return null;
    return { lat: lat, lon: lon };
  }

  function geocodeGsi(q) {
    var url =
      "https://msearch.gsi.go.jp/address-search/AddressSearch?q=" +
      encodeURIComponent(q);
    return fetch(url).then(function (res) {
      if (!res.ok) throw new Error("gsi");
      return res.json();
    }).then(parseGsi);
  }

  function geocode(addr) {
    var key = normalizeQuery(addr);
    if (!key) return Promise.resolve(null);
    if (KNOWN_COORDS[addr]) return Promise.resolve(KNOWN_COORDS[addr]);
    if (KNOWN_COORDS[key]) return Promise.resolve(KNOWN_COORDS[key]);
    if (geoCache[key]) return geoCache[key];
    var variants = queryVariants(addr);
    var job = variants.reduce(function (prev, q) {
      return prev.then(function (pt) {
        if (pt) return pt;
        return geocodeGsi(q);
      });
    }, Promise.resolve(null)).then(function (pt) {
      geoCache[key] = Promise.resolve(pt);
      return pt;
    }).catch(function () {
      geoCache[key] = Promise.resolve(null);
      return null;
    });
    geoCache[key] = job;
    return job;
  }

  function sleep(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  function geocodePoints(points) {
    var out = [];
    var i = 0;
    function next() {
      if (i >= points.length) return Promise.resolve(out);
      var p = points[i];
      i += 1;
      return geocode(p.addr).then(function (pt) {
        out.push({ point: p, latlng: pt });
        return sleep(40).then(next);
      });
    }
    return next();
  }

  function waitForCanvasSize() {
    var el = document.getElementById("route-map-canvas");
    return new Promise(function (resolve) {
      var n = 0;
      function tick() {
        if (el && el.offsetWidth > 0 && el.offsetHeight > 0) {
          resolve();
          return;
        }
        n += 1;
        if (n > 30) {
          resolve();
          return;
        }
        requestAnimationFrame(tick);
      }
      tick();
    });
  }

  function loadLeaflet() {
    if (window.L) return Promise.resolve(window.L);
    return new Promise(function (resolve, reject) {
      var css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
      document.head.appendChild(css);
      var s = document.createElement("script");
      s.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
      s.onload = function () {
        resolve(window.L);
      };
      s.onerror = function () {
        reject(new Error("leaflet"));
      };
      document.head.appendChild(s);
    });
  }

  function ensureMap() {
    return loadLeaflet().then(function (L) {
      var el = document.getElementById("route-map-canvas");
      if (!el) throw new Error("canvas");
      if (liveMap) {
        liveMap.invalidateSize({ animate: false });
        return L;
      }
      liveMap = L.map(el, { zoomControl: true, attributionControl: true });
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap",
      }).addTo(liveMap);
      liveMap.setView([35.749, 139.586], 13);
      liveLayer = L.layerGroup().addTo(liveMap);
      return L;
    });
  }

  function numberedIcon(L, label, color) {
    return L.divIcon({
      className: "map-pin",
      html:
        '<span class="map-pin-inner" style="background:' +
        color +
        '">' +
        esc(label) +
        "</span>",
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });
  }

  function fetchDriving(latlngs) {
    if (!latlngs || latlngs.length < 2) return Promise.resolve(null);
    var path = latlngs
      .map(function (ll) {
        return ll.lng + "," + ll.lat;
      })
      .join(";");
    var url =
      "https://router.project-osrm.org/route/v1/driving/" +
      path +
      "?overview=full&geometries=geojson";
    return fetch(url)
      .then(function (res) {
        if (!res.ok) throw new Error("osrm");
        return res.json();
      })
      .then(function (data) {
        var geom = data && data.routes && data.routes[0] && data.routes[0].geometry;
        if (!geom || !geom.coordinates) return null;
        return geom.coordinates.map(function (c) {
          return [c[1], c[0]];
        });
      })
      .catch(function () {
        return null;
      });
  }

  function drawRoutes(L, routes) {
    if (liveLayer) liveLayer.clearLayers();
    var allLatLngs = [];
    var jobs = routes.map(function (route) {
      var color = ROUTE_COLORS[route.doctor] || "#334155";
      return geocodePoints(route.points).then(function (located) {
        var latlngs = [];
        located.forEach(function (item) {
          if (!item.latlng) return;
          var ll = L.latLng(item.latlng.lat, item.latlng.lon);
          latlngs.push(ll);
          allLatLngs.push(ll);
          var marker = L.marker(ll, {
            icon: numberedIcon(L, markerLabel(item.point), color),
            keyboard: false,
          });
          marker.bindTooltip(kindMeta(item.point).badge, { direction: "top" });
          liveLayer.addLayer(marker);
        });
        if (latlngs.length < 2) {
          return { ok: latlngs.length, missed: located.length - latlngs.length };
        }
        var straight = L.polyline(
          latlngs.map(function (ll) {
            return [ll.lat, ll.lng];
          }),
          { color: color, weight: 5, opacity: 0.7, dashArray: "8 8" }
        );
        liveLayer.addLayer(straight);
        if (allLatLngs.length && liveMap) {
          liveMap.fitBounds(L.latLngBounds(allLatLngs).pad(0.18));
        }
        return fetchDriving(latlngs).then(function (line) {
          if (line) {
            liveLayer.removeLayer(straight);
            liveLayer.addLayer(
              L.polyline(line, {
                color: color,
                weight: 5,
                opacity: 0.85,
              })
            );
          }
          return { ok: latlngs.length, missed: located.length - latlngs.length };
        });
      });
    });
    return Promise.all(jobs).then(function (stats) {
      if (allLatLngs.length && liveMap) {
        liveMap.fitBounds(L.latLngBounds(allLatLngs).pad(0.18));
        liveMap.invalidateSize({ animate: false });
      }
      var ok = 0;
      var missed = 0;
      (stats || []).forEach(function (s) {
        if (!s) return;
        ok += s.ok || 0;
        missed += s.missed || 0;
      });
      return { ok: ok, missed: missed };
    });
  }

  function openForDay(dayId) {
    var card = document.getElementById(dayId);
    var modal = document.getElementById("route-map-modal");
    if (!card || !modal) return;
    var data = collectRoutes(card);
    renderList(data);
    modal.hidden = false;
    setStatus("地図を準備しています…");
    waitForCanvasSize()
      .then(ensureMap)
      .then(function (L) {
        if (liveMap) liveMap.invalidateSize({ animate: false });
        setStatus("停留所を地図に載せています…");
        return drawRoutes(L, data.routes);
      })
      .then(function (stats) {
        if (liveMap) liveMap.invalidateSize({ animate: false });
        if (!stats || !stats.ok) {
          setStatus("停留所を地図に載せられませんでした。ネット接続を確認してください。");
          return;
        }
        if (stats.missed) {
          setStatus("一部の住所は地図に載せられませんでした（" + stats.missed + "件）。");
          return;
        }
        setStatus("");
      })
      .catch(function () {
        setStatus("地図を読み込めませんでした。ネット接続を確認してください。");
      });
  }

  function close() {
    var modal = document.getElementById("route-map-modal");
    var body = document.getElementById("route-map-modal-body");
    if (liveLayer) liveLayer.clearLayers();
    if (body) body.innerHTML = "";
    setStatus("");
    if (modal) modal.hidden = true;
  }

  window.OusehinRouteMap = {
    one: openForDay,
    close: close,
  };

  document.addEventListener("click", function (ev) {
    var t = ev.target;
    if (!t) return;
    if (t.id === "route-map-modal-close" || t.id === "route-map-modal-backdrop") {
      close();
    }
  });
})();
