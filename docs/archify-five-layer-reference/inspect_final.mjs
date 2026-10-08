import { chromium } from '/home/fzg/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs';
import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';import {fileURLToPath,pathToFileURL} from 'node:url';
const out=path.dirname(fileURLToPath(import.meta.url));
const binding=f=>{const b=fs.readFileSync(path.join(out,f));return{file:f,sha256:crypto.createHash('sha256').update(b).digest('hex'),bytes:b.length}};
const browser=await chromium.launch({headless:true,executablePath:'/home/fzg/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome'});
try{
 const p=await browser.newPage({viewport:{width:2180,height:1400}});
 await p.goto(pathToFileURL(path.join(out,'framework.html')).href);await p.evaluate(()=>document.fonts.ready);
 const structure=await p.evaluate(()=>{
  const native=model;const issues=[];const themes=[];
  const overlaps=(a,b)=>a.x<b.x+b.width&&a.x+a.width>b.x&&a.y<b.y+b.height&&a.y+a.height>b.y;
  const segHit=(a,b,r)=>a.x===b.x?r.x<a.x&&a.x<r.x+r.width&&Math.max(Math.min(a.y,b.y),r.y)<Math.min(Math.max(a.y,b.y),r.y+r.height):r.y<a.y&&a.y<r.y+r.height&&Math.max(Math.min(a.x,b.x),r.x)<Math.min(Math.max(a.x,b.x),r.x+r.width);
  for(const theme of ['light','dark']){
   const section=document.querySelector('#'+theme);section.hidden=false;const svg=section.querySelector('svg');
   const ns=[...svg.querySelectorAll('[data-node-id]')],es=[...svg.querySelectorAll('[data-edge-id]')];
   const ni=ns.map(e=>e.dataset.nodeId).sort(),ei=es.map(e=>e.dataset.edgeId).sort();
   const sameNodes=JSON.stringify(ni)===JSON.stringify(native.nodes.map(n=>n.id).sort());
   const sameEdges=JSON.stringify(ei)===JSON.stringify(native.edges.map(e=>e.id).sort());
   const sameDirectedEdges=es.every(el=>{const e=native.edges.find(e=>e.id===el.dataset.edgeId);return e&&e.source===el.dataset.from&&e.target===el.dataset.to});
   for(const node of ns){const shape=node.querySelector('rect,polygon'),b=shape.getBBox();for(const tx of node.querySelectorAll('text')){const t=tx.getBBox();if(t.x<b.x-1||t.x+t.width>b.x+b.width+1||t.y<b.y-1||t.y+t.height>b.y+b.height+1)issues.push({theme,kind:'node-text-outside-box',node:node.dataset.nodeId,text:tx.textContent});}}
   const labels=[...svg.querySelectorAll('[data-edge-label]')];
   for(const l of labels){const b=l.getBBox();for(const el of es){if(el.dataset.edgeId===l.dataset.edgeLabel)continue;const pts=[...el.points];for(let i=1;i<pts.length;i++)if(segHit(pts[i-1],pts[i],b))issues.push({theme,kind:'label-masks-unrelated-route',label:l.dataset.edgeLabel,edge:el.dataset.edgeId});}}
   for(let i=0;i<labels.length;i++)for(let j=i+1;j<labels.length;j++)if(overlaps(labels[i].getBBox(),labels[j].getBBox()))issues.push({theme,kind:'edge-label-overlap',labels:[labels[i].dataset.edgeLabel,labels[j].dataset.edgeLabel]});
   themes.push({theme,sameNodes,sameEdges,sameDirectedEdges,annotationsAreNonTopology:[...svg.querySelectorAll('[data-annotation]')].every(e=>!e.querySelector('[data-node-id],[data-edge-id]'))});
   section.hidden=theme==='dark';
  }
  return {themes,issues,status:!issues.length&&themes.every(t=>t.sameNodes&&t.sameEdges&&t.sameDirectedEdges&&t.annotationsAreNonTopology)?'pass':'fail'};
 });
 const captures=[];
 for(const theme of ['light','dark']){
  if(await p.evaluate(()=>document.body.classList.contains('dark'))!==(theme==='dark'))await p.locator('#theme').click();
  for(const phase of ['data','plan','exec','measure','stats']){const f=`reference.browser.phase.${phase}.${theme}.png`;await p.locator('#'+theme+' [data-stage="'+phase+'"]').screenshot({path:path.join(out,f)});captures.push(binding(f));}
 }
 const r={evidenceKind:'derived-presentation-rendered-structure',artifact:binding('framework.html'),...structure,stageCaptures:captures};fs.writeFileSync(path.join(out,'reference-dom-check.json'),JSON.stringify(r,null,2)+'\n');console.log(JSON.stringify({reference:r.status,issues:r.issues}));
 const native={evidenceKind:'supplementary-native-browser-measurements',artifact:binding('native-final.html'),doesNotOverrideCanonicalReceipt:true,viewports:[]};
 await p.goto(pathToFileURL(path.join(out,'native-final.html')).href);await p.evaluate(()=>document.fonts.ready);
 for(const [w,h] of [[1440,900],[1600,1000],[1920,1080],[2048,1320]]){await p.setViewportSize({width:w,height:h});for(const theme of ['light','dark']){if(await p.evaluate(()=>document.documentElement.dataset.theme)!==theme)await p.locator('#btn-theme').click();native.viewports.push({width:w,height:h,theme,...await p.evaluate(()=>({scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,overflowX:document.documentElement.scrollWidth>innerWidth,overflowY:document.documentElement.scrollHeight>innerHeight}))});}}
 native.status=native.viewports.every(v=>!v.overflowX&&!v.overflowY)?'pass':'fail';fs.writeFileSync(path.join(out,'native-browser-supplement.json'),JSON.stringify(native,null,2)+'\n');console.log(JSON.stringify({native:native.status,measurements:native.viewports.length}));
}finally{await browser.close()}
