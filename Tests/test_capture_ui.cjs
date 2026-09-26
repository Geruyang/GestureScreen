/* UI logic tests with a minimal DOM. This is not a real-browser acceptance test. */
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const elements = new Map();
function element() {
  return {value:'', checked:false, disabled:false, hidden:false, children:[],
    classList:{toggle(){}}, append(...rows){this.children.push(...rows);},
    replaceChildren(...rows){this.children=rows;}, addEventListener(){},
    getAttribute(name){return this[name];}, scrollIntoView(){}};
}
const context = vm.createContext({console, Date, Math, Number, Object, Error,
  document:{getElementById(id){if(!elements.has(id)) elements.set(id, element()); return elements.get(id);}, createElement:element},
  fetch:()=>new Promise(()=>{}), setInterval(){}});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../HostTools/web/app.js'), 'utf8'), context);
function run(code){vm.runInContext(code,context);}
run(`globalThis.sample={record_id:'a'.repeat(32),session:'b'.repeat(32),split:'train',device_id:'board',frame_id:1,label:PENDING,excluded:true}; selectFrame(sample);`);
assert.equal(elements.get('save-annotation').disabled,true);
run(`renderGallery([{...sample,label:'V_SIGN',excluded:false}],1);`);
assert.equal(elements.get('review-label').value,'V_SIGN','Post-clip label must refresh the open review');
assert.equal(elements.get('save-annotation').disabled,false);
run(`selectFrame({...sample,label:'PALM',training_duplicate_of:'c'.repeat(32),excluded:true});`);
assert.equal(elements.get('excluded').disabled,true,'Duplicate exclusion must be locked');
assert.equal(elements.get('review-label').disabled,false,'A duplicate label can still be corrected');
run(`selectFrame({...sample,label:'PALM',excluded:false}); document.getElementById('review-label').value='FIST'; renderGallery([{...sample,label:'PALM',excluded:false}],1);`);
assert.equal(elements.get('review-label').value,'FIST','Unchanged polling must preserve unsaved edits');
console.log('PASS: 4 capture UI logic groups (mock DOM, no browser)');
