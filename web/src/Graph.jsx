import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph from 'react-force-graph-2d';

const colours = { concept: '#177556', fact: '#78a28f', document: '#ba863d' };
const labelPriority = { document: 0, concept: 1, fact: 2 };
const classificationTypes = new Set(['is_a', 'include_in']);
const relationshipColour = '#3b6558';
const nodeRadius = 3.8;
const labelHeight = 12;
const labelCell = 16;
const count = new Intl.NumberFormat();

function canvasLabel(name) {
  const characters = Array.from(name.trim().replace(/\s+/g, ' '));
  return characters.length > 48 ? `${characters.slice(0, 47).join('')}…` : characters.join('');
}

function graphLinks(relationships) {
  const pairs = new Map();
  const links = relationships.map(({ source, target, type }) => {
    const key = JSON.stringify(source <= target ? [source, target] : [target, source]);
    const link = { source, target, type, label: canvasLabel(type), curvature: 0 };
    if (!pairs.has(key)) pairs.set(key, []);
    pairs.get(key).push(link);
    return link;
  });
  for (const group of pairs.values()) {
    const center = (group.length - 1) / 2;
    const spacing = Math.min(0.16, 0.35 / Math.max(1, center));
    group.forEach((link, index) => {
      const direction = link.source < link.target ? 1 : -1;
      link.curvature = link.source === link.target ? 0.45 + index * 0.14 : (index - center) * spacing * direction;
    });
  }
  return links;
}

function relationshipTooltip({ type }) {
  const label = document.createElement('span');
  label.textContent = type;
  return label;
}

function drawLabels(context, scale, nodes, links, widths, activeLink) {
  const transform = context.getTransform();
  const ratio = window.devicePixelRatio;
  const width = context.canvas.width / ratio;
  const height = context.canvas.height / ratio;
  const columns = Math.ceil(width / labelCell);
  const occupied = new Uint8Array(columns * Math.ceil(height / labelCell));
  context.save();
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.font = `500 ${labelHeight}px system-ui, sans-serif`;
  context.textAlign = 'center';
  context.textBaseline = 'top';
  context.strokeStyle = '#fcfdfb';
  context.lineWidth = 3;
  context.lineJoin = 'round';

  const screenX = x => (x * transform.a + transform.e) / ratio;
  const screenY = y => (y * transform.d + transform.f) / ratio;
  function textWidth(label) {
    if (!widths.has(label)) widths.set(label, context.measureText(label).width);
    return widths.get(label);
  }

  function paint(label, x, top) {
    if (!(x >= 0 && x < width && top >= 2 && top + labelHeight + 3 < height)) return;
    const half = textWidth(label) / 2 + 3;
    const left = x - half;
    const right = x + half;
    if (left < 0 || right >= width) return;
    const firstColumn = Math.floor(left / labelCell);
    const lastColumn = Math.floor(right / labelCell);
    const firstRow = Math.floor((top - 2) / labelCell);
    const lastRow = Math.floor((top + labelHeight + 2) / labelCell);
    // Reserve screen space so zooming reveals more names without overlapping labels.
    for (let row = firstRow; row <= lastRow; row++) {
      for (let column = firstColumn; column <= lastColumn; column++) {
        if (occupied[row * columns + column]) return;
      }
    }
    for (let row = firstRow; row <= lastRow; row++) {
      occupied.fill(1, row * columns + firstColumn, row * columns + lastColumn + 1);
    }
    context.strokeText(label, x, top);
    context.fillText(label, x, top);
    return true;
  }

  function paintRelationship({ source, target, curvature, label }, focused) {
    const dx = target.x - source.x;
    const dy = target.y - source.y;
    const loop = source === target ? 26.25 * curvature : 0;
    const span = loop ? loop * 2 : Math.hypot(dx, dy);
    if (!focused && span * scale < textWidth(label) + 12) return;
    // The quadratic curve's midpoint is halfway toward its perpendicular control point.
    const x = source.x + (dx + dy * curvature) / 2 + loop;
    const y = source.y + (dy - dx * curvature) / 2 - loop;
    return paint(label, screenX(x), screenY(y) - labelHeight / 2);
  }

  context.fillStyle = relationshipColour;
  if (activeLink) paintRelationship(activeLink, true);
  // Leave space for a few distinct relationship names in the full-graph overview.
  const featuredTypes = new Set(activeLink ? [activeLink.type] : []);
  for (const link of links) {
    if (featuredTypes.size >= 6 || classificationTypes.has(link.type)) break;
    if (!featuredTypes.has(link.type) && paintRelationship(link, false)) featuredTypes.add(link.type);
  }
  context.fillStyle = '#22352d';
  for (const { x, y, label } of nodes) {
    const top = screenY(y) + nodeRadius * scale + 3;
    paint(label, screenX(x), top);
  }
  context.fillStyle = relationshipColour;
  for (const link of links) {
    if (link !== activeLink) paintRelationship(link, false);
  }
  context.restore();
}

