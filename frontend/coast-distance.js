'use strict';

(function (root) {
  const radians = Math.PI / 180;
  const earthRadiusKm = 6371.0088;

  function unitVector(lat, lon) {
    const phi = lat * radians;
    const lambda = lon * radians;
    return [Math.cos(phi) * Math.cos(lambda), Math.cos(phi) * Math.sin(lambda), Math.sin(phi)];
  }

  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
  const length = v => Math.hypot(...v);

  function nearestAngle(point, a, b) {
    const normal = cross(a, b);
    const magnitude = length(normal);
    const endpoint = Math.acos(Math.min(1, Math.max(-1, dot(point, a), dot(point, b))));
    if (magnitude < 1e-12) return endpoint;
    const unitNormal = normal.map(value => value / magnitude);
    // The perpendicular foot must fall between the segment's two endpoints.
    if (dot(point, cross(unitNormal, a)) < 0 || dot(point, cross(b, unitNormal)) < 0) return endpoint;
    return Math.asin(Math.min(1, Math.abs(dot(point, unitNormal))));
  }

  function distanceToLandKm(land, lat, lon) {
    const point = unitVector(lat, lon);
    let closest = Infinity;
    for (const { geometry } of land.features) {
      const polygons = geometry.type === 'MultiPolygon' ? geometry.coordinates : [geometry.coordinates];
      for (const polygon of polygons) {
        let onLand = false;
        for (const ring of polygon) {
          let inside = false;
          let a = unitVector(ring[0][1], ring[0][0]);
          for (let i = 1; i < ring.length; i++) {
            const [x1, y1] = ring[i - 1];
            const [x2, y2] = ring[i];
            if ((y1 > lat) !== (y2 > lat) && lon < x1 + (x2 - x1) * (lat - y1) / (y2 - y1)) inside = !inside;
            const b = unitVector(y2, x2);
            // The polygons are split at the antimeridian. That edge is not a coast.
            if (!(Math.abs(x1) === 180 && Math.abs(x2) === 180)) {
              closest = Math.min(closest, nearestAngle(point, a, b));
            }
            a = b;
          }
          if (inside) onLand = !onLand;
        }
        if (onLand) return 0;
      }
    }
    return closest * earthRadiusKm;
  }

  root.R34Coast = { distanceToLandKm };
})(typeof window === 'undefined' ? module.exports : window);
