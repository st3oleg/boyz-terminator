/* Browser-only vineyard survey: image analysis runs on the live Esri map tiles. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const config = window.TERMINATOR_CONFIG || {};
  const storageKey = config.sharedMap ? 'terminator_vineyard_boundary' : 'terminator_zones_geojson';
  const surveyKey = 'terminator_vineyard_survey';
  const map = L.map('map', { maxZoom: 22, zoomControl: true }).setView([45.9055, 12.438], 18);
  const localTiles = ['127.0.0.1', 'localhost'].includes(location.hostname) && location.port === '8765';
  const tileUrl = localTiles ? '/api/tiles/{z}/{y}/{x}' :
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
  const satellite = L.tileLayer(tileUrl, {
    maxNativeZoom: 18, maxZoom: 22, crossOrigin: 'anonymous', attribution: 'Tiles © Esri'
  }).addTo(map);
  const boundary = L.featureGroup().addTo(map);
  const preview = L.featureGroup().addTo(map);
  const rowNumbers = L.layerGroup().addTo(map);
  const countControl = L.control({ position: 'topleft' });
  countControl.onAdd = () => L.DomUtil.create('div', 'row-count');
  countControl.addTo(map);
  const rowCount = countControl.getContainer();
  rowCount.hidden = true;
  const boundaryStyle = { color: '#328bff', weight: 3, fillColor: '#328bff', fillOpacity: 0.13 };
  let rows = [];
  let detection = null;
  let drawing = false;
  let editingRows = false;
  let analysisRequest = 0;

  function status(message, error = false) {
    $('status').textContent = message;
    $('status').classList.toggle('error', error);
  }
  function analysisStatus(message, error = false) {
    const output = $('analysis-status');
    output.textContent = message;
    output.classList.toggle('error', error);
  }
  function cancelAnalysis() {
    analysisRequest++;
    $('detect').disabled = false;
    analysisStatus('');
  }
  function onlyPolygon() { return boundary.getLayers()[0] || null; }
  function polygonLatLngs() {
    const layer = onlyPolygon();
    return layer ? layer.getLatLngs()[0].map(p => [p.lat, p.lng]) : null;
  }
  function saveBoundary() {
    cancelAnalysis();
    localStorage.setItem(storageKey, JSON.stringify(boundary.toGeoJSON()));
    rows = []; detection = null; preview.clearLayers(); $('summary').textContent = '';
    rowNumbers.clearLayers();
    rowCount.hidden = true;
  }
  function setPolygon(points) {
    boundary.clearLayers();
    const layer = L.polygon(points, boundaryStyle).addTo(boundary);
    layer.on('pm:edit', saveBoundary);
    saveBoundary();
    map.fitBounds(layer.getBounds(), { padding: [35, 35] });
  }
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
    const feature = saved?.features?.find(f => f.geometry?.type === 'Polygon');
    if (feature) setPolygon(feature.geometry.coordinates[0].slice(0, -1).map(p => [p[1], p[0]]));
  } catch (error) { status('Geofencing salvato non leggibile: ridisegnalo o importa un GeoJSON.', true); }

  $('draw').onclick = () => {
    map.pm.disableGlobalEditMode();
    map.pm.enableDraw('Polygon', { snappable: true, pathOptions: boundaryStyle });
    drawing = true;
    status('Clicca per aggiungere vertici; chiudi il poligono sul primo punto.');
  };
  map.on('pm:create', e => {
    if (!drawing) return;
    drawing = false;
    map.pm.disableDraw();
    const pts = e.layer.getLatLngs()[0].map(p => [p.lat, p.lng]);
    map.removeLayer(e.layer);
    if (pts.length < 3) return status('Servono almeno tre vertici.', true);
    setPolygon(pts);
    status(`Geofencing salvato: ${pts.length} vertici. Ora analizza l'immagine satellitare.`);
  });
  $('edit').onclick = () => {
    if (!onlyPolygon()) return status('Disegna prima il perimetro.', true);
    if (map.pm.globalEditModeEnabled()) {
      map.pm.disableGlobalEditMode(); saveBoundary(); status('Perimetro modificato e salvato.');
    } else {
      map.pm.enableGlobalEditMode(); status('Trascina i vertici, poi premi di nuovo Modifica vertici.');
    }
  };
  $('clear').onclick = () => { map.pm.disableGlobalEditMode(); boundary.clearLayers(); saveBoundary(); status('Perimetro cancellato.'); };
  $('import').onclick = () => $('import-file').click();
  $('import-file').onchange = async event => {
    const file = event.target.files[0]; if (!file) return;
    try {
      const source = JSON.parse(await file.text());
      const geometry = source.type === 'FeatureCollection' ? source.features.find(f => f.geometry?.type === 'Polygon')?.geometry
        : source.type === 'Feature' ? source.geometry : source;
      if (geometry?.type !== 'Polygon') throw new Error('Serve un poligono GeoJSON.');
      const pts = geometry.coordinates[0].slice(0, -1).map(([lng, lat]) => [lat, lng]);
      if (pts.length < 3 || pts.some(p => !p.every(Number.isFinite))) throw new Error('Coordinate non valide.');
      setPolygon(pts); status(`Importati ${pts.length} vertici.`);
    } catch (error) { status(`Importazione fallita: ${error.message}`, true); }
    event.target.value = '';
  };

  function download(name, value) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a'); a.href = url; a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  $('export-geofence').onclick = () => {
    if (!onlyPolygon()) return status('Disegna prima il perimetro.', true);
    download('geofencing.geojson', boundary.toGeoJSON());
  };

  const haversine = (a, b) => {
    const r = Math.PI / 180, dLat = (b.lat - a.lat) * r, dLon = (b.lng - a.lng) * r;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLon / 2) ** 2;
    return 12742017.6 * Math.asin(Math.sqrt(h));
  };
  const pointInside = (p, poly) => {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const a = poly[i], b = poly[j];
      if ((a.y > p.y) !== (b.y > p.y) && p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x) inside = !inside;
    }
    return inside;
  };
  async function captureTiles(vertices) {
    const zoom = satellite.options.maxNativeZoom;
    const tileSize = satellite.getTileSize().x;
    const points = vertices.map(point => map.project(L.latLng(point), zoom));
    const left = Math.floor(Math.min(...points.map(point => point.x))) - 3;
    const top = Math.floor(Math.min(...points.map(point => point.y))) - 3;
    const right = Math.ceil(Math.max(...points.map(point => point.x))) + 3;
    const bottom = Math.ceil(Math.max(...points.map(point => point.y))) + 3;
    // Work with half-pixel bins. This interpolates the native imagery, independently of map zoom.
    const scale = 2;
    const canvas = document.createElement('canvas');
    canvas.width = (right - left) * scale;
    canvas.height = (bottom - top) * scale;
    if (Math.max(canvas.width, canvas.height) > 4096 || canvas.width * canvas.height > 4_000_000) {
      throw new Error('Il perimetro è troppo esteso per analizzarlo in una volta. Seleziona un appezzamento più piccolo.');
    }
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) throw new Error('Il browser non riesce a preparare l’immagine satellitare.');
    const tileCount = 2 ** zoom;
    const signal = AbortSignal.timeout(15000);
    const tiles = [];
    for (let y = Math.floor(top / tileSize); y < Math.ceil(bottom / tileSize); y++) {
      for (let x = Math.floor(left / tileSize); x < Math.ceil(right / tileSize); x++) {
        const tileX = (x % tileCount + tileCount) % tileCount;
        const url = L.Util.template(tileUrl, { z: zoom, x: tileX, y });
        tiles.push((async () => {
          try {
            const response = await fetch(url, { signal });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const bitmap = await createImageBitmap(await response.blob());
            try {
              ctx.drawImage(bitmap, (x * tileSize - left) * scale, (y * tileSize - top) * scale,
                tileSize * scale, tileSize * scale);
            } finally {
              bitmap.close();
            }
          } catch (error) {
            throw new Error(`Tessera satellitare non disponibile (${zoom}/${y}/${tileX}, ${error.message}). Riprova tra poco.`);
          }
        })());
      }
    }
    await Promise.all(tiles);
    const toLatLng = point => map.unproject(L.point(left + point.x / scale, top + point.y / scale), zoom);
    const center = { x: canvas.width / 2, y: canvas.height / 2 };
    const metresPerPx = haversine(toLatLng(center), toLatLng({ x: center.x + 100, y: center.y })) / 100;
    return {
      image: { width: canvas.width, height: canvas.height, data: ctx.getImageData(0, 0, canvas.width, canvas.height).data, toLatLng },
      poly: points.map(point => ({ x: (point.x - left) * scale, y: (point.y - top) * scale })),
      metresPerPx
    };
  }
  function gray(image, x, y) {
    const ix = Math.round(x), iy = Math.round(y);
    if (ix < 0 || iy < 0 || ix >= image.width || iy >= image.height) return null;
    const i = (iy * image.width + ix) * 4;
    if (!image.data[i + 3]) return null;
    return 0.299 * image.data[i] + 0.587 * image.data[i + 1] + 0.114 * image.data[i + 2];
  }
  function geometry(poly, image) {
    const bounds = { minX: Math.max(2, Math.floor(Math.min(...poly.map(p => p.x)))),
      maxX: Math.min(image.width - 3, Math.ceil(Math.max(...poly.map(p => p.x)))),
      minY: Math.max(2, Math.floor(Math.min(...poly.map(p => p.y)))),
      maxY: Math.min(image.height - 3, Math.ceil(Math.max(...poly.map(p => p.y)))) };
    if (bounds.maxX - bounds.minX < 12 || bounds.maxY - bounds.minY < 12)
      throw new Error('Il perimetro è troppo piccolo rispetto alla risoluzione delle tessere satellitari.');
    return bounds;
  }
  function dominantAngle(image, poly, bounds, metresPerPx) {
    const center = poly.reduce((s, p) => ({ x: s.x + p.x / poly.length, y: s.y + p.y / poly.length }), { x: 0, y: 0 });
    const samples = [];
    for (let y = bounds.minY; y <= bounds.maxY; y += 2) for (let x = bounds.minX; x <= bounds.maxX; x += 2) {
      if (!pointInside({ x, y }, poly)) continue;
      const value = gray(image, x, y);
      if (value !== null) samples.push([x - center.x, y - center.y, value]);
    }
    if (samples.length < 100) throw new Error('Le tessere hanno troppo pochi pixel utili dentro il perimetro.');
    const windowPx = Math.max(5, Math.min(30, Math.round(3 / metresPerPx)));
    function angleScore(angle) {
      const rad = angle * Math.PI / 180, nx = -Math.sin(rad), ny = Math.cos(rad);
      const coordinates = poly.map(p => (p.x - center.x) * nx + (p.y - center.y) * ny);
      const min = Math.floor(Math.min(...coordinates)), max = Math.ceil(Math.max(...coordinates));
      const sums = new Float64Array(max - min + 1), counts = new Uint32Array(sums.length);
      for (const [x, y, value] of samples) {
        const index = Math.round(x * nx + y * ny) - min;
        if (index >= 0 && index < sums.length) { sums[index] += value; counts[index]++; }
      }
      const values = [...sums].map((sum, i) => counts[i] >= 2 ? sum / counts[i] : null);
      let score = 0, valid = 0;
      for (let i = 0; i < values.length; i++) {
        if (values[i] === null) continue;
        let local = 0, n = 0;
        for (let j = Math.max(0, i - windowPx); j <= Math.min(values.length - 1, i + windowPx); j++)
          if (values[j] !== null) { local += values[j]; n++; }
        if (n < 3) continue;
        score += (values[i] - local / n) ** 2;
        valid++;
      }
      return valid ? score / valid : 0;
    }
    const scores = Array.from({ length: 90 }, (_, i) => angleScore(i * 2));
    const best = scores.indexOf(Math.max(...scores));
    const average = scores.reduce((a, b) => a + b, 0) / scores.length;
    let angle = best * 2;
    let score = scores[best];
    for (let delta = -1.75; delta <= 1.75; delta += 0.25) {
      if (delta === 0) continue;
      const candidate = (best * 2 + delta + 180) % 180;
      const candidateScore = angleScore(candidate);
      if (candidateScore > score) { angle = candidate; score = candidateScore; }
    }
    return { angle, confidence: average ? score / average : 0 };
  }
  function lineSegments(poly, angle, offset, center) {
    const rad = angle * Math.PI / 180, dir = { x: Math.cos(rad), y: Math.sin(rad) };
    const normal = { x: -dir.y, y: dir.x };
    const origin = { x: center.x + normal.x * offset, y: center.y + normal.y * offset };
    const crossings = [];
    for (let i = 0; i < poly.length; i++) {
      const a = poly[i], b = poly[(i + 1) % poly.length], ex = b.x - a.x, ey = b.y - a.y;
      const determinant = dir.x * ey - dir.y * ex;
      if (Math.abs(determinant) < 1e-8) continue;
      const ax = a.x - origin.x, ay = a.y - origin.y;
      const t = (ax * ey - ay * ex) / determinant;
      const u = (ax * dir.y - ay * dir.x) / determinant;
      if (u >= -1e-7 && u < 1 - 1e-7) crossings.push(t);
    }
    crossings.sort((a, b) => a - b);
    const segments = [];
    for (let i = 0; i + 1 < crossings.length; i++) {
      const t0 = crossings[i], t1 = crossings[i + 1];
      if (t1 - t0 < 2) continue;
      const mid = { x: origin.x + dir.x * (t0 + t1) / 2, y: origin.y + dir.y * (t0 + t1) / 2 };
      if (pointInside(mid, poly)) segments.push({ origin, dir, normal, t0, t1 });
    }
    return segments;
  }
  function pixelToLatLng(p) { const q = map.containerPointToLatLng(L.point(p.x, p.y)); return [q.lat, q.lng]; }
  function trimRow(segment, image, spacingPx, polarity, metresPerPx) {
    const { origin, dir, normal, t0, t1 } = segment;
    const n = Math.max(5, Math.floor(t1 - t0)), scores = [];
    for (let i = 0; i <= n; i++) {
      const t = t0 + (t1 - t0) * i / n, x = origin.x + dir.x * t, y = origin.y + dir.y * t;
      const mid = gray(image, x, y), left = gray(image, x - normal.x * spacingPx * 0.38, y - normal.y * spacingPx * 0.38);
      const right = gray(image, x + normal.x * spacingPx * 0.38, y + normal.y * spacingPx * 0.38);
      scores.push(mid === null || left === null || right === null ? 0 : polarity * ((left + right) / 2 - mid));
    }
    const width = Math.max(2, Math.round(0.7 / metresPerPx));
    const smoothed = scores.map((_, i) => {
      let sum = 0, count = 0;
      for (let j = Math.max(0, i - width); j <= Math.min(n, i + width); j++) { sum += scores[j]; count++; }
      return sum / count;
    });
    const peak = Math.max(...smoothed), threshold = Math.max(2, peak * 0.28);
    let first = smoothed.findIndex(v => v >= threshold), last = smoothed.findLastIndex(v => v >= threshold);
    const visible = first >= 0 && last - first >= n * 0.45;
    let method = 'immagine';
    if (!visible) {
      const margin = Math.min((t1 - t0) * 0.15, 2 / metresPerPx);
      first = Math.round(margin / (t1 - t0) * n);
      last = Math.round(n - margin / (t1 - t0) * n);
      method = 'margine assunto 2 m';
    }
    // A crest must stay visible along the segment, not just where it crosses other features.
    const trace = visible ? smoothed.slice(first, last + 1) : [];
    const supported = visible && [0, 1, 2].every(part => {
      const window = trace.slice(Math.floor(part * trace.length / 3), Math.floor((part + 1) * trace.length / 3));
      return window.filter(value => value >= threshold).length >= window.length * 0.6;
    });
    const a = t0 + (t1 - t0) * first / n, b = t0 + (t1 - t0) * last / n;
    return { points: [a, b].map(t => {
      const p = { x: origin.x + dir.x * t, y: origin.y + dir.y * t };
      if (!image.toLatLng) return pixelToLatLng(p);
      const coordinate = image.toLatLng(p);
      return [coordinate.lat, coordinate.lng];
    }),
      headland: Math.min(a - t0, t1 - b) * metresPerPx, method, supported };
  }
  function sampleProfile(image, poly, bounds, angle, center) {
    const rad = angle * Math.PI / 180, nx = -Math.sin(rad), ny = Math.cos(rad);
    const offsets = poly.map(p => (p.x - center.x) * nx + (p.y - center.y) * ny);
    const min = Math.floor(Math.min(...offsets)), max = Math.ceil(Math.max(...offsets));
    const sums = new Float64Array(max - min + 1), counts = new Uint32Array(sums.length);
    for (let y = bounds.minY; y <= bounds.maxY; y += 2) for (let x = bounds.minX; x <= bounds.maxX; x += 2) {
      if (!pointInside({ x, y }, poly)) continue;
      const g = gray(image, x, y); if (g === null) continue;
      const k = Math.round((x - center.x) * nx + (y - center.y) * ny) - min;
      if (k >= 0 && k < sums.length) { sums[k] += g; counts[k]++; }
    }
    const values = [...sums].map((sum, i) => counts[i] ? sum / counts[i] : null);
    for (let i = 0; i < values.length; i++) if (values[i] === null) {
      const a = values.slice(0, i).findLast(v => v !== null), b = values.slice(i + 1).find(v => v !== null);
      values[i] = a ?? b ?? 128;
    }
    return { min, values, counts };
  }
  function inferSpacing(profile, metresPerPx) {
    const { values, counts } = profile;
    const radius = Math.max(4, Math.round(2.5 / metresPerPx));
    const signal = values.map((value, index) => {
      const start = Math.max(0, index - radius);
      const end = Math.min(values.length, index + radius + 1);
      let total = 0, weight = 0;
      for (let i = start; i < end; i++) {
        total += values[i] * counts[i];
        weight += counts[i];
      }
      return value - (weight ? total / weight : value);
    });
    const low = Math.max(4, Math.ceil(1.1 / metresPerPx));
    const high = Math.min(Math.floor(values.length / 3), Math.floor(5 / metresPerPx));
    const correlations = [];
    for (let lag = low; lag <= high; lag++) {
      let dot = 0, normA = 0, normB = 0;
      for (let i = 1; i + lag < signal.length - 1; i++) {
        if (counts[i] < 2 || counts[i + lag] < 2) continue;
        dot += signal[i] * signal[i + lag];
        normA += signal[i] ** 2;
        normB += signal[i + lag] ** 2;
      }
      correlations.push(normA && normB ? dot / Math.sqrt(normA * normB) : 0);
    }
    const strongest = Math.max(...correlations);
    if (strongest < 0.22) return null;
    // Prefer the first strong repetition so a double row spacing cannot win on correlation alone.
    const first = correlations.findIndex((value, i) => value >= strongest * 0.8
      && value > (correlations[i - 1] ?? -Infinity) && value >= (correlations[i + 1] ?? -Infinity));
    const lag = first >= 0 ? first : correlations.indexOf(strongest);
    const spacing = low + lag;
    const neighborhood = Math.max(2, Math.round(spacing * 0.47));
    const eligible = Math.max(3, Math.round(Math.max(...counts) * 0.15));
    function findPeaks(polarity) {
      // Positive polarity describes dark crests in trimRow; negative describes light crests.
      const levels = signal.map(value => -polarity * value);
      const peaks = [];
      for (let i = 1; i < levels.length - 1; i++) {
        if (counts[i] < eligible || levels[i] < levels[i - 1] || levels[i] <= levels[i + 1]) continue;
        const left = levels.slice(Math.max(0, i - neighborhood), i);
        const right = levels.slice(i + 1, i + neighborhood + 1);
        const prominence = Math.min(levels[i] - Math.min(...left), levels[i] - Math.min(...right));
        if (prominence < 2.5) continue;
        const curvature = levels[i - 1] - 2 * levels[i] + levels[i + 1];
        const fraction = curvature ? 0.5 * (levels[i - 1] - levels[i + 1]) / curvature : 0;
        peaks.push({ position: i + fraction, prominence });
      }
      peaks.sort((a, b) => b.prominence - a.prominence);
      const strongest = peaks[0]?.prominence ?? 0;
      const selected = [];
      for (const peak of peaks) {
        if (peak.prominence < strongest * 0.22) continue;
        if (selected.every(existing => Math.abs(existing.position - peak.position) >= spacing * 0.58)) selected.push(peak);
      }
      selected.sort((a, b) => a.position - b.position);
      return selected;
    }
    const bright = findPeaks(-1);
    const dark = findPeaks(1);
    const strength = peaks => peaks.reduce((total, peak) => total + peak.prominence, 0);
    const polarity = strength(dark) > strength(bright) * 1.20 ? 1 : -1;
    const peaks = polarity === 1 ? dark : bright;
    if (peaks.length < 2) return null;
    const gaps = peaks.slice(1).map((peak, i) => peak.position - peaks[i].position)
      .filter(gap => gap >= spacing * 0.55 && gap <= spacing * 1.45).sort((a, b) => a - b);
    return {
      spacing: gaps.length ? gaps[Math.floor(gaps.length / 2)] : spacing,
      polarity,
      contrast: strength(peaks) / peaks.length,
      offsets: peaks.map(peak => profile.min + peak.position)
    };
  }
  function buildRows(poly, angle, offsets, image, spacingPx, polarity, metresPerPx) {
    const center = poly.reduce((s, p) => ({ x: s.x + p.x / poly.length, y: s.y + p.y / poly.length }), { x: 0, y: 0 });
    const result = [];
    for (const offset of offsets) for (const segment of lineSegments(poly, angle, offset, center)) {
      if ((segment.t1 - segment.t0) * metresPerPx < 3) continue;
      const trimmed = image ? trimRow(segment, image, spacingPx, polarity, metresPerPx)
        : trimRow(segment, { width: 0, height: 0, data: [] }, spacingPx, polarity, metresPerPx);
      let [a, b] = trimmed.points;
      if (a[0] > b[0]) [a, b] = [b, a]; // first bay is southern
      if (haversine({ lat: a[0], lng: a[1] }, { lat: b[0], lng: b[1] }) < 2) continue;
      result.push({ endpoints: [a, b], headland: trimmed.headland, method: trimmed.method, supported: trimmed.supported });
    }
    return result.sort((a, b) => a.endpoints[0][1] - b.endpoints[0][1]);
  }
  function numberRowsAcrossField() {
    if (rows.length < 2) return;
    // Use the longest row as the axis so short rows and irregular headlands do not change the order.
    const projected = rows.map(row => {
      const [start, end] = row.endpoints.map(point => map.project(L.latLng(point), 18));
      return { row, start, end, length: start.distanceTo(end) };
    });
    const reference = projected.reduce((longest, row) => row.length > longest.length ? row : longest);
    let east = reference.start.y - reference.end.y;
    let south = reference.end.x - reference.start.x;
    // Cross the rows towards the east, or towards the south for east–west rows.
    if (east < -1e-6 || (Math.abs(east) <= 1e-6 && south < 0)) {
      east = -east;
      south = -south;
    }
    const cross = ({ start, end }) => east * (start.x + end.x) + south * (start.y + end.y);
    projected.sort((a, b) => cross(a) - cross(b));
    rows = projected.map(({ row }) => row);
  }

  function rowNumberPosition(row, index) {
    const [start, end] = row.endpoints.map(point => map.project(L.latLng(point), 18));
    const fraction = index % 2 === 0 ? 0.64 : 0.36;
    return map.unproject(start.add(end.subtract(start).multiplyBy(fraction)), 18);
  }

  function showRows(reorder = true) {
    if (reorder) numberRowsAcrossField();
    preview.clearLayers();
    rowNumbers.clearLayers();
    rowCount.hidden = rows.length === 0;
    rowCount.textContent = `${detection?.confidence > 0 ? 'Filari individuati' : 'Filari in anteprima'}: ${rows.length}`;
    rows.forEach((row, i) => {
      const number = i + 1;
      const line = L.polyline(row.endpoints, { color: '#ffe06a', weight: 3 }).addTo(preview);
      line.bindTooltip(`Filare ${number}: ${haversine({ lat: row.endpoints[0][0], lng: row.endpoints[0][1] },
        { lat: row.endpoints[1][0], lng: row.endpoints[1][1] }).toFixed(1)} m`, { className: 'row-label' });
      const label = L.marker(rowNumberPosition(row, i), {
        icon: L.divIcon({ className: 'row-number', html: String(number), iconSize: [26, 26], iconAnchor: [13, 13] }),
        interactive: false, keyboard: false, pmIgnore: true
      }).addTo(rowNumbers);
      line.on('pm:edit', () => {
        const points = line.getLatLngs();
        if (points.length < 2) return;
        let a = [points[0].lat, points[0].lng], b = [points[points.length - 1].lat, points[points.length - 1].lng];
        if (a[0] > b[0]) [a, b] = [b, a];
        rows[i] = { endpoints: [a, b], headland: null, method: 'manuale' };
        label.setLatLng(rowNumberPosition(rows[i], i));
        localStorage.setItem(surveyKey, JSON.stringify(survey()));
      });
      if (editingRows) line.pm.enable();
    });
    const short = rows.filter(row => Number.isFinite(row.headland) && row.headland < 1.5).length;
    const fallback = rows.filter(row => row.method === 'margine assunto 2 m').length;
    const corrected = rows.filter(row => row.method === 'manuale').length;
    const lane = detection ? detection.spacingMetres - Number($('profile-width').value) : null;
    $('summary').innerHTML = `${rows.length} filari · ${detection?.spacingMetres.toFixed(2) ?? '?'} m interasse stimato<br>` +
      `${short ? `<strong style="color:#ff8b75">Attenzione: ${short} filari con testata stimata sotto 1,5 m.</strong><br>` : ''}` +
      `${lane !== null && lane < 0.94 ? `<strong style="color:#ff8b75">Corsia residua stimata ${lane.toFixed(2)} m: inferiore all'ingombro delle ruote del Terminator (circa 0,94 m).</strong><br>` : ''}` +
      `${fallback ? `${fallback} filari con margine assunto fino a 2 m.<br>` : ''}` +
      `${corrected ? `${corrected} filari corretti a mano.<br>` : ''}`;
    localStorage.setItem(surveyKey, JSON.stringify(survey()));
  }
  $('edit-rows').onclick = () => {
    if (!rows.length) return status('Riconosci prima i filari.', true);
    if ($('detect').disabled) cancelAnalysis();
    editingRows = !editingRows;
    preview.eachLayer(layer => editingRows ? layer.pm.enable() : layer.pm.disable());
    if (!editingRows) showRows(false);
    status(editingRows ? 'Trascina gli estremi dei filari gialli; premi di nuovo Correggi testate per terminare.' : 'Correzioni salvate.');
  };
  $('profile-width').addEventListener('change', () => { if (rows.length) showRows(false); });
  $('detect').onclick = async () => {
    const verts = polygonLatLngs();
    if (!verts) return analysisStatus('Disegna prima il perimetro.', true);
    const request = ++analysisRequest;
    $('detect').disabled = true;
    analysisStatus('Caricamento delle tessere satellitari…');
    try {
      const { image, poly, metresPerPx } = await captureTiles(verts);
      if (request !== analysisRequest) return;
      const bounds = geometry(poly, image);
      const angleResult = dominantAngle(image, poly, bounds, metresPerPx);
      if (angleResult.confidence < 1.5)
        throw new Error('La direzione dei filari non è abbastanza distinguibile nelle tessere disponibili.');
      const center = poly.reduce((s, p) => ({ x: s.x + p.x / poly.length, y: s.y + p.y / poly.length }), { x: 0, y: 0 });
      const profile = sampleProfile(image, poly, bounds, angleResult.angle, center);
      const fit = inferSpacing(profile, metresPerPx);
      if (!fit)
        throw new Error('La trama delle righe non è abbastanza regolare o visibile.');
      const candidates = buildRows(poly, angleResult.angle, fit.offsets, image, fit.spacing, fit.polarity, metresPerPx);
      const detectedRows = candidates.filter(row => row.supported);
      if (detectedRows.length < 2 || detectedRows.length / candidates.length < 0.75) {
        throw new Error('Le tracce visibili non confermano la direzione e la continuità dei filari proposti.');
      }
      const discarded = candidates.length - detectedRows.length;
      rows = detectedRows;
      detection = { angle: angleResult.angle, confidence: angleResult.confidence,
        spacingMetres: fit.spacing * metresPerPx, contrast: fit.contrast };
      $('angle').value = angleResult.angle.toFixed(1); $('count').value = rows.length;
      showRows();
      const omitted = discarded ? ` Esclusi ${discarded} segmenti con traccia debole.` : '';
      analysisStatus(`Rilevati ${rows.length} filari a ${angleResult.angle.toFixed(1)}°.${omitted} Controlla le linee gialle e le testate sulla mappa.`);
    } catch (error) {
      if (request === analysisRequest) {
        analysisStatus(`Analisi automatica non affidabile. ${error.message} Inserisci direzione e numero, poi premi «Aggiorna anteprima».`, true);
      }
    } finally {
      if (request === analysisRequest) $('detect').disabled = false;
    }
  };
  $('rebuild').onclick = () => {
    cancelAnalysis();
    const verts = polygonLatLngs(); if (!verts) return status('Disegna prima il geofencing.', true);
    try {
      const count = Number($('count').value), angle = Number($('angle').value);
      if (!Number.isInteger(count) || count < 1 || count > 250 || !Number.isFinite(angle)) throw new Error('Direzione o numero di filari non valido.');
      const poly = verts.map(p => { const v = map.latLngToContainerPoint(p); return { x: v.x, y: v.y }; });
      const rad = angle * Math.PI / 180, nx = -Math.sin(rad), ny = Math.cos(rad);
      const center = poly.reduce((s, p) => ({ x: s.x + p.x / poly.length, y: s.y + p.y / poly.length }), { x: 0, y: 0 });
      const projections = poly.map(p => (p.x - center.x) * nx + (p.y - center.y) * ny);
      const min = Math.min(...projections), max = Math.max(...projections), spacing = (max - min) / (count + 1);
      const metresPerPx = haversine(map.containerPointToLatLng([map.getSize().x / 2 - 50, map.getSize().y / 2]),
        map.containerPointToLatLng([map.getSize().x / 2 + 50, map.getSize().y / 2])) / 100;
      const offsets = Array.from({ length: count }, (_, i) => min + spacing * (i + 1));
      rows = buildRows(poly, angle, offsets, null, spacing, 1, metresPerPx);
      detection = { angle, spacingMetres: spacing * metresPerPx, confidence: 0, contrast: 0 };
      showRows(); status('Anteprima aggiornata con direzione e numero indicati. Le testate usano un margine assunto di 2 m.');
    } catch (error) { status(error.message, true); }
  };

  function survey() {
    return { schema: 'terminator-vineyard-v1', name: $('name').value.trim() || 'vigneto',
      geofence: polygonLatLngs(),
      rows: rows.map((row, index) => ({ number: index + 1, endpoints: row.endpoints, headlandEstimate: row.headland, endpointMethod: row.method })),
      detection, parameters: { vineSpacing: Number($('vine-spacing').value), plantsPerBay: Number($('plants-per-bay').value),
        firstPlants: Number($('first-plants').value), postSpacing: Number($('post-spacing').value),
        ditchDepth: Number($('ditch').value), moundHeight: Number($('mound').value),
        profileWidth: Number($('profile-width').value), treeVisual: $('tree-visual').value } };
  }
  function validatedSurvey() {
    if (!polygonLatLngs() || !rows.length) throw new Error('Disegna il perimetro e riconosci i filari prima di procedere.');
    const result = survey();
    for (const [key, value] of Object.entries(result.parameters)) if (key !== 'treeVisual' && (!Number.isFinite(value) || value < 0))
      throw new Error(`Parametro ${key} non valido.`);
    return result;
  }
  $('export-survey').onclick = () => { try { download('rilievo_vigneto.json', validatedSurvey()); status('Rilievo JSON esportato.'); } catch (e) { status(e.message, true); } };
  $('import-survey').onclick = () => $('survey-file').click();
  $('survey-file').onchange = async event => {
    const file = event.target.files[0]; if (!file) return;
    try {
      const source = JSON.parse(await file.text());
      if (source.schema !== 'terminator-vineyard-v1' || !Array.isArray(source.geofence) || !Array.isArray(source.rows))
        throw new Error('Formato rilievo non valido.');
      setPolygon(source.geofence);
      rows = source.rows.map(row => ({ endpoints: row.endpoints, headland: row.headlandEstimate, method: row.endpointMethod }));
      detection = source.detection || null;
      $('name').value = source.name || 'vigneto';
      if (detection) { $('angle').value = detection.angle; $('count').value = rows.length; }
      const fields = { vineSpacing: 'vine-spacing', plantsPerBay: 'plants-per-bay', firstPlants: 'first-plants',
        postSpacing: 'post-spacing', ditchDepth: 'ditch', moundHeight: 'mound', profileWidth: 'profile-width', treeVisual: 'tree-visual' };
      for (const [key, id] of Object.entries(fields)) if (source.parameters?.[key] !== undefined) $(id).value = source.parameters[key];
      showRows(!source.rows.every((row, index) => row.number === index + 1));
      status(`Rilievo importato: ${rows.length} filari. Controlla l'anteprima prima di generare.`);
    } catch (error) { status(`Importazione fallita: ${error.message}`, true); }
    event.target.value = '';
  };
  if (config.sharedMap) {
    $('recordings-link').hidden = false;
    $('autopilot-link').hidden = !config.roverOrigin;
    if (config.roverOrigin) $('autopilot-link').href = new URL('autopilota.html', config.roverOrigin);
    $('generate').hidden = true;
    $('webots-note').textContent = 'Per generare un mondo Webots esporta il rilievo JSON e importalo nella pagina servita dal PC.';
    $('load-shared-boundary').hidden = false;
    $('load-shared-boundary').onclick = async () => {
      const button = $('load-shared-boundary');
      button.disabled = true;
      try {
        const response = await fetch('/api/v1/map/perimeters', { signal: AbortSignal.timeout(5000) });
        if (!response.ok) throw new Error('Archivio perimetri HP non disponibile.');
        const { collection } = await response.json();
        const geometry = collection.features.find(feature => feature.geometry?.type === 'Polygon')?.geometry;
        if (!geometry) throw new Error('Nessun poligono disponibile nella Mappa Live.');
        setPolygon(geometry.coordinates[0].slice(0, -1).map(([lon, lat]) => [lat, lon]));
        status('Primo poligono della Mappa Live caricato come copia di lavoro.');
      } catch (error) {
        status(error.message, true);
      } finally {
        button.disabled = false;
      }
    };
  }

  $('generate').onclick = async () => {
    try {
      const result = validatedSurvey();
      $('generate').disabled = true; status('Generazione del mondo Webots in corso…');
      const response = await fetch('/api/vineyard/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(result) });
      const body = await response.json(); if (!response.ok) throw new Error(body.error || 'Generazione fallita.');
      const surveyWarning = result.detection?.confidence === 0
        ? '\nAttenzione: i filari derivano da direzione e numero inseriti a mano; controlla posizione e testate sul campo.' : '';
      status(`Mondo creato: ${body.world}\n${body.rows} filari, ${body.posts} pali, ${body.plants} piante. Aprilo in Webots.${surveyWarning}`);
    } catch (error) { status(`Impossibile generare: ${error.message}. Avvia il server locale sul PC oppure esporta il rilievo JSON.`, true); }
    finally { $('generate').disabled = false; }
  };
})();
