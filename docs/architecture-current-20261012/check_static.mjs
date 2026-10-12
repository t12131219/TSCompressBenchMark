import { chromium } from '/home/fzg/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url));
const browser=await chromium.launch({headless:true,executablePath:'/home/fzg/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome'});
const receipt={kind:'standalone-svg-browser',checks:[]};
try {
 const page=await browser.newPage({viewport:{width:1080,height:625}});
 for(const theme of ['light','dark']) {
  const file=path.join(root,'framework.'+theme+'.svg');
  await page.goto(pathToFileURL(file).href);
  await page.evaluate(()=>document.fonts.ready);
  const measured=await page.evaluate(()=>{
   const svg=document.documentElement;
   const bounds=svg.viewBox.baseVal;
   const overflow=[...svg.querySelectorAll('text')].filter(t=>{const b=t.getBBox();return b.x<0||b.y<0||b.x+b.width>bounds.width+.1||b.y+b.height>bounds.height+.1}).map(t=>t.textContent);
   return {theme:svg.getAttribute('data-theme'),background:getComputedStyle(svg).getPropertyValue('--bg').trim(),nodeCount:svg.querySelectorAll('[data-node-id]').length,textWithinViewBox:!overflow.length,overflow};
  });
  const bytes=fs.readFileSync(file);
  const screenshot=path.join(root,'review-static.'+theme+'.png');
  await page.screenshot({path:screenshot});
  receipt.checks.push({...measured,path:file,sha256:crypto.createHash('sha256').update(bytes).digest('hex'),bytes:bytes.length,screenshot,ok:measured.theme===theme&&measured.nodeCount===12&&measured.textWithinViewBox});
 }
} finally {await browser.close();}
receipt.status=receipt.checks.length===2&&receipt.checks.every(c=>c.ok)?'pass':'fail';
fs.writeFileSync(path.join(root,'static-svg-receipt.json'),JSON.stringify(receipt,null,2)+'\n');
console.log(JSON.stringify(receipt));
process.exitCode=receipt.status==='pass'?0:1;
