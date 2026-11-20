/* Historical Rover/PC trace browser and read-only replay preview. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const R = 6371000;
  let ws = null;
  let connectionId = 0;
  let activeRoverBase = null;
  let roverHistory = [];
  const pcFiles = new Map();
  let pcSequence = 0;
  let selectedTrace = null;
  let selectedSource = null;
  let geoMap = null;
  let geoRoute = null;
  let fenceLayers = null;
  let selectionRequest = 0;
  let fence = null;
  let fenceSignature = null;
  let importedFence = null;
  let fenceOverride = false;
  let localFenceSource = '';
  let hasLoaded = false;

  function stored(key) { try { return localStorage.getItem(key); } catch { return null; } }
  function store(key, value) { try { localStorage.setItem(key, value); } catch { /* file:// may have opaque storage */ } }

  function show(id, value) { $(id).textContent = value == null ? '—' : String(value); }
  function meters(value) { return value == null ? '—' : `${Number(value).toFixed(2)} m`; }
  function dateText(value) {
    const number = Number(value);
    if (!Number.isFinite(number) || number <= 0) return '—';
    const date = new Date(number > 1e12 ? number : number * 1000);
    return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('it-IT');
  }
  function roverBase() {
    const url = new URL($('rover-url').value.trim());
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname) throw new Error('Usa un indirizzo http:// o https:// del Rover.');
    return url.origin;
  }
  function updateRoverPageLink() {
    try { $('rover-page').href = `${roverBase()}/riproduzione.html`; }
    catch { $('rover-page').removeAttribute('href'); }
  }
  function send(message) {
    if (ws?.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(message));
    return true;
  }
  function refreshReady() {
    $('load').disabled = !(selectedTrace && fence && ws?.readyState === WebSocket.OPEN);
    $('download').disabled = !selectedTrace;
    $('save-pc-fence').disabled = !fence;
    $('save-rover-fence').disabled = !(fence && ws?.readyState === WebSocket.OPEN);
  }

  function connect() {
    const id = ++connectionId;
    if (ws) { ws.onclose = null; ws.close(); ws = null; }
    let base;
    try { base = roverBase(); }
    catch (error) { show('connection', error.message); refreshReady(); return; }
    if (base !== activeRoverBase) {
      activeRoverBase = base;
      roverHistory = [];
      if (selectedSource === 'Rover') clearTrace();
      renderHistoryList();
    }
    store('terminator_rover_url', base);
    updateRoverPageLink();
    const url = new URL(base);
    const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    show('connection', 'Connessione in corso…');
    try { ws = new WebSocket(`${protocol}//${url.host}/ws`); }
    catch (error) { show('connection', error.message); refreshReady(); return; }
    ws.onopen = () => {
      if (id !== connectionId) return;
      show('connection', 'Rover connesso');
      show('history-status', 'Lettura dello storico Rover…');
      send({type: 'replay_history'});
      send({type: 'geofence_list'});
      refreshReady();
    };
    ws.onerror = () => { if (id === connectionId) show('connection', 'Rover non raggiungibile'); };
    ws.onclose = () => {
      if (id !== connectionId) return;
      hasLoaded = false;
      show('connection', 'Rover disconnesso');
      refreshReady();
      setTimeout(() => { if (id === connectionId) connect(); }, 2500);
    };
    ws.onmessage = event => {
      let data;
      try { data = JSON.parse(event.data); } catch { return; }
      if (data.type === 'replay_history_result') {
        roverHistory = Array.isArray(data.history) ? data.history : [];
        show('history-status', `${roverHistory.length} registrazioni sul Rover · ${pcFiles.size} file dal PC.`);
        if (selectedSource === 'Rover') selectedTrace = null;
        renderHistoryList();
      } else if (data.type === 'replay_trace_result') {
        if (data.request_id !== selectionRequest || $('history').value !== `rover:${data.filename}`) return;
        if (data.ok) setSelectedTrace(data.mission, 'Rover', data.filename);
        else show('trace-title', `Lettura non riuscita: ${data.detail || 'errore sconosciuto'}`);
      } else if (data.type === 'geofence_list_result') {
        const previous = $('saved-fences').value;
        const options = (Array.isArray(data.geofences) ? data.geofences : [])
          .map(item => new Option(`${item.filename} · ${dateText(item.modified_at)}`, item.filename));
        $('saved-fences').replaceChildren(...options);
        if (!options.length) $('saved-fences').append(new Option('Nessun geofence salvato sul Rover', ''));
        else if (options.some(option => option.value === previous)) $('saved-fences').value = previous;
      } else if (data.type === 'geofence_read_result') {
        if (data.ok) {
          importedFence = data.geofence;
          fenceOverride = true;
          $('fence-name').value = data.geofence.properties?.name || 'Geofence_1';
          readSelectedFence();
          show('fence-save-status', `Aperto dal Rover: ${data.filename}`);
        } else show('fence-save-status', `Apertura non riuscita: ${data.detail}`);
      } else if (data.type === 'geofence_save_result') {
        show('fence-save-status', data.ok
          ? `Salvato sul Rover: ${data.folder}/${data.filename}` : `Salvataggio sul Rover non riuscito: ${data.detail}`);
        if (data.ok) send({type: 'geofence_list'});
      } else if (data.type === 'replay_load_result') {
        show('message', data.detail);
        $('message').className = data.ok ? 'ok' : 'error';
        hasLoaded = Boolean(data.ok && data.mission);
        show('active-mission', hasLoaded ? `${data.mission} · ${data.points_count} punti · ${data.length_m} m` : '—');
      } else if (data.type === 'telemetry' && data.replay && hasLoaded) {
        const p = data.replay.preview;
        if (!p) return;
        show('reason', p.reason);
        show('heading', p.heading_source);
        show('cross', meters(p.cross_track_error_m));
        show('clearance', meters(p.boundary_clearance_m));
        show('goal', meters(p.goal_distance_m));
        show('curvature', p.curvature_1pm == null ? '—' : `${p.curvature_1pm} 1/m`);
        show('target', p.target ? `${p.target.x_east_m} m est, ${p.target.y_north_m} m nord` : '—');
      }
    };
  }

  function renderHistoryList() {
    const previous = $('history').value;
    const roverGroup = document.createElement('optgroup');
    roverGroup.label = `Rover (${roverHistory.length})`;
    for (const item of roverHistory) {
      const label = item.error ? `${item.filename} · ${item.error}`
        : `${dateText(item.timestamp)} · ${item.mission} · ${item.points_count} punti · FIX ${item.fix_count} · motori ${item.motor_samples}`;
      const option = new Option(label, `rover:${item.filename}`);
      option.disabled = Boolean(item.error);
      roverGroup.append(option);
    }
    const pcGroup = document.createElement('optgroup');
    pcGroup.label = `PC (${pcFiles.size})`;
    for (const [key, file] of pcFiles) pcGroup.append(new Option(`${file.webkitRelativePath || file.name} · ${dateText(file.lastModified)}`, key));
    $('history').replaceChildren(roverGroup, pcGroup);
    const options = Array.from($('history').options).filter(option => !option.disabled && option.value);
    const next = options.some(option => option.value === previous) ? previous : options[0]?.value || '';
    $('history').value = next;
    if (!next) {
      clearTrace();
      show('trace-title', 'Nessuna registrazione disponibile.');
    } else if (next !== previous || !selectedTrace) {
      selectHistory();
    }
  }

  function clearTrace() {
    selectedTrace = null;
    selectedSource = null;
    $('trace-line').setAttribute('points', '');
    if (geoMap && geoRoute) { geoMap.removeLayer(geoRoute); geoRoute = null; }
    for (const id of ['trace-start', 'trace-end']) { $(id).setAttribute('cx', '-20'); $(id).setAttribute('cy', '-20'); }
    $('points-body').replaceChildren();
    $('raw-details').open = false;
    show('raw-json', '');
    for (const id of ['trace-source', 'trace-date', 'trace-count', 'trace-quality', 'trace-length', 'trace-motors']) show(id, '—');
    show('point-note', '');
    refreshReady();
  }
  async function selectHistory() {
    const key = $('history').value;
    const request = ++selectionRequest;
    if (hasLoaded) send({type: 'replay_unload'});
    hasLoaded = false;
    show('active-mission', '—');
    clearTrace();
    if (!key) return;
    show('trace-title', 'Lettura della traccia…');
    if (key.startsWith('rover:')) {
      if (!send({type: 'replay_read', filename: key.slice(6), request_id: request})) {
        show('trace-title', 'Rover non connesso. Imposta l’indirizzo e premi Connetti.');
      }
      return;
    }
    const file = pcFiles.get(key);
    if (!file) return;
    if (file.size > 5_000_000) { show('trace-title', 'File troppo grande (massimo 5 MB).'); return; }
    try {
      const mission = JSON.parse(await file.text());
      if (request === selectionRequest) setSelectedTrace(mission, 'PC', file.name);
    } catch (error) {
      if (request === selectionRequest) show('trace-title', `JSON non leggibile: ${error.message}`);
    }
  }

  function setSelectedTrace(mission, source, filename) {
    if (!mission || !Array.isArray(mission.points)) {
      show('trace-title', 'Il JSON non contiene una traccia con points.');
      return;
    }
    selectedTrace = {mission, filename};
    selectedSource = source;
    const points = mission.points;
    const valid = points.filter(p => p?.lat != null && p?.lon != null
      && Number.isFinite(Number(p.lat)) && Number.isFinite(Number(p.lon))
      && Math.abs(Number(p.lat)) <= 90 && Math.abs(Number(p.lon)) <= 180);
    const quality = {};
    for (const point of points) {
      const status = String(point?.rtk_status || 'NON INDICATO');
      quality[status] = (quality[status] || 0) + 1;
    }
    const origin = valid[0];
    let length = 0;
    const xy = valid.map(point => {
      const lat = Number(point.lat), lon = Number(point.lon);
      return [Math.PI / 180 * (lon - origin.lon) * R * Math.cos(Math.PI / 180 * (lat + Number(origin.lat)) / 2),
              Math.PI / 180 * (lat - Number(origin.lat)) * R];
    });
    for (let i = 1; i < xy.length; i++) length += Math.hypot(xy[i][0] - xy[i - 1][0], xy[i][1] - xy[i - 1][1]);
    drawTrace(xy);
    drawGeoMap(valid);
    show('trace-title', `${filename} · ${mission.mission || 'senza nome'}`);
    show('trace-source', source);
    show('trace-date', dateText(mission.timestamp || points[0]?.fix_timestamp || points[0]?.timestamp));
    show('trace-count', `${points.length} (${valid.length} con coordinate)`);
    show('trace-quality', Object.entries(quality).map(([status, count]) => `${status}: ${count}`).join(' · ') || '—');
    show('trace-length', meters(length));
    show('trace-motors', points.filter(p => p && ('motor_left_pct' in p || 'motor_left_output_pct' in p)).length);
    show('point-note', points.length > 500 ? `Mostrati i primi 500 di ${points.length} punti; il JSON completo è disponibile qui sotto.` : `${points.length} punti disponibili.`);
    renderPointTable(points.slice(0, 500));
    refreshReady();
  }

  function drawTrace(xy) {
    if (!xy.length) return;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const [x, y] of xy) {
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
    const scale = Math.min(590 / Math.max(maxX - minX, 0.1), 310 / Math.max(maxY - minY, 0.1));
    const midX = (minX + maxX) / 2, midY = (minY + maxY) / 2;
    const step = Math.max(1, Math.ceil(xy.length / 5000));
    const display = xy.filter((_, index) => index % step === 0 || index === xy.length - 1);
    const plotted = display.map(([x, y]) => [320 + (x - midX) * scale, 180 - (y - midY) * scale]);
    $('trace-line').setAttribute('points', plotted.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' '));
    [['trace-start', plotted[0]], ['trace-end', plotted[plotted.length - 1]]].forEach(([id, [x, y]]) => {
      $(id).setAttribute('cx', x.toFixed(1)); $(id).setAttribute('cy', y.toFixed(1));
    });
  }
  function ensureMap() {
    if (geoMap) return true;
    if (!window.L) {
      show('map-status', 'Mappa non disponibile: controlla Internet. Puoi comunque importare un GeoJSON.');
      return false;
    }
    geoMap = L.map('geo-map').setView([45.9055, 12.438], 18);
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxNativeZoom: 18, maxZoom: 22, attribution: 'Tiles © Esri',
    }).addTo(geoMap);
    fenceLayers = L.featureGroup().addTo(geoMap);
    if (geoMap.pm) {
      geoMap.pm.setGlobalOptions({layerGroup: fenceLayers, snappable: true, snapDistance: 20});
      geoMap.on('pm:create', event => {
        const layer = event.layer;
        fenceLayers.clearLayers();
        fenceLayers.addLayer(layer);
        bindFenceEdits(layer);
        setFenceFromLayer(layer, 'Poligono disegnato sulla mappa.');
      });
      geoMap.on('pm:globaleditmodetoggled', event => {
        $('fence-edit').textContent = event.enabled ? 'Termina modifica' : 'Modifica vertici';
        if (!event.enabled) {
          const layer = fenceLayers.getLayers()[0];
          if (layer) setFenceFromLayer(layer, 'Geofence modificato sulla mappa.');
        }
      });
    } else show('map-status', 'Disegno sulla mappa non disponibile; puoi importare un GeoJSON.');
    return true;
  }
  function normalizeFence(value) {
    let feature = value;
    if (feature?.type === 'FeatureCollection') {
      const polygons = feature.features?.filter(item => item?.geometry?.type === 'Polygon') || [];
      if (polygons.length !== 1 || feature.features.length !== 1) throw new Error('Serve un solo poligono GeoJSON.');
      feature = polygons[0];
    }
    const geometry = feature?.type === 'Feature' ? feature.geometry : feature;
    if (geometry?.type !== 'Polygon' || !Array.isArray(geometry.coordinates)
        || geometry.coordinates.length !== 1 || !Array.isArray(geometry.coordinates[0])) {
      throw new Error('Serve un GeoJSON Polygon senza fori.');
    }
    const ring = geometry.coordinates[0].map(point => [Number(point[0]), Number(point[1])]);
    if (ring.length < 4 || ring.some(([lon, lat]) => !Number.isFinite(lon)
        || !Number.isFinite(lat) || Math.abs(lon) > 180 || Math.abs(lat) > 90)) {
      throw new Error('Vertici del poligono non validi.');
    }
    if (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1]) ring.push([...ring[0]]);
    if (ring.length > 1001) throw new Error('Il geofence ha troppi vertici.');
    if (new Set(ring.slice(0, -1).map(point => point.join(','))).size < 3) throw new Error('Servono tre vertici distinti.');
    const [originLon, originLat] = ring[0];
    const xy = ring.map(([lon, lat]) => [Math.PI / 180 * (lon - originLon) * R * Math.cos(Math.PI / 180 * (lat + originLat) / 2),
      Math.PI / 180 * (lat - originLat) * R]);
    const area = Math.abs(xy.slice(1).reduce((sum, point, i) => sum + xy[i][0] * point[1] - point[0] * xy[i][1], 0)) / 2;
    if (area < 1) throw new Error('Geofence troppo piccolo o degenerato.');
    const cross = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
    const onSegment = (a, b, c) => Math.abs(cross(a, b, c)) < 1e-9
      && Math.min(a[0], b[0]) <= c[0] && c[0] <= Math.max(a[0], b[0])
      && Math.min(a[1], b[1]) <= c[1] && c[1] <= Math.max(a[1], b[1]);
    const intersects = (a, b, c, d) => (cross(a, b, c) * cross(a, b, d) < 0 && cross(c, d, a) * cross(c, d, b) < 0)
      || onSegment(a, b, c) || onSegment(a, b, d) || onSegment(c, d, a) || onSegment(c, d, b);
    for (let i = 0; i < xy.length - 1; i++) {
      for (let j = i + 2; j < xy.length - 1; j++) {
        if (i === 0 && j === xy.length - 2) continue;
        if (intersects(xy[i], xy[i + 1], xy[j], xy[j + 1])) throw new Error('Geofence auto-intersecante.');
      }
    }
    return {type: 'Feature', properties: {...(feature.properties || {})},
      geometry: {type: 'Polygon', coordinates: [ring]}};
  }
  function bindFenceEdits(layer) {
    layer.on('pm:edit', () => setFenceFromLayer(layer, 'Geofence modificato sulla mappa.'));
  }
  function setFenceFromLayer(layer, status) {
    try {
      layer.setStyle({color: '#f59e0b', weight: 4, fillOpacity: 0.15});
      importedFence = normalizeFence(layer.toGeoJSON());
      fenceOverride = true;
      localFenceSource = status;
      applyFence(importedFence, status, false);
    } catch (error) { show('fence-status', error.message); }
  }
  function showFenceOnMap(value) {
    if (!ensureMap()) return;
    fenceLayers.clearLayers();
    if (!value) return;
    L.geoJSON(value, {style: {color: '#f59e0b', weight: 4, fillOpacity: 0.15}}).eachLayer(layer => {
      fenceLayers.addLayer(layer);
      bindFenceEdits(layer);
    });
    const bounds = fenceLayers.getBounds();
    if (bounds.isValid()) geoMap.fitBounds(bounds.pad(0.2), {maxZoom: 19});
  }
  function drawGeoMap(points) {
    if (!ensureMap() || !points.length) return;
    if (geoRoute) geoMap.removeLayer(geoRoute);
    const latlngs = points.map(point => [Number(point.lat), Number(point.lon)]);
    geoRoute = L.featureGroup([
      L.polyline(latlngs, {color: '#38bdf8', weight: 4, pmIgnore: true}),
      L.circleMarker(latlngs[0], {radius: 6, color: '#22c55e', fillOpacity: 1, pmIgnore: true}),
      L.circleMarker(latlngs[latlngs.length - 1], {radius: 6, color: '#f43f5e', fillOpacity: 1, pmIgnore: true}),
    ]).addTo(geoMap);
    setTimeout(() => { geoMap.invalidateSize(); geoMap.fitBounds(geoRoute.getBounds().pad(0.25), {maxZoom: 19}); }, 0);
    show('map-status', 'Traccia sulla mappa: verde partenza, rosso arrivo. Poligono arancione: geofence.');
  }
  function renderPointTable(points) {
    const fragment = document.createDocumentFragment();
    points.forEach((point, index) => {
      const row = document.createElement('tr');
      const values = [index + 1, dateText(point?.fix_timestamp || point?.timestamp),
        point?.lat ?? '—', point?.lon ?? '—', point?.rtk_status || '—',
        point?.motor_left_pct ?? point?.motor_left_output_pct ?? '—',
        point?.motor_right_pct ?? point?.motor_right_output_pct ?? '—'];
      for (const value of values) { const cell = document.createElement('td'); cell.textContent = String(value); row.append(cell); }
      fragment.append(row);
    });
    $('points-body').replaceChildren(fragment);
  }

  function applyFence(nextFence, status, updateMap = true) {
    const nextSignature = nextFence ? JSON.stringify(nextFence) : null;
    const changed = fenceSignature !== nextSignature;
    if (changed && fenceSignature !== null) {
      if (hasLoaded) send({type: 'replay_unload'});
      hasLoaded = false;
      show('active-mission', '—');
      show('reason', 'Geofence cambiato: valida nuovamente la traccia.');
    }
    fence = nextFence;
    fenceSignature = nextSignature;
    show('fence-status', status);
    if (updateMap && changed) showFenceOnMap(nextFence);
    refreshReady();
  }
  function readSelectedFence() {
    if (fenceOverride) { applyFence(importedFence, localFenceSource || 'Geofence scelto in questa pagina.'); return; }
    try {
      const saved = stored('terminator_zones_geojson');
      const features = saved ? JSON.parse(saved)?.features : null;
      const polygons = Array.isArray(features) ? features.filter(item => item?.geometry?.type === 'Polygon') : [];
      const selectedId = stored('terminator_selected_geofence_id');
      const selected = (selectedId ? polygons.find(item => item.properties?.replay_id === selectedId) : null)
        || (polygons.length === 1 ? polygons[0] : null);
      if (selected) applyFence(normalizeFence(selected), `Area ${polygons.indexOf(selected) + 1} selezionata in Mappa Live.`);
      else if (polygons.length > 1) applyFence(null, 'Ci sono più aree: clicca quella desiderata in Mappa Live.');
      else applyFence(null, 'Nessun geofence in questo browser: selezionalo in Mappa Live o importa un GeoJSON.');
    } catch (error) { applyFence(null, `Geofence salvato non leggibile: ${error.message}`); }
  }

  async function addPcFiles(fileList) {
    let added = 0;
    for (const file of fileList) {
      if (!file.name.toLowerCase().endsWith('.json')) continue;
      const exists = [...pcFiles.values()].some(old => old.name === file.name && old.size === file.size && old.lastModified === file.lastModified && old.webkitRelativePath === file.webkitRelativePath);
      if (!exists) { pcFiles.set(`pc:${++pcSequence}`, file); added++; }
    }
    show('history-status', `${roverHistory.length} registrazioni sul Rover · ${pcFiles.size} file dal PC (${added} aggiunti).`);
    renderHistoryList();
  }

  $('rover-url').value = (location.protocol === 'http:' || location.protocol === 'https:')
    ? location.origin : stored('terminator_rover_url') || 'http://terminator.local:8080';
  updateRoverPageLink();
  $('rover-url').addEventListener('change', updateRoverPageLink);
  $('connect').onclick = connect;
  $('refresh').onclick = () => {
    if (!send({type: 'replay_history'})) connect();
    else show('history-status', 'Aggiornamento dello storico Rover…');
  };
  $('history').onchange = selectHistory;
  $('pc-files').onchange = event => addPcFiles(event.target.files);
  $('pc-folder').onchange = event => addPcFiles(event.target.files);
  $('fence-file').onchange = async event => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      if (file.size > 1_000_000) throw new Error('File troppo grande (massimo 1 MB)');
      importedFence = normalizeFence(JSON.parse(await file.text()));
      fenceOverride = true;
      localFenceSource = `Geofence importato: ${file.name}`;
      $('fence-name').value = importedFence.properties?.name || file.name.replace(/\.(geojson|json)$/i, '');
      readSelectedFence();
    } catch (error) { show('fence-status', `GeoJSON non leggibile: ${error.message}`); }
  };
  $('use-map-fence').onclick = () => {
    importedFence = null;
    fenceOverride = false;
    $('fence-file').value = '';
    readSelectedFence();
  };
  $('fence-draw').onclick = () => {
    if (!ensureMap() || !geoMap.pm) return show('fence-status', 'Disegno non disponibile: importa un GeoJSON.');
    geoMap.pm.enableDraw('Polygon', {pathOptions: {color: '#f59e0b', weight: 4, fillOpacity: 0.15}});
    show('fence-status', 'Clicca sulla mappa per aggiungere vertici; clicca il primo per chiudere.');
  };
  $('fence-edit').onclick = () => {
    if (!fenceLayers?.getLayers().length || !geoMap?.pm) return show('fence-status', 'Disegna o importa prima un geofence.');
    geoMap.pm.toggleGlobalEditMode();
  };
  $('fence-clear').onclick = () => {
    fenceLayers?.clearLayers();
    importedFence = null;
    fenceOverride = true;
    localFenceSource = 'Nessun geofence: disegna un poligono o importane uno.';
    applyFence(null, localFenceSource, false);
  };
  $('center-trace').onclick = () => {
    if (geoMap && geoRoute) geoMap.fitBounds(geoRoute.getBounds().pad(0.25), {maxZoom: 19});
    else show('map-status', 'Seleziona prima una traccia con coordinate GPS.');
  };
  $('refresh-fences').onclick = () => {
    if (!send({type: 'geofence_list'})) connect();
  };
  $('open-rover-fence').onclick = () => {
    const filename = $('saved-fences').value;
    if (!filename) return show('fence-save-status', 'Seleziona un file geofence dal Rover.');
    if (!send({type: 'geofence_read', filename})) show('fence-save-status', 'Rover non connesso.');
  };
  $('save-rover-fence').onclick = () => {
    if (!fence) return;
    if (!send({type: 'geofence_save', name: $('fence-name').value.trim() || 'Geofence', geofence: fence})) {
      show('fence-save-status', 'Rover non connesso.');
    } else show('fence-save-status', 'Salvataggio sul Rover in corso…');
  };
  $('save-pc-fence').onclick = async () => {
    if (!fence) return;
    const name = $('fence-name').value.trim() || 'Geofence';
    const feature = normalizeFence(fence);
    feature.properties.name = name;
    const slug = name.normalize('NFKD').replace(/[^A-Za-z0-9_-]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 48) || 'Geofence';
    const filename = `${slug}_${new Date().toISOString().replace(/[-:]/g, '').replace(/\..*/, '')}_${Math.random().toString(36).slice(2, 8)}.geojson`;
    const content = JSON.stringify(feature, null, 2) + '\n';
    if (!window.showDirectoryPicker) {
      const url = URL.createObjectURL(new Blob([content], {type: 'application/geo+json'}));
      const link = document.createElement('a');
      link.href = url; link.download = filename; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      return show('fence-save-status', `Scaricato ${filename}. Spostalo nella cartella Geofencing del progetto.`);
    }
    try {
      const root = await window.showDirectoryPicker({id: 'terminator-geofencing', mode: 'readwrite'});
      const folder = root.name === 'Geofencing' ? root
        : root.name === 'boyz-terminator-main' ? await root.getDirectoryHandle('Geofencing', {create: true}) : null;
      if (!folder) throw new Error('Seleziona boyz-terminator-main oppure la sua cartella Geofencing.');
      const handle = await folder.getFileHandle(filename, {create: true});
      const writable = await handle.createWritable();
      await writable.write(content);
      await writable.close();
      show('fence-save-status', `Salvato sul PC in Geofencing/${filename}`);
    } catch (error) {
      if (error.name !== 'AbortError') show('fence-save-status', `Salvataggio sul PC non riuscito: ${error.message}`);
    }
  };
  $('load').onclick = () => {
    readSelectedFence();
    if (!selectedTrace || !fence || ws?.readyState !== WebSocket.OPEN) return;
    const message = {type: 'replay_load', filename: selectedTrace.filename, geofence: fence};
    if (selectedSource === 'PC') message.mission = selectedTrace.mission;
    send(message);
    show('message', 'Validazione in corso…');
  };
  $('unload').onclick = () => send({type: 'replay_unload'});
  $('download').onclick = () => {
    if (!selectedTrace) return;
    const blob = new Blob([JSON.stringify(selectedTrace.mission, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = selectedTrace.filename.replace(/[\\/:*?"<>|]/g, '_');
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  $('raw-details').ontoggle = () => show('raw-json', $('raw-details').open && selectedTrace ? JSON.stringify(selectedTrace.mission, null, 2) : '');
  window.addEventListener('focus', readSelectedFence);
  window.addEventListener('storage', event => {
    if (['terminator_zones_geojson', 'terminator_selected_geofence_id'].includes(event.key)) readSelectedFence();
  });
  ensureMap();
  readSelectedFence();
  connect();
})();
