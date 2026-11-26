'use strict';
const $ = id => document.getElementById(id);
const chart = $('chart'), palette = $('palette'), service = $('service');
const layersPanel = $('layersPanel'), layerToggle = $('layerToggle'), statusLine = $('status');
const base = new URL('../../', document.baseURI);
const encNamespace = 'urn:geoserver:enc:viewer:1';
const view = new ol.View({center: [0, 0], zoom: 2, minZoom: 1, maxZoom: 22});
const map = new ol.Map({target: 'map', view, controls: ol.control.defaults().extend([
  new ol.control.ScaleLine({units: 'nautical'})
])});
let entries = [], tileCapabilities, baseLayer;
const overlays = new Map();
const charts = new Map();

function endpoint(path, params) {
  const url = new URL(path, base);
  url.search = new URLSearchParams(params);
  return url.href;
}
function label(item) {
  return item.title === item.name ? item.name : item.title + ' (' + item.name + ')';
}
function child(node, name) {
  return Array.from(node?.children || []).find(el => el.localName === name);
}
function content(node, name) {
  return child(node, name)?.textContent.trim();
}
function readEntry(layer) {
  const kind = layer.getAttributeNS(encNamespace, 'kind');
  const name = content(layer, 'Name');
  if (!name || !kind) return;
  let extent, credit;
  for (let node = layer; node?.localName === 'Layer'; node = node.parentElement) {
    const bounds = child(node, 'EX_GeographicBoundingBox');
    if (!extent && bounds) {
      const coords = ['westBoundLongitude','southBoundLatitude','eastBoundLongitude','northBoundLatitude']
        .map(key => Number.parseFloat(content(bounds, key)));
      if (coords.every(Number.isFinite)) extent = coords;
    }
    credit ||= content(child(node, 'Attribution'), 'Title');
  }
  return {name, kind, extent, credit, title: content(layer, 'Title') || name,
    workspace: layer.getAttributeNS(encNamespace, 'workspace') || '', store: layer.getAttributeNS(encNamespace, 'store') || ''};
}
function zoomTo(item) {
  if (!item?.extent) return;
  const [west, south, east, north] = item.extent;
  const extent = ol.proj.transformExtent([west, Math.max(south,-85.05), east < west ? east+360 : east,
    Math.min(north,85.05)], 'EPSG:4326', view.getProjection());
  view.fit(extent, map.getSize(), {padding: [24,24,24,24], maxZoom: 17});
}
function tiled(item) {
  if (service.value !== 'auto' || !tileCapabilities) return;
  const record = tileCapabilities.Contents.Layer.find(layer => layer.Identifier === item.name);
  if (!record?.Format.includes('image/png') || !record.Style?.some(s => s.isDefault)) return;
  const matrix = record.TileMatrixSetLink.find(link => {
    const set = tileCapabilities.Contents.TileMatrixSet.find(s => s.Identifier === link.TileMatrixSet);
    // Older OpenLayers accepts the EPSG alias but not every OGC URN spelling of it.
    const crs = set?.SupportedCRS.replace(/^urn:ogc:def:crs:EPSG:[^:]*:(\d+)$/i, 'EPSG:$1');
    const projection = crs && ol.proj.get(crs);
    return projection && ol.proj.equivalent(projection, view.getProjection());
  });
  if (!matrix) return;
  const options = ol.source.WMTS.optionsFromCapabilities(tileCapabilities, {
    layer: item.name, matrixSet: matrix.TileMatrixSet, format: 'image/png', requestEncoding: 'KVP'
  });
  if (options) return new ol.source.WMTS({...options, urls: [new URL('gwc/service/wmts', base).href]});
}
function mapLayer(item, order) {
  const tileSource = tiled(item);
  const layer = tileSource ? new ol.layer.Tile({source: tileSource}) : new ol.layer.Image({
    source: new ol.source.ImageWMS({url: new URL('wms', base).href, ratio: 1, serverType: 'geoserver',
      params: {LAYERS: item.name, VERSION: '1.1.1', FORMAT: 'image/png', TRANSPARENT: true}})
  });
  layer.setZIndex(order);
  layer.getSource().on(tileSource ? 'tileloaderror' : 'imageloaderror', () => {
    if (map.getLayers().getArray().includes(layer)) statusLine.textContent = 'Could not render ' + item.name + '.';
  });
  map.addLayer(layer);
  return layer;
}
function selectedChart() {
  const group = charts.get(chart.value);
  return group?.find(item => item.name === palette.value) || group?.[0];
}
function updateCredit() {
  const credits = [selectedChart(), ...overlays.keys()].map(item => item?.credit).filter(Boolean);
  $('credit').textContent = [...new Set(credits)].join(' · ');
}
function changeBase(fit) {
  if (baseLayer) map.removeLayer(baseLayer);
  const item = selectedChart();
  baseLayer = item && mapLayer(item, 0);
  if (fit) zoomTo(item);
  updateCredit();
}
function toggleLayer(item, enabled) {
  if (enabled) {
    const first = !baseLayer && !overlays.size;
    overlays.set(item, mapLayer(item, 1));
    if (first) zoomTo(item);
  } else {
    map.removeLayer(overlays.get(item));
    overlays.delete(item);
  }
  updateCredit();
}
function showLayers() {
  const container = $('layers'), filter = $('filter').value.trim().toLocaleLowerCase();
  container.replaceChildren();
  let previous;
  for (const item of entries.filter(item => item.kind === 'layer')) {
    const group = item.workspace + ' / ' + item.store;
    if (!(group + ' ' + label(item)).toLocaleLowerCase().includes(filter)) continue;
    if (previous !== group) {
      const heading = document.createElement('h3');
      heading.textContent = previous = group;
      container.append(heading);
    }
    const row = document.createElement('label'), box = document.createElement('input');
    const title = document.createElement('span'), name = document.createElement('small');
    box.type = 'checkbox';
    box.checked = overlays.has(item);
    box.value = item.name;
    box.onchange = () => toggleLayer(item, box.checked);
    title.textContent = item.title;
    name.textContent = item.name;
    title.append(name);
    row.append(box, title);
    container.append(row);
  }
  if (!container.childElementCount) container.textContent = 'No matching ENC layers.';
}
function configureChart(fit) {
  const group = charts.get(chart.value) || [];
  palette.replaceChildren(...group.map(item => new Option(item.variant || item.title, item.name)));
  $('paletteLabel').hidden = group.length < 2;
  changeBase(fit);
}
function configure() {
  charts.clear();
  for (const item of entries.filter(item => item.kind === 'group')) {
    // The publisher emits chart_day/dusk/night. Only group variants actually advertised together.
    const variant = /^(.*:|^)chart_(day|dusk|night)$/.exec(item.name);
    item.variant = variant?.[2];
    const key = variant ? variant[1] + 'chart_day/dusk/night' : item.name;
    if (!charts.has(key)) charts.set(key, []);
    charts.get(key).push(item);
  }
  chart.replaceChildren(new Option('No base chart', ''));
  let day;
  for (const [key, group] of charts) {
    const order = ['day','dusk','night'];
    group.sort((a,b) => order.indexOf(a.variant) - order.indexOf(b.variant));
    chart.add(new Option(label(group[0]),key));
    if (group[0].variant === 'day') day ||= key;
  }
  chart.disabled = !charts.size;
  chart.value = day || charts.keys().next().value || '';
  configureChart(true);
  if (!baseLayer && entries.length) toggleLayer(entries[0], true);
  showLayers();
  statusLine.textContent = entries.length ? '' : 'No published ENC layers. Add an S-57 store in GeoServer and publish a feature type.';
}
async function loadCatalogue() {
  $('retry').hidden = true;
  statusLine.textContent = 'Discovering published charts…';
  try {
    const params = {service: 'WMS', version: '1.3.0', request: 'GetCapabilities', encDiscovery: true};
    const response = await fetch(endpoint('wms', params), {cache: 'no-store'});
    if (!response.ok) throw Error();
    const xml = new DOMParser().parseFromString(await response.text(), 'application/xml');
    if (xml.documentElement.getAttributeNS(encNamespace,'discovery') !== '1') throw Error();
    const byName = new Map();
    for (const el of xml.getElementsByTagNameNS('http://www.opengis.net/wms', 'Layer')) {
      const item = readEntry(el);
      if (item) byName.set(item.name, item);
    }
    entries = [...byName.values()].sort((a,b) => a.workspace.localeCompare(b.workspace) ||
      a.store.localeCompare(b.store) || a.title.localeCompare(b.title) || a.name.localeCompare(b.name));
    // Finish WMS discovery before asking GWC to initialize its tile grids.
    if (entries.length) await loadTiles();
    configure();
    layerToggle.disabled = searchToggle.disabled = !entries.length;
    if (!searchPanel.hidden) loadTypes();
  } catch {
    statusLine.textContent = 'Could not discover the published ENC layers.';
    $('retry').hidden = false;
  }
}
async function loadTiles() {
  try {
    const response = await fetch(endpoint('gwc/service/wmts', {service:'WMTS', request:'GetCapabilities', version:'1.0.0'}),
      {signal: AbortSignal.timeout(8000)});
    if (!response.ok) return;
    const caps = new ol.format.WMTSCapabilities().read(await response.text());
    if (caps?.Contents?.Layer && caps.Contents.TileMatrixSet) {
      tileCapabilities = caps;

    }
  } catch { /* Tile caching is optional. */ }
}
layerToggle.onclick = () => {
  searchPanel.hidden = true;
  searchToggle.setAttribute('aria-expanded', 'false');
  layersPanel.hidden = !layersPanel.hidden;
  layerToggle.setAttribute('aria-expanded', String(!layersPanel.hidden));
  map.updateSize();
};
$('filter').oninput = showLayers;
$('retry').onclick = loadCatalogue;
chart.onchange = () => configureChart(true);
palette.onchange = () => changeBase(false);
service.onchange = () => {
  changeBase(false);
  for (const [item, layer] of overlays) {
    map.removeLayer(layer);
    overlays.set(item, mapLayer(item, 1));
  }
};
const searchPanel = document.getElementById('searchPanel');
const searchToggle = document.getElementById('searchToggle');
const objectType = document.getElementById('objectType');
const objectName = document.getElementById('objectName');
const searchStatus = document.getElementById('searchStatus');
const findObjects = document.getElementById('findObjects');
const results = document.getElementById('results');
const limit = 25;
let discovery, searchRequest, selectedFeature;

