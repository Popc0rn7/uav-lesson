// Execute the real page script with delayed image responses: all visible input
// fields must wait for both images, and a pending step must clear old actions.
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const elements=new Map(), pending=[];
function element(id='') {return {id,textContent:'old',src:'old',hidden:true,append(){},removeAttribute(){this.src=''},replaceWith(other){elements.set(this.id,other)}}}
const document={getElementById(id){if(!elements.has(id))elements.set(id,element(id));return elements.get(id)},createElement(){return element()},documentElement:{requestFullscreen(){}},fullscreenElement:null};
let data={run_id:'run',control:{mode:'infer'},task:{control:{}},observation:{step:1,estimated_world_ned:[1,2,3],quaternion_xyzw:[0,0,0,1],prompt_preview:'new'},inference:{step:1,prompt:'actual',action:{fwd:2,down:0,yaw:0}},report:{}};
class Image {set src(value){this.url=value;pending.push(this)} replaceWith(other){elements.set(this.id,other)} removeAttribute(){this.url=''}}
const context=vm.createContext({document,Image,fetch:async()=>({ok:true,json:async()=>data}),setTimeout(){},console});
const html=fs.readFileSync(require('node:path').join(__dirname,'../webui.html'),'utf8');
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 await flush();assert.equal(pending.length,2);assert.equal(document.getElementById('prompt').textContent,'old');
 pending[0].onload();await flush();assert.equal(document.getElementById('prompt').textContent,'old');
 pending[1].onload();await flush();assert.equal(document.getElementById('prompt').textContent,'actual');
 assert.match(elements.get('front').url,/step=1$/);assert.match(elements.get('down').url,/step=1$/);
 data={...data,observation:{...data.observation,step:2,prompt_preview:'pending'},inference:{}};
 vm.runInContext('refresh()',context);await flush();assert.equal(document.getElementById('prompt').textContent,'actual');
 pending[2].onload();pending[3].onload();await flush();
 assert.equal(document.getElementById('prompt').textContent,'pending');assert.equal(document.getElementById('fwd').textContent,'—');
 assert.match(elements.get('front').url,/step=2$/);console.log('WebUI delayed image consistency passed');
})().catch(error=>{console.error(error);process.exitCode=1});
