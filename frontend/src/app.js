import {runQuery, listTables, reorganizeTable, health} from './services/api.js';
import {renderPlan} from './execution-plan.js';
import {setupCsvImport} from './csv-import.js';
import {sqlExample} from './sql-examples.js';
const $ = id => document.getElementById(id);
let busy=false, currentSql='', offset=0, total=0, selectedTable=null, catalogTables=[];
const activity=[];
const format = n => new Intl.NumberFormat('es-PE').format(n);
function element(tag, text, className='') { const node=document.createElement(tag); node.textContent=text; node.className=className; return node; }
function highlight() {
  const sql=$('sql').value;
  $('highlight').replaceChildren();
  const pattern=/(--[^\n]*|'(?:''|[^'])*'|\b(?:SELECT|FROM|WHERE|AND|CREATE|TABLE|INDEX|USING|PRIMARY|KEY|HEAP|SEQUENTIAL|BTREE|HASH|INSERT|INTO|VALUES|DELETE|DROP|INT|FLOAT|CHAR)\b|\b\d+(?:\.\d+)?\b)/gi;
  let start=0;
  for (const match of sql.matchAll(pattern)) {
    $('highlight').append(document.createTextNode(sql.slice(start,match.index)));
    const token=match[0], style=token.startsWith('--')?'comment':token.startsWith("'")?'string':/^\d/.test(token)?'number':'keyword';
    $('highlight').append(element('span',token,'tok-'+style)); start=match.index+token.length;
  }
  $('highlight').append(document.createTextNode(sql.slice(start)+'\n'));
  $('line-numbers').textContent=sql.split('\n').map((_,i)=>i+1).join('\n');
  syncScroll();
}
function syncScroll(){ $('highlight').scrollTop=$('sql').scrollTop; $('highlight').scrollLeft=$('sql').scrollLeft; $('line-numbers').scrollTop=$('sql').scrollTop; }
function setStatus(text,kind=''){ $('status').className=kind; $('status').replaceChildren(element('span',kind==='success'?'✓':kind==='error'?'!':'○','status-symbol'),document.createTextNode(text)); }
function setBusy(value){ busy=value; for(const id of ['run','clear','examples','reorganize','page-size','refresh','import-open']) $(id).disabled=value; $('run-label').textContent=value?'Ejecutando…':'Ejecutar consulta'; $('run-icon').textContent=value?'◌':'▶'; $('previous').disabled=value||offset===0; $('next').disabled=value||offset+Number($('page-size').value)>=total;updateExamples(); }
function metrics(result){
  $('access-path').textContent=result.access_path;
  $('index-name').textContent=result.index_name?`Índice: ${result.index_name}`:result.access_path==='SeqScan'?'Organización física de la tabla':'Operación del motor';
  $('disk-reads').textContent=format(result.disk_reads); $('disk-writes').textContent=format(result.disk_writes);
  $('parse-time').textContent=result.parse_time_ms.toFixed(2); $('exec-time').textContent=result.exec_time_ms.toFixed(2);
  activity.push(result); if(activity.length>10)activity.shift();
  const maximum=Math.max(1,...activity.flatMap(x=>[x.disk_reads,x.disk_writes]));
  $('history').replaceChildren();
  activity.forEach((item,i)=>{const group=element('div','','history-item');group.title=`${i+1}. ${item.access_path}: ${format(item.disk_reads)} lecturas, ${format(item.disk_writes)} escrituras`;
    for(const kind of ['reads','writes']){const bar=element('div','','bar '+kind);bar.style.height=`${item['disk_'+kind]/maximum*100}%`;group.append(bar);} $('history').append(group);});
}
function showResults(result){
  total=result.total_rows;
  $('row-count').textContent=`${format(total)} filas`;
  $('results').replaceChildren();
  if(result.rows.length){
    const table=document.createElement('table'),head=document.createElement('thead'),row=document.createElement('tr');
    row.append(element('th','#','row-number')); result.columns.forEach(name=>row.append(element('th',name)));head.append(row);table.append(head);
    const body=document.createElement('tbody');result.rows.forEach((record,i)=>{const tr=document.createElement('tr');tr.append(element('td',format(offset+i+1),'row-number'));result.columns.forEach(name=>tr.append(element('td',record[name]??'')));body.append(tr);});table.append(body);$('results').append(table);
  } else {
    const empty=element('div','','empty-state');empty.append(element('div','▤','empty-icon'),element('h3',result.message||'No se encontraron filas'),element('p',result.affected_rows?`${format(result.affected_rows)} filas afectadas`:'Prueba otra consulta o selecciona un ejemplo.'));$('results').append(empty);
  }
  $('page-info').textContent=total?`${format(offset+1)}–${format(Math.min(offset+result.rows.length,total))} de ${format(total)} filas`:'Sin filas para mostrar';
  $('page-number').textContent=Math.floor(offset/Number($('page-size').value))+1;
  $('result-note').textContent=total?'Paginación en servidor · cada página ejecuta SQL':result.message;
}
async function execute(pageOffset=0, reuseExecutedSql=false){
  if(busy)return;
  if(!reuseExecutedSql)currentSql=$('sql').value.trim();
  if(!currentSql){setStatus('Escribe una consulta para continuar.','error');return;}
  offset=pageOffset;setBusy(true);setStatus('Ejecutando consulta sobre archivos en disco…');
  try{const result=await runQuery(currentSql,offset,Number($('page-size').value));metrics(result);showResults(result);renderPlan(result.execution_plan);setStatus(`Consulta completada · ${result.message}`,'success');await refreshTables();}
  catch(error){setStatus(error.message,'error');renderPlan(null,'No hay plan disponible para la consulta fallida.');total=0;for(const id of ['access-path','disk-reads','disk-writes','parse-time','exec-time'])$(id).textContent='—';$('index-name').textContent='Consulta fallida';$('results').replaceChildren(element('div',error.message,'empty-state'));$('row-count').textContent='0 filas';$('page-info').textContent='Sin resultados';$('result-note').textContent='Consulta fallida';}
  finally{setBusy(false);}
}
async function refreshTables(){
  const {tables}=await listTables();catalogTables=tables;$('tables').replaceChildren();
  selectedTable=tables.find(table=>table.name===selectedTable?.name)??tables[0]??null;
  if(!tables.length){const empty=element('div','','table-detail');empty.append(element('p','Todavía no hay tablas.'),element('p','Usa «Importar CSV» o el ejemplo «Crear tabla demo».'));$('tables').append(empty);}
  for(const table of tables){
    const details=document.createElement('details');details.className='table-entry';details.dataset.table=table.name;details.open=selectedTable?.name===table.name;
    const summary=document.createElement('summary');summary.append(element('span','▦','muted'),element('span',table.name,'table-name'),element('span',table.organization,'org-badge'));details.append(summary);
    const content=element('div','','table-detail');content.append(element('div','Columnas','tree-label'));
    table.columns.forEach(c=>{const row=element('div','','column-row');row.append(element('span',c.name),element('small',c.dtype));content.append(row);});
    content.append(element('div','Índices','tree-label'));
    table.indexes.forEach(index=>content.append(element('div',`${index.kind} · ${index.internal?'PRIMARY KEY (interno)':index.name}`,'index-row')));
    const select=element('button','Consultar tabla →','table-select');select.onclick=()=>chooseTable(table.name,true);content.append(select);details.append(content);
    details.addEventListener('toggle',()=>{if(details.open&&details.isConnected&&selectedTable?.name!==table.name)chooseTable(table.name);});$('tables').append(details);
  }
  updateReorganize();updateExamples();
  if(selectedTable&&!$('sql').value.trim()){$('sql').value=`SELECT * FROM ${selectedTable.name};`;highlight();}
}
function updateReorganize(){ $('reorganize').hidden=selectedTable?.organization!=='SEQUENTIAL';$('reorganize').textContent=selectedTable?`Reorganizar ${selectedTable.name}`:''; }
$('run').onclick=()=>execute();$('sql').addEventListener('input',highlight);$('sql').addEventListener('scroll',syncScroll);
$('sql').addEventListener('keydown',event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();execute();}});
$('clear').onclick=()=>{$('sql').value='';highlight();$('sql').focus();};
$('refresh').onclick=()=>refreshTables().catch(error=>setStatus(error.message,'error'));
$('previous').onclick=()=>execute(Math.max(0,offset-Number($('page-size').value)),true);
$('next').onclick=()=>execute(offset+Number($('page-size').value),true);
$('page-size').onchange=()=>{if(!busy && total>0)execute(0,true);};
function updateExamples(){
  for(const option of $('examples').options)option.disabled=!!option.value&&option.value!=='demo'&&!selectedTable;
}
function chooseTable(name,loadSql=false){
  selectedTable=catalogTables.find(table=>table.name===name)??null;
  updateReorganize();updateExamples();
  for(const details of $('tables').querySelectorAll('.table-entry'))details.open=details.dataset.table===selectedTable?.name;
  if(loadSql&&selectedTable){$('sql').value=`SELECT * FROM ${selectedTable.name};`;highlight();$('sql').focus();}
}
$('examples').onchange=()=>{
  const kind=$('examples').value;$('examples').value='';
  if(busy||!kind)return;
  try{const sql=sqlExample(kind,selectedTable,catalogTables);if(sql){$('sql').value=sql;highlight();$('sql').focus();}}
  catch(error){setStatus(error.message,'error');}
};
$('reorganize').onclick=async()=>{if(busy||!selectedTable)return;setBusy(true);setStatus('Reorganizando principal y reconstruyendo índices…');try{const result=await reorganizeTable(selectedTable.name);metrics(result);renderPlan(null,'Reorganización completada. Ejecuta una consulta para ver su nuevo plan.');setStatus(result.message,'success');}catch(error){setStatus(error.message,'error');}finally{setBusy(false);}};
setupCsvImport({isBusy:()=>busy,setBusy,onImported:async result=>{
  offset=0;currentSql='';selectedTable={name:result.table};
  metrics(result);showResults(result);renderPlan(result.execution_plan);
  $('sql').value=`SELECT * FROM ${result.table};`;highlight();
  setStatus(`${result.message} · consulta preparada en el editor`,'success');
  try{await refreshTables();}catch(error){setStatus(`${result.message}. No se pudo actualizar el explorador: ${error.message}`,'error');}
}});
highlight();
Promise.all([health(),refreshTables()]).then(()=>{$('connection').replaceChildren(element('span','','dot'),document.createTextNode('Motor conectado'));}).catch(error=>{$('connection').classList.add('offline');$('connection').textContent='Sin conexión';setStatus(error.message,'error');});