function highlightStyle(color, fill, width, radius, zIndex) {
  const stroke = new ol.style.Stroke({color, width});
  return new ol.style.Style({
    stroke, fill: new ol.style.Fill({color: fill}), zIndex,
    image: new ol.style.Circle({radius, stroke})
  });
}
const matchesStyle = [
  highlightStyle('#142536', 'transparent', 5, 8, 0),
  highlightStyle('#28dbff', 'rgba(40,219,255,.14)', 2.5, 8, 1)
];
const selectedStyle = [
  highlightStyle('#142536', 'transparent', 7, 11, 2),
  highlightStyle('#ffbe40', 'rgba(255,190,64,.22)', 4, 11, 3)
];
const highlights = new ol.source.Vector();
map.addLayer(new ol.layer.Vector({
  source: highlights, zIndex: 10000,
  style: feature => feature === selectedFeature ? selectedStyle : matchesStyle
}));

function clearMatches() {
  searchRequest?.abort();
  selectedFeature = null;
  highlights.clear();
  results.replaceChildren();
  searchStatus.textContent = '';
}
function wfsUrl(parameters) {
  return endpoint('wfs', {service: 'WFS', version: '1.0.0', ...parameters});
}
async function fetchWfsXml(parameters, signal, root) {
  const response = await fetch(wfsUrl(parameters), {signal});
  if (!response.ok) throw new Error('WFS request failed');
  const xml = new DOMParser().parseFromString(await response.text(), 'application/xml');
  if (xml.documentElement.localName !== root) throw new Error('Unexpected WFS response');
  return xml;
}
async function loadTypes() {
  discovery?.abort();
  discovery = new AbortController();
  const {signal} = discovery;
  searchStatus.textContent = 'Loading object types…';
  try {
    const xml = await fetchWfsXml({request: 'GetCapabilities'}, signal, 'WFS_Capabilities');
    if (signal.aborted) return;
    const names = new Set(Array.from(xml.getElementsByTagNameNS('*', 'FeatureType'),
      type => type.getElementsByTagNameNS('*', 'Name')[0]?.textContent.trim()));
    objectType.replaceChildren();
    for (const item of entries.filter(item => item.kind === 'layer' && names.has(item.name))) {
      objectType.add(new Option(label(item), item.name));
    }
    objectType.disabled = findObjects.disabled = !objectType.length;
    searchStatus.textContent = objectType.length ? '' : 'No published ENC feature types are available through WFS.';
  } catch (error) {
    if (!signal.aborted) searchStatus.textContent = 'Could not load object types. Reopen search to retry.';
  }
}

