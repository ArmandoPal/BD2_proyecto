import {importCsv} from './services/api.js';
const $ = id => document.getElementById(id);
export function setupCsvImport({isBusy, setBusy, onImported}) {
  const dialog = $('import-dialog'), form = $('import-form');
  let importing = false;
  $('import-open').onclick = () => {
    if (isBusy()) return;
    form.reset();
    $('import-error').textContent = '';
    $('import-progress').hidden = true;
    dialog.showModal();
  };
  $('import-cancel').onclick = () => dialog.close();
  dialog.addEventListener('cancel', event => { if (importing) event.preventDefault(); });
  $('csv-file').onchange = () => {
    const file = $('csv-file').files[0];
    if (!file || $('csv-table').value) return;
    let name = file.name.replace(/\.csv$/i, '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-zA-Z0-9_]+/g, '_').replace(/^_+|_+$/g, '').toLowerCase();
    if (/^\d/.test(name)) name = 'table_' + name;
    $('csv-table').value = (name || 'imported_data').slice(0, 128);
  };
  form.onsubmit = async event => {
    event.preventDefault();
    if (importing || isBusy() || !form.reportValidity()) return;
    const file = $('csv-file').files[0];
    $('import-error').textContent = '';
    if (!file || file.size > 256 * 1024 * 1024) {
      $('import-error').textContent = 'Selecciona un CSV de hasta 256 MB.';
      return;
    }
    const options = {table_name:$('csv-table').value, organization:$('csv-organization').value, delimiter:$('csv-delimiter').value};
    if ($('csv-limit').value) options.limit = $('csv-limit').value;
    importing = true;
    setBusy(true);
    form.querySelectorAll('input, select, button').forEach(el => el.disabled = true);
    $('import-progress').hidden = false;
    try {
      const result = await importCsv(file, options);
      dialog.close();
      await onImported(result);
    } catch (error) {
      $('import-error').textContent = error.message;
    } finally {
      importing = false;
      setBusy(false);
      form.querySelectorAll('input, select, button').forEach(el => el.disabled = false);
      $('import-progress').hidden = true;
    }
  };
}
