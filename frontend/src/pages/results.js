import {jobs} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {chart} from '../components/common/chart.js';
import {table} from '../components/common/table.js';
import {status} from '../components/common/status.js';
import {JobStatus} from '../constants/enums.js';
import {esc,fmt,date,notify} from '../utils/dom.js';
export async function results(id){
 workspace.jobs=await jobs.list();const j=id?await jobs.get(id):(workspace.jobs.find(j=>j.id===workspace.selectedJob)||workspace.jobs[0]);
 if(j&&!workspace.jobs.some(x=>x.id===j.id))workspace.jobs.push(j);
 if(!j)return heading('04 / REVIEW','结果复核','尚无分析结果。')+'<div class="empty">先到分析工作台，选择批次并提交一次计算。<a href="#/workbench">前往工作台 ↗</a></div>';
 workspace.selectedJob=j.id;const r=j.result||{};
 const canWrite=session.user.role!=='viewer',mine=session.user.role==='admin'||session.user.id===j.created_by;
 const sharedInfo=(j.run_id?'<span class="shared">共享计算 #'+j.run_id+'</span>':'')+(j.shared>1?'<span class="shared">'+j.shared+' 个申请合用本次计算</span>':'')+(j.recoveries>0?'<span class="recovered">中断后恢复 ×'+j.recoveries+'</span>':'');
 const selector='<div class="result-selector"><label>分析记录<select id="select-job">'+workspace.jobs.map(x=>'<option value="'+x.id+'" '+(x.id===j.id?'selected':'')+'>'+esc(x.name)+' · '+esc(JobStatus[x.status]||x.status)+'</option>').join('')+'</select></label>'+status(j.status)+sharedInfo+'<span>'+date(j.created_at)+'</span><span class="approval">'+(j.approved?'已获业务批准':'待负责人复核')+'</span></div>';
 const completed='<section class="result-lead"><p class="eyebrow">COMPUTED FINDING</p><h2>'+esc(r.summary)+'</h2><div class="metrics">'+(r.metrics||[]).map(m=>'<div><span>'+esc(m.label)+'</span><strong>'+esc(fmt(m.value))+'<small>'+esc(m.unit||'')+'</small></strong></div>').join('')+'</div></section><section class="panel">'+chart(r.chart)+'</section><div class="two-columns"><section class="panel"><div class="section-title"><h2>业务解释</h2><span>由计算结果生成</span></div><ol class="questions">'+(r.findings||[]).map(v=>'<li>'+esc(v)+'</li>').join('')+'</ol>'+(r.warnings||[]).map(v=>'<p class="warning">'+esc(v)+'</p>').join('')+'</section><section class="method-sheet compact"><p class="eyebrow">REPRODUCIBILITY</p><h3>计算口径与参数</h3><p>'+esc(r.method)+'</p><pre>'+esc(JSON.stringify(j.params,null,2))+'</pre>'+(j.recoveries>0?'<p class="hint">该结果在计算进程中断后由接管进程恢复完成（恢复 '+j.recoveries+' 次，第 '+j.attempts+' 次执行）。</p>':'')+(session.user.role==='admin'&&!j.approved?'<button class="primary" id="approve-job">批准此业务结论</button>':'')+'<p class="hint">仅批准结果可进入定时分发档案。</p></section></div><section class="panel"><div class="section-title"><h2>结果明细</h2><span>'+(r.table?.rows?.length||0)+' 行</span></div>'+table(r.table?.columns||[],r.table?.rows||[])+'</section>';
 const failed='<section class="panel empty">计算失败：'+esc(j.error)+'。重试不会重复创建申请，沿用本次申请重新排队。'+(canWrite?'<button class="button small" id="retry-job">重试计算 ↻</button>':'')+'<a href="#/workbench">返回工作台 ↗</a></section>';
 const withdrawn='<section class="panel empty">本次申请已撤销，未接收计算结果；合用本次计算的其他申请不受影响，仍可各自获得结果。</section>';
 const pending='<section class="panel empty">'+(j.status==='waiting'?'正在等待共享计算：同批样本与相同参数的复核申请合用一次计算，各自保留任务名称、批准与分发。':'计算运行中，完成后各申请各自获得结果。')+(mine?'<button class="button small" id="withdraw-job">撤销本次申请</button>':'')+'<a href="#/workbench">返回工作台 ↗</a></section>';
 const body=j.status==='completed'?completed:(j.status==='failed'?failed:(j.status==='withdrawn'?withdrawn:pending));
 return heading('04 / REVIEW','结果复核与业务解释',j.name,'<button class="button" id="refresh-results">刷新结果 ↻</button>')+selector+body;
}
export function bindResults(refresh){
 document.querySelector('#refresh-results')?.addEventListener('click',refresh);
 document.querySelector('#select-job')?.addEventListener('change',e=>{workspace.selectedJob=Number(e.target.value);location.hash='#/results/'+e.target.value;});
 document.querySelector('#approve-job')?.addEventListener('click',async()=>{try{await jobs.approve(workspace.selectedJob);notify('已批准，可创建分发计划');await refresh();}catch(e){notify(e.message,true);}});
 document.querySelector('#withdraw-job')?.addEventListener('click',async()=>{try{await jobs.withdraw(workspace.selectedJob);notify('已撤销本次申请，其他申请不受影响');await refresh();}catch(e){notify(e.message,true);}});
 document.querySelector('#retry-job')?.addEventListener('click',async()=>{try{await jobs.retry(workspace.selectedJob);notify('已重新排队，等待共享计算');await refresh();}catch(e){notify(e.message,true);}});
}
