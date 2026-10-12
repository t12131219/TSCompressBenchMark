import {chromium} from '/home/fzg/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url));
const browser=await chromium.launch({headless:true,executablePath:'/home/fzg/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome'});
const receipt={kind:'unaltered-native-viewer-exports',files:[],errors:[]};
try {
 for(const name of ['overview','lanes','object']){
  const page=await browser.newPage({acceptDownloads:true,viewport:{width:1600,height:1000}});
  page.on('pageerror',e=>receipt.errors.push(e.message));
  await page.goto(pathToFileURL(path.join(root,name+'.native.html')).href);
  await page.evaluate(()=>document.fonts.ready);
  for(const theme of ['light','dark']){
   if(await page.locator('html').getAttribute('data-theme')!==theme)await page.locator('#btn-theme').click();
   await page.locator('#btn-export').click();
   const pending=page.waitForEvent('download');
   await page.locator('#export-menu [data-format="svg"]').click();
   const downloaded=await pending;
   const target=path.join(root,name+'.native.'+theme+'.svg');
   await downloaded.saveAs(target);
   const buf=fs.readFileSync(target);
   receipt.files.push({name,theme,file:path.basename(target),bytes:buf.length,sha256:crypto.createHash('sha256').update(buf).digest('hex')});
  }
  await page.close();
 }
}finally{await browser.close();}
receipt.status=receipt.files.length===6&&!receipt.errors.length?'pass':'fail';
fs.writeFileSync(path.join(root,'native-export-receipt.json'),JSON.stringify(receipt,null,2)+'\n');
console.log(receipt.status);
process.exitCode=receipt.status==='pass'?0:1;