export default function Graph({ result }) {
  const panel = useRef(null);
  const container = useRef(null);
  const view = useRef(null);
  const didFit = useRef(false);
  const [{ width, height }, setSize] = useState({ width: 0, height: 0 });
  const [fullscreen, setFullscreen] = useState(false);
  const [selected, setSelected] = useState(null);
  const [hovered, setHovered] = useState(null);
  const { data, labelOrder, relationshipOrder, labelWidths } = useMemo(() => {
    const nodes = result.nodes.map(({ id, labels, properties }) => {
      const name = String(properties.name || properties.title || labels[0] || id);
      return {
        id, kind: labels[0], name, label: canvasLabel(name),
        page: Number.isInteger(properties.page_number) ? properties.page_number + 1 : null,
      };
    });
    const links = graphLinks(result.relationships);
    const labelOrder = [...nodes].sort((a, b) => (labelPriority[a.kind] ?? 3) - (labelPriority[b.kind] ?? 3));
    const relationshipOrder = [...links].sort((a, b) => Number(classificationTypes.has(a.type)) - Number(classificationTypes.has(b.type)));
    return { data: { nodes, links }, labelOrder, relationshipOrder, labelWidths: new Map() };
  }, [result]);
  const detail = selected || hovered;
  const relationship = detail?.type ? detail : null;
  const node = relationship ? null : detail;
  const highlightedLink = hovered?.type ? hovered : relationship;
  const linkColour = useCallback(link => link === highlightedLink ? '#2c725b' : '#b1bfb7', [highlightedLink]);
  const linkWidth = useCallback(link => link === highlightedLink ? 1.8 : 0.7, [highlightedLink]);
  const fit = useCallback((duration = 250) => {
    view.current?.zoomToFit(duration, Math.min(48, width / 6, height / 6));
  }, [width, height]);

  useEffect(() => {
    const observer = new ResizeObserver(([{ contentRect }]) => {
      const width = Math.floor(contentRect.width);
      const height = Math.floor(contentRect.height);
      setSize(previous => previous.width === width && previous.height === height ? previous : { width, height });
    });
    observer.observe(container.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!width || !height) return;
    const frame = requestAnimationFrame(() => fit(0));
    return () => cancelAnimationFrame(frame);
  }, [fit, width, height]);

  useEffect(() => {
    const host = panel.current;
    function syncFullscreen() {
      setFullscreen(document.fullscreenElement === host);
    }
    document.addEventListener('fullscreenchange', syncFullscreen);
    return () => document.removeEventListener('fullscreenchange', syncFullscreen);
  }, []);

  useEffect(() => {
    if (!fullscreen) return;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    function closeExpanded(event) {
      if (event.key === 'Escape' && !document.fullscreenElement) setFullscreen(false);
    }
    document.addEventListener('keydown', closeExpanded);
    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener('keydown', closeExpanded);
    };
  }, [fullscreen]);

  async function toggleFullscreen() {
    if (document.fullscreenElement === panel.current) {
      await document.exitFullscreen();
    } else if (fullscreen) {
      setFullscreen(false);
    } else {
      try {
        if (panel.current.requestFullscreen) await panel.current.requestFullscreen();
        else setFullscreen(true);
      } catch {
        setFullscreen(true);
      }
    }
  }

  return <div className={`graph-panel${fullscreen ? ' graph-fullscreen' : ''}`} ref={panel}>
    <div className="graph-surface interactive-graph" ref={container} aria-label="Interactive knowledge graph">
      <div className="graph-controls">
        <button className="small-button fit" onClick={() => fit()}>Fit graph</button>
        <button className="small-button fullscreen-toggle" onClick={toggleFullscreen}>{fullscreen ? 'Exit full screen' : 'Full screen'}</button>
      </div>
      {width > 0 && height > 0 && <ForceGraph
        ref={view} width={width} height={height} graphData={data}
        nodeColor={({ kind }) => colours[kind] || colours.fact} nodeRelSize={nodeRadius}
        linkColor={linkColour} linkWidth={linkWidth} linkCurvature="curvature" linkDirectionalArrowLength={2}
        nodeLabel={() => ''} linkLabel={relationshipTooltip}
        onRenderFramePost={(context, scale) => drawLabels(context, scale, labelOrder, relationshipOrder, labelWidths, highlightedLink)}
        onNodeClick={setSelected} onNodeHover={setHovered}
        onLinkClick={setSelected} onLinkHover={setHovered} onBackgroundClick={() => setSelected(null)}
        cooldownTicks={200} cooldownTime={6500}
        onEngineStop={() => {
          if (!didFit.current) {
            didFit.current = true;
            fit();
          }
        }}
      />}
    </div>
    <div className="graph-caption">
      {relationship ? <div className="relationship-detail">{relationship.source.name} → <strong>{relationship.type}</strong> → {relationship.target.name}</div>
        : node ? <div><strong>{node.name}</strong><span className="node-description">{node.kind}{node.page ? ` · Page ${node.page}` : ''}</span></div>
        : <div className="legend">{Object.entries(colours).map(([kind, colour]) =>
          <span key={kind}><i style={{ background: colour }} />{kind}</span>)}</div>}
      {selected && <button className="text-button" onClick={() => setSelected(null)}>Clear selection</button>}
      {fullscreen && <span className="graph-count">{count.format(data.nodes.length)} nodes · {count.format(data.links.length)} relationships</span>}
    </div>
  </div>;
}
