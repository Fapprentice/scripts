let state = null;
let focusStatusPill = null;
let allApps = [];
let usableApps = [];
let activePage = 'dashboard';
let sessionToken = null;
let sessionClaimPromise = null;
let heatmapMonthOffset = 0;
let _lastFilePickTs = 0;  // guard against render() destroying the file input while picker is open
const $ = (s, ctx) => (ctx||document).querySelector(s);
const $$ = (s, ctx) => [...(ctx||document).querySelectorAll(s)];
const pageTitles = {
  dashboard:['总览','今日专注、任务完成度与前台时间。'],
  review:['复盘','退出记录、事件流与每日归档。'],
  settings:['设置','目标、生成参数、休息与退出。']
};
const runNames = {generate:'生成任务', evaluate:'AI 验收'};
// ---- motion & a11y helpers (JS wiring for CSS classes provided in app.css) ----
const reducedMotionQuery = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
function prefersReducedMotion(){ return !!(reducedMotionQuery && reducedMotionQuery.matches); }
function scrollIntoViewSafe(el, opts={}){
  if(!el) return;
  el.scrollIntoView({behavior: prefersReducedMotion() ? 'auto' : 'smooth', ...opts});
}
// ---- theme (light / dark): data-theme on <html>, persisted in localStorage ----
const THEME_KEY = 'taskverge-theme';
function currentTheme(){ return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'; }
function applyTheme(theme){
  document.documentElement.dataset.theme = theme;
  try{ localStorage.setItem(THEME_KEY, theme); }catch(_){}
  const btn = document.getElementById('themeToggle');
  if(btn) btn.setAttribute('aria-pressed', String(theme === 'dark'));
}
function initTheme(){
  let saved = null;
  try{ saved = localStorage.getItem(THEME_KEY); }catch(_){}
  const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  applyTheme(saved || (prefersDark ? 'dark' : 'light'));
}
initTheme();
document.getElementById('themeToggle')?.addEventListener('click', ()=>{
  applyTheme(currentTheme() === 'dark' ? 'light' : 'dark');
});
let _pageSwitchGen = 0, _pageSwitchTimer = null;
function switchPage(page){
  if(page===activePage) return;
  const next = document.getElementById(page);
  if(!next) return;
  const old = document.querySelector('.page.active');
  const gen = ++_pageSwitchGen;
  const swap = () => {
    if(old) old.classList.remove('active','page-leaving');
    $$('.page').forEach(x=>x.classList.remove('active'));
    next.classList.add('active');               // CSS pageIn plays on .page.active
  };
  const finish = () => {
    if(gen !== _pageSwitchGen) return;          // superseded by a newer switch
    if(_pageSwitchTimer){ clearTimeout(_pageSwitchTimer); _pageSwitchTimer=null; }
    setPage(page);
    activePage = page;
    document.body.classList.remove('focus-active');
    if(page==='dashboard') refreshLive();
  };
  if(!old || old===next || prefersReducedMotion()){ swap(); finish(); return; }
  if(document.startViewTransition){
    // View Transitions API: native crossfade (progressive enhancement over the class fallback)
    const vt = document.startViewTransition(swap);
    vt.finished.then(finish).catch(finish);
    return;
  }
  old.classList.add('page-leaving');            // CSS pageOut animation (fallback)
  const onEnd = e => { if(e && e.target!==old) return; old.removeEventListener('animationend', onEnd); swap(); finish(); };
  old.addEventListener('animationend', onEnd);
  _pageSwitchTimer = setTimeout(()=>{ swap(); finish(); }, 180); // fallback if animationend never fires
}
// ---- unified modal base: role/aria + initial focus + Esc + focus trap + .modal-leaving exit ----
const _openModals = new Set();
let _lastFocusBeforeModal = null;
function modalFocusables(modal){
  return [...modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
    .filter(el => !el.disabled && el.offsetParent !== null);
}
function setBackgroundInert(on){
  const shell = document.querySelector('.shell');
  if(!shell) return;
  if('inert' in shell) shell.inert = on;
  else if(on) shell.setAttribute('aria-hidden','true');
  else shell.removeAttribute('aria-hidden');
}
function openModal(modal){
  if(!modal || _openModals.has(modal)) return;
  if(!_openModals.size && !modal.closest('.shell')){ _lastFocusBeforeModal = document.activeElement; setBackgroundInert(true); }
  _openModals.add(modal);
  modal.hidden = false;
  modal.style.display = 'flex';
  modal.classList.remove('modal-leaving');
  document.body.classList.add('modal-open');
  modal.setAttribute('role','dialog');
  modal.setAttribute('aria-modal','true');
  const titleEl = modal.querySelector('.modal-title') || modal.querySelector('h2') || modal.querySelector('h3');
  if(titleEl){
    if(!titleEl.id) titleEl.id = 'modal-title-' + Math.random().toString(36).slice(2,8);
    modal.setAttribute('aria-labelledby', titleEl.id);
  }
  const first = modalFocusables(modal)[0];
  if(first) first.focus();
}
function closeModal(modal){
  if(!modal || !_openModals.has(modal)) return;
  _openModals.delete(modal);
  if(modal.dataset.closing) return;
  modal.dataset.closing = '1';
  const done = () => {
    delete modal.dataset.closing;
    modal.classList.remove('modal-leaving');
    modal.hidden = true;
    modal.style.display = 'none';
    if(!_openModals.size){
      document.body.classList.remove('modal-open');
      setBackgroundInert(false);
      if(_lastFocusBeforeModal && _lastFocusBeforeModal.focus) _lastFocusBeforeModal.focus();
      _lastFocusBeforeModal = null;
    }
  };
  if(prefersReducedMotion()){ done(); return; }
  modal.classList.add('modal-leaving');         // CSS modalOut animation
  const onEnd = e => { if(e && e.target!==modal) return; modal.removeEventListener('animationend', onEnd); done(); };
  modal.addEventListener('animationend', onEnd);
  setTimeout(done, 180);
}
function setModalOpen(modal, open){ open ? openModal(modal) : closeModal(modal); }
// ---- 400ms count-up for numbers (points / streak / completion %) ----
function countTo(el, to, suffix=''){
  if(!el) return;
  const target = Number(to) || 0;
  if(prefersReducedMotion()){ el.textContent = target + suffix; return; }
  const from = parseFloat(String(el.textContent).replace(/[^\d.\-]/g,'')) || 0;
  if(from === target){ el.textContent = target + suffix; return; }
  const t0 = performance.now();
  const tick = t => {
    const p = Math.min(1, (t - t0) / 400);
    const eased = 1 - Math.pow(1 - p, 3);       // ease-out cubic (one-shot easing)
    el.textContent = Math.round(from + (target - from) * eased) + suffix;
    if(p < 1) requestAnimationFrame(tick);
    else el.textContent = target + suffix;
  };
  requestAnimationFrame(tick);
}
// ---- task list motion: stagger index + FLIP position preservation ----
function staggerTasks(){
  $$('#taskList .task').forEach((el,i)=>el.style.setProperty('--i', String(Math.min(i,8))));
}
function captureTaskRects(){
  const map = new Map();
  $$('#taskList .task').forEach(el=>{
    const key = el.querySelector('.task-title')?.textContent || el.textContent.slice(0,40);
    const rect = el.getBoundingClientRect();
    map.set(key, {top:rect.top, left:rect.left});
  });
  return map;
}
function flipTasks(before){
  if(!before || !before.size || prefersReducedMotion()) return;
  $$('#taskList .task').forEach(el=>{
    const key = el.querySelector('.task-title')?.textContent || el.textContent.slice(0,40);
    const prev = before.get(key);
    if(!prev) return;                            // new row -> stagger entrance instead
    const rect = el.getBoundingClientRect();
    const dx = prev.left - rect.left, dy = prev.top - rect.top;
    if(!dx && !dy) return;
    el.style.transition = 'none';
    el.style.transform = `translate(${dx}px, ${dy}px)`;
    requestAnimationFrame(()=>{
      el.style.transition = '';
      el.style.transform = '';
    });
  });
}
async function api(path, body){
  if(!sessionToken && !await ensureSession()) throw new Error('无法建立本地会话');
  const opt = body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};
  opt.headers ||= {};
  if(sessionToken) opt.headers['X-Session'] = sessionToken;
  let r;
  try{
    r = await fetch('/api/'+path,opt);
  }catch(e){
    showModal('网络错误', '无法连接到服务器：'+e.message+'。请检查服务是否在运行。');
    throw e;
  }
  if(r.status===401 && sessionToken){
    sessionToken = null;
    if(await ensureSession()){
      opt.headers['X-Session'] = sessionToken;
      r = await fetch('/api/'+path,opt);
    }
  }
  if(r.status===409){
    let msg = '另一个窗口正在操作，请勿并发写入。';
    try{ const j = await r.json(); msg = j.message || msg; }catch(_){}
    showModal('会话冲突', msg, 'warn');
    throw new Error(msg);
  }
  if(!r.ok){
    let msg = await r.text();
    try{ const j = JSON.parse(msg); msg = j.message || msg; }catch(_){}
    showModal('操作失败', msg);
    throw new Error(msg);
  }
  return r.json();
}
async function uploadApi(path, formData){
  // Ensure we have a session token before POST (re-claim if lost)
  if(!sessionToken) await ensureSession();
  let opt = {method:'POST',headers:{},body:formData};
  if(sessionToken) opt.headers['X-Session'] = sessionToken;
  let r;
  try{
    r = await fetch('/api/'+path,opt);
  }catch(e){
    showModal('网络错误', '无法连接到服务器：'+e.message);
    throw e;
  }
  if(r.status===401 && sessionToken){
    sessionToken = null;
    if(await ensureSession()){
      opt.headers['X-Session'] = sessionToken;
      r = await fetch('/api/'+path,opt);
    }
  }
  // On 409, try to re-claim session and retry once
  if(r.status===409){
    sessionToken = null;
    if(await ensureSession()){
      opt.headers['X-Session'] = sessionToken;
      try{
        r = await fetch('/api/'+path,opt);
      }catch(e){
        showModal('网络错误', '无法连接到服务器：'+e.message);
        throw e;
      }
    }
  }
  if(r.status===409){
    let msg = '另一个窗口正在操作，请勿并发写入。';
    try{ const j = await r.json(); msg = j.message || msg; }catch(_){}
    showModal('会话冲突', msg, 'warn');
    throw new Error(msg);
  }
  if(!r.ok){
    let msg = await r.text();
    try{ const j = JSON.parse(msg); msg = j.message || msg; }catch(_){}
    showModal('操作失败', msg);
    throw new Error(msg);
  }
  return r.json();
}
function logEvent(kind, message, extra={}){
  const headers = {'Content-Type':'application/json'};
  if(sessionToken) headers['X-Session'] = sessionToken;
  fetch('/api/event',{method:'POST',headers,body:JSON.stringify({kind,message,extra})}).catch(()=>{});
}
function showModal(title, msg, kind='error'){
  let m = $('#modal');
  if(!m){
    m = document.createElement('div');
    m.id = 'modal';
    m.className = 'modal-overlay';
    m.innerHTML = `<div class="modal-box">
      <h3 class="modal-title"></h3>
      <p class="modal-msg"></p>
      <div class="modal-actions"><button class="primary modal-ok">知道了</button></div>
    </div>`;
    document.body.appendChild(m);
    m.addEventListener('click', e=>{
      if(e.target===m || e.target.classList.contains('modal-ok')) closeModal(m);
    });
  }
  $('.modal-title', m).textContent = title;
  $('.modal-title', m).className = 'modal-title ' + kind;
  $('.modal-msg', m).textContent = msg;
  openModal(m);
}
function setPage(page){
  const t = pageTitles[page] || [page, ''];
  if($('#title')) $('#title').textContent = t[0];
  if($('#subtitle')) $('#subtitle').textContent = t[1] || '';
  $('.actions')?.classList.toggle('page-actions-hidden', page !== 'dashboard');
  requestAnimationFrame(() => {
    document.scrollingElement.scrollTop = 0;
    $('.main').scrollTop = 0;
    const panel=$('#'+page+' > .panel');
    if(panel) panel.scrollTop=0;
  });
}
function askEvidence(){
  return new Promise(resolve=>{
    let m = $('#evidenceModal');
    if(!m){
      m = document.createElement('div');
      m.id = 'evidenceModal';
      m.className = 'modal-overlay';
      m.innerHTML = `<div class="modal-box">
        <h3 class="modal-title">提交验收证据</h3>
        <p class="modal-msg">请填写交付物路径、链接或完成说明。</p>
        <input class="modal-input" placeholder="例如 D:\\work\\student_grades.py">
        <div class="modal-actions"><button data-evidence-cancel>取消</button><button class="primary" data-evidence-ok>提交</button></div>
      </div>`;
      document.body.appendChild(m);
      m.addEventListener('click', e=>{
        if(e.target.dataset.evidenceOk!==undefined){ const v=$('.modal-input',m).value.trim(); closeModal(m); resolve(v); }
        else if(e.target.dataset.evidenceCancel!==undefined || e.target===m){ closeModal(m); resolve(''); }
      });
    }
    const input = $('.modal-input', m);
    input.value = '';
    openModal(m);
    input.focus();
  });
}
function confirmDlg(msg, title='请确认'){
  return window.confirm(msg);
}
function promptDlg(message, initial=''){
  return new Promise(resolve=>{
    let m=$('#textPrompt');
    if(!m){
      m=document.createElement('div'); m.id='textPrompt'; m.className='modal-overlay';
      m.innerHTML='<div class="modal-box"><h3 class="modal-title">请输入</h3><p class="modal-msg"></p><input class="modal-input"><div class="modal-actions"><button data-cancel>取消</button><button class="primary" data-ok>确定</button></div></div>';
      document.body.appendChild(m);
      m.addEventListener('click', e=>{
        if(e.target.dataset.ok!==undefined){ const v=$('.modal-input',m).value.trim(); closeModal(m); resolve(v); }
        else if(e.target.dataset.cancel!==undefined || e.target===m){ closeModal(m); resolve(''); }
      });
    }
    $('.modal-msg',m).textContent=message; const input=$('.modal-input',m); input.value=initial;
    openModal(m); input.focus();
  });
}
function showExitScreen(){
  const div = document.createElement('div');
  div.className = 'exit-overlay';
  div.innerHTML = `<div class="exit-box exit-ceremony">
    <h2>结束今日工作</h2>
    <p>你还有未完成的任务。你打算怎么处理？</p>
    <div class="exit-actions">
      <button id="exitContinue" class="primary">继续 15 分钟</button>
      <button id="exitDefer">延期到下一个时间块</button>
      <button id="exitQuit" class="danger">标记中断并退出</button>
    </div>
    <textarea id="exitReason" placeholder="可选：填写中断原因..." rows="2" style="width:100%;margin-top:12px;background:var(--mc-panel);color:var(--mc-text);border:1px solid var(--border);border-radius:var(--radius);padding:8px;font:inherit;resize:none"></textarea>
    <small class="hint" style="margin-top:8px;display:block">提示：托盘图标的退出功能已改为打开此页面</small>
  </div>`;
  document.body.appendChild(div);

  const exit = async (action) => {
    const reason = $('#exitReason')?.value?.trim() || '';
    try {
      await api('quit', { reason, action });
    } catch(e) {
      // quit may trigger server shutdown — ignore fetch errors
    }
  };

  $('#exitContinue')?.addEventListener('click', async () => {
    div.innerHTML = `<div class="exit-box"><div class="exit-spinner"></div><h2>继续工作</h2><p>15 分钟后教练会再次提醒你。</p></div>`;
    await exit('continue_15');
    setTimeout(() => { div.remove(); load(); }, 1500);
  });

  $('#exitDefer')?.addEventListener('click', async () => {
    div.innerHTML = `<div class="exit-box"><div class="exit-spinner"></div><h2>已延期</h2><p>未完成任务已标记为延期，明天继续。</p></div>`;
    await exit('defer');
    setTimeout(() => { div.remove(); load(); }, 1500);
  });

  $('#exitQuit')?.addEventListener('click', async () => {
    div.innerHTML = `<div class="exit-box"><div class="exit-spinner"></div><h2>Task Verge 已退出</h2><p>程序正在关闭，可关闭此窗口。</p></div>`;
    await exit('quit');
    setTimeout(() => { if(!document.hidden) window.close(); }, 2000);
  });
}
// Independent fixed toast container (no longer overwrites the hero #statusPill).
function toast(msg, good=true){
  let host = $('#toastHost');
  if(!host){
    host = document.createElement('div');
    host.id = 'toastHost';
    host.className = 'toast-host';
    host.setAttribute('aria-live','polite');
    host.setAttribute('role','status');
    host.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);z-index:10000;display:flex;flex-direction:column;gap:8px;align-items:center;pointer-events:none';
    document.body.appendChild(host);
  }
  const el = document.createElement('div');
  el.className = 'toast ' + (good ? 'toast-ok' : 'toast-err');
  el.textContent = msg;
  el.style.cssText = 'padding:10px 18px;border-radius:10px;background:#1f2937;color:#fff;font-size:13px;box-shadow:0 6px 20px rgba(0,0,0,.25);max-width:80vw;transition:opacity .3s ease,transform .3s ease';
  if(!good) el.style.background = '#b42318';
  host.appendChild(el);
  setTimeout(()=>{ el.style.opacity = '0'; el.style.transform = 'translateY(6px)'; setTimeout(()=>el.remove(), 320); }, 3500);
}
function renderOnboarding(){
  let banner = $('#onboarding');
  const hasGoal = !!(state.goal && state.goal.trim());
  const hasTasks = !!(state.tasks && state.tasks.length);
  if(hasGoal && hasTasks){ if(banner) banner.remove(); return; }
  if(!banner){
    banner = document.createElement('div');
    banner.id = 'onboarding';
    banner.className = 'onboarding';
    $('#dashboard').insertBefore(banner, $('#dashboard').firstChild);
  }
  const steps = [];
  if(!hasGoal) steps.push(`<li>第 1 步：去 <b data-goto="settings">设置</b> 页填写你的目标，每行一个</li>`);
  if(!hasTasks && hasGoal) steps.push(`<li>第 2 步：回到总览点 <b>生成任务</b> 让 AI 为你的目标生成任务</li>`);
  if(!hasGoal) steps.push(`<li>第 2 步：填好目标后回总览点 <b>生成任务</b></li>`);
  const recovery = !hasGoal && hasTasks ? '<p class="hint">检测到已有任务，但当前目标为空；请先在设置中补回目标，现有任务不会被删除。</p>' : '';
  banner.innerHTML = `<div class="onboarding-box">
    <h3>👋 欢迎使用 Task Verge</h3>
    <p>这是一个目标专注控制台，先完成下面步骤：</p>
    <ol>${steps.join('')}</ol>${recovery}
  </div>`;
}
function renderBreakWidget(){
  const info = $('#breakInfo');
  if(!info) return;
  const breaks = state.breaks || [];
  const todayStr = new Date().toISOString().slice(0,10);
  const todays = breaks.filter(b => (b.date||'').slice(0,10) === todayStr);
  const activeTask=(state.tasks||[]).find(t=>!t.done && t.status==='doing');
  if(activeTask){
    $('#statusPill').textContent='专注中';
    $('#statusPill').style.color='var(--accent)';
  } else if(state.break_active){
    const now = Date.now()/1000;
    const active = breaks.find(b => b.until && b.until > now);
    if(active){
      const remain = Math.max(0, Math.ceil((active.until - now)/60));
      info.textContent = `休息中，剩 ${remain} 分钟（今日 ${todays.length}/3 次）`;
      info.style.color = 'var(--warn)';
      return;
    }
  }
  info.textContent = `今日 ${todays.length}/3 次`;
  info.style.color = 'var(--muted)';
}
function render(){
  localizeShell();
  updateClock();
  const doingTask=(state.tasks||[]).find(t=>!t.done && t.status==='doing');
  document.body.classList.remove('focus-active');
  $('#dashboard')?.classList.toggle('focus-first', !!(state.tasks||[]).some(t=>!t.done && t.status!=='skipped'));
  const hasGoal = !!(state.goal && state.goal !== '[object Object]' && String(state.goal).trim());
  $('#goal').textContent = state.goal || '尚未设置目标';
  if($('#goalSelectTop')) $('#goalSelectTop').innerHTML = (state.goals || []).map((g,i)=>`<option value="${i}" ${i===state.active_goal?'selected':''}>${escapeHtml(g)}</option>`).join('') || '<option value="0">尚未设置目标</option>';
  $('#goalsText').value = (state.goals && state.goals.length ? state.goals : (state.goal ? [state.goal] : [])).join('\n');
  const gd=state.goal_details||{};
  if($('#goalOutcome')) $('#goalOutcome').value=gd.outcome||'';
  if($('#goalDeadline')) $('#goalDeadline').value=gd.deadline||'';
  if($('#goalBaseline')) $('#goalBaseline').value=gd.baseline||'';
  if($('#goalCriteria')) $('#goalCriteria').value=(gd.success_criteria||[]).join('\n');
  if($('#goalConstraints')) $('#goalConstraints').value=(gd.constraints||[]).join('\n');
  if($('#goalReadiness')){
    const gr=state.goal_readiness||{};
    $('#goalReadiness').textContent=gr.ready?'目标定义完整，可以制定计划。':`目标定义 ${gr.score||0}%：${(gr.questions||[]).join(' ')}`;
    $('#goalReadiness').style.color=gr.ready?'var(--good)':'var(--warn)';
  }
  countTo($('#pct'), Math.round(state.completion_pct||0), '%');
  const motivation=state.motivation||{};
  $('#pct').title=`积分 ${motivation.points||0} · 连续完成 ${motivation.streak||0} 次`;
  renderMotivationScore();
  $('#progressArc').style.strokeDashoffset = 314 - 314*Math.max(0,Math.min(100,state.completion_pct||0))/100;
  $('#focus').textContent = '前台：'+(state.focus||'--');
  $('#autostart').checked = !!state.autostart;
  if($('#workspace')) $('#workspace').value = state.workspace || '';
  $('#generate').disabled = !hasGoal;
  $('#generate').hidden = false;
  if($('#genAvailableMinutes')) $('#genAvailableMinutes').value = state.task_gen?.available_minutes || 120;
  if($('#genTaskCount')) $('#genTaskCount').value = state.task_gen?.task_count || 3;
  if($('#genMaxTaskMinutes')) $('#genMaxTaskMinutes').value = state.task_gen?.max_task_minutes || 45;
  if($('#desiredRetention')) $('#desiredRetention').value = state.user_model?.desired_retention || 0.9;
  if($('#genPreferContinuation')) $('#genPreferContinuation').checked = state.task_gen?.prefer_continuation !== false;
  if($('#genForceOutput')) $('#genForceOutput').checked = state.task_gen?.force_measurable_output !== false;
  if($('#focusTemplate')) $('#focusTemplate').value = (state.schedule && state.schedule.focus_template) || '90';
  // Privacy toggles
  const priv = state.privacy || {cloud_ai_enabled:true,upload_raw_file_enabled:true,fine_grained_fg_enabled:true,diagnostic_log_verbose:false};
  if($('#privacyCloudAI')) $('#privacyCloudAI').checked = priv.cloud_ai_enabled !== false;
  if($('#privacyUpload')) $('#privacyUpload').checked = priv.upload_raw_file_enabled !== false;
  if($('#privacyFG')) $('#privacyFG').checked = priv.fine_grained_fg_enabled !== false;
  if($('#privacyShareFG')) $('#privacyShareFG').checked = priv.share_foreground_with_ai === true;
  if($('#privacyLogVerbose')) $('#privacyLogVerbose').checked = priv.diagnostic_log_verbose === true;
  const guard = state.focus_guard || {};
  const guardStats = guard.stats || {};
  if($('#focusGuardEnabled')) $('#focusGuardEnabled').checked = guard.enabled !== false;
  if($('#focusStats')) $('#focusStats').textContent = `本次记录：分心 ${guardStats.distractions||0} 次 · ${formatDuration(guardStats.distraction_seconds||0)} · 关闭窗口 ${guardStats.closed_windows||0} 次 · 临时放行 ${guardStats.temporary_allows||0} 次`;
  if($('#dashboardToggleLock')) {
    $('#dashboardToggleLock').textContent = state.plan_locked ? '\u5df2\u9501\u5b9a' : '\u9501\u5b9a\u8ba1\u5212';
    $('#dashboardToggleLock').disabled = !(state.tasks || []).length;
    $('#dashboardToggleLock').title = (state.tasks || []).length ? '锁定今日任务计划' : '生成任务后可锁定计划';
  }
  if($('#regenerateTasks')) {
    $('#regenerateTasks').hidden = !(state.tasks || []).length;
  }
  const dsStatus = $('#deepseekStatus');
  if(dsStatus){
    dsStatus.textContent = state.deepseek_configured ? '✓ 已配置' : '✗ 未配置（生成任务将用本地模板）';
    dsStatus.style.color = state.deepseek_configured ? 'var(--good)' : 'var(--warn)';
  }
  if(doingTask){
    $('#statusPill').textContent = '专注中';
    $('#statusPill').style.color = 'var(--accent)';
  } else if(state.break_active){
    $('#statusPill').textContent = '休息中';
    $('#statusPill').style.color = 'var(--warn)';
  } else {
    $('#statusPill').textContent = '就绪';
    $('#statusPill').style.color = 'var(--accent)';
  }
  renderBreakWidget();
  renderOnboarding();
  renderCurrentTaskBar();
  syncFocusStatusPill();
  renderSessionControls();
  renderRecoveryAction();
  renderReview();
  renderGoalUnderstanding();
  // Skip taskList rebuild if a file picker was opened within the last 5s
  // (refreshFg runs every 2s and would destroy the file input mid-pick)
  const _hasFileSelected = $$('#taskList [data-evidence-file]').some(inp => inp.files && inp.files.length);
  const _skipTaskList = _hasFileSelected || Date.now() - _lastFilePickTs < 5000;
  if(!_skipTaskList){
    const _beforeRects = captureTaskRects();
    $('#taskList').innerHTML = state.tasks.map(taskCard).join('') || '<p class="hint">还没有任务。</p>';
    staggerTasks();
    flipTasks(_beforeRects);
  }
  addTaskAdjustControls();
  renderCrashNotice();
  renderUndoAction();
  renderDailyWrap();
}
function renderMotivationScore(){
  const motivation=state.motivation||{};
  const pts=Number(motivation.points)||0;
  const ptsEl=$('#motivationPoints');
  if(ptsEl){
    countTo(ptsEl, pts);
    // semantic color: negative→red (.negative), positive→green (.positive), 0→neutral (no class)
    ptsEl.classList.remove('negative','positive');
    if(pts<0) ptsEl.classList.add('negative');
    else if(pts>0) ptsEl.classList.add('positive');
  }
  if($('#motivationStreak')) countTo($('#motivationStreak'), Number(motivation.streak)||0);
  if($('#motivationBest')) countTo($('#motivationBest'), Number(motivation.best_streak)||0);
  if($('#motivationHistory')) $('#motivationHistory').innerHTML=(motivation.history||[]).slice(-4).reverse().map(x=>`<div class="ledger-row ${Number(x.points)>=0?'positive':'negative'}"><b>${Number(x.points)>=0?'+':''}${x.points||0}</b><span>${escapeHtml(({accepted:'验收通过',partial:'部分完成',skipped:'跳过任务',failed:'验收失败'}[x.outcome]||x.outcome||'反馈'))}</span></div>`).join('')||'<p class="hint">完成任务后显示反馈记录</p>';
  if($('#motivationRecovery')) $('#motivationRecovery').hidden=!(state.tasks||[]).some(t=>!t.done&&['paused','partial'].includes(t.status));
}

