import { chromium } from '/home/fzg/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';
const out=path.dirname(fileURLToPath(import.meta.url));
const model=JSON.parse(fs.readFileSync(path.join(out,'semantic-model.json'),'utf8'));
const fingerprint=file=>crypto.createHash('sha256').update(fs.readFileSync(path.join(out,file))).digest('hex');
const receipt={artifact:'framework.html',sha256:fingerprint('framework.html'),policy:'Single five-layer long figure; vertical scrolling allowed, no horizontal overflow',viewports:[],interactions:{},errors:[]};
let browser;
try {
  browser=await chromium.launch({headless:true,executablePath:'/home/fzg/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome'});
  const page=await browser.newPage();
  page.on('pageerror',e=>receipt.errors.push(e.message));
  await page.goto(pathToFileURL(path.join(out,'framework.html')).href);
  await page.evaluate(()=>document.fonts.ready);
  for(const [width,height] of [[1440,900],[1600,1000],[1920,1080],[2048,1320]]) {
    await page.setViewportSize({width,height});
    for(const theme of ['light','dark']) {
      if(await page.evaluate(()=>document.body.classList.contains('dark'))!==(theme==='dark'))await page.locator('#theme').click();
      await page.evaluate(()=>window.scrollTo(0,0));
      const result=await page.evaluate(()=>{
        const root=document.querySelector(document.body.classList.contains('dark')?'#dark':'#light'),svg=root.querySelector('svg'),vb=svg.viewBox.baseVal;
        const overflow=[],nodeOverflow=[],cardOverflow=[];
        for(const t of svg.querySelectorAll('text')) {
          const b=t.getBBox();if(b.x<-.2||b.y<-.2||b.x+b.width>vb.width+.2||b.y+b.height>vb.height+.2)overflow.push(t.textContent);
        }
        for(const node of svg.querySelectorAll('[data-node-id]')) {
          const shape=node.querySelector('.node-shape').getBBox();
          for(const t of node.querySelectorAll('text')) {
            const b=t.getBBox();if(b.x<shape.x-.2||b.y<shape.y-.2||b.x+b.width>shape.x+shape.width+.2||b.y+b.height>shape.y+shape.height+.2)nodeOverflow.push({node:node.dataset.nodeId,text:t.textContent});
          }
        }
        for(const card of svg.querySelectorAll('[data-annotation]')) {
          const shape=card.querySelector('rect').getBBox();
          for(const t of card.querySelectorAll('text')) {
            const b=t.getBBox();if(b.x<shape.x||b.y<shape.y||b.x+b.width>shape.x+shape.width||b.y+b.height>shape.y+shape.height)cardOverflow.push({card:card.dataset.annotation,text:t.textContent});
          }
        }
        const scale=svg.getBoundingClientRect().width/vb.width;
        return {scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,nodeCount:svg.querySelectorAll('[data-node-id]').length,edgeCount:svg.querySelectorAll('[data-edge-id]').length,layerCount:svg.querySelectorAll('[data-stage]').length,minimumDetailPx:17*scale,fontLoaded:document.fonts.check('17px "Noto Sans CJK SC"'),overflow,nodeOverflow,cardOverflow};
      });
      result.ok=result.scrollWidth<=width&&result.nodeCount===model.nodes.length&&result.edgeCount===model.edges.length&&result.layerCount===5&&result.fontLoaded&&result.minimumDetailPx>=10&&![...result.overflow,...result.nodeOverflow,...result.cardOverflow].length;
      receipt.viewports.push({width,height,theme,...result});
      if(width===1440||width===2048)await page.screenshot({path:path.join(out,`browser.${width}x${height}.${theme}.png`),fullPage:true});
    }
  }
  if(await page.evaluate(()=>document.body.classList.contains('dark')))await page.locator('#theme').click();
  await page.locator('#search').fill('Finalize');
  receipt.interactions.search=await page.locator('#light [data-node-id="finalize"]').evaluate(el=>el.classList.contains('selected'));
  await page.locator('#search').fill('pipeline_runner.py');
  receipt.interactions.sourceSearch=await page.locator('#light [data-node-id="p2_execute"]').evaluate(el=>el.classList.contains('selected'));
  await page.locator('#search').fill('');
  await page.locator('#light [data-node-id="p2_execute"]').click();
  receipt.interactions.nodeDialog=await page.locator('dialog').evaluate(el=>el.open)&&(await page.locator('#source-list').innerText()).includes('execute_pipeline_comparison');
  await page.locator('#close').click();
  receipt.interactions.closeDialog=!(await page.locator('dialog').evaluate(el=>el.open));
  // Keyboard access to source evidence.
  await page.locator('#light [data-node-id="development_pilot"]').focus();
  await page.keyboard.press('Enter');
  receipt.interactions.keyboardDialog=await page.locator('dialog').evaluate(el=>el.open)&&(await page.locator('#source-list').innerText()).includes('pilot_comparison');
  await page.keyboard.press('Escape');
  receipt.interactions.escapeClose=!(await page.locator('dialog').evaluate(el=>el.open));
  await page.locator('[data-jump="stats"]').click();
  await page.waitForFunction(()=>{const r=document.querySelector('#light [data-stage="stats"]').getBoundingClientRect();return r.top>=0&&r.top<innerHeight/2&&r.bottom<=innerHeight});
  receipt.interactions.layerJump=true;
  await page.locator('#theme').click();
  receipt.interactions.theme=await page.locator('#dark').isVisible()&&!(await page.locator('#light').isVisible());
  receipt.interactions.exports=true;
  for(const id of ['svg-download','png-download']) {
    const href=await page.locator('#'+id).getAttribute('href');
    receipt.interactions.exports&&=href.includes('.dark.')&&fs.existsSync(path.join(out,href));
  }
  await page.evaluate(()=>window.scrollTo(0,document.documentElement.scrollHeight));
  receipt.interactions.bottomReachable=await page.locator('#dark [data-node-id="scope_acceptance"]').evaluate(el=>{const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight});
  // The standalone SVG exports must also render, independent of the HTML wrapper.
  receipt.interactions.standaloneSvg=true;
  for(const theme of ['light','dark']) {
    await page.goto(pathToFileURL(path.join(out,`framework.${theme}.svg`)).href);
    receipt.interactions.standaloneSvg&&=await page.locator('svg [data-node-id]').count()===model.nodes.length;
  }
} catch(e) {receipt.errors.push(e.stack||e.message)} finally {if(browser)await browser.close()}
receipt.status=receipt.viewports.length===8&&receipt.viewports.every(v=>v.ok)&&Object.values(receipt.interactions).every(Boolean)&&!receipt.errors.length?'pass':'fail';
fs.writeFileSync(path.join(out,'browser-check.json'),JSON.stringify(receipt,null,2)+'\n');
console.log(JSON.stringify(receipt,null,2));
process.exitCode=receipt.status==='pass'?0:1;
