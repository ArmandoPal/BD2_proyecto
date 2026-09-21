// Plantillas basadas en el catálogo. Elegir un ejemplo solo prepara el editor.
function uniqueName(base, names) {
  let name = base, suffix = 2;
  while (names.has(name)) name = `${base}_${suffix++}`;
  return name;
}
function literal(column, upper=false) {
  if (column.dtype === 'INT') return upper ? '10' : '1';
  if (column.dtype === 'FLOAT') return upper ? '10.0' : '1.0';
  const size = Number(column.dtype.match(/CHAR\((\d+)\)/i)?.[1] || 1);
  const text = column.primary_key ? (upper ? 'Z' : 'A') : 'Ejemplo';
  return `'${text.slice(0, size)}'`;
}
export function sqlExample(kind, table, tables) {
  if (kind === 'demo') {
    const name = uniqueName('products_demo', new Set(tables.map(item => item.name)));
    return `CREATE TABLE ${name} (\n  id INT PRIMARY KEY,\n  name CHAR(40),\n  price FLOAT\n) USING SEQUENTIAL;`;
  }
  if (!table) throw new Error('Importa o crea una tabla para usar este ejemplo.');
  const primary = table.columns.find(column => column.primary_key);
  const value = literal(primary);
  const indexName = indexKind => uniqueName(
    `idx_${table.name}_${primary.name}_${indexKind.toLowerCase()}`,
    new Set(tables.flatMap(item => item.indexes.map(index => index.name)))
  );
  switch (kind) {
    case 'select': return `SELECT * FROM ${table.name};`;
    case 'point': return `SELECT * FROM ${table.name} WHERE ${primary.name} = ${value};`;
    case 'range': return `SELECT * FROM ${table.name}\nWHERE ${primary.name} >= ${value}\n  AND ${primary.name} <= ${literal(primary, true)};`;
    case 'index': return `CREATE INDEX ${indexName('BTREE')}\nON ${table.name}(${primary.name}) USING BTREE;`;
    case 'hash': return `CREATE INDEX ${indexName('HASH')}\nON ${table.name}(${primary.name}) USING HASH;`;
    case 'insert': return `-- Ajusta los valores y usa una clave primaria nueva.\nINSERT INTO ${table.name}\nVALUES (${table.columns.map(column => literal(column)).join(', ')});`;
    case 'delete': return `DELETE FROM ${table.name} WHERE ${primary.name} = ${value};`;
    case 'deleteAll': return `DELETE FROM ${table.name};`;
    case 'drop': return `DROP TABLE ${table.name};`;
    default: return '';
  }
}
