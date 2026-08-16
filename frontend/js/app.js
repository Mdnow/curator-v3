/* ═══════════════════════════════════════════
   КУРАТОР v3 — JavaScript
   Modular, clean, intentional
   ═══════════════════════════════════════════ */

const API = '/api';
const RU_MONTHS = ['январь','февраль','март','апрель','май','июнь','июль','август','сентябрь','октябрь','ноябрь','декабрь'];
const RU_DAYS = ['воскресенье','понедельник','вторник','среда','четверг','пятница','суббота'];

// ═══ State ═══
let token = localStorage.getItem('curator_v3_token');
let currentUser = null;
let selectedDate = todayStr();
let calYear, calMonth;
let currentPage = 'notes';
let isMobile = () => window.innerWidth <= 932;
let drawerOpen = false;
let lastCenterPage = 'notes';

// ═══ Utils ═══
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);
function todayStr() {
  const d = new Date();
  return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
}
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function escAttr(s) { return esc(s).replace(/"/g, '&quot;'); }

function fmtDate(iso) {
  if (!iso) return '';
  const p = String(iso).slice(0, 10).split('-');
  if (p.length !== 3) return String(iso);
  return p[2] + '.' + p[1] + '.' + p[0];
}
function toast(msg) { const el = $('#toast'); el.textContent = msg; el.classList.add('show'); setTimeout(() => el.classList.remove('show'), 2000); }
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

// ═══ API ═══
async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (token) opts.headers['Authorization'] = 'Bearer ' + token;
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(API + path, opts);
  if (r.status === 401) { logout(); throw new Error('unauthorized'); }
  if (!r.ok) { const err = await r.json().catch(() => ({ detail: 'ошибка' })); throw new Error(err.detail || 'ошибка'); }
  return r.json();
}

// ═══ Auth ═══
function initAuth() {
  if (token) {
    api('GET', '/me').then(u => { currentUser = u.user; startApp(); }).catch(() => {
      token = null; localStorage.removeItem('curator_v3_token'); showAuth();
    });
  } else { showAuth(); }
}
function showAuth() { $('#authOverlay').style.display = 'flex'; $('#appLayout').style.display = 'none'; }
function startApp() { $('#authOverlay').style.display = 'none'; $('#appLayout').style.display = 'flex'; if (isMobile()) { $('#mobileHeader').style.display = 'flex'; $('#mobileBottomBar').style.display = 'flex'; } $('#sidebarUser').textContent = currentUser; initCalendar(); renderPageTitle(); loadProjects(); loadPageData(); }
function logout() { token = null; currentUser = null; localStorage.removeItem('curator_v3_token'); showAuth(); }

async function handleAuth(mode) {
  const username = $('#authUsername').value.trim();
  const password = $('#authPassword').value.trim();
  const errEl = $('#authError');
  if (!username || !password) { errEl.textContent = 'заполни все поля'; return; }
  try {
    const data = await api('POST', '/' + mode, { username, password });
    token = data.token; currentUser = data.user;
    localStorage.setItem('curator_v3_token', token);
    startApp();
  } catch (e) { errEl.textContent = e.message || 'ошибка'; }
}

// ═══ Navigation ═══
function navigateTo(page) {
  if (page !== 'chat') {
    lastCenterPage = page;
    closeChatPanelUI();
  }
  currentPage = page;
  closeProjectSilently();
  $$('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.page === page));
  $$('.mobile-tab').forEach(b => b.classList.toggle('active', b.dataset.page === page));
  loadPageData();
  updateMobileHeader();
  if (isMobile() && page !== 'chat') {
    $('#mobileHeader').style.display = 'flex';
    $('#mobileBottomBar').style.display = 'flex';
  }
  if (drawerOpen) closeDrawer();
}

function loadPageData() {
  switch (currentPage) {
    case 'notes': loadNotes(); break;
    case 'tasks': loadTasks(); break;
    case 'goals': loadGoals(); break;
    case 'chat': showChat(); break;
    case 'tiktok': loadTikTok(); break;
  }
  renderPageTitle();
}

// ═══ Calendar ═══
function initCalendar() { const n = new Date(); calYear = n.getFullYear(); calMonth = n.getMonth(); renderCalendar(); }

function renderCalendar() {
  const monthLabel = RU_MONTHS[calMonth] + ' ' + calYear;
  const calMonthEl = $('#calMonth');
  const calMonthMobileEl = $('#calMonthMobile');
  if (calMonthEl) calMonthEl.textContent = monthLabel;
  if (calMonthMobileEl) calMonthMobileEl.textContent = monthLabel;

  const first = new Date(calYear, calMonth, 1);
  const last = new Date(calYear, calMonth + 1, 0);
  let startDay = first.getDay() - 1; if (startDay < 0) startDay = 6;
  let html = '';
  for (let i = 0; i < startDay; i++) { const d = new Date(calYear, calMonth, -startDay+i+1); html += `<div class="cal-day other">${d.getDate()}</div>`; }
  for (let d = 1; d <= last.getDate(); d++) {
    const ds = calYear + '-' + String(calMonth+1).padStart(2,'0') + '-' + String(d).padStart(2,'0');
    const cls = ['cal-day'];
    if (ds === todayStr()) cls.push('today');
    if (ds === selectedDate) cls.push('selected');
    html += `<div class="${cls.join(' ')}" data-date="${ds}">${d}</div>`;
  }
  const rem = 7 - ((startDay + last.getDate()) % 7);
  if (rem < 7) for (let i = 1; i <= rem; i++) html += `<div class="cal-day other">${i}</div>`;

  const calDaysEl = $('#calDays');
  const calDaysMobileEl = $('#calDaysMobile');
  if (calDaysEl) calDaysEl.innerHTML = html;
  if (calDaysMobileEl) calDaysMobileEl.innerHTML = html;

  loadDateMarkers();
}

async function loadDateMarkers() {
  try {
    const dates = await api('GET', '/notes/dates');
    dates.forEach(d => {
      const els = document.querySelectorAll(`.cal-day[data-date="${d.date}"]`);
      els.forEach(el => el.classList.add('has-notes'));
    });
  } catch (e) {}
}

function calNav(dir) { calMonth += dir; if (calMonth > 11) { calMonth = 0; calYear++; } if (calMonth < 0) { calMonth = 11; calYear--; } renderCalendar(); }
function selectDate(ds) { selectedDate = ds; renderCalendar(); renderPageTitle(); loadPageData(); if (isMobile() && drawerOpen) closeDrawer(); }
function goToday() { selectedDate = todayStr(); const n = new Date(); calYear = n.getFullYear(); calMonth = n.getMonth(); renderCalendar(); renderPageTitle(); loadPageData(); if (isMobile() && drawerOpen) closeDrawer(); }

function renderPageTitle() {
  const d = new Date(selectedDate + 'T12:00:00');
  const today = selectedDate === todayStr();
  const titles = { notes: 'Заметки', goals: 'Цели', tasks: 'Задачи', chat: 'Куратор', tiktok: 'Тикток' };
  $('#pageTitle').textContent = titles[currentPage] || '';
  if (currentPage === 'notes' || currentPage === 'tasks') {
    $('#pageSubtitle').textContent = today ? 'Сегодня' : fmtDate(selectedDate) + ', ' + RU_DAYS[d.getDay()];
  } else {
    $('#pageSubtitle').textContent = today ? RU_DAYS[d.getDay()] : fmtDate(selectedDate);
  }
  $('#btnToday').classList.toggle('active', today);
  updateMobileHeader();
}

function updateMobileHeader() {
  if (!isMobile()) return;
  const d = new Date(selectedDate + 'T12:00:00');
  const today = selectedDate === todayStr();
  const titles = { notes: 'ЗАМЕТКИ', goals: 'ЦЕЛИ', tasks: 'ЗАДАЧИ', chat: 'КУРАТОР', tiktok: 'ТИКТОК' };
  const el = $('#mobileHeaderTitle');
  if (el) el.textContent = titles[currentPage] || '';
  const dateEl = $('#mobileHeaderDate');
  if (dateEl) {
    dateEl.textContent = today ? 'Сегодня' : fmtDate(selectedDate);
  }
}

// ═══ Notes ═══
async function loadNotes() {
  hideAllSections(); $('#notesSection').style.display = 'block';
  try {
    const notes = await api('GET', '/notes?date=' + selectedDate);
    if (!notes.length) { $('#notesList').innerHTML = ''; $('#emptyState').style.display = 'block'; return; }
    $('#emptyState').style.display = 'none';
    const groups = clusterNotes(notes);
    let html = '';
    for (const [title, items] of Object.entries(groups)) {
      html += `<div class="note-group"><div class="group-header"><span class="group-label">${esc(title)}</span><span class="group-count">${items.length}</span><div class="group-line"></div></div><div class="notes-grid">`;
      for (const note of items) {
        const time = fmtTimeMsk(note.created_at, false);
        const title = noteTitle(note);
        const summary = noteSummary(note);
        let aiHtml = '';
        if (note.ai_category || (note.ai_theses && note.ai_theses.length)) {
          const sent = note.ai_sentiment;
          const sentLabel = sent > 0.3 ? 'светлое' : sent < -0.3 ? 'тёмное' : '';
          const thesesHtml = (note.ai_theses && note.ai_theses.length)
            ? `<div class="note-ai-theses">${note.ai_theses.map(t => `<div class="note-ai-thesis">${esc(t)}</div>`).join('')}</div>`
            : '';
          aiHtml = `<div class="note-ai">
            ${note.ai_category ? `<span class="note-ai-category">${esc(note.ai_category)}</span>` : ''}
            ${thesesHtml}
            ${sentLabel ? `<span class="note-ai-sentiment">${sentLabel}</span>` : ''}
          </div>`;
        }
        let threadHtml = '';
        if (note.thread_id) {
          threadHtml = `<div class="note-thread" data-thread="${esc(note.thread_id)}">нить: ${esc(note.thread_id.slice(0,8))}</div>`;
        }
        html += `<div class="note-card ${note.is_favorited ? 'favorited' : ''}" data-note-id="${note.id}">
          <div class="note-title">${esc(title)}</div>
          <div class="note-summary">${esc(summary)}</div>
          <div class="note-body" hidden>
            <div class="note-content" data-note-text="${escAttr(note.content)}">${esc(note.content)}</div>
            ${threadHtml}${aiHtml}
          </div>
          <div class="note-actions">
            <button class="note-action-btn" data-edit-note="${note.id}" title="редактировать">&#9998;</button>
            <button class="note-action-btn" data-discuss-note="${note.id}" data-discuss-text="${escAttr(note.content)}" title="обсудить с куратором">&#9671;</button>
          </div>
          <div class="note-meta">
            <button class="note-fav" data-fav-note="${note.id}" title="в избранное">${note.is_favorited ? '&#9733;' : '&#9734;'}</button>
            <button class="note-assign-btn ${note.project_id ? 'assigned' : ''}" data-assign-note="${note.id}" data-assign-cur="${note.project_id || 0}" title="${note.project_id ? 'сменить проект' : 'в проект'}">
              <svg class="assign-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                <line x1="12" y1="11" x2="12" y2="17"></line>
                <line x1="9" y1="14" x2="15" y2="14"></line>
              </svg>
            </button>
            <span class="note-expand-btn" data-expand-note="${note.id}" title="развернуть текст">показать текст</span>
            <span class="note-time">${time}</span>
            ${note.mood ? `<span class="note-mood">${esc(note.mood)}</span>` : ''}
            <button class="note-delete" data-id="${note.id}">&#10005;</button>
          </div>
        </div>`;
      }
      html += '</div></div>';
    }
    $('#notesList').innerHTML = html;
  } catch (e) {
    $('#notesList').innerHTML = '<div class="empty-state"><div class="empty-icon">&#9888;</div><div class="empty-text">ошибка загрузки</div></div>';
  }
}

function clusterNotes(notes) {
  if (notes.length <= 1) return notes.length ? { 'Заметки': notes } : {};
  const groups = {};
  for (const note of notes) { const cat = note.ai_category || 'Другое'; if (!groups[cat]) groups[cat] = []; groups[cat].push(note); }
  return Object.fromEntries(Object.entries(groups).sort((a, b) => b[1].length - a[1].length));
}

function noteTitle(note) {
  if (note.ai_title && note.ai_title.trim()) return note.ai_title.trim().slice(0, 80);
  const first = (note.content || '').split('\n')[0].trim();
  return (first || 'Заметка').slice(0, 80);
}

function noteSummary(note) {
  if (note.ai_summary && note.ai_summary.trim()) return note.ai_summary.trim().slice(0, 200);
  const lines = (note.content || '').split('\n').map(l => l.trim()).filter(Boolean);
  const rest = lines.slice(1).join(' ');
  return rest.slice(0, 200);
}

function toggleNoteBody(id) {
  const card = document.querySelector(`.note-card[data-note-id="${id}"]`);
  if (!card) return;
  const body = card.querySelector('.note-body');
  const btn = card.querySelector('.note-expand-btn');
  if (!body) return;
  if (body.hasAttribute('hidden')) {
    body.removeAttribute('hidden');
    card.classList.add('expanded');
    if (btn) btn.textContent = 'свернуть';
  } else {
    body.setAttribute('hidden', '');
    card.classList.remove('expanded');
    if (btn) btn.textContent = 'показать текст';
  }
}

function hideHeadsUp() { const hu = $('#headsUp'); if (hu) hu.style.display = 'none'; }

function showHeadsUp(related) {
  const hu = $('#headsUp');
  const list = $('#headsUpList');
  if (!hu || !list) return;
  list.innerHTML = related.map(n => {
    const snippet = (n.ai_summary || n.content || '').slice(0, 110);
    return `<div class="heads-up-item" data-related-id="${n.id}" data-related-text="${escAttr(n.content)}" title="${escAttr(n.content)}">
      <span class="heads-up-date">${esc(fmtDate(n.note_date))}</span>
      <span class="heads-up-text">${esc(snippet)}</span>
    </div>`;
  }).join('');
  hu.style.display = 'block';
}

async function saveNote() {
  const input = $('#noteInput');
  const content = input.value.trim();
  if (!content) return;
  const saveBtn = $('#saveBtn'); const aiStatus = $('#aiStatus');
  saveBtn.textContent = '...'; saveBtn.disabled = true; aiStatus.classList.add('active');
  try {
    const result = await api('POST', '/notes', { content, note_date: selectedDate, tags: [], mood: '' });
    input.value = ''; autoResize(); updateCharCount();
    toast('сохранено');
    await loadNotes(); loadDateMarkers();
  } catch (e) { toast('ошибка сохранения'); }
  saveBtn.textContent = 'СОХРАНИТЬ'; saveBtn.disabled = false; aiStatus.classList.remove('active');
}

async function toggleNoteFavorite(id) { try { const r = await api('POST', '/notes/' + id + '/favorite'); toast(r.is_favorited ? 'в избранном' : 'убрано'); await loadNotes(); } catch (e) { toast('ошибка'); } }
async function deleteNote(id) { try { await api('DELETE', '/notes/' + id); toast('удалено'); await loadNotes(); } catch (e) { toast('ошибка'); } }

// ═══ Edit Note ═══
let editingNoteId = null;

function startEditNote(id) {
  const card = document.querySelector(`.note-card[data-note-id="${id}"]`);
  if (!card) return;
  const body = card.querySelector('.note-body');
  if (body && body.hasAttribute('hidden')) toggleNoteBody(id);
  const contentEl = card.querySelector('.note-content');
  const oldText = contentEl.dataset.noteText;
  editingNoteId = id;

  contentEl.outerHTML = `<textarea class="note-edit-input" id="noteEditInput" rows="3">${oldText}</textarea>`;
  const textarea = $('#noteEditInput');
  textarea.focus();
  textarea.setSelectionRange(textarea.value.length, textarea.value.length);

  const actions = card.querySelector('.note-actions');
  actions.innerHTML = `
    <button class="note-action-btn note-action-save" data-save-edit="${id}">&#10003; сохранить</button>
    <button class="note-action-btn note-action-cancel" data-cancel-edit="${id}">&#10005; отмена</button>
  `;
}

function cancelEditNote(id) {
  editingNoteId = null;
  loadNotes();
}

async function saveEditNote(id) {
  const textarea = $('#noteEditInput');
  if (!textarea) return;
  const newContent = textarea.value.trim();
  if (!newContent) { toast('пустая заметка'); return; }
  try {
    await api('PUT', '/notes/' + id, { content: newContent });
    toast('обновлено');
    editingNoteId = null;
    await loadNotes();
  } catch (e) { toast('ошибка'); }
}

// ═══ Discuss with Curator ═══
function discussWithCurator(text) {
  const short = text.length > 200 ? text.slice(0, 200) + '...' : text;
  $('#chatInput').value = 'Расскажи подробнее об этой мысли: "' + short + '"';
  navigateTo('chat');
  setTimeout(() => $('#chatInput').focus(), 100);
}

// ═══ Daily Summary (Итог дня) ═══
async function dailySummary() {
  const el = $('#dailySummary');
  el.style.display = 'block';
  el.innerHTML = '<div class="patterns-loading">думаю над итогами дня...</div>';

  try {
    const [notes, patterns] = await Promise.all([
      api('GET', '/notes?date=' + selectedDate),
      api('GET', '/insights/daily'),
    ]);

    let summaryHtml = '<div class="summary-content">';

    if (notes.length > 0) {
      summaryHtml += `<div class="summary-section">
        <div class="summary-label">заметок за день</div>
        <div class="summary-big">${notes.length}</div>
      </div>`;

      const categories = {};
      for (const n of notes) {
        const cat = n.ai_category || 'другое';
        categories[cat] = (categories[cat] || 0) + 1;
      }
      const catHtml = Object.entries(categories)
        .sort((a, b) => b[1] - a[1])
        .map(([cat, cnt]) => `<span class="summary-tag">${esc(cat)} (${cnt})</span>`)
        .join('');
      if (catHtml) {
        summaryHtml += `<div class="summary-section">
          <div class="summary-label">темы дня</div>
          <div class="summary-tags">${catHtml}</div>
        </div>`;
      }

      const sentiments = notes.filter(n => n.ai_sentiment).map(n => n.ai_sentiment);
      if (sentiments.length) {
        const avg = sentiments.reduce((a, b) => a + b, 0) / sentiments.length;
        const moodLabel = avg > 0.3 ? 'светлое' : avg > 0 ? 'спокойное' : avg > -0.3 ? 'нейтральное' : 'тревожное';
        summaryHtml += `<div class="summary-section">
          <div class="summary-label">настроение дня</div>
          <div class="summary-big">${moodLabel}</div>
        </div>`;
      }
    }

    if (patterns.key_insight || patterns.emotional_arc) {
      summaryHtml += `<div class="summary-section summary-insight">
        <div class="summary-label">инсайт</div>
        ${patterns.emotional_arc ? `<p>${esc(patterns.emotional_arc)}</p>` : ''}
        ${patterns.key_insight ? `<p><strong>${esc(patterns.key_insight)}</strong></p>` : ''}
        ${patterns.suggestion ? `<p class="summary-suggestion">${esc(patterns.suggestion)}</p>` : ''}
      </div>`;
    }

    if (patterns.recurring_themes && patterns.recurring_themes.length) {
      summaryHtml += `<div class="summary-section">
        <div class="summary-label">повторяющиеся темы</div>
        <div class="summary-tags">${patterns.recurring_themes.map(t => `<button class="summary-tag theme-btn" data-theme="${escAttr(t)}" title="обсудить с куратором">${esc(t)}</button>`).join('')}</div>
        <div class="summary-theme-hint">нажми на тему — куратор поможет увидеть паттерн и связи</div>
      </div>`;
    }

    summaryHtml += '</div>';
    el.innerHTML = summaryHtml;

  } catch (e) {
    el.innerHTML = '<div class="patterns-loading">ошибка загрузки</div>';
  }
}

function discussTheme(theme) {
  const msg = 'Тема «' + theme + '» снова повторилась в моих заметках. Почему она вообще образовалась? Помоги увидеть паттерн и связи между заметками — какие мысли и события её питают, к чему она ведёт.';
  $('#chatInput').value = msg;
  navigateTo('chat');
  sendChat();
}

// ═══ Tasks ═══
async function loadTasks() {
  hideAllSections(); $('#tasksSection').style.display = 'block';
  try {
    const tasks = await api('GET', '/tasks?date=' + selectedDate);
    const upcoming = await api('GET', '/tasks/upcoming');
    let html = '';
    if (tasks.length) {
      html += `<div class="note-group"><div class="group-header"><span class="group-label">на этот день</span><span class="group-count">${tasks.length}</span><div class="group-line"></div></div><div class="tasks-list">`;
      for (const task of tasks) html += renderTask(task);
      html += '</div></div>';
    }
    const otherTasks = upcoming.filter(t => t.due_date !== selectedDate);
    if (otherTasks.length) {
      html += `<div class="note-group"><div class="group-header"><span class="group-label">ближайшие</span><span class="group-count">${otherTasks.length}</span><div class="group-line"></div></div><div class="tasks-list">`;
      for (const task of otherTasks) html += renderTask(task);
      html += '</div></div>';
    }
    if (!tasks.length && !otherTasks.length) html = '<div class="empty-state"><div class="empty-icon">&#9744;</div><div class="empty-text">нет задач</div></div>';
    $('#tasksList').innerHTML = html;
  } catch (e) { $('#tasksList').innerHTML = '<div class="empty-state"><div class="empty-icon">&#9888;</div><div class="empty-text">ошибка загрузки</div></div>'; }
}

function renderTask(task) {
  const isOverdue = task.due_date && task.due_date < todayStr() && !task.completed;
  const dueStr = task.due_date ? formatDueDate(task.due_date, task.due_time) : '';
  return `<div class="task-card ${task.completed ? 'completed' : ''} ${task.is_favorited ? 'favorited' : ''}">
    <button class="task-fav" data-fav-task="${task.id}">${task.is_favorited ? '&#9733;' : '&#9734;'}</button>
    <div class="task-priority p${task.priority}"></div>
    <div class="task-check ${task.completed ? 'checked' : ''}" data-task-id="${task.id}"></div>
    <div class="task-body"><div class="task-title">${esc(task.title)}</div>${dueStr ? `<div class="task-due ${isOverdue ? 'overdue' : ''}">${dueStr}</div>` : ''}</div>
    <button class="task-delete" data-task-delete="${task.id}">&#10005;</button>
  </div>`;
}

function formatDueDate(date, time) {
  const d = new Date(date + 'T12:00:00');
  const diff = Math.floor((d - new Date(new Date().getFullYear(), new Date().getMonth(), new Date().getDate())) / 86400000);
  let dateStr = '';
  if (diff === 0) dateStr = 'сегодня'; else if (diff === 1) dateStr = 'завтра'; else if (diff === -1) dateStr = 'вчера';
  else dateStr = fmtDate(date);
  return time ? dateStr + ', ' + time : dateStr;
}

async function createTask() {
  const title = $('#taskTitle').value.trim();
  if (!title) return;
  try {
    await api('POST', '/tasks', { title, due_date: $('#taskDate').value || selectedDate, due_time: $('#taskTime').value, priority: parseInt($('#taskPriority').value) || 0 });
    $('#taskTitle').value = ''; $('#taskTime').value = '';
    toast('задача создана'); await loadTasks();
  } catch (e) { toast('ошибка'); }
}

async function toggleTask(id) { try { const tasks = await api('GET', '/tasks?date=' + selectedDate); const task = tasks.find(t => t.id === id); if (task) { await api('PUT', '/tasks/' + id, { completed: task.completed ? 0 : 1 }); await loadTasks(); } } catch (e) {} }
async function deleteTask(id) { try { await api('DELETE', '/tasks/' + id); toast('удалено'); await loadTasks(); } catch (e) {} }
async function toggleTaskFavorite(id) { try { const r = await api('POST', '/tasks/' + id + '/favorite'); toast(r.is_favorited ? 'в избранном' : 'убрано'); await loadTasks(); } catch (e) { toast('ошибка'); } }

// ═══ Goals ═══
async function loadGoals() {
  hideAllSections(); $('#goalsSection').style.display = 'block';
  try {
    const data = await api('GET', '/goals');
    const active = data.active || [];
    const archived = data.archived || [];
    const listEl = $('#goalsList');
    const emptyEl = $('#goalsEmpty');
    if (!active.length && !archived.length) { listEl.innerHTML = ''; emptyEl.style.display = 'block'; return; }
    emptyEl.style.display = 'none';
    const max = Math.max(1, ...active.map(g => g.source_count || 0));
    let html = active.map(g => renderGoal(g, max)).join('');
    if (archived.length) {
      html += `<div class="goals-archived-block">
        <button class="goals-archived-toggle" data-archived-toggle>прошлые направления · ${archived.length}</button>
        <div class="goals-archived-list" style="display:none">${archived.map(g => renderGoal(g, max, true)).join('')}</div>
      </div>`;
    }
    listEl.innerHTML = html;
  } catch (e) {
    $('#goalsList').innerHTML = '<div class="empty-state"><div class="empty-icon">&#9888;</div><div class="empty-text">ошибка загрузки</div></div>';
  }
}

function renderGoal(goal, maxCount = 1, isArchived = false) {
  const cats = (goal.categories || []).map(c => `<span class="goal-cat">${esc(c)}</span>`).join('');
  const ev = (goal.evidence || []).map(e =>
    `<button class="goal-quote" data-goal-date="${esc(e.note_date || '')}">
       <span class="goal-quote-text">«${esc(e.quote)}»</span>
       ${e.note_date ? `<span class="goal-quote-date">${esc(fmtDate(e.note_date))}</span>` : ''}
     </button>`
  ).join('');
  const pct = maxCount > 0 ? Math.round((goal.source_count / maxCount) * 100) : 0;
  const strength = `<div class="goal-strength">
    <div class="goal-strength-bar"><div class="goal-strength-fill" style="width:${Math.max(6, pct)}%"></div></div>
    <div class="goal-strength-label">${goal.source_count} подтверждений${goal.last_activity ? ` · последнее ${esc(goal.last_activity)}` : ''}</div>
  </div>`;
  const pinBtn = isArchived ? '' : `<button class="goal-pin" data-goal-pin="${goal.id}" title="закрепить">${goal.is_pinned ? '&#9733;' : '&#9734;'}</button>`;
  const actions = isArchived
    ? `<button class="goal-activate" data-goal-activate="${goal.id}" title="вернуть в созвездие">вернуть</button>`
    : `<button class="goal-archive" data-goal-archive="${goal.id}" title="убрать из зеркала">в архив</button>`;
  return `<div class="goal-card ${goal.is_pinned ? 'pinned' : ''} ${isArchived ? 'archived' : ''}">
    <div class="goal-header">
      ${pinBtn}
      <div class="goal-title">${esc(goal.title)}</div>
      <div class="goal-actions">${actions}<button class="goal-delete" data-goal-delete="${goal.id}" title="удалить">&#10005;</button></div>
    </div>
    ${goal.description ? `<div class="goal-desc">${esc(goal.description)}</div>` : ''}
    ${cats ? `<div class="goal-cats">${cats}</div>` : ''}
    ${strength}
    <div class="goal-evidence">${ev}</div>
  </div>`;
}

async function generateGoals() {
  const statusEl = $('#goalsStatus');
  try {
    statusEl.style.display = 'flex';
    await api('POST', '/goals/generate');
    toast('пересобираю созвездие');
    let reloads = 0;
    const t = setInterval(async () => {
      reloads++;
      if (currentPage !== 'goals') {
        clearInterval(t);
        statusEl.style.display = 'none';
        return;
      }
      try { await loadGoals(); } catch (e) {}
      if (currentPage !== 'goals') {
        $('#goalsSection').style.display = 'none';
        clearInterval(t);
        statusEl.style.display = 'none';
        return;
      }
      if (reloads >= 20) { clearInterval(t); statusEl.style.display = 'none'; }
    }, 4000);
    setTimeout(() => { clearInterval(t); statusEl.style.display = 'none'; }, 90000);
  } catch (e) {
    statusEl.style.display = 'none';
    toast(e.message || 'ошибка');
  }
}

async function toggleGoalPin(id) {
  try { await api('POST', '/goals/' + id + '/pin'); await loadGoals(); } catch (e) { toast('ошибка'); }
}
async function archiveGoal(id) {
  try { await api('POST', '/goals/' + id + '/archive'); toast('в архив'); await loadGoals(); } catch (e) { toast('ошибка'); }
}
async function activateGoal(id) {
  try { await api('POST', '/goals/' + id + '/activate'); toast('возвращено в созвездие'); await loadGoals(); } catch (e) { toast('ошибка'); }
}
async function deleteGoal(id) {
  try { await api('DELETE', '/goals/' + id); toast('удалено'); await loadGoals(); } catch (e) { toast('ошибка'); }
}

// ═══ Projects ═══
async function loadProjects() {
  try {
    projectsCache = await api('GET', '/projects');
  } catch (e) {
    projectsCache = [];
  }
  renderProjects();
}

function renderProjects() {
  const html = projectsCache.map(p =>
    `<div class="project-item ${currentProjectId === p.id ? 'active' : ''}" data-project-id="${p.id}" title="${escAttr(p.name)}">
      <span class="project-item-name">${esc(p.name)}</span>
      <span class="project-item-meta">${(p.note_count || 0) + (p.msg_count || 0)}</span>
    </div>`
  ).join('');
  const list = $('#projectsList');
  const listM = $('#projectsListMobile');
  const emptyHtml = '<div class="project-item-meta" style="padding:6px 8px">нет проектов</div>';
  if (list) list.innerHTML = html || emptyHtml;
  if (listM) listM.innerHTML = html || emptyHtml;
}

function showAddProjectForm() {
  const form = $('#projectsAddForm');
  const input = $('#projectsAddInput');
  form.style.display = form.style.display === 'none' ? 'block' : 'none';
  if (form.style.display === 'block') input.focus();
}

async function createProject() {
  const input = $('#projectsAddInput');
  const name = input.value.trim();
  input.value = '';
  $('#projectsAddForm').style.display = 'none';
  if (!name) return;
  try {
    const p = await api('POST', '/projects', { name });
    projectsCache.push(p);
    renderProjects();
    toast('проект создан');
    openProject(p.id);
  } catch (e) { toast(e.message || 'ошибка'); }
}

async function createProjectMobile() {
  const input = $('#projectsAddInputMobile');
  const name = input.value.trim();
  input.value = '';
  $('#projectsAddFormMobile').style.display = 'none';
  if (!name) return;
  try {
    const p = await api('POST', '/projects', { name });
    projectsCache.push(p);
    renderProjects();
    toast('проект создан');
    closeDrawer();
    openProject(p.id);
  } catch (e) { toast(e.message || 'ошибка'); }
}

function closeProjectSilently() {
  currentProjectId = null;
  $('#projectSection').classList.remove('active');
  renderProjects();
  if (isMobile()) {
    $('#mobileHeader').style.display = 'flex';
    $('#mobileBottomBar').style.display = 'flex';
  }
}

function openProject(id) {
  currentProjectId = id;
  hideAllSections();
  $('#projectSection').classList.add('active');
  switchProjectTab('chat');
  renderProjects();
  if (isMobile()) {
    $('#mobileHeader').style.display = 'none';
    $('#mobileBottomBar').style.display = 'none';
  }
  loadProjectDetail();
}

function switchProjectTab(tab) {
  $$('.project-tab').forEach(b => b.classList.toggle('active', b.dataset.projectTab === tab));
  const mat = $('#projectMaterialsPane');
  const chat = $('#projectChatPane');
  if (mat) mat.classList.toggle('pane-active', tab === 'materials');
  if (chat) chat.classList.toggle('pane-active', tab === 'chat');
}

function closeProject() {
  closeProjectSilently();
  navigateTo('notes');
}

async function loadProjectDetail() {
  if (!currentProjectId) return;
  const p = await api('GET', '/projects/' + currentProjectId).catch(() => null);
  if (!p) { toast('проект не найден'); closeProject(); return; }
  $('#projectTitleInput').value = p.name;
  $('#projectTitleInput').disabled = true;
  renderProjectNotes(p.notes);
  renderProjectChat(p.messages);
}

function renderProjectNotes(notes) {
  const list = $('#projectNotesList');
  const empty = $('#projectNotesEmpty');
  const countEl = $('#projectMaterialsCount');
  const badge = $('#projectTabCount');
  if (badge) {
    badge.textContent = notes.length;
    badge.classList.toggle('show', notes.length > 0);
  }
  if (countEl) countEl.textContent = notes.length ? notes.length + ' записей' : '';
  if (!notes.length) {
    list.innerHTML = '';
    empty.style.display = 'block';
    return;
  }
  empty.style.display = 'none';
  list.innerHTML = notes.map(n => {
    const title = noteTitle(n);
    const summary = (n.ai_summary || n.content || '').slice(0, 200);
    return `<div class="project-note" data-pnote-id="${n.id}">
      <div class="project-note-title">${esc(title)}</div>
      <div class="project-note-summary">${esc(summary)}</div>
      <div class="project-note-meta">
        <span class="project-note-date">${esc(fmtDate(n.note_date))}</span>
        <div class="project-note-actions">
          <button class="project-note-btn" data-pnote-discuss="${n.id}" data-pnote-text="${escAttr(n.content)}" title="обсудить с куратором">обсудить</button>
          <button class="project-note-btn" data-pnote-unassign="${n.id}" title="убрать из проекта">убрать</button>
        </div>
      </div>
    </div>`;
  }).join('');
}

async function reloadProjectNotes() {
  if (!currentProjectId) return;
  const p = await api('GET', '/projects/' + currentProjectId).catch(() => null);
  if (p) renderProjectNotes(p.notes);
}

async function saveProjectNote() {
  const input = $('#projectNoteInput');
  const content = input.value.trim();
  if (!content || !currentProjectId) return;
  try {
    await api('POST', '/notes', { content, note_date: todayStr(), tags: [], mood: '', project_id: currentProjectId });
    input.value = '';
    toast('в материалы проекта');
    await reloadProjectNotes();
    loadProjects();
  } catch (e) { toast(e.message || 'ошибка'); }
}

function unassignProjectNote(noteId) {
  api('PUT', '/notes/' + noteId, { project_id: 0 }).then(() => {
    toast('убрано из проекта');
    reloadProjectNotes();
    loadProjects();
  }).catch(() => toast('ошибка'));
}

function renderProjectChat(messages) {
  const el = $('#projectChatMessages');
  if (!messages.length) {
    el.innerHTML = '<div class="chat-msg ai">диалог проекта пуст. спроси меня про материалы или расскажи, что хочешь проработать.</div>';
    return;
  }
  el.innerHTML = messages.map(m => chatMsgHtml(m.role === 'assistant' ? 'ai' : 'user', m.content)).join('');
  el.scrollTop = el.scrollHeight;
}

async function sendProjectChat() {
  const input = $('#projectChatInput');
  const msg = input.value.trim();
  if (!msg || !currentProjectId) return;
  const messagesEl = $('#projectChatMessages');
  messagesEl.innerHTML += `<div class="chat-msg user">${esc(msg)}</div>`;
  input.value = '';
  messagesEl.innerHTML += `<div class="chat-msg ai" id="projectChatLoading"><div class="ai-dot"></div> думаю...</div>`;
  messagesEl.scrollTop = messagesEl.scrollHeight;
  try {
    const result = await api('POST', '/ai/chat', { message: msg, project_id: currentProjectId });
    const loadingEl = $('#projectChatLoading'); if (loadingEl) loadingEl.remove();
    const parsed = parseChatReply(result.reply);
    messagesEl.innerHTML += chatMsgHtml('ai', parsed.text);
    if (result.saved && result.saved.text) {
      messagesEl.innerHTML += `<div class="chat-auto-saved">куратор сохранил это в материалы проекта</div>`;
    }
    if (result.note_refs && result.note_refs.length) {
      const refs = result.note_refs.map(n =>
        `<button class="chat-note-ref" data-note-id="${n.id}" data-note-content="${escAttr(n.content)}" data-note-date="${escAttr(n.note_date)}" data-note-title="${escAttr(noteTitle(n))}">` +
          `<span class="chat-note-ref-title">${esc(noteTitle(n))}</span>` +
          `<span class="chat-note-ref-date">${esc(fmtDate(n.note_date))}</span>` +
        `</button>`
      ).join('');
      messagesEl.innerHTML += `<div class="chat-note-refs"><div class="chat-note-refs-label">куратор ссылается на материалы проекта — нажми, чтобы прочитать</div>${refs}</div>`;
    }
    loadProjects();
    await reloadProjectNotes();
  } catch (e) {
    const loadingEl = $('#projectChatLoading'); if (loadingEl) loadingEl.remove();
    messagesEl.innerHTML += `<div class="chat-msg ai">ошибка соединения</div>`;
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function startRenameProject() {
  const input = $('#projectTitleInput');
  input.disabled = false;
  input.focus();
  input.select();
}

async function saveProjectName() {
  const input = $('#projectTitleInput');
  if (!currentProjectId) return;
  const name = input.value.trim();
  if (!name) { input.disabled = true; return; }
  input.disabled = true;
  const prev = projectsCache.find(p => p.id === currentProjectId);
  if (prev && name !== prev.name) {
    try {
      await api('PUT', '/projects/' + currentProjectId, { name });
      toast('переименовано');
    } catch (e) { toast('ошибка'); }
  }
  loadProjects();
}

async function deleteProject() {
  if (!currentProjectId) return;
  const name = $('#projectTitleInput').value.trim();
  if (!confirm('удалить проект «' + name + '»? заметки останутся, диалог проекта удалится')) return;
  try {
    await api('DELETE', '/projects/' + currentProjectId);
    toast('проект удалён');
    closeProject();
    loadProjects();
  } catch (e) { toast('ошибка'); }
}

// ═══ Assign note to project ═══
let assignNoteId = null;

function closeAssignModal() {
  assignNoteId = null;
  $('#assignModal').style.display = 'none';
}

async function openAssignModal(noteId, curProjectId) {
  assignNoteId = noteId;
  const modal = $('#assignModal');
  const list = $('#assignModalList');
  const empty = $('#assignModalEmpty');
  try {
    if (!projectsCache.length) projectsCache = await api('GET', '/projects');
  } catch (e) { projectsCache = []; }
  if (!projectsCache.length && !curProjectId) {
    list.innerHTML = '';
    empty.style.display = 'block';
  } else {
    empty.style.display = 'none';
    const unassignHtml = curProjectId
      ? `<button class="assign-project-btn active" data-assign-project="0">
          <span class="assign-name">убрать из проекта</span>
          <span class="assign-count"></span>
        </button>`
      : '';
    list.innerHTML = unassignHtml + projectsCache.map(p =>
      `<button class="assign-project-btn ${curProjectId === p.id ? 'active' : ''}" data-assign-project="${p.id}">
        <span class="assign-name">${esc(p.name)}</span>
        <span class="assign-count">${(p.note_count || 0)} записей</span>
      </button>`
    ).join('');
  }
  modal.style.display = 'flex';
}

async function assignNoteToProject(projectId) {
  if (!assignNoteId) return;
  try {
    await api('PUT', '/notes/' + assignNoteId, { project_id: projectId });
    toast('заметка в проекте');
  } catch (e) { toast(e.message || 'ошибка'); }
  closeAssignModal();
  loadNotes();
  loadProjects();
}

// ═══ Chat ═══
let currentSessionId = null;
let currentProjectId = null;
let projectsCache = [];

function showChat() {
  openChatPanel();
}

// ═══ Chat Panel (right) ═══
function openChatPanel() {
  $('#chatPanel').classList.add('open');
  $('#chatPanelOverlay').classList.add('show');
  if (isMobile()) {
    $('#mobileHeader').style.display = 'none';
    $('#mobileBottomBar').style.display = 'none';
  }
}

function closeChatPanelUI() {
  $('#chatPanel').classList.remove('open');
  $('#chatPanelOverlay').classList.remove('show');
  if (isMobile()) {
    $('#mobileHeader').style.display = 'flex';
    $('#mobileBottomBar').style.display = 'flex';
  }
}

function closeChatPanel() {
  if (!$('#chatPanel').classList.contains('open')) return;
  closeChatPanelUI();
  navigateTo(lastCenterPage);
}

// ═══ Swipe — свайп влево/вправо с любой точки экрана к панелям ═══
function initSwipe() {
  const THRESHOLD = 72;
  let startX = 0, startY = 0, tracking = false;

  document.addEventListener('touchstart', (e) => {
    if (e.touches.length !== 1) { tracking = false; return; }
    const t = e.touches[0];
    startX = t.clientX; startY = t.clientY;
    tracking = true;
  }, { passive: true });

  document.addEventListener('touchmove', (e) => {
    if (!tracking) return;
    const t = e.touches[0];
    const dx = t.clientX - startX;
    const dy = t.clientY - startY;
    if (Math.abs(dx) < 12 && Math.abs(dy) < 12) return;
    if (Math.abs(dy) > Math.abs(dx) * 1.5) { tracking = false; return; }
    const panelOpen = $('#chatPanel').classList.contains('open');
    if (panelOpen) {
      if (dx > THRESHOLD) {
        e.preventDefault();
        tracking = false;
        closeChatPanel();
      }
      return;
    }
    if (dx < -THRESHOLD) {
      e.preventDefault();
      tracking = false;
      openChatPanel();
    } else if (dx > THRESHOLD) {
      e.preventDefault();
      tracking = false;
      openDrawer();
    }
  }, { passive: false });
}

function newChat() {
  currentSessionId = null;
  $('#chatMessages').innerHTML = '<div class="chat-msg ai">привет. я куратор — помогу структурировать мысли, найти связи, предложить инсайты. о чём думаешь?</div>';
  $('#archivePanel').style.display = 'none';
  $('#chatSection').classList.add('active');
  setTimeout(() => $('#chatInput').focus(), 100);
}

function parseChatReply(text) {
  return { text, saveable: null };
}

function chatMsgHtml(role, text) {
  const copyBtn = role === 'ai'
    ? `<button class="chat-copy" data-copy="${escAttr(text)}" title="копировать">&#10697;</button>`
    : '';
  return `<div class="chat-msg ${role}">${esc(text).replace(/\n/g, '<br>')}${copyBtn}</div>`;
}

async function copyChatText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }
  toast('скопировано');
}

async function saveThought(text) {
  try { await api('POST', '/ai/save-thought', { message: text }); toast('мысль сохранена'); } catch (e) { toast('ошибка'); }
}

function openNoteModal(note) {
  $('#noteModalTitle').textContent = note.title || 'заметка';
  $('#noteModalDate').textContent = note.date ? fmtDate(note.date) : '';
  $('#noteModalBody').textContent = note.content || '';
  $('#noteModalOpenBtn').dataset.noteDate = note.date || '';
  $('#noteModal').hidden = false;
}

function closeNoteModal() {
  $('#noteModal').hidden = true;
}

function openNoteInNotes(date) {
  closeNoteModal();
  if (date) { selectedDate = date; renderCalendar(); renderPageTitle(); }
  navigateTo('notes');
  loadPageData();
}

async function sendChat() {
  const input = $('#chatInput'); const msg = input.value.trim();
  if (!msg) return;
  const messagesEl = $('#chatMessages');
  messagesEl.innerHTML += `<div class="chat-msg user">${esc(msg)}</div>`;
  input.value = '';
  messagesEl.innerHTML += `<div class="chat-msg ai" id="chatLoading"><div class="ai-dot"></div> думаю...</div>`;
  messagesEl.scrollTop = messagesEl.scrollHeight;
  try {
    const result = await api('POST', '/ai/chat', { message: msg, session_id: currentSessionId });
    const loadingEl = $('#chatLoading'); if (loadingEl) loadingEl.remove();
    if (result.session_id) currentSessionId = result.session_id;
    const parsed = parseChatReply(result.reply);
    messagesEl.innerHTML += chatMsgHtml('ai', parsed.text);
    if (result.saved && result.saved.text) {
      messagesEl.innerHTML += `<div class="chat-auto-saved">куратор сохранил это в заметки</div>`;
    }
    if (result.note_refs && result.note_refs.length) {
      const refs = result.note_refs.map(n =>
        `<button class="chat-note-ref" data-note-id="${n.id}" data-note-content="${escAttr(n.content)}" data-note-date="${escAttr(n.note_date)}" data-note-title="${escAttr(noteTitle(n))}">` +
          `<span class="chat-note-ref-title">${esc(noteTitle(n))}</span>` +
          `<span class="chat-note-ref-date">${esc(fmtDate(n.note_date))}</span>` +
        `</button>`
      ).join('');
      messagesEl.innerHTML += `<div class="chat-note-refs"><div class="chat-note-refs-label">куратор ссылается на заметки — нажми, чтобы прочитать полностью</div>${refs}</div>`;
    }
  } catch (e) {
    const loadingEl = $('#chatLoading'); if (loadingEl) loadingEl.remove();
    messagesEl.innerHTML += `<div class="chat-msg ai">ошибка соединения</div>`;
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ═══ Dialogs (archive) ═══
function openArchive() { $('#chatSection').classList.remove('active'); $('#archivePanel').style.display = 'flex'; loadArchiveSessions(); }
function closeArchive() { $('#archivePanel').style.display = 'none'; $('#chatSection').classList.add('active'); }

async function loadArchiveSessions() {
  const list = $('#archiveList'); list.innerHTML = '<div class="archive-empty">загрузка...</div>';
  try {
    const sessions = await api('GET', '/chat/sessions');
    if (!sessions.length) { list.innerHTML = '<div class="archive-empty">нет диалогов</div>'; return; }
    list.innerHTML = sessions.map(s => {
      const date = s.started ? formatArchiveDate(s.started) : 'ранее';
      return `<div class="archive-session" data-session-id="${s.session_id}">
        <div class="archive-session-date">${date}</div>
        <div class="archive-session-preview">${esc(s.preview)}</div>
        <div class="archive-session-count">${s.msg_count} сообщений</div>
        <button class="btn btn-icon archive-session-delete" data-del-session="${s.session_id}" title="удалить">&#10005;</button>
      </div>`;
    }).join('');
  } catch (e) { list.innerHTML = '<div class="archive-empty">ошибка загрузки</div>'; }
}

// Время сервера — naive UTC (Neon GMT, колонки timestamp без tz). Парсим как UTC,
// форматируем явно в московское (UTC+3) — результат не зависит от локали браузера.
function parseAsUtc(value) {
  if (!value) return null;
  let s = String(value);
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(s)) s = s.replace(' ', 'T');
  if (!/(Z|[+-]\d{2}:\d{2})$/.test(s)) s += 'Z';
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

function fmtTimeMsk(value, withDate = true) {
  const d = parseAsUtc(value);
  if (!d) return '';
  const base = { timeZone: 'Europe/Moscow' };
  const opts = withDate
    ? Object.assign(base, { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
    : Object.assign(base, { hour: '2-digit', minute: '2-digit' });
  return d.toLocaleString('ru-RU', opts);
}

function formatArchiveDate(iso) {
  return fmtTimeMsk(iso, true);
}

async function openSessionInChat(sessionId) {
  closeArchive();
  const messagesEl = $('#chatMessages');
  messagesEl.innerHTML = '<div class="chat-msg ai">загрузка...</div>';
  try {
    const messages = await api('GET', '/chat/sessions/' + sessionId);
    if (!messages.length) { messagesEl.innerHTML = '<div class="chat-msg ai">диалог пуст</div>'; return; }
    messagesEl.innerHTML = messages.map(m => {
      const role = m.role === 'assistant' ? 'ai' : 'user';
      return chatMsgHtml(role, m.content);
    }).join('');
    currentSessionId = sessionId;
  } catch (e) {
    messagesEl.innerHTML = '<div class="chat-msg ai">ошибка загрузки диалога</div>';
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function deleteSession(sessionId) {
  try { await api('DELETE', '/chat/sessions/' + sessionId); loadArchiveSessions(); } catch (e) { toast('ошибка'); }
}

async function clearAllChat() {
  try { await api('DELETE', '/chat/history'); loadArchiveSessions(); } catch (e) { toast('ошибка'); }
}

async function searchArchive() {
  const q = $('#archiveSearch').value.trim();
  const list = $('#archiveList'); const results = $('#archiveResults');
  if (!q) { results.style.display = 'none'; list.style.display = 'flex'; return; }
  list.style.display = 'none'; results.style.display = 'flex';
  results.innerHTML = '<div class="archive-empty">поиск...</div>';
  try {
    const data = await api('GET', '/chat/search?q=' + encodeURIComponent(q));
    if (!data.length) { results.innerHTML = '<div class="archive-empty">ничего не найдено</div>'; return; }
    results.innerHTML = data.map(r => {
      const hl = r.snippet.replace(new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi'), '<mark>$1</mark>');
      const roleLabel = r.role === 'user' ? 'ты' : 'куратор';
      return `<div class="archive-result" data-result-session="${r.session_id || 0}"><div class="archive-result-snippet">${roleLabel}: ${hl}</div><div class="archive-result-meta">${r.time ? formatArchiveDate(r.time) : ''}</div></div>`;
    }).join('');
  } catch (e) { results.innerHTML = '<div class="archive-empty">ошибка поиска</div>'; }
}

// ═══ TikTok ═══
const TIKTOK_STATUS_LABELS = {
  pending: 'в очереди',
  downloading: 'скачиваю видео',
  transcribing: 'расшифровываю речь',
  translating: 'перевожу на русский',
  thinking: 'осмысляю',
  saving: 'сохраняю в заметки',
  done: 'в зеркале',
  error: 'ошибка',
};
const TIKTOK_BUSY = ['pending','downloading','transcribing','translating','thinking','saving'];

function tiktokCardHtml(t) {
  const st = t.status || 'pending';
  const cls = st === 'done' ? 'done' : (st === 'error' ? 'error' : 'busy');
  const label = TIKTOK_STATUS_LABELS[st] || st;
  let html = `<div class="tiktok-card ${cls}">
    <div class="tiktok-card-head">
      <span class="tiktok-card-author">@${esc(t.author || '—')}</span>
      <span class="tiktok-card-status">${esc(label)}</span>
    </div>`;
  if (t.title) html += `<div class="tiktok-card-title">${esc(t.title)}</div>`;
  if (t.error) html += `<div class="tiktok-card-error">${esc(t.error)}</div>`;
  html += `<div class="tiktok-card-meta">${t.note_id ? '<span class="in-mirror">в зеркале</span>' : ''}</div></div>`;
  return html;
}

async function loadTikTok() {
  hideAllSections(); $('#tiktokSection').style.display = 'block';
  const list = $('#tiktokList');
  const empty = $('#tiktokEmpty');
  list.innerHTML = '<div class="ai-status active"><div class="ai-dot"></div>загружаю...</div>';
  try {
    const tasks = await api('GET', '/tiktok?day=' + encodeURIComponent(selectedDate));
    const busy = tasks.some(t => TIKTOK_BUSY.includes(t.status));
    if (!tasks.length) {
      list.innerHTML = ''; empty.style.display = 'block';
    } else {
      list.innerHTML = tasks.map(tiktokCardHtml).join('');
      empty.style.display = 'none';
    }
    if (busy) setTimeout(loadTikTok, 5000);
  } catch (e) {
    list.innerHTML = '<div class="tiktok-card error"><div class="tiktok-card-error">' + esc(e.message || 'зеркало дня недоступно') + '</div></div>';
    empty.style.display = 'none';
  }
}

let tiktokPollTimer = null;

async function pollTikTok(taskId) {
  clearTimeout(tiktokPollTimer);
  try {
    const t = await api('GET', '/tiktok/' + taskId);
    const statusEl = $('#tiktokStatusText');
    if (t.status === 'done') {
      $('#tiktokStatus').style.display = 'none';
      toast('перевод сохранён в заметки');
      await loadTikTok();
      if (selectedDate === todayStr()) loadNotes();
      return;
    }
    if (t.status === 'error') {
      $('#tiktokStatus').style.display = 'none';
      toast('ошибка обработки');
      await loadTikTok();
      return;
    }
    if (statusEl) statusEl.textContent = (TIKTOK_STATUS_LABELS[t.status] || t.status) + '...';
    tiktokPollTimer = setTimeout(() => pollTikTok(taskId), 5000);
  } catch (e) {
    $('#tiktokStatus').style.display = 'none';
    toast('зеркало дня не ответило');
    await loadTikTok();
  }
}

async function submitTikTok() {
  const input = $('#tiktokUrl');
  const url = input.value.trim();
  if (!url) return;
  const btn = $('#tiktokBtn');
  btn.textContent = '...'; btn.disabled = true;
  try {
    const res = await api('POST', '/tiktok/import', { url, note_date: selectedDate });
    input.value = '';
    $('#tiktokStatus').style.display = 'flex';
    $('#tiktokStatusText').textContent = 'в очереди...';
    await loadTikTok();
    pollTikTok(res.id);
  } catch (e) {
    $('#tiktokStatus').style.display = 'none';
    toast(e.message || 'ошибка');
  }
  btn.textContent = 'СОХРАНИТЬ'; btn.disabled = false;
}

// ═══ Helpers ═══
function hideAllSections() {
  $('#notesSection').style.display = 'none';
  $('#tasksSection').style.display = 'none';
  $('#goalsSection').style.display = 'none';
  $('#chatSection').classList.remove('active');
  $('#tiktokSection').style.display = 'none';
  $('#archivePanel').style.display = 'none';
  $('#projectSection').classList.remove('active');
}

function autoResize() { const i = $('#noteInput'); i.style.height = 'auto'; i.style.height = Math.min(i.scrollHeight, 200) + 'px'; }
function updateCharCount() { $('#charCount').textContent = $('#noteInput').value.length; }

async function downloadBackup() {
  try {
    const data = await api('GET', '/backup');
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url;
    const d = new Date();
    a.download = `curator-v3-${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}.json`;
    a.click(); URL.revokeObjectURL(url);
    toast(`бекап: ${data.stats.notes} заметок, ${data.stats.tasks} задач, ${data.stats.dreams} записей о снах`);
  } catch (e) { toast('ошибка бекапа'); }
}

async function reanalyzeNotes() {
  try {
    const data = await api('POST', '/notes/reanalyze');
    if (data.reanalyzed > 0) {
      toast(`переанализ: ${data.reanalyzed} заметок в фоне`);
    } else {
      toast('все заметки уже проанализированы');
    }
  } catch (e) { toast('ошибка переанализа'); }
}

// ═══ Mobile Drawer ═══
function openDrawer() {
  drawerOpen = true;
  $('#drawerOverlay').classList.add('open');
  $('#mobileDrawer').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeDrawer() {
  drawerOpen = false;
  $('#drawerOverlay').classList.remove('open');
  $('#mobileDrawer').classList.remove('open');
  document.body.style.overflow = '';
}

// ═══ Selection Toolbar — выделение в любом месте приложения ═══
function initSelectionToolbar() {
  const toolbar = $('#selectionToolbar');
  let selectedText = '';
  let hideTimer = null;

  function showToolbar(range) {
    const rect = range.getBoundingClientRect();
    const tw = toolbar.offsetWidth || 228;
    if (isMobile()) {
      const bh = parseInt(
        getComputedStyle(document.documentElement)
          .getPropertyValue('--bar-height') || '64', 10
      ) || 64;
      toolbar.style.top = 'auto';
      toolbar.style.left = '50%';
      toolbar.style.bottom = 'calc(var(--safe-bottom, 0px) + ' + bh + 'px + 16px)';
      toolbar.style.transform = 'translateX(-50%)';
    } else {
      let top = rect.top - 48;
      if (top < 8) top = rect.bottom + 8;
      let left = rect.left + rect.width / 2 - tw / 2;
      left = Math.max(8, Math.min(left, window.innerWidth - tw - 8));
      toolbar.style.top = top + 'px';
      toolbar.style.left = left + 'px';
      toolbar.style.bottom = 'auto';
      toolbar.style.transform = 'none';
    }
    toolbar.style.display = 'flex';
  }

  function maybeShow() {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.toString().trim()) { hideToolbar(); return; }
    const text = sel.toString().trim();
    if (text.length < 3) { hideToolbar(); return; }
    const range = sel.getRangeAt(0);
    if (toolbar.contains(range.commonAncestorContainer)) return;
    const node = range.commonAncestorContainer;
    const el = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
    if (el && el.closest('input, textarea, [contenteditable="true"]')) { hideToolbar(); return; }
    selectedText = text;
    showToolbar(range);
  }

  function hideToolbar() {
    toolbar.style.display = 'none';
    selectedText = '';
  }

  let selTimer = null;
  document.addEventListener('selectionchange', () => {
    clearTimeout(selTimer);
    selTimer = setTimeout(maybeShow, 250);
  });
  document.addEventListener('mouseup', (e) => {
    if (toolbar.contains(e.target)) return;
    setTimeout(maybeShow, 10);
  });
  document.addEventListener('touchend', (e) => {
    if (toolbar.contains(e.target)) return;
    clearTimeout(hideTimer);
    setTimeout(maybeShow, 300);
  });
  document.addEventListener('mousedown', (e) => {
    if (toolbar.contains(e.target)) return;
    hideToolbar();
  });
  document.addEventListener('touchstart', (e) => {
    if (toolbar.contains(e.target)) return;
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || !sel.toString().trim()) hideToolbar();
    }, 500);
  });
  document.addEventListener('scroll', hideToolbar, true);

  function clearSelection() {
    const sel = window.getSelection();
    if (sel) sel.removeAllRanges();
    hideToolbar();
  }

  $('#selAsk').addEventListener('click', () => {
    if (!selectedText) return;
    $('#chatInput').value = 'расскажи подробнее: "' + selectedText + '"';
    $('#chatInput').focus();
    clearSelection();
    navigateTo('chat');
  });
  $('#selSave').addEventListener('click', async () => {
    if (!selectedText) return;
    await saveThought(selectedText);
    clearSelection();
  });
}

// ═══ Init ═══
document.addEventListener('DOMContentLoaded', () => {
  // Auth
  $('#authLoginBtn').addEventListener('click', () => handleAuth('login'));
  $('#authRegisterBtn').addEventListener('click', () => handleAuth('register'));
  $$('.auth-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      $$('.auth-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const isLogin = tab.dataset.mode === 'login';
      $('#authLoginBtn').style.display = isLogin ? 'block' : 'none';
      $('#authRegisterBtn').style.display = isLogin ? 'none' : 'block';
      $('#authError').textContent = '';
    });
  });

  // Navigation (desktop)
  $$('.nav-btn').forEach(btn => btn.addEventListener('click', () => navigateTo(btn.dataset.page)));

  // Mobile navigation
  $$('.mobile-tab').forEach(btn => btn.addEventListener('click', () => navigateTo(btn.dataset.page)));
  $('#mobileHamburger').addEventListener('click', openDrawer);
  $('#drawerOverlay').addEventListener('click', closeDrawer);

  // Calendar
  $('#btnToday').addEventListener('click', goToday);
  const mobileTodayBtn = $('.btn-today-mobile');
  if (mobileTodayBtn) mobileTodayBtn.addEventListener('click', goToday);
  $('#calDays').addEventListener('click', e => { const day = e.target.closest('[data-date]'); if (day) selectDate(day.dataset.date); });
  const calDaysMobile = $('#calDaysMobile');
  if (calDaysMobile) calDaysMobile.addEventListener('click', e => { const day = e.target.closest('[data-date]'); if (day) selectDate(day.dataset.date); });
  $$('.cal-nav').forEach(btn => btn.addEventListener('click', () => calNav(parseInt(btn.dataset.dir))));

  // Note input
  const noteInput = $('#noteInput');
  noteInput.addEventListener('input', () => { autoResize(); updateCharCount(); });
  noteInput.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveNote(); } });
  $('#saveBtn').addEventListener('click', saveNote);

  // Heads Up — похожие прошлые заметки при вводе
  let headsUpTimer = null;
  noteInput.addEventListener('input', () => {
    clearTimeout(headsUpTimer);
    const text = noteInput.value.trim();
    if (text.length < 12) { hideHeadsUp(); return; }
    headsUpTimer = setTimeout(async () => {
      try {
        const related = await api('POST', '/notes/related', { content: text, limit: 3 });
        if (related && related.length && noteInput.value.trim().length >= 12) {
          showHeadsUp(related);
        } else { hideHeadsUp(); }
      } catch (e) { hideHeadsUp(); }
    }, 1400);
  });
  noteInput.addEventListener('focus', () => { if (noteInput.value.trim().length >= 12) {} });
  document.addEventListener('click', (e) => {
    const hu = $('#headsUp');
    if (hu && !hu.contains(e.target) && e.target !== noteInput) hideHeadsUp();
  });
  $('#headsUpList').addEventListener('click', e => {
    const item = e.target.closest('.heads-up-item');
    if (!item) return;
    const relatedText = (item.dataset.relatedText || '').slice(0, 300);
    const draft = $('#noteInput').value.trim().slice(0, 200);
    $('#chatInput').value = 'Моя прошлая заметка: «' + relatedText + '». А сейчас я пишу: «' + draft + '». Как это связано?';
    hideHeadsUp();
    navigateTo('chat');
    $('#chatInput').focus();
  });

  // Notes
  $('#notesSection').addEventListener('click', e => {
    const fav = e.target.closest('[data-fav-note]');
    if (fav) { toggleNoteFavorite(parseInt(fav.dataset.favNote)); return; }
    const assign = e.target.closest('[data-assign-note]');
    if (assign) { openAssignModal(parseInt(assign.dataset.assignNote), parseInt(assign.dataset.assignCur || 0)); return; }
    const del = e.target.closest('[data-id]');
    if (del) { deleteNote(parseInt(del.dataset.id)); return; }
    const edit = e.target.closest('[data-edit-note]');
    if (edit) { startEditNote(parseInt(edit.dataset.editNote)); return; }
    const discuss = e.target.closest('[data-discuss-note]');
    if (discuss) { discussWithCurator(discuss.dataset.discussText); return; }
    const saveEdit = e.target.closest('[data-save-edit]');
    if (saveEdit) { saveEditNote(parseInt(saveEdit.dataset.saveEdit)); return; }
    const cancelEdit = e.target.closest('[data-cancel-edit]');
    if (cancelEdit) { cancelEditNote(parseInt(cancelEdit.dataset.cancelEdit)); return; }
    const expand = e.target.closest('[data-expand-note]');
    if (expand) { toggleNoteBody(parseInt(expand.dataset.expandNote)); return; }
    const card = e.target.closest('.note-card');
    if (card && card.dataset.noteId && !card.querySelector('.note-edit-input')) {
      toggleNoteBody(parseInt(card.dataset.noteId));
      return;
    }
  });
  $('#notesSection').addEventListener('keydown', e => {
    if (e.target.id === 'noteEditInput') {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); saveEditNote(editingNoteId); }
      if (e.key === 'Escape') { cancelEditNote(editingNoteId); }
    }
  });

  // Tasks
  $('#addTaskBtn').addEventListener('click', () => $('#taskForm').classList.toggle('active'));
  $('#taskFormSubmit').addEventListener('click', createTask);
  $('#tasksSection').addEventListener('click', e => {
    const fav = e.target.closest('[data-fav-task]');
    if (fav) { toggleTaskFavorite(parseInt(fav.dataset.favTask)); return; }
    const check = e.target.closest('[data-task-id]');
    if (check) toggleTask(parseInt(check.dataset.taskId));
    const del = e.target.closest('[data-task-delete]');
    if (del) deleteTask(parseInt(del.dataset.taskDelete));
  });

  // Goals
  $('#goalsRefreshBtn').addEventListener('click', generateGoals);
  $('#goalsSection').addEventListener('click', e => {
    const pin = e.target.closest('[data-goal-pin]');
    if (pin) { toggleGoalPin(parseInt(pin.dataset.goalPin)); return; }
    const arc = e.target.closest('[data-goal-archive]');
    if (arc) { archiveGoal(parseInt(arc.dataset.goalArchive)); return; }
    const act = e.target.closest('[data-goal-activate]');
    if (act) { activateGoal(parseInt(act.dataset.goalActivate)); return; }
    const del = e.target.closest('[data-goal-delete]');
    if (del) { deleteGoal(parseInt(del.dataset.goalDelete)); return; }
    const toggle = e.target.closest('[data-archived-toggle]');
    if (toggle) {
      const list = toggle.nextElementSibling;
      list.style.display = list.style.display === 'none' ? 'block' : 'none';
      return;
    }
    const quote = e.target.closest('[data-goal-date]');
    if (quote && quote.dataset.goalDate) {
      selectedDate = quote.dataset.goalDate;
      renderCalendar(); renderPageTitle();
      navigateTo('notes');
    }
  });

  // Chat
  $('#chatSend').addEventListener('click', sendChat);
  $('#chatInput').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); } });
  $('#chatMessages').addEventListener('click', e => {
    const save = e.target.closest('.btn-save-thought');
    if (save) { saveThought(save.dataset.save); return; }
    const copy = e.target.closest('.chat-copy');
    if (copy) copyChatText(copy.dataset.copy);
    const ref = e.target.closest('.chat-note-ref');
    if (ref) openNoteModal({ id: ref.dataset.noteId, content: ref.dataset.noteContent, date: ref.dataset.noteDate, title: ref.dataset.noteTitle });
  });  $('#chatNewBtn').addEventListener('click', newChat);
  const noteModal = $('#noteModal');
  if (noteModal) {
    $$('[data-close-note-modal]').forEach(el => el.addEventListener('click', closeNoteModal));
    const noteModalOpenBtn = $('#noteModalOpenBtn');
    if (noteModalOpenBtn) noteModalOpenBtn.addEventListener('click', () => openNoteInNotes(noteModalOpenBtn.dataset.noteDate));
  }
  $('#archiveToggle').addEventListener('click', openArchive);
  $('#archiveBack').addEventListener('click', closeArchive);
  $('#archiveClearAll').addEventListener('click', clearAllChat);
  $('#archiveSearch').addEventListener('input', debounce(searchArchive, 300));
  $('#archiveList').addEventListener('click', e => {
    const del = e.target.closest('.archive-session-delete');
    if (del) { e.stopPropagation(); deleteSession(parseInt(del.dataset.delSession)); return; }
    const s = e.target.closest('[data-session-id]');
    if (s) openSessionInChat(parseInt(s.dataset.sessionId));
  });
  $('#archiveResults').addEventListener('click', e => { const r = e.target.closest('[data-result-session]'); if (r) openSessionInChat(parseInt(r.dataset.resultSession)); });
  const chatBackBtn = $('#chatBackBtn');
  if (chatBackBtn) chatBackBtn.addEventListener('click', closeChatPanel);
  const chatCloseBtn = $('#chatCloseBtn');
  if (chatCloseBtn) chatCloseBtn.addEventListener('click', closeChatPanel);
  $('#chatPanelOverlay').addEventListener('click', closeChatPanel);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && $('#chatPanel').classList.contains('open')) closeChatPanel();
  });
  initSwipe();

  // TikTok
  $('#tiktokBtn').addEventListener('click', submitTikTok);
  $('#tiktokUrl').addEventListener('keydown', e => { if (e.key === 'Enter') submitTikTok(); });

  // User menu
  $('#sidebarUser').addEventListener('click', logout);
  $('#logoBtn').addEventListener('click', () => location.reload());
  $('#btnBackup').addEventListener('click', downloadBackup);
  $('#btnDailySummary').addEventListener('click', dailySummary);
  $('#btnReanalyze').addEventListener('click', reanalyzeNotes);
  $('#dailySummary').addEventListener('click', e => {
    const themeBtn = e.target.closest('[data-theme]');
    if (themeBtn) discussTheme(themeBtn.dataset.theme);
  });

  // Mobile drawer buttons
  const mobileBackupBtn = $('.btn-backup-mobile');
  if (mobileBackupBtn) mobileBackupBtn.addEventListener('click', () => { closeDrawer(); downloadBackup(); });
  const mobileSummaryBtn = $('.btn-daily-summary-mobile');
  if (mobileSummaryBtn) mobileSummaryBtn.addEventListener('click', () => { closeDrawer(); dailySummary(); });
  const mobileReanalyzeBtn = $('.btn-reanalyze-mobile');
  if (mobileReanalyzeBtn) mobileReanalyzeBtn.addEventListener('click', () => { closeDrawer(); reanalyzeNotes(); });

  // Selection toolbar
  initSelectionToolbar();

  // Projects
  $('#projectsAdd').addEventListener('click', showAddProjectForm);
  $('#projectsAddInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') createProject();
    if (e.key === 'Escape') { $('#projectsAddForm').style.display = 'none'; }
  });
  $('#projectsAddSubmit').addEventListener('click', createProject);
  $('#projectsAddMobile').addEventListener('click', () => {
    const form = $('#projectsAddFormMobile');
    form.style.display = form.style.display === 'none' ? 'block' : 'none';
    if (form.style.display === 'block') $('#projectsAddInputMobile').focus();
  });
  $('#projectsAddSubmitMobile').addEventListener('click', createProjectMobile);
  $('#projectsAddInputMobile').addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); createProjectMobile(); }
  });
  $('#projectsList').addEventListener('click', e => { const it = e.target.closest('[data-project-id]'); if (it) openProject(parseInt(it.dataset.projectId)); });
  $('#projectsListMobile').addEventListener('click', e => { const it = e.target.closest('[data-project-id]'); if (it) { closeDrawer(); openProject(parseInt(it.dataset.projectId)); } });

  // Project screen
  $('#projectBackBtn').addEventListener('click', closeProject);
  $('#projectRenameBtn').addEventListener('click', startRenameProject);
  $('#projectTitleInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') saveProjectName();
    if (e.key === 'Escape') { $('#projectTitleInput').disabled = true; loadProjects(); }
  });
  $('#projectTitleInput').addEventListener('blur', saveProjectName);
  $('#projectDeleteBtn').addEventListener('click', deleteProject);
  $('#projectNoteSave').addEventListener('click', saveProjectNote);
  $('#projectNoteInput').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveProjectNote(); } });
  $('#projectChatSend').addEventListener('click', sendProjectChat);
  $('#projectChatInput').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendProjectChat(); } });
  $$('.project-tab').forEach(b => b.addEventListener('click', () => switchProjectTab(b.dataset.projectTab)));
  $('#projectNotesList').addEventListener('click', e => {
    const unassign = e.target.closest('[data-pnote-unassign]');
    if (unassign) { unassignProjectNote(parseInt(unassign.dataset.pnoteUnassign)); return; }
    const discuss = e.target.closest('[data-pnote-discuss]');
    if (discuss) {
      $('#chatInput').value = 'Расскажи подробнее об этой мысли: "' + (discuss.dataset.pnoteText || '').slice(0, 200) + '"';
      closeProject();
      setTimeout(() => $('#chatInput').focus(), 100);
    }
  });
  $('#projectChatMessages').addEventListener('click', e => {
    const ref = e.target.closest('.chat-note-ref');
    if (ref) openNoteModal({ id: ref.dataset.noteId, content: ref.dataset.noteContent, date: ref.dataset.noteDate, title: ref.dataset.noteTitle });
  });

  // Assign note to project
  $('#assignModalCancel').addEventListener('click', closeAssignModal);
  $('#assignModal').addEventListener('click', e => { if (e.target === $('#assignModal')) closeAssignModal(); });
  $('#assignModalList').addEventListener('click', e => {
    const btn = e.target.closest('[data-assign-project]');
    if (btn) assignNoteToProject(parseInt(btn.dataset.assignProject));
  });

  // Keyboard shortcuts
  document.addEventListener('keydown', e => {
    if (e.ctrlKey || e.metaKey) {
      if (e.key === 'n') { e.preventDefault(); navigateTo('notes'); $('#noteInput').focus(); }
      if (e.key === 'd') { e.preventDefault(); navigateTo('goals'); }
      if (e.key === 'k') { e.preventDefault(); navigateTo('chat'); $('#chatInput').focus(); }
    }
    if (e.key === 'Escape' && drawerOpen) closeDrawer();
  });

  // Resize handler
  let resizeTimer;
  let wasMobile = isMobile();
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      const nowMobile = isMobile();
      if (wasMobile !== nowMobile) location.reload();
      wasMobile = nowMobile;
    }, 200);
  });

  // Swipe to close drawer
  let touchStartX = 0;
  $('#mobileDrawer').addEventListener('touchstart', e => {
    touchStartX = e.touches[0].clientX;
  }, { passive: true });
  $('#mobileDrawer').addEventListener('touchend', e => {
    const diff = e.changedTouches[0].clientX - touchStartX;
    if (diff < -60) closeDrawer();
  }, { passive: true });

  // Init
  initAuth();
});
