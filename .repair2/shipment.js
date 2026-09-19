function shipmentText(value) {
  if (typeof value !== 'string') return '';
  const clean = value.trim();
  return /^(null|undefined|none)$/i.test(clean) ? '' : clean.slice(0, 400);
}

function showShipment(row, shipment) {
  if (!shipment || typeof shipment !== 'object' || Array.isArray(shipment)) return;
  const card = el('div', 'shipment-card');
  const header = el('div', 'shipment-header');
  const status = typeof shipment.status === 'string' && /^[a-z_]{1,40}$/.test(shipment.status) ? shipment.status : 'unknown';
  header.append(
    el('strong', '', '\ud83d\ude9a ' + (shipmentText(shipment.carrier) || 'Th\u00f4ng tin v\u1eadn chuy\u1ec3n')),
    el('span', 'tracking-pill ' + status, shipmentText(shipment.status_text) || 'Ch\u01b0a c\u00f3 d\u1eef li\u1ec7u h\u00e0nh tr\u00ecnh')
  );
  const body = el('div', 'shipment-body');
  for (const [key, label] of [
    ['tracking_code', 'M\u00e3 v\u1eadn \u0111\u01a1n: '], ['current_location', 'V\u1ecb tr\u00ed hi\u1ec7n t\u1ea1i: '],
    ['shipper', 'Shipper: '], ['estimated_delivery', '\u23f0 D\u1ef1 ki\u1ebfn nh\u1eadn: ']
  ]) {
    const value = shipmentText(shipment[key]);
    if (value) body.append(el('p', key === 'estimated_delivery' ? 'delivery-eta' : '', label + value));
  }
  const steps = Array.isArray(shipment.steps) ? shipment.steps.filter(step => step && shipmentText(step.event)).slice(0, 20) : [];
  if (steps.length) {
    const timeline = el('div', 'shipment-timeline');
    for (const step of steps) {
      const item = el('div', 'timeline-item');
      item.append(el('span', 'timeline-time', shipmentText(step.time)), el('span', 'timeline-event', shipmentText(step.event)));
      timeline.append(item);
    }
    body.append(timeline);
  }
  if (!body.children.length) {
    body.append(el('p', '', 'H\u1ec7 th\u1ed1ng ch\u01b0a c\u00f3 m\u00e3 v\u1eadn \u0111\u01a1n, v\u1ecb tr\u00ed ho\u1eb7c ng\u00e0y giao d\u1ef1 ki\u1ebfn cho \u0111\u01a1n n\u00e0y.'));
  }
  card.append(header, body);
  row.append(card);
}
