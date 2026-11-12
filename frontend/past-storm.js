'use strict';

window.R34Past = (() => {
  const stormIds = { 'isaias-2026': '09L', 'polo-2026': '17E' };
  const cases = new Map();
  let selected = 'isaias-2026';
  let archive, map, line, marker;
  let initialized = false;
  let frameIndex = 0;
  let loadVersion = 0;
  let imageVersion = 0;

  const baseUrl = slug => `data/past/${slug}/`;
  const points = () => archive.track.map(point => [point.lat, point.lon]);
  const frameTime = frame => dateText(frame.observed_at || frame.time);

  function fitTrack() {
    if (map && archive && !$('view-past').hidden) {
      map.invalidateSize();
      map.fitBounds(points(), { padding: [45, 45], maxZoom: 6, animate: false });
    }
  }

  function setTimeLabel(element, value) {
    element.textContent = dateText(value);
    element.setAttribute('datetime', value);
  }

  function updateFrame(index) {
    if (!archive) return;
    frameIndex = Math.max(0, Math.min(archive.frames.length - 1, index));
    const frame = archive.frames[frameIndex];
    const slider = $('past-time');
    slider.value = String(frameIndex);
    slider.setAttribute('aria-valuetext', frameTime(frame));
    $('past-time-label').textContent = frameTime(frame);
    $('past-prev').disabled = frameIndex === 0;
    $('past-next').disabled = frameIndex === archive.frames.length - 1;
    $('past-position').textContent = position(frame);
    marker?.setLatLng([frame.lat, frame.lon]);
    openFrame();
  }

  function showImageStatus(message) {
    $('past-image-status').textContent = message;
    $('past-image-status').hidden = false;
  }

  function openFrame() {
    if (!archive) return;
    const frame = archive.frames[frameIndex];
    const version = ++imageVersion;
    $('past-frame').hidden = false;
    $('past-result').hidden = true;
    $('past-radius').hidden = true;
    $('past-image').hidden = true;
    $('past-crosshair').hidden = true;
    $('past-infer').disabled = true;
    $('past-observation').textContent = frame.observed_at
      ? `Image · ${dateText(frame.observed_at)} · ${frame.satellite || archive.satellite}`
      : `Track · ${dateText(frame.time)}`;
    if (!frame.image) {
      showImageStatus(frame.unavailable || 'No saved infrared image for this hour.');
      return;
    }
    showImageStatus('Loading archived infrared image…');
    const image = new Image();
    image.onload = () => {
      if (version !== imageVersion) return;
      $('past-image').src = image.src;
      $('past-image').hidden = false;
      $('past-crosshair').hidden = false;
      $('past-image-status').hidden = true;
      $('past-infer').disabled = false;
    };
    image.onerror = () => {
      if (version === imageVersion) showImageStatus('The infrared image could not be loaded.');
    };
    image.src = baseUrl(archive.id) + frame.image + '?scan=' + encodeURIComponent(frame.observed_at);
  }

  function showResult() {
    const frame = archive?.frames[frameIndex];
    if (!frame || $('past-infer').disabled) return;
    $('past-mean').textContent = frame.mean_nmi.toFixed(1);
    $('past-km').textContent = `≈ ${(frame.mean_nmi * 1.852).toFixed(1)} km`;
    renderChart({ ...frame, bins_nmi: archive.bins_nmi }, $('past-chart'));
    const radius = frame.mean_nmi * 1.852;
    $('past-radius').innerHTML = `<svg viewBox="0 0 1248 1248"><g class="radius-reveal"><circle class="radius-outline" cx="624" cy="624" r="${radius}"/><circle class="radius-highlight" pathLength="1" cx="624" cy="624" r="${radius}"/></g></svg>`;
    $('past-radius').hidden = false;
    $('past-domain-warning').hidden = archive.id === 'isaias-2026';
    $('past-result').hidden = false;
  }

  async function selectCase(slug) {
    const version = ++loadVersion;
    ++imageVersion;
    selected = slug;
    archive = undefined;
    line?.remove();
    marker?.remove();
    line = marker = undefined;
    document.querySelectorAll('[data-past-case]').forEach(button => {
      const active = button.dataset.pastCase === slug;
      button.classList.toggle('selected', active);
      button.setAttribute('aria-pressed', String(active));
    });
    for (const id of ['past-time', 'past-prev', 'past-next', 'past-fit']) $(id).disabled = true;
    $('past-frame').hidden = true;
    $('past-position').textContent = '';
    $('past-time-label').textContent = '—';
    $('past-status').textContent = 'Loading archive…';
    $('past-status').hidden = false;
    try {
      if (!cases.has(slug)) {
        const response = await fetch(baseUrl(slug) + 'case.json', { cache: 'no-cache' });
        if (!response.ok) throw new Error('Archive request failed');
        const data = await response.json();
        if (data.schema_version !== 1 || data.id !== slug ||
            !Array.isArray(data.frames) || !data.frames.length ||
            !Array.isArray(data.track) || data.track.length < 2 ||
            data.bins_nmi?.length !== 59) {
          throw new Error('Invalid archive data');
        }
        cases.set(slug, data);
      }
      if (version !== loadVersion) return;
      archive = cases.get(slug);
      $('past-status').hidden = true;
      const name = document.querySelector('[data-past-case="' + slug + '"] .storm-card-name').textContent;
      $('past-name').textContent = name;
      $('past-id').textContent = stormIds[slug];
      $('past-basin').textContent = archive.basin;
      $('past-time').max = String(archive.frames.length - 1);
      $('past-time').disabled = false;
      setTimeLabel($('past-start'), archive.frames[0].time);
      setTimeLabel($('past-end'), archive.frames.at(-1).time);
      if (map) {
        line = L.polyline(points(), { color: '#89d3e1', weight: 2, opacity: .9, interactive: false }).addTo(map);
        const first = archive.frames[0];
        const icon = L.divIcon({
          className: 'storm-marker selected-marker', iconSize: [34, 34], iconAnchor: [17, 17],
          html: markerMarkup({ ...first, name, id: stormIds[slug] }),
        });
        marker = L.marker([first.lat, first.lon], { icon, title: name }).addTo(map);
        $('past-fit').disabled = false;
        fitTrack();
      }
      updateFrame(0);
    } catch {
      if (version !== loadVersion) return;
      $('past-status').textContent = 'This archive could not be loaded. Select the case to retry.';
    }
  }

  function open() {
    if (initialized) {
      map?.invalidateSize();
      return;
    }
    initialized = true;
    if (window.L) {
      map = L.map('past-map', { minZoom: 1, maxZoom: 8, zoomSnap: .25 }).setView([20, -100], 3);
      map.attributionControl.addAttribution('Natural Earth');
      fetch('data/world.geojson').then(response => response.json()).then(land => {
        L.geoJSON(land, { style: { color: '#4c6679', weight: .7, fillColor: '#263e50', fillOpacity: 1 },
          interactive: false }).addTo(map).bringToBack();
      }).catch(() => {});
    }
    document.querySelectorAll('[data-past-case]').forEach(button => {
      button.addEventListener('click', () => {
        if (button.dataset.pastCase !== selected || !archive) selectCase(button.dataset.pastCase);
      });
    });
    $('past-time').addEventListener('input', event => updateFrame(Number(event.target.value)));
    $('past-prev').addEventListener('click', () => updateFrame(frameIndex - 1));
    $('past-next').addEventListener('click', () => updateFrame(frameIndex + 1));
    $('past-fit').addEventListener('click', fitTrack);
    $('past-infer').addEventListener('click', showResult);
    selectCase(selected);
  }

  return { open };
})();
