import {chromium} from '/home/fzg/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs';
import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url)),artifact=path.join(root,'framework.html');
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const receipt={kind:'independent-publication-viewer',artifact:{sha256:hash(fs.readFileSync(artifact)),bytes:fs.statSync(artifact).size},viewports:[],static:[],interactions:{},exports:[],errors:[]};
const browser=await chromium.launch({headless:true,executablePath:'/home/fzg/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome'});
try{
 const page=await browser.newPage({acceptDownloads:true});page.on('pageerror',e=>receipt.errors.push(e.message));
 await page.goto(pathToFileURL(artifact).href);await page.evaluate(()=>document.fonts.ready);
 for(const [width,height] of [[1440,900],[1600,1000],[1920,1080],[2048,1320]]){
  await page.setViewportSize({width,height});
  for(const view of ['overview','lanes','object']){
   await page.locator('[data-view="'+view+'"]').click();
   for(const theme of ['light','dark']){
    if(await page.locator('html').getAttribute('data-theme')!==theme)await page.locator('#theme').click();
    const metrics=await page.evaluate(()=>{
     const svg=[...document.querySelectorAll('.figure')].find(x=>!x.hidden).querySelector('svg');
     const scale=svg.getBoundingClientRect().width/svg.viewBox.baseVal.width;
     const nodes=[...svg.querySelectorAll('[data-node-id]')];
     const textIssues=[];
     for(const n of nodes){const rect=n.querySelector('rect').getBBox();for(const t of n.querySelectorAll(':scope > text')){const b=t.getBBox();if(b.x<rect.x+7||b.x+b.width>rect.x+rect.width-7||b.y<rect.y+4||b.y+b.height>rect.y+rect.height-4)textIssues.push({node:n.dataset.nodeId,text:t.textContent,bounds:{x:b.x,y:b.y,w:b.width,h:b.height},rect:{x:rect.x,y:rect.y,w:rect.width,h:rect.height}})}}
     for(const n of nodes){const boxes=[...n.querySelectorAll(':scope > text')].map(t=>({text:t.textContent,b:t.getBBox()}));for(let i=1;i<boxes.length;i++){const a=boxes[i-1],b=boxes[i];if(a.b.y+a.b.height>b.b.y+.5)textIssues.push({node:n.dataset.nodeId,overlapping:[a.text,b.text]})}}
     return {width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,nodeCount:nodes.length,minimumContextPx:Math.min(...nodes.flatMap(n=>[...n.querySelectorAll(':scope > text')].slice(0,2).map(t=>Number(t.getAttribute('font-size'))*scale))),textIssues};
    });
    receipt.viewports.push({view,theme,...metrics,ok:metrics.scrollWidth<=width&&metrics.scrollHeight<=height&&metrics.minimumContextPx>=8&&metrics.textIssues.length===0});
    if(width===1440||width===2048)await page.screenshot({path:path.join(root,'publication.'+view+'.'+width+'x'+height+'.'+theme+'.png')});
   }
  }
 }
 await page.setViewportSize({width:1600,height:1000});await page.locator('[data-view="overview"]').click();
 await page.locator('#overview [data-node-id="logical_inputs"]').click();
 receipt.interactions.nodeDetails=await page.locator('#detail').evaluate(n=>n.open)&&await page.locator('#detail-sources li').count()===3;
 await page.locator('#close-detail').click();
 await page.locator('#search').fill('execute_pipeline_comparison');await page.locator('#matches button').first().click();
 receipt.interactions.crossViewSearch=(await page.locator('#detail-title').textContent())==='execute_pipeline_comparison'&&(await page.locator('#lanes').isVisible());
 await page.locator('#close-detail').click();await page.locator('#search').fill('');
 await page.locator('#lanes [data-node-id="legacy_execute"]').focus();await page.keyboard.press('Enter');
 receipt.interactions.keyboard=await page.locator('#detail').evaluate(n=>n.open);await page.keyboard.press('Escape');
 for(const view of ['overview','lanes','object']){
  await page.locator('[data-view="'+view+'"]').click();
  for(const theme of ['light','dark']){
   if(await page.locator('html').getAttribute('data-theme')!==theme)await page.locator('#theme').click();
   for(const format of ['svg','png']){
    const pending=page.waitForEvent('download');await page.locator('#'+format+'-export').click();const download=await pending;
    const target=path.join(root,(view==='overview'?'framework':view)+'.'+theme+'.'+format);
    // Keep independently generated SVG bytes; capture dynamic SVG as a separate export.
    const saveTo=format==='svg'?path.join(root,view+'.viewer-export.'+theme+'.svg'):target;
    await download.saveAs(saveTo);const b=fs.readFileSync(saveTo);
    receipt.exports.push({view,theme,format,file:path.basename(saveTo),bytes:b.length,sha256:hash(b)});
   }
  }
 }
 for(const view of ['overview','lanes','object'])for(const theme of ['light','dark']){
  const file=path.join(root,(view==='overview'?'framework':view)+'.'+theme+'.svg');
  await page.goto(pathToFileURL(file).href);await page.evaluate(()=>document.fonts.ready);
  const result=await page.evaluate(()=>{const s=document.documentElement,v=s.viewBox.baseVal;const outside=[...s.querySelectorAll('text')].filter(t=>{const b=t.getBBox();return b.x<0||b.y<0||b.x+b.width>v.width+.1||b.y+b.height>v.height+.1}).map(t=>t.textContent);return {theme:s.dataset.theme,nodes:s.querySelectorAll('[data-node-id]').length,outside}});
  receipt.static.push({view,theme,...result,sha256:hash(fs.readFileSync(file)),ok:!result.outside.length&&result.theme===theme});
 }
}catch(e){receipt.errors.push(e.stack)}finally{await browser.close()}
receipt.status=receipt.viewports.length===24&&receipt.viewports.every(c=>c.ok)&&receipt.static.length===6&&receipt.static.every(c=>c.ok)&&Object.values(receipt.interactions).every(Boolean)&&receipt.exports.length===12&&!receipt.errors.length?'pass':'fail';
fs.writeFileSync(path.join(root,'publication-browser-receipt.json'),JSON.stringify(receipt,null,2)+'\n');
console.log(JSON.stringify({status:receipt.status,failed:receipt.viewports.filter(v=>!v.ok),interactions:receipt.interactions,errors:receipt.errors}));process.exitCode=receipt.status==='pass'?0:1;
