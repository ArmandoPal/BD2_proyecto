/** Conexión del cliente con el motor real, en el mismo origen. */
async function request(path, body) {
  const response = await fetch(`/api${path}`, body ? {
    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)
  } : {});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
  return data;
}
export const runQuery = (sql, offset=0, limit=100) => request('/query', {sql,offset,limit});
export const listTables = () => request('/tables');
export const reorganizeTable = table_name => request('/tables/reorganize', {table_name});
export const health = () => request('/health');
