import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const escapeHtml = text => text.replace(/[&<>"']/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[character]);

const source = path.resolve(process.argv[2]);
const values = {
  title: escapeHtml(path.basename(source)),
  base: escapeHtml(pathToFileURL(path.dirname(source) + path.sep).href),
  stylesheet: escapeHtml(new URL('style.css', import.meta.url).href),
  body: fs.readFileSync(process.argv[3], 'utf8'),
};
const template = fs.readFileSync(new URL('page.html', import.meta.url), 'utf8');
process.stdout.write(template.replace(/\{\{(title|base|stylesheet|body)\}\}/g, (_, name) => values[name]));
