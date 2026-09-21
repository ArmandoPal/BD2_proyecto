const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
if (!process.env.BD2_URL) throw Error('Define BD2_URL con la URL del servidor de pruebas.');
(async () => {
  const browser = await chromium.launch({executablePath:process.env.CHROME_PATH, headless:true});
  const errors = [];
  const suffix = Date.now();
  const tableName = `csv_ui_${suffix}`;
  const allName = `csv_all_${suffix}`;
  const out = 'output/qa/csv-plan';
  fs.mkdirSync(out, {recursive:true});
  try {
    const page = await browser.newPage({viewport:{width:1366,height:1000}});
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.BD2_URL);
    await page.getByText('Motor conectado',{exact:true}).waitFor();
    const csv = Buffer.from('\ufeffCódigo,Nombre,Precio,Stock\n001,"Café, especial",3.50,4\n002,Té,2,0\n003,Chocolate,5,8\n');
    async function selectTable(name) {
      const entry = page.locator(`.table-entry[data-table="${name}"]`);
      if(await entry.getAttribute('open')===null)await entry.locator('summary').click();
      await entry.locator('.table-select').click();
    }
    assert.equal(await page.locator('#example-table').count(), 0);
    async function submitImport(expectedStatus=200) {
      const promise = page.waitForResponse(response => response.url().includes('/api/tables/import-csv?'));
      await page.locator('#import-submit').click();
      const response = await promise;
      assert.equal(response.status(), expectedStatus);
      await page.waitForFunction(() => !document.getElementById('import-submit').disabled);
      return response.json();
    }
    async function query(sql, status=200) {
      await page.locator('#sql').fill(sql);
      const promise = page.waitForResponse(response => response.url().endsWith('/api/query'));
      await page.locator('#run').click();
      const response = await promise;
      assert.equal(response.status(), status);
      await page.waitForFunction(() => !document.getElementById('run').disabled);
      return response.json();
    }
    await page.locator('#import-open').click();
    await page.locator('#csv-file').setInputFiles({name:'Catálogo.csv',mimeType:'text/csv',buffer:csv});
    assert.equal(await page.locator('#csv-table').inputValue(), 'catalogo');
    await page.locator('#csv-table').fill(tableName);
    await page.locator('#csv-limit').fill('2');
    await page.locator('#csv-organization').selectOption('SEQUENTIAL');
    await page.screenshot({path:`${out}/import-dialog.png`});
    const imported = await submitImport();
    assert.equal(imported.affected_rows, 2);
    assert.equal(await page.locator('#import-dialog').isVisible(), false);
    assert.equal(await page.locator('#sql').inputValue(), `SELECT * FROM ${tableName};`);
    assert.equal(await page.locator('#tables summary').filter({hasText:tableName}).count(), 1);
    const select = `SELECT nombre FROM ${tableName} WHERE precio >= 2.5;`;
    const result = await query(select);
    assert.equal(result.total_rows, 1);
    assert.deepEqual(result.execution_plan.steps.map(step => step.actual_rows), [2,1,1,1]);
    assert.match(await page.locator('#results').innerText(), /Café, especial/);
    assert.equal(await page.locator('#plan-mode').innerText(), 'Ejecución real');
    assert.equal(await page.locator('#explain').count(), 0);
    assert.equal((await page.locator('#tables').innerText()).includes('⚿'), false);
    assert.equal(await page.evaluate(() => document.querySelector('.results-card').getBoundingClientRect().bottom <= document.getElementById('execution-plan').getBoundingClientRect().top), true);
    await query(`CREATE INDEX idx_ui_${suffix} ON ${tableName}(precio) USING BTREE;`);
    const range = `SELECT * FROM ${tableName} WHERE precio >= 2 AND precio <= 4;`;
    await query(range);
    assert.match(await page.locator('#plan-content').innerText(), /IndexRangeScan/);
    await page.screenshot({path:`${out}/execution-plan.png`,fullPage:true});
    await query('SELECT * FROM tabla_inexistente;', 400);
    assert.equal(await page.locator('#plan-mode').innerText(), 'Sin plan');
    assert.equal(await page.locator('.plan-node').count(), 0);
    await page.locator('#import-open').click();
    await page.locator('#csv-file').setInputFiles({name:'items.csv',mimeType:'text/csv',buffer:csv});
    await page.locator('#csv-table').fill(tableName);
    await submitImport(400);
    assert.match(await page.locator('#import-error').innerText(), /Tabla existente/);
    assert.equal(await page.locator('#import-dialog').isVisible(), true);
    await page.locator('#csv-table').fill(allName);
    assert.equal((await submitImport()).affected_rows, 3);
    await page.locator('#import-open').click();
    await page.locator('#csv-file').setInputFiles({name:'invalid.csv',mimeType:'text/csv',buffer:Buffer.from('a,a\n1,2\n')});
    await page.locator('#csv-table').fill(`invalid_${suffix}`);
    await submitImport(400);
    assert.match(await page.locator('#import-error').innerText(), /encabezados se repiten/);
    await page.locator('#import-cancel').click();
    await query(`SELECT * FROM ${allName};`);
    let queryRequests = 0;
    page.on('request', request => { if(request.url().endsWith('/api/query')) queryRequests++; });
    for(const name of [tableName,allName]) {
      await selectTable(name);
      const before = queryRequests;
      await page.locator('#examples').selectOption('point');
      assert.equal(await page.locator('#sql').inputValue(), `SELECT * FROM ${name} WHERE _row_id = 1;`);
      assert.equal(queryRequests, before, 'Elegir un ejemplo no debe ejecutarlo');
      await page.locator('#examples').selectOption('range');
      assert.match(await page.locator('#sql').inputValue(), new RegExp(`FROM ${name}\\nWHERE _row_id`));
      assert.equal((await query(await page.locator('#sql').inputValue())).total_rows, name===tableName ? 2 : 3);
    }
    const textName = `text_ui_${suffix}`;
    await query(`CREATE TABLE ${textName}(code CHAR(2) PRIMARY KEY, qty INT, price FLOAT, note CHAR(3)) USING HEAP;`);
    await selectTable(textName);
    await page.locator('#examples').selectOption('insert');
    const insertSql = await page.locator('#sql').inputValue();
    assert.match(insertSql, /VALUES \('A', 1, 1.0, 'Eje'\)/);
    assert.equal((await query(insertSql)).affected_rows, 1);
    for(const kind of ['point','range','select']) {
      await page.locator('#examples').selectOption(kind);
      assert.equal((await query(await page.locator('#sql').inputValue())).total_rows, 1);
    }
    let firstIndex;
    for(const kind of ['index','index','hash']) {
      await page.locator('#examples').selectOption(kind);
      const sql = await page.locator('#sql').inputValue();
      if(kind==='index' && firstIndex) assert.notEqual(sql, firstIndex);
      if(kind==='index') firstIndex = sql;
      assert.equal((await query(sql)).access_path, 'CreateIndex');
    }
    await page.locator('#examples').selectOption('delete');
    assert.equal((await query(await page.locator('#sql').inputValue())).affected_rows, 1);
    await page.locator('#examples').selectOption('deleteAll');
    assert.equal((await query(await page.locator('#sql').inputValue())).affected_rows, 0);
    await page.locator('#examples').selectOption('drop');
    assert.equal((await query(await page.locator('#sql').inputValue())).access_path, 'DropTable');
    assert.equal(await page.locator(`.table-entry[data-table="${textName}"]`).count(), 0);
    await selectTable(allName);
    await page.locator('#examples').selectOption('select');
    await query(await page.locator('#sql').inputValue());
    for (const width of [760,390]) {
      await page.setViewportSize({width,height:900});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `Overflow a ${width}px`);
      await page.screenshot({path:`${out}/frontend-${width}.png`,fullPage:true});
      await page.locator('#import-open').click();
      assert.equal(await page.locator('#import-dialog').isVisible(), true);
      await page.locator('#import-cancel').click();
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(`${out}/checks.json`, JSON.stringify({csv_import:true,optional_limit:true,generic_schema:true,catalog_refresh:true,duplicate_and_invalid_errors:true,actual_plan:true,no_explain_button:true,no_key_icon:true,plan_below_results:true,dynamic_examples:true,index_range:true,stale_plan_cleared:true,viewports:[1366,760,390],console_errors:errors},null,2));
    console.log('Frontend OK: importar CSV, límite opcional, errores, catálogo, plan bajo resultados y ejemplos para tablas existentes.');
    // Retirar únicamente las dos tablas creadas por esta prueba.
    for (const name of [tableName,allName]) await page.request.post(`${process.env.BD2_URL}/api/query`, {data:{sql:`DROP TABLE ${name};`}});
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
