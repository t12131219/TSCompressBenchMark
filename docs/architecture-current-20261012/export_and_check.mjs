import { chromium } from '/home/fzg/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url));
const artifact=path.join(root,'framework.html');
const data=fs.readFileSync(artifact);
const receipt={artifact:{sha256:crypto.createHash('sha256').update(data).digest('hex'),bytes:data.length},kind:'native-viewer-export-and-interaction',exports:[],errors:[],interactions:{}};
const browser=await chromium.launch({headless:true,executablePath:'/home/fzg/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome'});
try {
 const page=await browser.newPage({acceptDownloads:true,viewport:{width:1600,height:1000}});
 page.on('pageerror',e=>receipt.errors.push(e.message));
 await page.goto(pathToFileURL(artifact).href);
 await page.evaluate(()=>document.fonts.ready);
 for(const theme of ['light','dark']) {
  if(await page.locator('html').getAttribute('data-theme')!==theme)await page.locator('#btn-theme').click();
  for(const format of ['svg','png']) {
   await page.locator('#btn-export').click();
   const downloading=page.waitForEvent('download');
   await page.locator('#export-menu [data-format="'+format+'"]').click();
   const download=await downloading;
   const target=path.join(root,'framework.'+theme+'.'+format);
   await download.saveAs(target);
   if(format==='svg') {
    const native=fs.readFileSync(target,'utf8');
    fs.writeFileSync(path.join(root,'framework.svg'),native);
    fs.writeFileSync(target,native.replace('<svg ', '<svg data-theme=\"'+theme+'\" '));
   }
   const bytes=fs.readFileSync(target);
   receipt.exports.push({theme,format,path:target,bytes:bytes.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex'),method:format==='svg'?'Native viewer SVG with explicit root data-theme; adaptive native saved as framework.svg':'Native viewer export button'});
  }
 }
 await page.locator('#btn-theme').click();
 const node=page.locator('svg [data-node-id="development_pilot"]');
 if(await node.count()) {
  await node.click();
  receipt.interactions.nodeFocus=await page.evaluate(()=>!!document.querySelector('svg[data-focus-active]'));
  await page.keyboard.press('Escape');
 }
 receipt.interactions.theme=(await page.locator('html').getAttribute('data-theme'))==='light';
 receipt.status=receipt.errors.length===0&&receipt.exports.length===4&&Object.values(receipt.interactions).every(Boolean)?'pass':'fail';
} catch(error) {receipt.errors.push(error.stack);receipt.status='fail';}
finally {await browser.close();}
fs.writeFileSync(path.join(root,'export-receipt.json'),JSON.stringify(receipt,null,2)+'\n');
console.log(JSON.stringify(receipt));
process.exitCode=receipt.status==='pass'?0:1;
