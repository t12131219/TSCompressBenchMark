import { chromium } from '/home/fzg/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath,pathToFileURL} from 'node:url';
const out=path.dirname(fileURLToPath(import.meta.url));
const artifact=path.join(out,'framework.html');
const bytes=fs.readFileSync(artifact);
const receipt={schemaVersion:1,evidenceKind:'automated-browser-reference-presentation',artifact:{path:artifact,sha256:crypto.createHash('sha256').update(bytes).digest('hex'),bytes:bytes.length},policy:'long-form: vertical document scrolling allowed, horizontal overflow forbidden',viewports:[],captures:[],interactions:{},errors:[]};
let browser;
try{
 browser=await chromium.launch({headless:true,executablePath:'/home/fzg/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome'});
 const page=await browser.newPage();
 page.on('pageerror',e=>receipt.errors.push(e.message));
 await page.goto(pathToFileURL(artifact).href);
 await page.evaluate(()=>document.fonts.ready);
 for(const [w,h] of [[1440,900],[1600,1000],[1920,1080],[2048,1320]]){
  await page.setViewportSize({width:w,height:h});
  for(const theme of ['light','dark']){
   if(await page.evaluate(()=>document.body.classList.contains('dark')) !== (theme==='dark'))await page.locator('#theme').click();
   const observation=await page.evaluate(()=>{
    const id=document.body.classList.contains('dark')?'dark':'light';const svg=document.querySelector('#'+id+' svg');
    const texts=[...svg.querySelectorAll('text')];const box=svg.getBoundingClientRect();const scale=box.width/svg.viewBox.baseVal.width;
    const bounds=svg.viewBox.baseVal;const textOverflow=texts.filter(el=>{const b=el.getBBox();return b.x<0||b.y<0||b.x+b.width>bounds.width+.1||b.y+b.height>bounds.height+.1}).map(t=>t.textContent);
    return {innerWidth,innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,nodeCount:svg.querySelectorAll('[data-node-id]').length,edgeCount:svg.querySelectorAll('[data-edge-id]').length,minimumNodeDetailPx:16*scale,textWithinSvg:!textOverflow.length,textOverflow,fontLoaded:document.fonts.check('17px "Noto Sans CJK SC"')};
   });
   const row={width:w,height:h,theme,...observation};row.ok=row.scrollWidth<=w&&row.nodeCount===46&&row.edgeCount===51&&row.textWithinSvg&&row.fontLoaded&&row.minimumNodeDetailPx>=10;
   receipt.viewports.push(row);
   if(w===1440||w===2048){const filename=`reference.browser.${w}x${h}.${theme}.png`;await page.screenshot({path:path.join(out,filename),fullPage:true});receipt.captures.push({file:filename,width:w,height:h,theme,fullPage:true});}
  }
 }
 if(await page.evaluate(()=>document.body.classList.contains('dark')))await page.locator('#theme').click();
 await page.locator('#search').fill('Finalize');
 receipt.interactions.search=await page.locator('#light [data-node-id="finalize"]').evaluate(el=>el.classList.contains('selected'));
 await page.locator('#search').fill('');
 await page.locator('#light [data-node-id="formal"]').click();
 receipt.interactions.nodeDialog=await page.locator('dialog').evaluate(el=>el.open)&& (await page.locator('#dialog-title').innerText()).includes('正式');
 await page.locator('#close').click();
 receipt.interactions.dialogClose=!(await page.locator('dialog').evaluate(el=>el.open));
 await page.locator('#theme').click();
 receipt.interactions.theme=await page.locator('#dark').isVisible()&&!(await page.locator('#light').isVisible());
 receipt.interactions.exportLinks=true;
 for(const id of ['svg-download','png-download']){const href=await page.locator('#'+id).getAttribute('href');receipt.interactions.exportLinks&&=fs.existsSync(path.join(out,href));}
 await page.evaluate(()=>window.scrollTo(0,document.documentElement.scrollHeight));
 receipt.interactions.scrollEnd=await page.locator('#dark [data-node-id="report"]').evaluate(el=>{const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight});
 receipt.status=receipt.viewports.every(r=>r.ok)&&Object.values(receipt.interactions).every(Boolean)&&!receipt.errors.length?'pass':'fail';
}catch(e){receipt.status='fail';receipt.errors.push(e.stack||e.message)}finally{if(browser)await browser.close()}
fs.writeFileSync(path.join(out,'reference-browser-receipt.json'),JSON.stringify(receipt,null,2)+'\n');
console.log(JSON.stringify({status:receipt.status,interactions:receipt.interactions,viewports:receipt.viewports.map(v=>({width:v.width,height:v.height,theme:v.theme,ok:v.ok,overflowX:v.scrollWidth>v.width,textWithinSvg:v.textWithinSvg})),errors:receipt.errors}));
process.exitCode=receipt.status==='pass'?0:1;
