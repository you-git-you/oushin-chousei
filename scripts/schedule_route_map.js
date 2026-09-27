/* 日別ルートを画面内の地図に描く（表の現在順。住所の外部共有はしない） */
(function () {
  var CLINIC = "東京都練馬区東大泉1-28-7 フォンターナ琴坂";
  var KATAYAMA_HOME = "東京都練馬区大泉学園町6-28-34";
  var TORIGOE_HOME = "東京都練馬区東大泉2-40-8";
  var MISSING = { "（住所未登録）": true, "—": true, "-": true, "": true };
  var geoCache = Object.create(null);
  function blankView(canvas) {
    return {
      canvas: canvas,
      map: null,
      layer: null,
      pins: [],
      dots: [],
      pinsReady: false,
      fitting: false,
      generation: 0,
      statusEl: null,
    };
  }

  var modalView = blankView(null);
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

  function routeFromBlock(block, dayKey) {
    var dow = dowFromDayKey(dayKey);
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
    return {
      doctor: doctor,
      missingOrders: missingOrders,
      points: points,
      visitCount: patients.length,
    };
  }

  function collectRoutes(dayCard) {
    var dayKey = dayCard.getAttribute("data-day") || "";
    var routes = qsa(".doctor-block", dayCard).map(function (block) {
      return routeFromBlock(block, dayKey);
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
      if (pt) geoCache[key] = Promise.resolve(pt);
      else delete geoCache[key];
      return pt;
    }).catch(function () {
      delete geoCache[key];
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

  function waitForCanvasSize(el) {
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

  var leafletPromise = null;

  function loadLeaflet() {
    if (window.L) return Promise.resolve(window.L);
    if (leafletPromise) return leafletPromise;
    leafletPromise = new Promise(function (resolve, reject) {
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
        leafletPromise = null;
        reject(new Error("leaflet"));
      };
      document.head.appendChild(s);
    });
    return leafletPromise;
  }

  function ensureMap(view) {
    return loadLeaflet().then(function (L) {
      var el = view.canvas;
      if (!el) throw new Error("canvas");
      if (view.map) {
        view.map.invalidateSize({ animate: false });
        return L;
      }
      view.map = L.map(el, { zoomControl: true, attributionControl: true });
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap",
      }).addTo(view.map);
      view.map.setView([35.749, 139.586], 13);
      view.layer = L.layerGroup().addTo(view.map);
      view.map.on("zoomend", function () {
        if (!view.pinsReady || view.fitting) return;
        spreadOverlaps(L, view);
      });
      return L;
    });
  }

  function pinSize(label) {
    return String(label).length >= 2 ? 36 : 32;
  }

  function numberedIcon(L, label, color, ox, oy) {
    var text = String(label);
    var size = pinSize(text);
    var shiftX = ox || 0;
    var shiftY = oy || 0;
    var stem = "";
    var reach = Math.sqrt(shiftX * shiftX + shiftY * shiftY);
    if (reach > 2) {
      var edge = size / 2;
      var line = Math.max(0, reach - edge);
      var deg = (Math.atan2(-shiftY, -shiftX) * 180) / Math.PI;
      stem =
        '<span class="map-pin-stem" style="position:absolute;left:50%;top:50%;height:2px;margin-top:-1px;transform-origin:0 50%;pointer-events:none;opacity:.9;width:' +
        line.toFixed(1) +
        "px;background:" +
        color +
        ";transform:rotate(" +
        deg.toFixed(1) +
        "deg) translateX(" +
        edge.toFixed(1) +
        'px)"></span>';
    }
    return L.divIcon({
      className: "map-pin",
      html:
        '<span class="map-pin-inner" style="position:relative;box-sizing:border-box;border:2px solid #fff;background:' +
        color +
        ";width:" +
        size +
        "px;height:" +
        size +
        "px;font-size:14px;font-weight:800;line-height:1;transform:translate(" +
        shiftX +
        "px," +
        shiftY +
        'px)">' +
        stem +
        esc(text) +
        "</span>",
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
    });
  }

  function pinSeq(point, routeIndex) {
    if (point.kind === "start") return routeIndex * 100;
    if (point.kind === "end") return routeIndex * 100 + 80;
    var n = parseInt(point.order, 10);
    if (!isFinite(n)) n = 40;
    return routeIndex * 100 + n;
  }

  function clearAnchorDots(view) {
    view.dots.forEach(function (dot) {
      if (view.layer) view.layer.removeLayer(dot);
    });
    view.dots = [];
  }

  function placePinIcon(L, view, pin, ox, oy) {
    pin.marker.setIcon(numberedIcon(L, pin.label, pin.color, ox, oy));
    pin.marker.setZIndexOffset(pin.seq);
    pin.marker.unbindTooltip();
    pin.marker.bindTooltip(pin.badge, {
      direction: "top",
      offset: [ox, oy - pinSize(pin.label) / 2 - 6],
    });
    if (Math.abs(ox) + Math.abs(oy) <= 2) return;
    var dot = L.marker(pin.ll, {
      interactive: false,
      keyboard: false,
      zIndexOffset: pin.seq - 20,
      icon: L.divIcon({
        className: "map-pin",
        html:
          '<span style="display:block;width:8px;height:8px;border-radius:99px;box-sizing:border-box;background:#fff;border:2px solid ' +
          pin.color +
          ';"></span>',
        iconSize: [8, 8],
        iconAnchor: [4, 4],
      }),
    });
    view.layer.addLayer(dot);
    view.dots.push(dot);
  }

  /* 同じ建物・近接で円が重なる番号だけ、本来の位置から押し広げて全部読めるようにする */
  function spreadOverlaps(L, view) {
    if (!view.map || !view.pins.length) return;
    clearAnchorDots(view);
    var base = view.pins.map(function (pin) {
      return view.map.latLngToContainerPoint(pin.ll);
    });
    var offsets = view.pins.map(function () {
      return { x: 0, y: 0 };
    });
    var guard = 0;
    var moved = true;
    while (moved && guard < 120) {
      moved = false;
      guard += 1;
      for (var i = 0; i < view.pins.length; i++) {
        for (var j = i + 1; j < view.pins.length; j++) {
          var need = (pinSize(view.pins[i].label) + pinSize(view.pins[j].label)) / 2 + 6;
          var ix = base[i].x + offsets[i].x;
          var iy = base[i].y + offsets[i].y;
          var jx = base[j].x + offsets[j].x;
          var jy = base[j].y + offsets[j].y;
          var dx = jx - ix;
          var dy = jy - iy;
          var dist = Math.sqrt(dx * dx + dy * dy);
          if (dist >= need - 0.25) continue;
          var ux;
          var uy;
          if (dist < 0.5) {
            var ang = (i + 1) * 2.399963 + (j + 1) * 0.7;
            ux = Math.cos(ang);
            uy = Math.sin(ang);
            dist = 0.5;
          } else {
            ux = dx / dist;
            uy = dy / dist;
          }
          var push = (need - dist) / 2;
          offsets[i].x -= ux * push;
          offsets[i].y -= uy * push;
          offsets[j].x += ux * push;
          offsets[j].y += uy * push;
          moved = true;
        }
      }
    }
    view.pins.forEach(function (pin, i) {
      placePinIcon(L, view, pin, Math.round(offsets[i].x), Math.round(offsets[i].y));
    });
  }

  function pinCorners(view) {
    var pts = [];
    var mapRect = view.map.getContainer().getBoundingClientRect();
    view.pins.forEach(function (pin) {
      var el = pin.marker.getElement();
      var inner = el && el.querySelector(".map-pin-inner");
      if (!inner) return;
      var rect = inner.getBoundingClientRect();
      var pad = 6;
      pts.push(
        view.map.containerPointToLatLng([
          rect.left - mapRect.left - pad,
          rect.top - mapRect.top - pad,
        ])
      );
      pts.push(
        view.map.containerPointToLatLng([
          rect.right - mapRect.left + pad,
          rect.bottom - mapRect.top + pad,
        ])
      );
    });
    return pts;
  }

  function layoutPins(L, view) {
    if (!view.map || !view.pins.length) return;
    view.fitting = true;
    spreadOverlaps(L, view);
    var pts = pinCorners(view);
    if (pts.length && !view.map.getBounds().contains(L.latLngBounds(pts))) {
      view.map.fitBounds(L.latLngBounds(pts).pad(0.06), { animate: false });
      spreadOverlaps(L, view);
    }
    view.fitting = false;
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

  function drawRoutes(L, routes, view) {
    var generation = view.generation;
    view.pinsReady = false;
    view.pins = [];
    clearAnchorDots(view);
    if (view.layer) view.layer.clearLayers();
    var allLatLngs = [];
    var jobs = routes.map(function (route, routeIndex) {
      var color = ROUTE_COLORS[route.doctor] || "#334155";
      return geocodePoints(route.points).then(function (located) {
        if (generation !== view.generation) {
          return { ok: 0, missed: 0 };
        }
        var latlngs = [];
        located.forEach(function (item) {
          if (!item.latlng) return;
          var ll = L.latLng(item.latlng.lat, item.latlng.lon);
          latlngs.push(ll);
          allLatLngs.push(ll);
          var label = markerLabel(item.point);
          var marker = L.marker(ll, {
            icon: numberedIcon(L, label, color, 0, 0),
            keyboard: false,
            zIndexOffset: pinSeq(item.point, routeIndex),
          });
          var badge = kindMeta(item.point).badge;
          marker.bindTooltip(badge, {
            direction: "top",
            offset: [0, -12],
          });
          view.layer.addLayer(marker);
          view.pins.push({
            marker: marker,
            ll: ll,
            label: label,
            color: color,
            seq: pinSeq(item.point, routeIndex),
            badge: badge,
          });
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
        view.layer.addLayer(straight);
        if (allLatLngs.length && view.map) {
          view.map.fitBounds(L.latLngBounds(allLatLngs).pad(0.22), { animate: false });
        }
        return fetchDriving(latlngs).then(function (line) {
          if (generation !== view.generation) {
            return { ok: latlngs.length, missed: located.length - latlngs.length };
          }
          if (line) {
            view.layer.removeLayer(straight);
            view.layer.addLayer(
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
      if (generation !== view.generation) {
        return { ok: 0, missed: 0, stale: true };
      }
      if (allLatLngs.length && view.map) {
        view.map.fitBounds(L.latLngBounds(allLatLngs).pad(0.22), { animate: false });
        view.map.invalidateSize({ animate: false });
        view.pinsReady = true;
        layoutPins(L, view);
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

  function setViewStatus(view, text) {
    var el = view.statusEl;
    if (el) el.textContent = text || "";
  }

  function openForDay(dayId) {
    var card = document.getElementById(dayId);
    var modal = document.getElementById("route-map-modal");
    if (!card || !modal) return;
    var data = collectRoutes(card);
    renderList(data);
    modal.hidden = false;
    modalView.canvas = document.getElementById("route-map-canvas");
    modalView.statusEl = document.getElementById("route-map-status");
    modalView.generation += 1;
    setViewStatus(modalView, "地図を準備しています…");
    waitForCanvasSize(modalView.canvas)
      .then(function () {
        return ensureMap(modalView);
      })
      .then(function (L) {
        if (modalView.map) modalView.map.invalidateSize({ animate: false });
        setViewStatus(modalView, "停留所を地図に載せています…");
        return drawRoutes(L, data.routes, modalView);
      })
      .then(function (stats) {
        if (stats && stats.stale) return;
        if (modalView.map && window.L && modalView.pinsReady) {
          modalView.map.invalidateSize({ animate: false });
          layoutPins(window.L, modalView);
        }
        if (!stats || !stats.ok) {
          setViewStatus(modalView, "停留所を地図に載せられませんでした。ネット接続を確認してください。");
          return;
        }
        if (stats.missed) {
          setViewStatus(
            modalView,
            "一部の住所は地図に載せられませんでした（" + stats.missed + "件）。"
          );
          return;
        }
        setViewStatus(modalView, "");
      })
      .catch(function () {
        setViewStatus(modalView, "地図を読み込めませんでした。ネット接続を確認してください。");
      });
  }

  function close() {
    var modal = document.getElementById("route-map-modal");
    var body = document.getElementById("route-map-modal-body");
    modalView.generation += 1;
    modalView.pinsReady = false;
    modalView.pins = [];
    clearAnchorDots(modalView);
    if (modalView.layer) modalView.layer.clearLayers();
    if (body) body.innerHTML = "";
    setViewStatus(modalView, "");
    if (modal) modal.hidden = true;
  }

  function paintInline(view, block) {
    var dayCard = block.closest(".day-card");
    var dayKey = dayCard ? dayCard.getAttribute("data-day") || "" : "";
    var route = routeFromBlock(block, dayKey);
    view.generation += 1;
    setViewStatus(view, "停留所を地図に載せています…");
    return waitForCanvasSize(view.canvas)
      .then(function () {
        return ensureMap(view);
      })
      .then(function (L) {
        if (view.map) view.map.invalidateSize({ animate: false });
        return drawRoutes(L, [route], view);
      })
      .then(function (stats) {
        if (stats && stats.stale) return;
        try {
          if (view.map && window.L && view.pinsReady) {
            view.map.invalidateSize({ animate: false });
            layoutPins(window.L, view);
          }
        } catch (err) {
          setViewStatus(view, "地図の表示を調整できませんでした。");
          return;
        }
        if (!stats || !stats.ok) {
          setViewStatus(view, "停留所を地図に載せられませんでした。ネット接続を確認してください。");
          return;
        }
        if (stats.missed) {
          setViewStatus(view, "一部の住所は地図に載せられませんでした（" + stats.missed + "件）。");
          return;
        }
        setViewStatus(view, "");
      })
      .catch(function () {
        setViewStatus(view, "地図を読み込めませんでした。ネット接続を確認してください。");
      });
  }

  function mountInlineMaps() {
    var chain = Promise.resolve();
    qsa(".inline-route-map").forEach(function (canvas) {
      var block = canvas.closest(".doctor-block");
      if (!block || block._routeMapView) return;
      var view = blankView(canvas);
      var wrap = canvas.parentNode;
      view.statusEl = wrap ? wrap.querySelector(".map-status") : null;
      block._routeMapView = view;
      chain = chain.then(function () {
        return paintInline(view, block);
      });
    });
  }

  function refreshCard(card) {
    if (!card) return;
    qsa(".doctor-block", card).forEach(function (block) {
      if (block._routeMapView) paintInline(block._routeMapView, block);
    });
  }

  window.OusehinRouteMap = {
    one: openForDay,
    close: close,
    refreshCard: refreshCard,
  };

  document.addEventListener("click", function (ev) {
    var t = ev.target;
    if (!t) return;
    if (t.id === "route-map-modal-close" || t.id === "route-map-modal-backdrop") {
      close();
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountInlineMaps);
  } else {
    mountInlineMaps();
  }
})();
