const $ = id => document.getElementById(id);
const format = value => new Intl.NumberFormat('es-PE').format(value);
function node(tag, text, className='') {
  const el = document.createElement(tag);
  el.textContent = text;
  el.className = className;
  return el;
}
export function renderPlan(plan, emptyMessage='Ejecuta una consulta para ver sus pasos y métricas.') {
  const content = $('plan-content');
  content.replaceChildren();
  $('plan-mode').textContent = plan ? (plan.mode === 'actual' ? 'Ejecución real' : 'Sin ejecutar') : 'Sin plan';
  if (!plan) { content.append(node('p', emptyMessage, 'plan-empty')); return; }
  content.append(node('p', plan.reason, 'plan-reason'));
  const context = node('div', '', 'plan-context');
  context.append(node('span', `Tabla: ${plan.table}`));
  if (plan.organization) context.append(node('span', `Organización: ${plan.organization}`));
  if (plan.index_name) context.append(node('span', `Índice: ${plan.index_name}`));
  content.append(context);
  if (plan.sql) content.append(node('pre', plan.sql, 'plan-sql'));
  const flow = node('ol', '', 'plan-flow');
  flow.setAttribute('aria-label', 'Operadores en orden de ejecución');
  plan.steps.forEach((step, i) => {
    const item = node('li', '', 'plan-node');
    item.append(node('span', `PASO ${i + 1}`, 'plan-step'), node('strong', step.operator), node('p', step.detail));
    if (step.actual_rows !== null && step.actual_rows !== undefined) item.append(node('small', `${format(step.actual_rows)} filas`, 'plan-rows'));
    flow.append(item);
  });
  content.append(flow);
  if (plan.metrics) {
    const summary = node('div', '', 'plan-totals');
    summary.append(
      node('span', `${format(plan.metrics.disk_reads)} páginas leídas`),
      node('span', `${format(plan.metrics.disk_writes)} páginas escritas`),
      node('span', `${plan.metrics.exec_time_ms.toFixed(2)} ms de ejecución`),
      node('span', `${plan.metrics.parse_time_ms.toFixed(2)} ms de parseo`)
    );
    content.append(summary, node('p', 'Métricas totales de la operación, incluidas las páginas de datos, índices y metadata.', 'plan-footnote'));
  } else {
    content.append(node('p', 'Plan elegido por reglas. Las filas y métricas reales se mostrarán al ejecutar la consulta.', 'plan-footnote'));
  }
}
