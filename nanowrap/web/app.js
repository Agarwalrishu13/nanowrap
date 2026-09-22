/* nanoWrap — the page.
   No framework, no build step: one script the browser can read as it is.
   Everything the app says to a person is written for a person. */

const $ = (id) => document.getElementById(id);
const app = {
  state: null,        // everything /api/state said
  files: [],          // what you have dropped in, as the server sees them
  task: null,         // the job you picked
  jobId: null,
  cursor: 0,          // how many log lines we have already shown
  timer: null,
  step: 'machine',
};

// --------------------------------------------------------------------------
// Talking to the server
// --------------------------------------------------------------------------
async function get(url) {
  const response = await fetch(url);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || ('The app answered with ' + response.status));
  return data;
}

async function post(url, body, raw) {
  const response = await fetch(url, {
    method: 'POST',
    headers: raw ? {} : { 'Content-Type': 'application/json' },
    body: raw || JSON.stringify(body || {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || ('The app answered with ' + response.status));
  return data;
}

function toast(message, kind) {
  const node = document.createElement('div');
  node.className = 'toast' + (kind ? ' ' + kind : '');
  node.textContent = message;
  $('toasts').appendChild(node);
  setTimeout(() => node.remove(), kind === 'bad' ? 9000 : 5000);
}

function busy(button, on, label) {
  if (!button) return;
  if (on) {
    button.dataset.label = button.textContent;
    button.disabled = true;
    button.innerHTML = '<span class="spinner"></span> ' + (label || 'working…');
  } else {
    button.disabled = false;
    button.textContent = button.dataset.label || label || 'Done';
  }
}

// --------------------------------------------------------------------------
// Steps
// --------------------------------------------------------------------------
function go(step) {
  app.step = step;
  document.querySelectorAll('.panel').forEach((panel) => { panel.hidden = true; });
  $('panel-' + step).hidden = false;
  document.querySelectorAll('.step').forEach((button) => {
    const name = button.dataset.step;
    button.classList.toggle('active', name === step);
    button.classList.toggle('done', rank(name) < rank(step));
  });
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

const rank = (name) => ['machine', 'drop', 'choose', 'result'].indexOf(name);

// --------------------------------------------------------------------------
// 1. What is on this computer
// --------------------------------------------------------------------------
async function loadState(checking) {
  busy($('checkBtn'), true, 'looking…');
  try {
    const data = checking ? await post('/api/check') : await get('/api/state');
    app.state = data;
    renderMachine();
    renderHistory();
    fillSettings();
    if (data.message) toast(data.message, 'good');
  } catch (error) {
    toast(error.message, 'bad');
  } finally {
    busy($('checkBtn'), false, 'Check again');
  }
}

function renderMachine() {
  const data = app.state;
  if (!data) return;
  const ready = data.tools.filter((tool) => tool.available).length;
  $('machinePill').textContent = ready + ' of ' + data.tools.length + ' ready';
  $('machinePill').className = 'pill ' + (ready > 1 ? 'good' : 'warn');
  $('machineNote').textContent = data.note;
  $('readySummary').textContent = data.tools.filter((tool) => tool.available && !tool.builtin).length
    + ' of the extra programs are here. Anything marked “not installed” still has a one-line way to get it.';

  $('toolGrid').innerHTML = '';
  data.tools.forEach((tool) => {
    const card = document.createElement('div');
    card.className = 'tool ' + (tool.available ? 'here' : 'away');

    const head = document.createElement('div');
    head.className = 'head';
    const name = document.createElement('b');
    name.textContent = (tool.builtin ? '🧩 ' : (tool.available ? '✅ ' : '⬜ ')) + tool.called;
    const badge = document.createElement('span');
    badge.className = 'badge ' + (tool.builtin ? 'builtin' : (tool.available ? 'here' : 'away'));
    badge.textContent = tool.builtin ? 'always here' : (tool.available ? 'ready' : 'not installed');
    head.append(name, badge);

    const what = document.createElement('div');
    what.className = 'what';
    what.textContent = tool.what;

    const used = document.createElement('div');
    used.className = 'used-for';
    used.textContent = tool.used_for;

    card.append(head, what, used);

    if (tool.available && tool.path) {
      const where = document.createElement('div');
      where.className = 'where';
      where.textContent = tool.path + (tool.version ? '  ·  ' + tool.version : '');
      card.appendChild(where);
    }
    if (!tool.available) {
      const how = document.createElement('div');
      how.className = 'getit';
      how.textContent = tool.get_it || ('Get it from ' + tool.homepage);
      card.appendChild(how);
      const hint = document.createElement('div');
      hint.className = 'used-for';
      hint.textContent = 'Open a terminal, paste that line, then press “Check again” above.';
      card.appendChild(hint);
    }
    $('toolGrid').appendChild(card);
  });
  renderAllJobs();
}

function renderAllJobs() {
  const holder = $('allJobs');
  holder.innerHTML = '';
  const byTool = {};
  (app.state?.tasks || []).forEach((task) => {
    (byTool[task.tool] = byTool[task.tool] || []).push(task);
  });
  Object.keys(byTool).forEach((toolId) => {
    const tool = (app.state.tools || []).find((entry) => entry.id === toolId) || { called: toolId };
    const group = document.createElement('div');
    const title = document.createElement('h3');
    title.textContent = tool.called;
    group.appendChild(title);
    byTool[toolId].forEach((task) => group.appendChild(jobCard(task, false)));
    holder.appendChild(group);
  });
}

function jobCard(task, selectable) {
  const card = document.createElement('button');
  card.className = 'job' + (task.ready ? '' : ' off') + (app.task && app.task.id === task.id ? ' picked' : '');
  card.type = 'button';

  const top = document.createElement('div');
  top.className = 'top';
  const name = document.createElement('b');
  name.textContent = task.title;
  const badge = document.createElement('span');
  badge.className = 'badge ' + (task.ready ? 'here' : 'away');
  badge.textContent = task.ready ? 'ready' : 'needs ' + toolName(task.tool);
  top.append(name, badge);

  const blurb = document.createElement('div');
  blurb.className = 'blurb';
  blurb.textContent = task.blurb;
  card.append(top, blurb);

  if (!task.ready) {
    const needs = document.createElement('div');
    needs.className = 'needs';
    const tool = (app.state.tools || []).find((entry) => entry.id === task.tool);
    needs.textContent = 'To use this one: ' + (tool?.get_it || 'install ' + toolName(task.tool));
    card.appendChild(needs);
  } else if (selectable) {
    card.addEventListener('click', () => pickTask(task));
  }
  return card;
}

const toolName = (id) => (app.state.tools || []).find((tool) => tool.id === id)?.called || id;

// --------------------------------------------------------------------------
// 2. Dropping files in
// --------------------------------------------------------------------------
function wireDrop() {
  const zone = $('drop');
  ['dragenter', 'dragover'].forEach((name) => zone.addEventListener(name, (event) => {
    event.preventDefault();
    zone.classList.add('over');
  }));
  ['dragleave', 'drop'].forEach((name) => zone.addEventListener(name, (event) => {
    event.preventDefault();
    zone.classList.remove('over');
  }));
  zone.addEventListener('drop', (event) => {
    const items = event.dataTransfer?.files;
    if (items && items.length) uploadAll(items);
  });
  $('browseBtn').addEventListener('click', () => $('fileInput').click());
  $('fileInput').addEventListener('change', (event) => {
    if (event.target.files.length) uploadAll(event.target.files);
    event.target.value = '';
  });
}

async function uploadAll(fileList) {
  const files = Array.from(fileList);
  for (const file of files) {
    const row = document.createElement('div');
    row.className = 'file-row';
    row.innerHTML = '<div class="what"><b></b><span class="muted"></span>' +
      '<div class="upload-bar"><span></span></div></div>';
    row.querySelector('b').textContent = file.name;
    const detail = row.querySelector('span');
    detail.textContent = (file.size / 1048576).toFixed(1) + ' MB — copying in…';
    $('droppedCard').hidden = false;
    $('fileList').appendChild(row);

    try {
      const started = await post('/api/upload/start', {
        name: file.name, size_mb: file.size / 1048576,
      });
      const chunk = started.chunk_bytes || 4194304;
      let offset = 0;
      while (offset < file.size) {
        const slice = file.slice(offset, offset + chunk);
        const answer = await post('/api/upload/chunk?id=' + started.id + '&offset=' + offset, null, slice);
        offset = answer.received;
        row.querySelector('.upload-bar > span').style.width =
          Math.round(offset * 100 / Math.max(1, file.size)) + '%';
      }
      const finished = await post('/api/upload/finish', { id: started.id });
      app.files.push(finished);
      detail.textContent = finished.size_mb.toFixed(1) + ' MB — ' + finished.kind_word;
      row.querySelector('.upload-bar').remove();
      if (finished.note) toast(finished.note, 'bad');
    } catch (error) {
      detail.textContent = 'could not be copied in';
      row.querySelector('.upload-bar').remove();
      toast(file.name + ': ' + error.message, 'bad');
    }
  }
  renderFiles();
  go('choose');
}

function renderFiles() {
  $('droppedCard').hidden = app.files.length === 0;
  $('chooseHeadline').textContent = app.files.length === 1
    ? app.files[0].name : app.files.length + ' files';
  $('chooseSummary').textContent = app.files.length
    ? app.files.map((file) => file.name + ' (' + file.size_mb.toFixed(1) + ' MB, ' + file.kind_word + ')').join('  ·  ')
    : '';
  renderJobs();
}

function renderJobs() {
  const kinds = new Set(app.files.map((file) => file.kind));
  const many = app.files.length > 1;
  const ready = (app.state?.tasks || []).filter((task) => {
    if (task.wants === 'any') return true;
    return kinds.has(task.wants);
  }).filter((task) => !many || task.many);

  $('chooseHint').textContent = app.files.length
    ? (ready.length + ' job' + (ready.length === 1 ? '' : 's') + ' fit what you dropped in.')
    : 'Drop a file in first.';
  const holder = $('jobList');
  holder.innerHTML = '';
  ready.forEach((task) => holder.appendChild(jobCard(task, true)));
  if (!ready.length && app.files.length) {
    holder.innerHTML = '<p class="muted">None of nanoWrap’s jobs recognise this kind of file. ' +
      'The built-in ones (packing, numbering) work on anything.</p>';
  }
  $('jobForm').hidden = true;
  $('goRow').hidden = true;
}

// --------------------------------------------------------------------------
// 3. Choosing a job and answering its questions
// --------------------------------------------------------------------------
function pickTask(task) {
  app.task = task;
  renderJobs();
  const form = $('jobForm');
  form.innerHTML = '';
  form.hidden = false;
  $('goRow').hidden = false;
  $('goBtn').textContent = task.title;

  const lead = document.createElement('div');
  lead.className = 'card highlight';
  lead.style.marginTop = '6px';
  lead.innerHTML = '<div class="label">You picked</div><h2></h2><p class="muted"></p>';
  lead.querySelector('h2').textContent = task.title;
  lead.querySelector('p').textContent = task.blurb;
  form.appendChild(lead);

  task.fields.forEach((field) => form.appendChild(fieldNode(field)));

  const note = document.createElement('p');
  note.className = 'muted';
  note.textContent = app.files.length > 1
    ? 'It will work through your ' + app.files.length + ' files one after another.'
    : 'Your original file is never changed — the result is a new file.';
  form.appendChild(note);
  form.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function fieldNode(field) {
  const wrap = document.createElement('div');
  wrap.className = 'field';
  const label = document.createElement('label');
  label.textContent = field.label;
  wrap.appendChild(label);

  if (field.type === 'choice') {
    const group = document.createElement('div');
    group.className = 'choices';
    field.options.forEach((option) => {
      const choice = document.createElement('label');
      choice.className = 'choice';
      const input = document.createElement('input');
      input.type = 'radio';
      input.name = 'f_' + field.name;
      input.value = option.value;
      input.checked = option.value === field.default;
      const text = document.createElement('span');
      text.textContent = option.label;
      choice.append(input, text);
      group.appendChild(choice);
    });
    wrap.appendChild(group);
  } else {
    const input = document.createElement('input');
    input.type = field.type === 'number' ? 'number' : 'text';
    input.id = 'f_' + field.name;
    input.value = field.default || '';
    if (field.placeholder) input.placeholder = field.placeholder;
    wrap.appendChild(input);
  }
  if (field.help) {
    const help = document.createElement('div');
    help.className = 'hint';
    help.textContent = field.help;
    wrap.appendChild(help);
  }
  return wrap;
}

function answers() {
  const values = {};
  (app.task?.fields || []).forEach((field) => {
    if (field.type === 'choice') {
      const picked = document.querySelector('input[name="f_' + field.name + '"]:checked');
      values[field.name] = picked ? picked.value : field.default;
    } else {
      values[field.name] = $('f_' + field.name)?.value || '';
    }
  });
  return values;
}

// --------------------------------------------------------------------------
// 4. Running it, and watching
// --------------------------------------------------------------------------
async function runJob() {
  if (!app.task) return;
  busy($('goBtn'), true, 'starting…');
  try {
    const started = await post('/api/run', {
      task: app.task.id,
      files: app.files.map((file) => file.path),
      values: answers(),
    });
    app.jobId = started.job_id;
    app.cursor = 0;
    $('runLog').textContent = '';
    $('runCommand').textContent = '…';
    $('runningCard').hidden = false;
    $('doneCard').hidden = true;
    $('failedCard').hidden = true;
    $('failedLog').hidden = true;
    $('runSpinner').style.display = '';
    $('stopBtn').hidden = false;
    $('runTitle').textContent = app.task.sentence || 'Working…';
    $('runBar').style.width = '0%';
    go('result');
    poll();
  } catch (error) {
    toast(error.message, 'bad');
  } finally {
    busy($('goBtn'), false, 'Do it');
  }
}

function poll() {
  clearTimeout(app.timer);
  app.timer = setTimeout(ask, 350);
}

async function ask() {
  if (!app.jobId) return;
  let payload;
  try {
    payload = await get('/api/job/' + app.jobId + '?since=' + app.cursor);
  } catch (error) {
    toast(error.message, 'bad');
    return;
  }
  if (payload.log && payload.log.length) {
    const log = $('runLog');
    const wasAtBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 40;
    const commands = payload.log.filter((line) => line.startsWith('$ '));
    if (commands.length && $('runCommand').textContent.trim() === '…') {
      $('runCommand').textContent = commands.join('\n');
    }
    log.append(payload.log.join('\n') + '\n');
    if (wasAtBottom) log.scrollTop = log.scrollHeight;
    app.cursor = payload.cursor;
  }
  if (typeof payload.progress === 'number') $('runBar').style.width = payload.progress + '%';

  if (payload.state === 'running') {
    poll();
    return;
  }

  $('runSpinner').style.display = 'none';
  $('stopBtn').hidden = true;
  $('runTitle').textContent = payload.state === 'done' ? 'Finished' : 'It stopped';
  if (payload.state === 'done') {
    showResult(payload.result);
  } else {
    $('failedSentence').textContent = payload.error || 'It did not finish.';
    $('failedLog').textContent = ($('runLog').textContent || '').split('\n').slice(-40).join('\n');
    $('failedCard').hidden = false;
  }
  loadState();
}

function showResult(result) {
  $('doneCard').hidden = false;
  $('doneSentence').textContent = result.note || 'Your file is ready.';
  const grid = $('resultGrid');
  grid.innerHTML = '';

  (result.files || []).forEach((file) => {
    const card = document.createElement('div');
    card.className = 'result-card';
    const name = document.createElement('div');
    name.className = 'name';
    name.textContent = (file.is_folder ? '📁 ' : '📄 ') + file.name;
    const size = document.createElement('div');
    size.className = 'size';
    size.textContent = file.size_mb.toFixed(1) + ' MB' + (file.is_folder ? ' in total' : '');
    const button = document.createElement('button');
    button.className = 'btn primary';
    button.textContent = file.is_folder ? 'Download it as one zip' : 'Download it';
    button.addEventListener('click', () => {
      window.location.href = file.download;
    });
    card.append(name, size, button);
    grid.appendChild(card);
  });

  const summary = document.createElement('p');
  summary.className = 'muted';
  if (result.saved_pct !== null && result.saved_pct !== undefined) {
    summary.innerHTML = 'It started at <b>' + result.before_mb.toFixed(1) + ' MB</b> and finished at <b>' +
      result.after_mb.toFixed(1) + ' MB</b> — <span class="saved">' +
      (result.saved_pct > 0 ? result.saved_pct + '% smaller' : 'about the same size') + '</span>.';
  } else {
    summary.textContent = 'Made ' + (result.files || []).length + ' thing' +
      ((result.files || []).length === 1 ? '' : 's') + ' in nanoWrap’s folder.';
  }
  grid.appendChild(summary);
  if (result.command) $('runCommand').textContent = result.command;
  if (app.state?.settings?.open_folder_when_done) reveal(result.folder);
}

async function reveal(name) {
  try {
    const answer = await post('/api/reveal', { name: name || '' });
    toast(answer.message, answer.opened ? 'good' : 'bad');
  } catch (error) {
    toast(error.message, 'bad');
  }
}

function renderHistory() {
  const holder = $('historyList');
  if (!holder || !app.state) return;
  holder.innerHTML = '';
  const items = app.state.history || [];
  if (!items.length) {
    holder.innerHTML = '<p class="muted">Nothing yet. Whatever you make will be listed here.</p>';
    return;
  }
  items.forEach((item) => {
    const row = document.createElement('div');
    row.className = 'file-row';
    const what = document.createElement('div');
    what.className = 'what';
    const title = document.createElement('b');
    title.textContent = (item.is_folder ? '📁 ' : '📄 ') + item.name;
    const detail = document.createElement('span');
    const when = new Date((item.when || 0) * 1000).toLocaleString();
    detail.textContent = (item.title || '') + '  ·  ' + (item.size_mb || 0).toFixed(1) + ' MB  ·  ' + when;
    what.append(title, detail);
    row.appendChild(what);
    if (item.here) {
      const button = document.createElement('button');
      button.className = 'btn small';
      button.textContent = 'Download';
      button.addEventListener('click', () => { window.location.href = '/api/download/' + item.name; });
      row.appendChild(button);
    } else {
      const gone = document.createElement('span');
      gone.className = 'muted';
      gone.textContent = 'cleared out';
      row.appendChild(gone);
    }
    holder.appendChild(row);
  });
}

// --------------------------------------------------------------------------
// Settings
// --------------------------------------------------------------------------
function fillSettings() {
  const settings = app.state?.settings || {};
  $('openFolder').checked = !!settings.open_folder_when_done;
  $('keepDays').value = settings.keep_days ?? 7;
  $('maxUpload').value = settings.max_upload_mb ?? 2048;
  $('folderInfo').textContent = 'Finished files: ' + (app.state?.folder || '') +
    (app.state?.free_mb >= 0 ? '   (' + app.state.free_mb.toLocaleString() + ' MB free)' : '');
  const tools = (app.state?.tools || []).filter((tool) => !tool.builtin);
  $('aboutInfo').textContent = tools.map((tool) =>
    tool.called + ': ' + (tool.available ? (tool.path + (tool.version ? ' (' + tool.version + ')' : '')) : 'not installed')
  ).join('\n');
  $('siblingsInfo').textContent = 'nanolaama (talk to an AI on your own computer), nanolearn (drop a ' +
    'spreadsheet, get an answer machine), nanosay (have anything read out loud), nonoforge (make a ' +
    'whole project without coding), nanohome (one window for all of them).';
}

async function saveSettings() {
  try {
    const answer = await post('/api/settings', {
      open_folder_when_done: $('openFolder').checked,
      keep_days: Number($('keepDays').value) || 7,
      max_upload_mb: Number($('maxUpload').value) || 2048,
    });
    app.state.settings = answer.settings;
    toast('Saved.', 'good');
  } catch (error) {
    toast(error.message, 'bad');
  }
}

function openModal(id) { $(id).classList.add('open'); }
function closeModal(id) { $(id).classList.remove('open'); }

// --------------------------------------------------------------------------
// Practice files, so the app can be tried with nothing to hand
// --------------------------------------------------------------------------
async function makeSamples() {
  busy($('sampleBtn'), true, 'making them…');
  try {
    const answer = await post('/api/sample', {});
    (answer.files || []).forEach((file) => app.files.push(file));
    renderFiles();
    toast(answer.message, 'good');
    go('choose');
  } catch (error) {
    toast(error.message, 'bad');
  } finally {
    busy($('sampleBtn'), false, 'Make me some practice files');
  }
}

// --------------------------------------------------------------------------
// Wiring
// --------------------------------------------------------------------------
function main() {
  wireDrop();
  document.querySelectorAll('.step').forEach((button) => {
    button.addEventListener('click', () => go(button.dataset.step));
  });
  $('toDropBtn').addEventListener('click', () => go('drop'));
  $('toChooseBtn').addEventListener('click', () => go('choose'));
  $('backToDropBtn').addEventListener('click', () => go('drop'));
  $('showJobsBtn').addEventListener('click', () => {
    const card = $('allJobsCard');
    card.hidden = !card.hidden;
    $('showJobsBtn').textContent = card.hidden ? 'See every job it can do' : 'Hide the list';
    if (!card.hidden) card.scrollIntoView({ behavior: 'smooth' });
  });
  $('checkBtn').addEventListener('click', () => loadState(true));
  $('clearFilesBtn').addEventListener('click', () => {
    app.files = [];
    $('fileList').innerHTML = '';
    renderFiles();
    toast('Taken out. They were only copies.', 'good');
  });
  $('sampleBtn').addEventListener('click', makeSamples);
  $('cancelJobBtn').addEventListener('click', () => { app.task = null; renderJobs(); });
  $('goBtn').addEventListener('click', runJob);
  $('stopBtn').addEventListener('click', async () => {
    try { await post('/api/job/' + app.jobId + '/stop', {}); } catch (error) { toast(error.message, 'bad'); }
  });
  $('revealBtn').addEventListener('click', () => reveal(''));
  $('againBtn').addEventListener('click', () => { app.task = null; renderJobs(); go('choose'); });
  $('startOverBtn').addEventListener('click', () => {
    app.files = []; app.task = null; app.jobId = null;
    $('fileList').innerHTML = '';
    renderFiles();
    go('machine');
  });
  $('tryAgainBtn').addEventListener('click', () => { app.task = null; renderJobs(); go('choose'); });
  $('showLogBtn').addEventListener('click', () => { $('failedLog').hidden = !$('failedLog').hidden; });
  $('settingsBtn').addEventListener('click', () => openModal('settingsModal'));
  $('revealFolderBtn').addEventListener('click', () => reveal(''));
  $('openFolder').addEventListener('change', saveSettings);
  $('keepDays').addEventListener('change', saveSettings);
  $('maxUpload').addEventListener('change', saveSettings);
  $('forgetHistoryBtn').addEventListener('click', async () => {
    const answer = await post('/api/forget', { what: 'history' });
    toast(answer.message, 'good');
    loadState();
  });
  $('clearAllBtn').addEventListener('click', async () => {
    const answer = await post('/api/forget', { what: 'all' });
    $('tidyLog').textContent = answer.message;
    toast(answer.message, 'good');
    loadState();
  });
  document.querySelectorAll('[data-close]').forEach((button) => {
    button.addEventListener('click', () => closeModal(button.dataset.close));
  });
  document.querySelectorAll('.backdrop').forEach((backdrop) => {
    backdrop.addEventListener('click', (event) => {
      if (event.target === backdrop) backdrop.classList.remove('open');
    });
  });
  loadState();
}

main();