function viewportFilter(geometry) {
  const projection = view.getProjection();
  const [left, bottom, right, top] = ol.proj.transformExtent(
    view.calculateExtent(map.getSize()), projection, 'EPSG:4326');
  const west = ((left + 180) % 360 + 360) % 360 - 180;
  const east = west + (right - left);
  const ranges = east - west >= 360 ? [[-180,180]] :
    east > 180 ? [[west,180],[-180,east-360]] : [[west,east]];
  const boxes = ranges.map(([x1,x2]) =>
    "BBOX(" + geometry + "," + [x1,bottom,x2,top].join(',') + ",'EPSG:4326')");
  return '(' + boxes.join(' OR ') + ')';
}
function addResult(feature, typeLabel) {
  const row = document.createElement('li');
  const button = document.createElement('button');
  button.type = 'button';
  button.setAttribute('aria-pressed', 'false');
  const name = feature.get('OBJNAM');
  const nationalName = feature.get('NOBJNM');
  button.textContent = name || nationalName || 'Unnamed ' + typeLabel.toLowerCase();
  const detail = document.createElement('small');
  const alternate = name && nationalName !== name ? nationalName : '';
  detail.textContent = [alternate, typeLabel, feature.get('_enc_cell')].filter(Boolean).join(' · ');
  button.append(detail);
  button.onclick = () => {
    results.querySelector('[aria-pressed=true]')?.setAttribute('aria-pressed', 'false');
    button.setAttribute('aria-pressed', 'true');
    selectedFeature = feature;
    feature.changed();
    view.fit(feature.getGeometry(), map.getSize(), {
      padding: [24, 24, 24, 24], maxZoom: Math.max(view.getZoom(), 15)
    });
  };
  row.append(button);
  results.append(row);
}
async function searchObjects(event) {
  event.preventDefault();
  clearMatches();
  if (view.getZoom() < 10) {
    searchStatus.textContent = 'Zoom in to search this map area.';
    return;
  }
  const typeName = objectType.value;
  if (!typeName) return;
  const typeLabel = objectType.selectedOptions[0].textContent;
  const term = objectName.value.trim();

  searchRequest = new AbortController();
  const {signal} = searchRequest;
  searchStatus.textContent = 'Searching…';
  try {
    const schema = await fetchWfsXml({request: 'DescribeFeatureType', typeName}, signal, 'schema');
    if (signal.aborted) return;
    const fields = new Set(Array.from(schema.getElementsByTagNameNS('*', 'element'), el => el.getAttribute('name')));
    const geometry = Array.from(schema.getElementsByTagNameNS('*', 'element')).find(el => {
      const [prefix, type] = (el.getAttribute('type') || '').split(':');
      return el.lookupNamespaceURI(prefix) === 'http://www.opengis.net/gml' && /PropertyType$/.test(type);
    })?.getAttribute('name');
    if (!geometry) {
      searchStatus.textContent = 'This feature type has no searchable geometry.';
      return;
    }
    let filter = viewportFilter('"' + geometry.replaceAll('"', '""') + '"');
    const names = ['OBJNAM', 'NOBJNM'].filter(name => fields.has(name));
    if (term) {
      if (!names.length) {
        searchStatus.textContent = 'This type has no name field. Clear the name to search by type.';
        return;
      }
      // A literal substring also lets names contain percent signs and underscores.
      const literal = "'" + term.replaceAll("'", "''") + "'";
      const tests = names.map(name => `strIndexOf(strToLowerCase(${name}),strToLowerCase(${literal})) >= 0`);
      filter += ' AND (' + tests.join(' OR ') + ')';
    }
    const properties = [geometry, ...names];
    if (fields.has('_enc_cell')) properties.push('_enc_cell');
    const response = await fetch(wfsUrl({
      request: 'GetFeature', typeName, srsName: 'EPSG:4326', outputFormat: 'application/json',
      propertyName: properties.join(','),
      CQL_FILTER: filter, maxFeatures: limit + 1
    }), {signal});
    if (!response.ok) throw new Error('WFS request failed');
    const collection = await response.json();
    if (signal.aborted) return;
    const page = {...collection, features: collection.features.slice(0, limit)};
    const features = new ol.format.GeoJSON().readFeatures(page, {
      dataProjection: 'EPSG:4326', featureProjection: view.getProjection()
    });
    highlights.addFeatures(features);
    for (const feature of features) addResult(feature, typeLabel);
    if (collection.features.length > limit) searchStatus.textContent = 'Showing the first 25 matches.';
    else if (!features.length) searchStatus.textContent = 'No matches in this map area.';
    else searchStatus.textContent = features.length + (features.length === 1 ? ' match.' : ' matches.');
  } catch (error) {
    if (!signal.aborted) searchStatus.textContent = 'Search failed. Try searching this area again.';
  }
}
searchToggle.onclick = () => {
  layersPanel.hidden = true;
  layerToggle.setAttribute('aria-expanded', 'false');
  searchPanel.hidden = !searchPanel.hidden;
  searchToggle.setAttribute('aria-expanded', String(!searchPanel.hidden));
  map.updateSize();
  if (!searchPanel.hidden && !objectType.length) loadTypes();
};
document.getElementById('searchForm').onsubmit = searchObjects;
document.getElementById('clearSearch').onclick = () => {
  objectName.value = '';
  if (!objectType.disabled) clearMatches();
};
loadCatalogue();