function localizeShell(){
  const labels = {
    '.brand small':'专注执行系统',
    '.nav-item[data-page="dashboard"] span':'今日执行',
    // note: [data-page="review"] span is intentionally renamed to '记录' at startup (see init block);
    // localizeShell must NOT override it back to '复盘' on every render.
    '.nav-item[data-page="settings"] span':'设置',
    '#title':'今日执行',
    '#subtitle':'聚焦一个可验收结果，完成后立即获得反馈。',
    '#generate':'生成任务',
    '.dash-tasks .panel-head h3':'任务队列',
    '#addTask':'新增',
    '.motivation-panel .panel-head h3':'执行反馈',
    '.motivation-score small':'积分',
    '.streak-grid > div:first-child small':'连续完成',
    '.streak-grid > div:last-child small':'最佳连续',
    '.recovery-box small':'补救行动',
    '.recovery-box p':'验收未通过时，从一个最小可验证步骤重新开始。',
    '.recovery-box button':'开始补救'
  };
  Object.entries(labels).forEach(([selector,value])=>{
    const el=$(selector);
    if(el) el.textContent=value;
  });
}

function renderCurrentTaskBar(){
  let bar=$('#currentTaskBar');
  const task=(state.tasks||[]).find(t=>!t.done && t.status==='doing') || (state.tasks||[]).find(t=>!t.done && t.status!=='skipped');
  if(!task){ if(bar) bar.remove(); return; }
  if(!bar){ bar=document.createElement('div'); bar.id='currentTaskBar'; bar.className='current-task-bar'; $('#dashboard').prepend(bar); }
  const idx=(state.tasks||[]).indexOf(task);
  const title=task.text||task.title||'未命名任务';
  const next=task.next_action||'从最小可执行步骤开始';
  const done=task.done_definition||task.expected_output||task.acceptance||'产出可检查的结果';
  const ancestry=[state.goal,task.milestone||'今日执行',title].filter(Boolean);
  const started=task.started_at ? new Date(task.started_at).getTime() : 0;
  const elapsed=Math.max(0,Number(task.actual_seconds)||0)/60+(started&&task.status==='doing'?Math.max(0,(Date.now()-started)/60000):0);
  const evidenceCount=Array.isArray(task.evidence)?task.evidence.filter(Boolean).length:(task.evidence?1:0);
  const acceptanceItems=String(done).split(/[；;\n]/).map(x=>x.trim()).filter(Boolean).slice(0,3);
  const taskMeta=[typeName(task.type),task.estimated_minutes?`${task.estimated_minutes} 分钟`:'',task.difficulty?`难度 ${task.difficulty}`:'',task.milestone||'',task.skill_id||''].filter(Boolean);
  const taskStatusLabel={doing:'进行中',paused:'已暂停',partial:'部分完成',deferred:'已顺延'}[task.status]||'待开始';
  const timerText=formatFocusElapsed(task);
  bar.className='current-task-bar mission-task';
  bar.innerHTML=`<div class="mission-head"><b>当前任务</b></div><article class="mission-card">
    <div class="mission-status"><span><i></i>${taskStatusLabel}${task.status==='doing'&&task.started_at?`　<small>开始于 ${new Date(task.started_at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}</small>`:''}</span><button data-goto-queue>查看历史任务</button></div>
    <div class="mission-title"><h2>${escapeHtml(title)}</h2><div><small>已用时</small><strong id="focusElapsed" data-started="${task.status==='doing'?escapeHtml(task.started_at||''):''}" data-actual="${Number(task.actual_seconds)||0}">${timerText}</strong><span>◷　预计 ${Number(task.estimated_minutes)||45}:00</span></div></div>
    <div class="mission-meta">${taskMeta.map(x=>`<span>${escapeHtml(x)}</span>`).join('')}</div>
    ${task.description?`<p class="mission-description">${escapeHtml(task.description)}</p>`:''}
    <h4>下一步行动</h4><p class="mission-next">${escapeHtml(next)}</p>
    <div class="mission-info">
      <div><b>交付物</b><span>${escapeHtml(task.expected_output||task.done_definition||'提交可检查的结果')}</span></div>
      <div><b>验收标准</b><span>${escapeHtml(task.acceptance||done)}</span></div>
    </div>
    ${task.skill_id?`<div class="mission-rating"><b>回忆质量</b><div>${[['again','忘记'],['hard','困难'],['good','正常'],['easy','轻松']].map(([value,label])=>`<button class="${task.recall_rating===value?'selected':''}" data-recall-rating="${value}" data-rating-idx="${idx}">${label}</button>`).join('')}</div></div>`:''}
    <h4>证据上传</h4><label class="mission-upload"><input data-evidence-file="${idx}" type="file" multiple><b>⇧　${evidenceCount?`已上传 ${evidenceCount} 项，继续上传`:'点击上传文件或拖拽到此处'}</b><small>支持：PDF、DOCX、PNG、JPG，单个文件 ≤ 50MB</small></label>
    <footer>${task.status==='doing'?`<button data-session-action="pause" data-session-idx="${idx}">Ⅱ　暂停</button><button class="primary" data-ai-evaluate="${idx}">☑　提交验收</button>`:`<button class="primary" data-start-task="${idx}">开始任务</button>`}</footer>
  </article>`;
}

function renderSessionControls(){
  const bar=$('#currentTaskBar'), task=(state.tasks||[]).find(t=>!t.done && t.status==='doing');
  if(!bar||!task) return;
  if(bar.classList.contains('focus-workspace') || bar.classList.contains('mission-task')) return;
  const idx=(state.tasks||[]).indexOf(task);
  const evidenceCount=Array.isArray(task.evidence)?task.evidence.filter(Boolean).length:(task.evidence?1:0);
  let box=bar.querySelector('.focus-first-actions');
  if(!box){ box=document.createElement('div'); box.className='focus-first-actions'; bar.appendChild(box); }
  box.innerHTML=`<label class="upload-file-button focus-upload">${evidenceCount?`继续上传 · ${evidenceCount} 项`:'上传交付物'}<input data-evidence-file="${idx}" type="file" multiple></label><button data-session-action="pause" data-session-idx="${idx}">暂停任务</button><button data-session-action="partial" data-session-idx="${idx}">部分完成</button><button class="primary" data-ai-evaluate="${idx}">提交验收</button>`;
}
function syncFocusStatusPill(){
  if(!focusStatusPill) focusStatusPill=$('#statusPill');
  if(!focusStatusPill) return;
  const target=$('.hero-copy');
  if(target && focusStatusPill.parentElement!==target) target.prepend(focusStatusPill);
}
function renderRecoveryAction(){
  let box=$('#recoveryAction');
  const task=(state.tasks||[]).find(t=>!t.done && ['paused','partial'].includes(t.status));
  if(!task){ if(box) box.remove(); return; }
  if(!box){ box=document.createElement('div'); box.id='recoveryAction'; box.className='recovery-card'; $('#dashboard').appendChild(box); }
  box.innerHTML=`<div><small>今天状态不理想也没关系</small><b>先完成一个 10 分钟保底动作</b><span>${escapeHtml(task.continuation_note||task.next_action||'从当前任务留下的续接点继续')}</span></div><button class="primary" data-recovery>开始恢复</button>`;
}
function renderDailyWrap(){
  let box=$('#dailyWrap');
  const tasks=state.tasks||[], done=tasks.length>0 && tasks.every(t=>t.done);
  const today=new Date().toISOString().slice(0,10);
  const archived=(state.archives||[]).some(a=>String(a.date||'').slice(0,10)===today);
  if(!done || archived){ if(box) box.remove(); return; }
  if(!box){
    box=document.createElement('div'); box.id='dailyWrap'; box.className='onboarding';
    $('#dashboard').insertBefore(box,$('#dashboard').firstChild);
  }
  box.innerHTML='<div class="onboarding-box"><h3>\u4eca\u65e5\u4efb\u52a1\u5df2\u5b8c\u6210</h3><p>\u4fdd\u5b58\u4eca\u65e5\u590d\u76d8\uff0c\u660e\u5929\u53ef\u4ee5\u4ece\u672a\u5b8c\u6210\u4efb\u52a1\u7ee7\u7eed\u3002</p><button data-archive-today>\u4fdd\u5b58\u4eca\u65e5\u590d\u76d8</button><button data-goto="review">\u67e5\u770b\u590d\u76d8</button></div>';
}
function addTaskAdjustControls(){
  $$('#taskList .task').forEach((el,i)=>{
    if(state.tasks[i]?.done || el.querySelector('.task-actions')) return;
    const box=document.createElement('div'); box.className='task-actions';
    box.innerHTML='<button data-task-action="extend">\u5ef6\u957f 15 \u5206\u949f</button><button data-task-action="skip">\u4eca\u5929\u8df3\u8fc7</button>';
    el.querySelector('.task-body')?.appendChild(box);
  });
}
function renderUndoAction(){
  let box=$('#undoAction');
  if(!state.undo_available){ if(box) box.remove(); return; }
  if(!box){
    box=document.createElement('button'); box.id='undoAction'; box.className='hint'; box.textContent='\u64a4\u9500\u4e0a\u4e00\u6b21\u64cd\u4f5c';
    $('.actions')?.appendChild(box);
  }
}
function renderGoalUnderstanding(){
  const list = $('#taskList');
  if(!list) return;
  let box = $('#goalUnderstanding');
  const tg = state.task_generation || {};
  const ga = tg.goal_analysis || {};
  const pd = tg.progress_diagnosis || {};
  const milestones = (tg.milestones||[]).map(x=>x.name||'').filter(Boolean).slice(0,4).join(' → ');
  if(!tg.ts){ if(box) box.remove(); return; }
  if(!box){
    box = document.createElement('div');
    box.id = 'goalUnderstanding';
    box.className = 'ai-brief';
    list.parentElement.insertBefore(box, list);
  }
  const success = (ga.success_criteria||[]).slice(0,3).join('；');
  const avoid = (pd.avoid||[]).slice(0,2).join('；');
  box.innerHTML = `<b>AI 目标理解</b><p>${escapeHtml(ga.intent || state.goal || '')}</p>
    ${success ? `<small>成功标准：${escapeHtml(success)}</small>` : ''}
    ${avoid ? `<small>避免：${escapeHtml(avoid)}</small>` : ''}
    ${tg.daily_strategy ? `<small>今日策略：${escapeHtml(tg.daily_strategy)}</small>` : ''}`;
  if(milestones) box.insertAdjacentHTML('beforeend', `<small>阶段：${escapeHtml(milestones)}</small>`);
}
function renderCrashNotice(){
  const box = $('#crashNotice');
  if(!box) return;
  const info = state.last_crash;
  if(!info){ box.style.display='none'; return; }
  if(String(info.reason||'').toLowerCase()==='running') info.reason='上次未正常关闭';
  box.style.display='block';
  box.innerHTML = `<b>⚠ 上次异常退出</b>时间：${escapeHtml(info.ts||'未知')}。原因：${escapeHtml(info.reason||'未知')}。建议检查任务数据是否完整。 <button id="dismissCrash" style="margin-left:8px;padding:4px 10px">忽略</button>`;
}
function renderReview(){
  if(!$('#quitList')) return;
  const summary=$('#reviewSummary');
  if(summary){
    const tasks=state.tasks||[], done=tasks.filter(t=>t.done).length, pending=tasks.find(t=>!t.done);
    const top=Object.entries(state.fg||{}).filter(([k])=>k!=='n/a').sort((a,b)=>b[1]-a[1])[0];
    const archives=state.archives||[], avg=archives.length ? Math.round(archives.reduce((n,a)=>n+Number(a.completion_pct||0),0)/archives.length) : 0, history=archives.length ? `历史 ${archives.length} 天平均完成 ${avg}%` : '暂无历史归档';
    summary.innerHTML=`<div class="panel-head"><h3>今日复盘摘要</h3><span>${done}/${tasks.length} 已完成</span></div>
      <p>${pending ? `下一步：${escapeHtml(pending.text||pending.title||'未命名任务')}` : '今日任务已全部完成，可以归档。'}</p>
      <small>${top ? `累计使用最多：${escapeHtml(top[0])} · ${formatDuration(top[1])}` : '暂无前台时间数据'} · ${history}${archives.some(a=>a.date===new Date().toISOString().slice(0,10)) ? ' · 今日已归档' : ''}</small>
      ${state.last_review?.ts ? `<p class="review-next-step">模型判断：容量系数 ${state.last_review.capacity_factor} · 合适任务时长 ${state.last_review.preferred_task_minutes} 分钟${state.last_review.common_friction?` · 常见阻力 ${escapeHtml(state.last_review.common_friction)}`:''}</p>` : ''}
      <button class="primary" id="startNextCycle">复盘并生成下一轮任务</button>`;
  }
  if(summary){
    const weekMap = new Map();
    for(const row of (state.history||[]).filter(x=>x && x.date).slice(-60)) weekMap.set(String(row.date).slice(0,10), row);
    const weekRows = [...weekMap.values()].slice(-7);
    if(weekRows.length){
      const total = weekRows.reduce((n,row)=>n+(row.tasks||[]).length,0);
      const done = weekRows.reduce((n,row)=>{
        const flags = Array.isArray(row.done_flags) && row.done_flags.length
          ? row.done_flags
          : (row.tasks||[]).map(task=>task && (task.done || task.status === 'done'));
        return n + flags.filter(Boolean).length;
      },0);
      const avg = Math.round(weekRows.reduce((n,row)=>n+Number(row.completion_pct||0),0)/weekRows.length);
      summary.insertAdjacentHTML('beforeend', `<small class="review-weekly">近 7 天：${weekRows.length} 天有记录 · 平均完成率 ${avg}% · 完成 ${done}/${total} 个任务</small>`);
    }
    const fs=state.focus_guard?.stats;
    if(fs) summary.insertAdjacentHTML('beforeend', `<small class="review-weekly">专注干预：分心 ${fs.distractions||0} 次 · ${formatDuration(fs.distraction_seconds||0)} · 关闭窗口 ${fs.closed_windows||0} 次</small>`);
  }
  const leadInsight = state.insights?.alerts?.[0];
  if(summary && leadInsight){
    summary.insertAdjacentHTML('beforeend', `<p class="review-next-step"><b>下一步建议：</b>${escapeHtml(leadInsight.message || leadInsight.title || '')}</p>`);
  }
  const eventMessage = x => ({
    plan_locked:'已生成并锁定今日任务', plan_lock:'已锁定计划', plan_unlock:'已解锁计划',
    ai_apps:'已完成任务应用匹配', ai_apps_failed:'应用匹配失败，请稍后重试', ai_apps_skipped:'未配置 AI，已保留已有应用',
    app_catalog:'已完成应用分类', fallback_gen:'AI 不可用，已使用本地任务模板',
    task_evidence:'已更新任务交付物', archive:'已归档今日记录', archive_delete:'已删除一条归档',
    coach_plan:'已重新生成时间块'
  }[x.kind] || x.message || x.reason || '已完成操作');
  const fmt = (label, x) => `<div class="log-item"><b>${escapeHtml(label)}</b><span>${escapeHtml(x.ts||x.date||'')}</span><p>${escapeHtml(eventMessage(x))}</p></div>`;
  $('#quitList').innerHTML=(state.quit_attempts||[]).slice().reverse().map(x=>fmt('退出申请', x)).join('') || '<p class="hint">暂无退出记录。</p>';
  $('#eventList').innerHTML=(state.events||[]).slice().reverse().map(x=>fmt(eventName(x.kind), x)).join('') || '<p class="hint">暂无事件。</p>';
  $('#archiveList').innerHTML=(state.archives||[]).slice().reverse().map(a=>`<div class="log-item"><div><b>${escapeHtml(a.date)}</b><button data-remove-archive="${escapeHtml(a.date)}" title="删除这条归档">删除</button></div><p>${escapeHtml(a.goal||'')} · 完成 ${doneCount(a)}/${(a.tasks||[]).length} · ${a.completion_pct||0}%</p></div>`).join('') || '<p class="hint">暂无归档。</p>';
  renderActivityHeatmap();
}
function renderActivityHeatmap(){
  const box=$('#activityHeatmap'); if(!box) return;
  const values=new Map();
  for(const row of [...(state.history||[]),...(state.archives||[])]){
    const date=String(row?.date||'').slice(0,10); if(date) values.set(date,Math.max(values.get(date)||0,Number(row.completion_pct)||0));
  }
  const today=new Date(), dateKey=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  values.set(dateKey(today),Math.max(values.get(dateKey(today))||0,Number(state.completion_pct)||0));
  const month=new Date(today.getFullYear(),today.getMonth()-heatmapMonthOffset,1), days=new Date(month.getFullYear(),month.getMonth()+1,0).getDate(), cells=[]; let active=0;
  for(const label of ['日','一','二','三','四','五','六']) cells.push(`<span>${label}</span>`);
  for(let pad=0;pad<month.getDay();pad++) cells.push('<i class="empty"></i>');
  for(let day=1;day<=days;day++){
    const date=new Date(month.getFullYear(),month.getMonth(),day), key=dateKey(date), pct=Math.max(0,Math.min(100,values.get(key)||0));
    if(pct>0) active++;
    const level=pct===0?0:pct<25?1:pct<50?2:pct<75?3:4;
    cells.push(`<i data-level="${level}" title="${key} · 完成 ${Math.round(pct)}%" aria-label="${key} 完成 ${Math.round(pct)}%"><small>${day}</small></i>`);
  }
  box.innerHTML=`<section class="heatmap-month"><div>${cells.join('')}</div></section>`;
  $('#heatmapTotal').textContent=`${month.getFullYear()}年${month.getMonth()+1}月 · ${active} 天有记录`;
  box.onwheel=e=>{ e.preventDefault(); const next=Math.max(0,Math.min(11,heatmapMonthOffset+(e.deltaY>0||e.deltaX>0?1:-1))); if(next!==heatmapMonthOffset){ heatmapMonthOffset=next; renderActivityHeatmap(); } };
}
const _renderReview = renderReview;
renderReview = function(){
  _renderReview();
  const graph=state.knowledge_graph||{}, host=$('#knowledgeGraphHost');
  if(host && (graph.nodes||[]).length){
    const edges=graph.edges||[];
    host.hidden=false;
    host.innerHTML=`<div id="knowledgeGraph" class="knowledge-graph">
      <div class="panel-head"><h3>知识图谱</h3><span>${graph.nodes.length} 个知识点 · ${edges.length} 条前置关系</span></div>
      <div class="knowledge-nodes">${graph.nodes.map(node=>{
        const parents=edges.filter(edge=>edge.to===node.id).map(edge=>edge.from);
        const active=graph.focus?.skill_id===node.id?' active':'';
        return `<div class="knowledge-node ${node.ready?'ready':'blocked'}${active}">
          <b>${escapeHtml(node.title||node.id)}</b><span>${Math.round((node.mastery||0)*100)}%</span>
          ${node.title&&node.title!==node.id?`<small>${escapeHtml(node.id)}</small>`:''}
          <small>${escapeHtml(node.state||'New')}${parents.length?` · 前置：${escapeHtml(parents.join('、'))}`:' · 起点'}</small>
        </div>`;
      }).join('')}</div></div>`;
  } else if(host){
    host.hidden=false;
    host.innerHTML='<div class="knowledge-graph"><div class="panel-head"><h3>知识图谱</h3><span>0 个知识点</span></div><div class="knowledge-empty">完成一次学习任务后，这里会显示能力节点与前置关系。</div></div>';
  }
  $$('#archiveList .log-item').forEach((el, i) => {
    el.dataset.archive = String((state.archives || []).length - 1 - i);
    el.title = '点击查看当天详情';
  });
};
function doneCount(a){ return (a.done_flags||[]).filter(Boolean).length; }
function eventName(k){
  return ({plan_lock:'锁定计划',plan_unlock:'解锁计划',task_edit:'修改任务',break:'休息申请',quit:'退出申请',quit_blocked:'退出被拦截',archive:'每日归档',archive_delete:'删除归档',fallback_gen:'本地生成任务',plan_locked:'生成并锁定任务',ai_apps:'AI 识别应用',ai_apps_skipped:'跳过应用匹配',ai_apps_failed:'AI 识别失败',app_catalog:'AI 应用分类',app_catalog_failed:'AI 分类失败',request_app:'应用申请',coach_plan:'生成时间块',focus_distraction:'检测到分心',focus_distraction_seconds:'记录分心时长',focus_closed_windows:'关闭分心窗口',focus_temporary_allows:'临时放行应用',focus_permanent_allows:'永久允许应用',focus_paused:'暂停专注',focus_policy:'更新专注策略'}[k] || k);
}
function taskCard(t,i){
  const skill=(state.user_model?.skills||{})[t.skill_id]||{};
  const learningLabel=({diagnostic:'诊断',recall:'闭卷回忆',practice:'练习',explain:'费曼解释',transfer:'迁移应用',review:'到期复习'}[t.learning_task_type]||t.learning_task_type||'');
  const learningMeta=t.skill_id ? `<div class="learning-meta"><b>${escapeHtml(t.skill_id)}</b>${learningLabel?`<span>${escapeHtml(learningLabel)}</span>`:''}<span>掌握度 ${Math.round((skill.mastery||0)*100)}%</span></div>` : '';
  if(t.status==='skipped') return `<div class="task task-compact deferred"><div class="task-body"><div class="task-title">${escapeHtml(t.text || t.title || '')}</div><div class="task-meta">今日已跳过，可稍后编辑</div></div><button data-edit="${i}">编辑</button></div>`;
  if(t.done) { const ar=t.acceptance_result||{}, ev=(t.evidence||[]).length; return `<div class="task task-compact done">
    <input type="checkbox" checked disabled aria-label="任务已完成">
    <div class="task-body"><div class="task-title">${escapeHtml(t.text || t.title || '')}</div><div class="task-meta">已完成${ev?` · ${ev} 项交付物`:''}${ar.reason?` · ${escapeHtml(ar.reason)}`:''}</div></div>
    <button data-edit="${i}">编辑</button>
  </div>`; }
  const requiredApps = [...new Set(t.required_apps||[])].slice(0,4);
  const optionalApps = [...new Set((t.allowed_apps||[]).filter(x => !requiredApps.some(r => String(r).toLowerCase() === String(x).toLowerCase())))].slice(0,4);
  const meta = [typeName(t.type), t.estimated_minutes ? `${t.estimated_minutes} 分钟` : '', t.difficulty ? `难度 ${t.difficulty}` : ''].filter(Boolean).join(' · ');
  const stateLabel=({doing:'进行中',paused:'已暂停',partial:'部分完成',deferred:'已顺延',skipped:'已跳过'}[t.status]||'待开始');
  const agentRun=(state.agent_runs||[]).slice().reverse().find(r=>r.task_id===(t.id||t.title));
  const agentUi=agentRun ? `<div class="agent-run"><b>Agent：${escapeHtml(agentRun.status)}</b><span>步骤 ${agentRun.step}/${agentRun.max_steps}</span>${agentRun.status==='awaiting_confirmation'?`<button data-agent="confirm" data-run-id="${escapeHtml(agentRun.run_id)}">确认继续</button>`:''}${['paused','failed','blocked'].includes(agentRun.status)?`<button data-agent="resume" data-run-id="${escapeHtml(agentRun.run_id)}">继续</button>`:''}${!['completed','failed','blocked','paused','awaiting_confirmation'].includes(agentRun.status)?`<button data-agent="stop" data-run-id="${escapeHtml(agentRun.run_id)}">暂停</button>`:''}</div>` : '';
  const ar = t.acceptance_result || {};
  const decisionLabel={accepted:'通过',conditional:'有条件通过',review:'待人工复核',rejected:'驳回'}[ar.decision]||'';
  const ancestry=[state.goal,t.milestone||'今日执行',t.text||t.title].filter(Boolean);
  // evidence is now a list; join names for display
  const evList = Array.isArray(t.evidence) ? t.evidence.filter(Boolean) : (t.evidence ? [t.evidence] : []);
  const evidenceNames = evList.length ? evList.map(e => String(e).split(/[\\/]/).pop()).join(', ') : '尚未上传交付物';
  const evidenceTitle = evList.length ? evList.map(String).join('\n') : '';
  return `<div class="task ${t.done?'done':''}">
    <input type="checkbox" ${t.done?'checked':''} data-ai-evaluate="${i}" aria-label="验收任务 ${escapeHtml(t.text || t.title || '')}" title="提交证据后由 AI 验收">
    <div class="task-body">
      <div class="task-title">${escapeHtml(t.text || t.title || '')}</div>
      <div class="goal-ancestry">${ancestry.map(escapeHtml).join('<i>→</i>')}</div>
      <div class="task-meta"><b>${stateLabel}</b> · ${escapeHtml(meta)}${t.milestone ? ` · 阶段 ${escapeHtml(t.milestone)}` : ''}</div>
      ${learningMeta}
      ${t.skill_id ? `<div class="recall-rating" aria-label="回忆质量">
        <small>回忆质量：</small>
        ${[['again','忘记'],['hard','困难'],['good','正常'],['easy','轻松']].map(([value,label])=>`<button class="${t.recall_rating===value?'selected':''}" data-recall-rating="${value}" data-rating-idx="${i}">${label}</button>`).join('')}
      </div>` : ''}
      ${agentUi}
      ${t.depends_on?.length ? `<div class="task-field"><b>前置</b><span>${escapeHtml(t.depends_on.join('、'))}</span></div>` : ''}
      ${t.description ? `<p>${escapeHtml(t.description)}</p>` : ''}
      ${t.expected_output ? `<div class="task-field"><b>交付物</b><span>${escapeHtml(t.expected_output)}</span></div>` : ''}
      ${t.acceptance ? `<div class="task-field"><b>验收</b><span>${escapeHtml(t.acceptance)}</span></div>` : ''}
      ${t.adjustment_reason ? `<div class="task-field"><b>调整依据</b><span>${escapeHtml(t.adjustment_reason)}</span></div>` : ''}
      ${!t.done ? `<div class="task-actions" aria-label="反馈当前任务">
        <small>反馈：</small>
        <button data-feedback="too_hard" data-feedback-idx="${i}">太难</button>
        <button data-feedback="stuck" data-feedback-idx="${i}">卡住 / 救援</button>
        <button data-feedback="no_time" data-feedback-idx="${i}">没时间</button>
        <button data-feedback="wrong_direction" data-feedback-idx="${i}">方向不对</button>
        <button data-feedback="too_easy" data-feedback-idx="${i}">太简单</button>
      </div>` : ''}
      <div class="evidence-row">
        <div class="evidence-display ${evList.length?'has-file':''}" title="${escapeHtml(evidenceTitle)}">${escapeHtml(evidenceNames)}</div>
        <label class="upload-file-button">${evList.length?'继续上传':'上传交付物'}<input data-evidence-file="${i}" type="file" multiple></label>
      </div>
      ${evList.length ? `<div class="evidence-files">${evList.map((e,j)=>`<span class="evidence-tag" title="${escapeHtml(e)}">${escapeHtml(String(e).split(/[\\/]/).pop())}<button data-remove-evidence="${i}" data-ev-idx="${j}" aria-label="删除交付物">×</button></span>`).join('')}</div>` : ''}
      ${ar.reason ? `<div class="task-field acceptance-decision ${escapeHtml(ar.decision||'')}"><b>${escapeHtml(decisionLabel||'验收结果')}</b><span>${escapeHtml(ar.reason)} · 置信度 ${Math.round((ar.confidence||0)*100)}%</span></div>` : ''}
      ${(ar.missing||[]).length ? `<div class="task-field"><b>缺少</b><span>${escapeHtml(ar.missing.join('；'))}</span></div>` : ''}
      ${(ar.next_steps||[]).length ? `<div class="task-field"><b>补交</b><span>${escapeHtml(ar.next_steps.join('；'))}</span></div>` : ''}
      ${(ar.evidence_refs||[]).length ? `<div class="task-field"><b>依据</b><span>${escapeHtml(ar.evidence_refs.join('；'))}</span></div>` : ''}
       ${requiredApps.length ? `<div class="task-apps"><small>必需应用</small>${requiredApps.map(appChipTiny).join('')}</div>` : ''}
       ${optionalApps.length ? `<div class="task-apps"><small>可选应用</small>${optionalApps.map(appChipTiny).join('')}</div>` : ''}
       ${t.app_reason ? `<div class="task-field"><b>应用建议</b><span>${escapeHtml(t.app_reason)}${t.app_confidence ? `（${Math.round(t.app_confidence*100)}%）` : ''}</span></div>` : ''}
    </div>
    <button data-edit="${i}">编辑</button>
  </div>`;
}
function typeName(x){
  return ({learn:'学习',practice:'练习',review:'复盘',build:'构建',write:'写作',research:'研究'}[x] || x || '任务');
}
function appChipTiny(exe){
  const app = allApps.find(a=>(a.exe||'').toLowerCase()===String(exe).toLowerCase());
  return `<span class="task-app-chip"><img src="${escapeHtml(app?.icon||'')}" onerror="this.style.display='none'">${escapeHtml(app?.name||exe)}</span>`;
}
async function uploadEvidenceFile(idx, input){
  const files=input?.files;
  if(!files || !files.length){ toast('请先选择交付物文件', false); return; }
  let ok = true;
  for(const file of files){
    logEvent('upload_selected','已选择交付物文件',{idx,name:file.name,size:file.size});
    const fd = new FormData();
    fd.append('idx', String(idx));
    fd.append('file', file);
    logEvent('upload_start','开始上传交付物',{idx,name:file.name,size:file.size});
    try{
      const r = await uploadApi('upload-evidence', fd);
      logEvent('upload_done','交付物上传成功',{idx,file:r.evidence||file.name});
    }catch(e){
      logEvent('upload_failed','交付物上传失败',{idx,name:file.name,error:e.message});
      toast('上传失败：'+file.name, false);
      ok = false;
    }
  }
  if(input) input.value='';
  _lastFilePickTs = 0;  // allow full refresh to show new evidence files
  if(ok) toast('交付物已保存');
  await load();
}
function formatFocusElapsed(task){
  const started=task.started_at?new Date(task.started_at).getTime():0;
  const accumulated=Number(task.actual_seconds)||0;
  const seconds=Math.floor(Math.max(0,accumulated+(task.status==='doing'&&started?Math.floor((Date.now()-started)/1000):0)));
  return [Math.floor(seconds/3600),Math.floor(seconds%3600/60),seconds%60].map(x=>String(x).padStart(2,'0')).join(':');
}
function updateClock(){
  $('#clock').textContent = new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'});
  const timer=$('#focusElapsed');
  if(timer){
    const started=timer.dataset.started?new Date(timer.dataset.started).getTime():0;
    const seconds=Math.max(0,Math.round(Number(timer.dataset.actual)||0)+(started?Math.floor((Date.now()-started)/1000):0));
    timer.textContent=[Math.floor(seconds/3600),Math.floor(seconds%3600/60),seconds%60].map(x=>String(x).padStart(2,'0')).join(':');
  }
}
function formatDuration(seconds){
  const s=Math.max(0,Math.round(Number(seconds)||0));
  if(s<60) return `${s}秒`;
  const m=Math.floor(s/60), h=Math.floor(m/60), d=Math.floor(h/24);
  if(d) return `${d}天${h%24}小时`;
  if(h) return `${h}小时${m%60}分`;
  return `${m}分钟`;
}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
let _lastSyncTs = 0;
// Drive the topbar .sync-state indicator (classes: .synced/.syncing/.error — styled in app.css).
function setSyncState(kind, detail){
  const el=$('.sync-state');
  if(!el) return;
  el.classList.remove('synced','syncing','error');
  if(kind) el.classList.add(kind);
  const span=el.querySelector('span');
  if(!span) return;
  const small=span.querySelector('small');
  const label = kind==='syncing' ? '同步中' : kind==='error' ? '同步失败' : '已同步';
  if(small){
    const first=span.firstChild;
    if(!first || first.nodeType!==3 || first.textContent!==label) span.replaceChildren(label, small);
    if(detail && small.textContent!==detail) small.textContent=detail;
  } else if(span.textContent!==label){
    span.textContent=label;
  }
}
function syncErrorDetail(){
  return _lastSyncTs ? Math.round((Date.now()-_lastSyncTs)/1000)+' 秒前' : '';
}
async function load(){
  setSyncState('syncing');
  let stateData;
  try{
    stateData = normalizeState(await api('state'));
  }catch(e){
    setSyncState('error', syncErrorDetail());
    throw e;
  }
  state = stateData;
  render();
  setSyncState('synced','刚刚');
  _lastSyncTs = Date.now();
  if(state.tasks?.length && !sessionStorage.getItem('taskVergeRecovered')){
    sessionStorage.setItem('taskVergeRecovered','1');
    toast(`\u5df2\u6062\u590d\u4eca\u65e5\u4efb\u52a1\uff0c\u5df2\u5b8c\u6210 ${state.tasks.filter(t=>t.done).length}/${state.tasks.length}`);
  }
}
function normalizeState(data){
  const goalText = g => {
    const text = typeof g === 'object' ? (g.title || g.goal || g.name || '') : String(g || '');
    return text === '[object Object]' ? '' : text;
  };
  data.goal = goalText(data.goal);
  data.goals = (data.goals || []).map(goalText);
  return data;
}
async function refreshFg(){
  if(activePage!=='dashboard') return;
  try{
    const s = await api('state');
    // Lightweight status refresh; foreground details are intentionally not exposed.
    $('#focus').textContent = '前台：'+(s.focus||'--');
    // update completion ring silently (completion_pct can change on eval)
    countTo($('#pct'), Math.round(s.completion_pct||0), '%');
    $('#progressArc').style.strokeDashoffset = 314 - 314*Math.max(0,Math.min(100,s.completion_pct||0))/100;
    setSyncState('synced','刚刚');
    _lastSyncTs = Date.now();
  }catch(e){
    // Don't swallow poll failures — surface them in the sync indicator.
    setSyncState('error', syncErrorDetail());
  }
}
let _lastFullSyncTs = 0;
function setGenerationUi(kind, message){
  const box=$('#generationStatus');
  if(!box) return;
  box.hidden=false;
  box.className=`generation-status ${kind}`;
  box.innerHTML=`<span>${escapeHtml(message)}</span>${kind==='error'?'<button id="generationRetry">重试</button>':''}`;
  ['generate','regenerateTasks'].forEach(id=>{ const button=$('#'+id); if(button) button.disabled=kind==='running'; });
  const regenerate=$('#regenerateTasks');
  if(regenerate) regenerate.textContent=kind==='running'?'生成中…':'重新生成任务';
}
async function refreshLive(){
  if(activePage!=='dashboard') return;
  await refreshFg();
  // Every 30s refresh only task-status DOM instead of a full render()
  // (keeps the file-picker guard; skips settings/goal/motivation fields).
  if(Date.now() - _lastFullSyncTs > 30000){
    _lastFullSyncTs = Date.now();
    try{
      state = normalizeState(await api('state'));
      renderTasksLight();
      setSyncState('synced','刚刚');
      _lastSyncTs = Date.now();
    }catch(e){
      setSyncState('error', syncErrorDetail());
    }
  }
}
// Lightweight task-status DOM refresh for the 30s poll (replaces the full render()).
function renderTasksLight(){
  $('#dashboard')?.classList.toggle('focus-first', !!(state.tasks||[]).some(t=>!t.done && t.status!=='skipped'));
  const doingTask=(state.tasks||[]).find(t=>!t.done && t.status==='doing');
  if(doingTask){
    $('#statusPill').textContent='专注中'; $('#statusPill').style.color='var(--accent)';
  } else if(state.break_active){
    $('#statusPill').textContent='休息中'; $('#statusPill').style.color='var(--warn)';
  } else {
    $('#statusPill').textContent='就绪'; $('#statusPill').style.color='var(--accent)';
  }
  renderMotivationScore();
  renderBreakWidget();
  renderOnboarding();
  renderCurrentTaskBar();
  syncFocusStatusPill();
  renderSessionControls();
  renderRecoveryAction();
  renderReview();
  renderGoalUnderstanding();
  // Same file-picker guard as render()
  const _hasFileSelected = $$('#taskList [data-evidence-file]').some(inp => inp.files && inp.files.length);
  const _skipTaskList = _hasFileSelected || Date.now() - _lastFilePickTs < 5000;
  if(!_skipTaskList){
    const _beforeRects = captureTaskRects();
    $('#taskList').innerHTML = state.tasks.map(taskCard).join('') || '<p class="hint">还没有任务。</p>';
    staggerTasks();
    flipTasks(_beforeRects);
  }
  addTaskAdjustControls();
  renderCrashNotice();
  renderUndoAction();
  renderDailyWrap();
}
async function runGeneration(){
  setGenerationUi('running','正在启动任务生成…');
  try{
    const started=await api('generate',{}); const jobId=started.job_id; let status=null;
    const deadline=Date.now()+300000;
    while(Date.now()<deadline){
      await new Promise(r=>setTimeout(r,1000));
      status=await api('generate-status');
      if(jobId && status.job_id && status.job_id!==jobId) continue;
      setGenerationUi('running',`${status.step}${status.message?'：'+status.message:''}`);
      if(!status.running) break;
    }
    if(!status || status.running){ setGenerationUi('error','生成超时，任务可能仍在后台处理中。'); return; }
    if(status.mode==='error' || status.mode==='conflict'){
      setGenerationUi('error',`生成失败：${status.message||status.error||'请稍后重试'}`);
      return;
    }
    await load();
    const count=(state.tasks||[]).filter(t=>!t.done).length;
    setGenerationUi(status.mode==='fallback'?'warning':'success',
      status.mode==='fallback'?`AI 生成失败，已使用本地模板生成 ${count} 个任务。`:`生成成功：已生成 ${count} 个待执行任务。`);
  }catch(err){
    setGenerationUi('error',`生成失败：${err.message||err}`);
  }
}
async function run(name){
  try{
    if(name==='generate') return await runGeneration();
    const r = await api(name,{});
    toast(r.message || '完成', r.ok);
    if(name==='evaluate'){
      const passed=(state.tasks||[]).filter(t=>t.done).length, total=(state.tasks||[]).length;
      showModal(passed===total?'验收完成':'验收未完成',`已通过 ${passed}/${total} 项。${passed===total?'今天的任务可以收尾并保存复盘。':'请查看任务卡片中的缺少项和补交建议。'}`,'warn');
    }
    await load();
  }catch(e){
    toast('请求失败：'+e.message, false);
  }
}
document.addEventListener('click', async e=>{
  const reviewLog=e.target.closest?.('[data-review-log]');
  if(reviewLog){
    const mode=reviewLog.dataset.reviewLog, events=mode==='events', archives=mode==='archives', modal=$('#reviewLogModal');
    $('#reviewLogTitle').textContent=events?'事件流':archives?'每日归档':'退出记录';
    $('#reviewLogSubtitle').textContent=events?'查看任务与系统操作记录。':archives?'查看或保存每日复盘归档。':'查看退出申请及原因。';
    $('#eventList').hidden=!events; $('#archiveList').hidden=!archives; $('#quitList').hidden=events||archives; $('#archiveToday').hidden=!archives;
    setModalOpen(modal,true); return;
  }
  if(e.target.id==='closeReviewLog'||e.target.id==='doneReviewLog'||e.target.id==='reviewLogModal'){
    setModalOpen($('#reviewLogModal'),false); return;
  }
  if(e.target.closest?.('#openAdvancedSettings')){
    const modal=$('#advancedSettingsModal');
    document.body.appendChild(modal);
    setModalOpen(modal,true);
    return;
  }
  if(e.target.closest?.('#closeAdvancedSettings') || e.target.closest?.('#cancelAdvancedSettings') || (e.target.id==='advancedSettingsModal')){
    setModalOpen($('#advancedSettingsModal'),false);
    return;
  }
  if(e.target.closest?.('#saveAdvancedSettings')){
    $('#saveSettings').click();
    setModalOpen($('#advancedSettingsModal'),false);
    return;
  }
  if(e.target.closest?.('[data-goto-queue]')){
    scrollIntoViewSafe($('#taskList'), {block:'start'});
    return;
  }
  if(e.target.closest?.('[data-start-recovery]')){
    try{ const r=await api('recovery',{}); await api('task-state',{idx:r.idx,status:'doing'}); toast('补救行动已开始'); await load(); }
    catch(err){ toast('当前没有需要补救的任务',false); }
    return;
  }
  const feedback=e.target.closest?.('[data-feedback]');
  if(feedback){
    const labels={too_hard:'任务太难',stuck:'我卡住了',no_time:'今天时间不够',wrong_direction:'任务方向不对',too_easy:'任务太简单'};
    const kind=feedback.dataset.feedback, idx=+feedback.dataset.feedbackIdx;
    const detail=await promptDlg(kind==='stuck'?'现在只做哪一个最小动作？（例如：找到 X 的调用位置）':'补充反馈（可直接确认）',labels[kind]||'');
    if(!detail) return;
    try{
      const result=await api('feedback',{idx,kind,text:detail}), d=result.decision||{};
      if(kind==='stuck'){
        await api('task-state',{idx,status:'partial',continuation_note:`先做：${detail}` ,next_action:`先做：${detail}`});
      }
      showModal(d.applied?'已自动调整':'已记录反馈',`${d.reason||''}\n可信度：${Math.round((d.confidence||0)*100)}%${(d.evidence||[]).length?'\n依据：'+d.evidence.join('；'):''}`,d.applied?'success':'warn');
      await load();
    }catch(err){ toast('反馈失败：'+err.message,false); }
    return;
  }
  const rating=e.target.closest?.('[data-recall-rating]');
  if(rating){
    try{
      await api('task-rating',{idx:+rating.dataset.ratingIdx,rating:rating.dataset.recallRating});
      toast(`已记录回忆质量：${rating.textContent.trim()}`); await load();
    }catch(err){ toast('评分失败：'+err.message,false); }
    return;
  }
  const agentAction=e.target.closest?.('[data-agent]');
  if(agentAction){
    try{ await api('agent-'+agentAction.dataset.agent,{run_id:agentAction.dataset.runId}); toast('Agent 状态已更新'); await load(); }
    catch(err){ toast('Agent 操作失败：'+err.message,false); }
    return;
  }
  if(e.target.dataset.startTask!==undefined){
    const idx=+e.target.dataset.startTask, previous=state.tasks[idx]?.status;
    state.tasks[idx].status='doing'; state.tasks[idx].started_at=new Date().toISOString(); render();
    try{ await api('task-state',{idx,status:'doing'}); await load(); }
    catch(err){ state.tasks[idx].status=previous; render(); toast('开始任务失败：'+err.message,false); }
    return;
  }
  if(e.target.closest?.('[data-recovery]')){
    const r=await api('recovery',{}); await api('task-state',{idx:r.idx,status:'doing'}); toast('已开始今日恢复'); await load(); return;
  }
  const sessionAction=e.target.closest?.('[data-session-action]');
  if(sessionAction){
    const idx=+sessionAction.dataset.sessionIdx, action=sessionAction.dataset.sessionAction;
    const status=action==='partial'?'partial':'paused';
    const continuation_note=action==='partial' ? await promptDlg('留下下一次继续的位置（可选）',state.tasks[idx]?.continuation_note||'') : '';
    const previous=state.tasks[idx]?.status;
    state.tasks[idx].status=status; render();
    try{
      await api('task-state',{idx,status,continuation_note});
      toast(action==='partial'?'已保存部分成果':action==='end'?'本次专注已结束':'本次专注已暂停'); await load();
    }catch(err){
      state.tasks[idx].status=previous; render(); toast('暂停任务失败：'+err.message,false);
    }
    return;
  }
  if(e.target.id==='startNextCycle'){
    try{ await api('next-cycle',{}); toast('复盘完成，正在生成下一轮任务'); await runGeneration(); }
    catch(err){ toast('无法开始下一轮：'+err.message,false); }
    return;
  }
  const start=e.target.closest?.('[data-begin-task]');
  if(start){
    try{
      const result=await api('agent-start',{idx:+start.dataset.beginTask,max_steps:20});
      toast(result.run?.status==='awaiting_confirmation'?'等待确认':'Agent 已开始执行'); await load();
    }catch(err){ toast('无法开始任务：'+err.message,false); }
    return;
  }
  const taskAction=e.target.closest('[data-task-action]');
  if(taskAction){
    const task=taskAction.closest('.task'), idx=[...$$('#taskList .task')].indexOf(task);
    if(idx>=0){ await api('task-adjust',{idx,action:taskAction.dataset.taskAction}); toast(taskAction.dataset.taskAction==='extend'?'\u5df2\u5ef6\u957f 15 \u5206\u949f':'\u5df2\u8df3\u8fc7\u4eca\u5929\u4efb\u52a1'); await load(); }
    return;
  }
  if(e.target.id==='undoAction'){
    await api('undo',{}); toast('\u5df2\u64a4\u9500\u4e0a\u4e00\u6b21\u64cd\u4f5c'); await load(); return;
  }
  const edit=e.target.closest('[data-edit]');
  if(edit){
    e.stopImmediatePropagation();
    const idx=+edit.dataset.edit, text=await promptDlg('编辑任务',state.tasks[idx]?.text||'');
    if(text){const reason=state.plan_locked?await promptDlg('计划已锁定，请填写修改原因'):''; await api('task',{idx,text,reason}); await load();}
    return;
  }
  if(e.target.id==='dashboardToggleLock'){
    e.stopImmediatePropagation();
    const reason=state.plan_locked?await promptDlg('解锁原因'):'';
    await api('lock-plan',{locked:!state.plan_locked,reason}); toast(state.plan_locked?'已解锁':'已锁定'); await load(); return;
  }
  if(e.target.dataset.removeArchive!==undefined){
    const date=e.target.dataset.removeArchive;
    if(!confirmDlg(`确定删除 ${date} 的归档吗？此操作不可恢复。`)) return;
    await api('archive-delete',{date}); toast('归档已删除'); await load(); return;
  }
  const archive = e.target.closest('[data-archive]');
  if(archive){
    const a = state.archives?.[+archive.dataset.archive];
    if(a) showModal('归档详情', `${a.date || ''}\n${a.goal || ''}\n任务：${doneCount(a)}/${(a.tasks||[]).length}\n前台：${Object.entries(a.fg||{}).map(([k,v])=>`${k} ${v}s`).join('，') || '暂无数据'}`, 'warn');
    return;
  }
  if(e.target.dataset.evidenceFile!==undefined){
    logEvent('upload_pick','点击上传交付物按钮',{idx:+e.target.dataset.evidenceFile});
    _lastFilePickTs = Date.now();
    return;
  }
  if(e.target.dataset.goto){
    const page = e.target.dataset.goto;
    $$('.nav-item').forEach(x=>x.classList.remove('active'));
    $(`.nav-item[data-page="${page}"]`)?.classList.add('active');
    switchPage(page);
    return;
  }
  const nav = e.target.closest('.nav-item');
  if(nav){
    const page = nav.dataset.page;
    $$('.nav-item').forEach(x=>x.classList.remove('active'));
    nav.classList.add('active');
    switchPage(page);
    return;
  }
  if(e.target.id==='refresh') return load();
  if(e.target.id==='generate') return run('generate');
  if(e.target.id==='evaluate') return run('evaluate');
  if(e.target.dataset.aiEvaluate!==undefined){
    const idx=+e.target.dataset.aiEvaluate, t=state.tasks[idx] || {};
    let evidence=t.evidence || await askEvidence();
    if(!evidence){ e.target.checked=!!t.done; showModal('不能验收', '未提交交付物或证据。请先上传交付物，或填写文件路径/链接/完成说明。', 'warn'); return; }
    await api('task-evidence',{idx,evidence});
    const r=await api('evaluate-task',{idx}); await load();
    const detail=r.result||{};
    const followUp=(detail.next_steps||[])[0], missing=(detail.missing||[]).join('；');
    showModal(r.pass?'验收通过':'需要补交',[detail.reason,missing&&`缺少：${missing}`,followUp&&`下一步：${followUp}`].filter(Boolean).join('\n')||'验收完成',r.pass?'success':'warn'); return;
  }
  if(e.target.id==='addTask'){
    const list=$('#taskList');
    if(!list.querySelector('.task-add-inline')){
      const row=document.createElement('div');
      row.className='task task-add-inline';
      row.innerHTML='<div style="width:28px;display:grid;place-items:center"><svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="var(--accent)" stroke-width="1.5" stroke-linecap="round"><path d="M10 4v12M4 10h12"/></svg></div><div class="task-body"><input id="addTaskInput" class="task-input" placeholder="输入任务名称，回车添加" style="width:100%"></div>';
      list.prepend(row);
      const inp=row.querySelector('#addTaskInput');
      inp.focus();
      inp.addEventListener('keydown',async ev=>{
        if(ev.key==='Enter'&&inp.value.trim()){
          const reason=state.plan_locked?await promptDlg('计划已锁定，请填写修改原因'):'';
          await api('tasks',{tasks:[...state.tasks.map(t=>({...t})),{text:inp.value.trim()}],reason});
          await load();
        }else if(ev.key==='Escape'){ row.remove(); }
      });
      inp.addEventListener('blur',()=>{ if(!inp.value.trim()) row.remove(); });
    }
    return;
  }
  if(e.target.id==='regenerateTasks'){
    const goal=(state.goals||[])[state.active_goal||0]||'当前目标';
    if(confirmDlg(`重新生成“${goal}”的任务？当前目标的任务将被替换，其他目标不受影响。`)) await runGeneration();
    return;
  }
  if(e.target.id==='generationRetry'){ await runGeneration(); return; }
  if(e.target.id==='saveSettings'){
    const goals=$('#goalsText').value.split(/\n+/).map(x=>x.trim()).filter(Boolean);
    if(!goals.length){ showModal('无法保存','请至少设置一个目标。','warn'); return; }
    const current=state.goals?.[state.active_goal||0];
    const active=Math.max(0, goals.indexOf(current));
    await api('settings',{goals,active_goal:active,autostart:$('#autostart').checked,goal_details:{
      outcome:$('#goalOutcome')?.value.trim()||'', deadline:$('#goalDeadline')?.value||'',
      baseline:$('#goalBaseline')?.value.trim()||'',
      success_criteria:($('#goalCriteria')?.value||'').split(/\n+/).map(x=>x.trim()).filter(Boolean),
      constraints:($('#goalConstraints')?.value||'').split(/\n+/).map(x=>x.trim()).filter(Boolean)
    },task_gen:{
      available_minutes:+($('#genAvailableMinutes')?.value || 120),
      task_count:+($('#genTaskCount')?.value || 3),
      max_task_minutes:+($('#genMaxTaskMinutes')?.value || 45),
      prefer_continuation:!!$('#genPreferContinuation')?.checked,
      force_measurable_output:!!$('#genForceOutput')?.checked
    },desired_retention:+($('#desiredRetention')?.value || 0.9),privacy:{
      cloud_ai_enabled:!!$('#privacyCloudAI')?.checked,
      upload_raw_file_enabled:!!$('#privacyUpload')?.checked,
      fine_grained_fg_enabled:!!$('#privacyFG')?.checked,
      share_foreground_with_ai:!!$('#privacyShareFG')?.checked,
      diagnostic_log_verbose:!!$('#privacyLogVerbose')?.checked
    },focus_guard:{enabled:!!$('#focusGuardEnabled')?.checked},schedule:{focus_template:$('#focusTemplate')?.value || '90'},workspace:$('#workspace')?.value.trim()||''});
    toast('设置已保存'); await load();
  }
  if(e.target.id==='pauseFocus30'){
    await api('focus-policy',{action:'pause',minutes:30}); toast('已暂停专注 30 分钟'); await load(); return;
  }
  if(e.target.id==='clearFocusOverrides'){
    if(!confirmDlg('清除所有应用例外吗？')) return;
    await api('focus-policy',{action:'clear_overrides'}); toast('应用例外已清除'); await load(); return;
  }
  if(e.target.id==='saveDeepseekKey'){
    const key=$('#deepseekKey').value.trim();
    if(!key && !confirmDlg('确定要清空 DeepSeek Key 吗？清空后将无法使用 AI 生成任务/识别应用。')) return;
    await api('deepseek-key',{key});
    $('#deepseekKey').value='';
    toast('Key 已保存'); await load(); return;
  }
  if(e.target.id==='quickStartBreak'){
    try{
      await api('break',{reason:$('#quickBreakReason').value,minutes:+$('#quickBreakMinutes').value});
      toast('已开始休息'); await load();
    }catch(_){}
    return;
  }
  if(e.target.id==='quitApp'){
    const r=$('#quitReason').value.trim();
    const unfinishedCnt = state.tasks.filter((t,i)=>!t.done).length;
    const doneCnt = state.tasks.length - unfinishedCnt;
    const focusSeconds = Object.values(state.fg||{}).reduce((sum,v)=>sum+Number(v||0),0);
    const summaryPrefix = `\u5df2\u5b8c\u6210 ${doneCnt} \u9879\uff0c\u672a\u5b8c\u6210 ${unfinishedCnt} \u9879\uff0c\u672c\u65e5\u524d\u53f0\u65f6\u95f4 ${formatDuration(focusSeconds)}`;
    const confirmMsg = unfinishedCnt>0
      ? `还有 ${unfinishedCnt} 个任务未完成。${r?'':'请先填写退出原因。'}\n点击确定将完全退出 Task Verge 程序（包括托盘）。`
      : '点击确定将完全退出 Task Verge 程序（包括托盘）。';
    if(!confirmDlg(summaryPrefix+'\\n'+confirmMsg)) return;
    try{
      const res=await api('quit',{reason:r});
      toast(res.message||'正在退出',res.ok);
      showExitScreen();
    }catch(_){}
    return;
  }
  if(e.target.id==='archiveToday'){ await api('archive',{}); toast('今日已归档'); await load(); }
  if(e.target.dataset.archiveToday!==undefined){ await api('archive',{}); toast('\u5df2\u4fdd\u5b58\u4eca\u65e5\u590d\u76d8'); await load(); return; }
  if(e.target.id==='exportData'){
    const data=await api('export');
    const blob=new Blob([JSON.stringify({exported_at:new Date().toISOString(),...data},null,2)],{type:'application/json'});
    const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=`task-verge-${new Date().toISOString().slice(0,10)}.json`; a.click(); setTimeout(()=>URL.revokeObjectURL(a.href),1000);
    toast('本地数据已导出'); return;
  }
  if(e.target.id==='clearFgData'){
    if(!confirmDlg('确定清除所有前台时间数据吗？此操作不可恢复。')) return;
    try{
      const r = await api('clear-fg',{});
      toast(r.message||'已清除', r.ok);
      await load();
    }catch(_){}
    return;
  }
  if(e.target.id==='dismissCrash'){
    try{ await api('dismiss-crash',{}); }catch(_){}
    await load();
    return;
  }
});
document.addEventListener('change', async e=>{
  if(e.target.dataset.evidenceFile!==undefined){
    await uploadEvidenceFile(+e.target.dataset.evidenceFile, e.target);
    return;
  }
  if(e.target.id==='goalSelectTop'){ await api('active-goal',{active_goal:+e.target.value||0}); await load(); }
});
// Kept only to populate allApps/usableApps (used by task app chips); rules-page DOM no longer exists.
async function loadProcesses(){
  const r = await api('processes');
  allApps = r.apps || (r.processes || []).map(p=>({exe:p,name:p,title:'',source:'running',icon:''}));
  usableApps = r.usable_apps || allApps;
}
// Keep the first-level navigation about action and review; advanced app rules stay available in settings/code paths.
  document.querySelector('[data-page="review"] span')?.replaceChildren('记录');
  document.querySelector('[data-page="review"]')?.setAttribute('title','记录');
  setInterval(updateClock,1000);
  setInterval(refreshLive,2000);
  setInterval(heartbeat,4000);
  // Dashboard skeleton while the first state fetch is in flight (replaced by real rows in load()).
  (function(){
    const list = $('#taskList');
    if(list && !list.children.length) list.innerHTML = '<div class="task skeleton"></div><div class="task skeleton"></div><div class="task skeleton"></div>';
  })();
  // Claim the backend session before the first protected state request.
ensureSession().then(ok=>{
    if(!ok) throw new Error('无法建立本地会话，请重试或接管窗口');
    return load();
}).then(showPrivacyNotice).then(loadProcesses).catch(e=>{ toast(e.message,false); if(confirmDlg('本地会话被其他窗口占用。关闭旧窗口后，是否立即重试？')) location.reload(); });
async function claimBackendSession(){
  try{
    const desktopToken=new URLSearchParams(location.search).get('desktop_token');
    const headers=desktopToken?{'X-TaskVerge-Desktop':desktopToken}:{};
    const r = await fetch('/api/claim',{headers});
    const j = await r.json();
    if(j.ok){ sessionToken = j.token; return true; }
  }catch(_){}
  return false;
}
// Retry claiming session if lost (e.g. another tab closed, lock expired)
async function ensureSession(){
  if(sessionToken) return true;
  if(!sessionClaimPromise) sessionClaimPromise=(async()=>{
    for(let i=0;i<9;i++){ // backend session expires after 8 seconds
      if(await claimBackendSession()) return true;
      await new Promise(r=>setTimeout(r, 1000));
    }
    return false;
  })();
  try{ return await sessionClaimPromise; }
  finally{ sessionClaimPromise=null; }
}
async function heartbeat(){
  if(!sessionToken) return;
  try{
    await fetch('/api/heartbeat',{method:'POST',headers:{'Content-Type':'application/json','X-Session':sessionToken},body:'{}'});
  }catch(_){}
}
document.addEventListener('keydown', e=>{
  // Modal accessibility: Esc closes the topmost open modal; Tab is trapped inside it.
  if(e.key==='Escape' && _openModals.size){
    e.preventDefault();
    const top=[..._openModals].pop();
    // Click the cancel button when present so pending prompt/evidence promises resolve as 'cancel'.
    const cancelBtn = top.querySelector('[data-evidence-cancel], [data-cancel]');
    if(cancelBtn) cancelBtn.click();
    else closeModal(top);
    return;
  }
  if(e.key==='Tab' && _openModals.size){
    const top=[..._openModals].pop();
    const items=modalFocusables(top);
    if(!items.length){ e.preventDefault(); return; }
    const first=items[0], last=items[items.length-1];
    if(!top.contains(document.activeElement)){ e.preventDefault(); first.focus(); return; }
    if(e.shiftKey && document.activeElement===first){ e.preventDefault(); last.focus(); return; }
    if(!e.shiftKey && document.activeElement===last){ e.preventDefault(); first.focus(); return; }
  }
});
async function showPrivacyNotice(){
  if(state.privacy?.monitoring_consent) return;
  const msg = '本应用会每 2 秒采集一次前台窗口标题（如 "chrome: 某网页"），用于统计专注时间。\n\n数据默认仅保存在本地 fgtime.json；只有你在设置中单独授权后，云 AI 才能使用前台应用时间统计。你可以随时关闭或清除。\n\n点击「我知道了」即表示你已知晓并同意本地监控。';
  if(confirmDlg(msg, '隐私提示')){
    await api('privacy-consent',{accepted:true});
    state.privacy.monitoring_consent=true;
  }
}
