const $ = (id) => document.getElementById(id);
let sid = localStorage.getItem('voxpolymem-demo-session') || crypto.randomUUID();
localStorage.setItem('voxpolymem-demo-session', sid);
let serviceStatus = null;
let recorder = null;
let recordingPurpose = null;
let working = false;
let pendingAudioName = null;

function node(tag, className = '', text = '') {
  const value = document.createElement(tag);
  if (className) value.className = className;
  if (text) value.textContent = text;
  return value;
}

function notice(message, error = false) {
  $('notice').textContent = message;
  $('notice').classList.toggle('error', error);
}

function busy(value) {
  working = value;
  for (const id of ['ask', 'add-text', 'audio-upload']) $(id).disabled = value;
  if (!recorder) {
    $('record-turn').disabled = value;
    $('record-question').disabled = value || !serviceStatus?.asr_available;
  }
}

async function getJSON(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

async function postJSON(url, payload) {
  const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function readableTime(value) {
  try { return new Date(value).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}); }
  catch { return ''; }
}

function speakerTone(identity) {
  let hash = 0;
  for (const char of String(identity || 'unknown')) hash = ((hash * 31) + char.codePointAt(0)) >>> 0;
  return `speaker-tone-${hash % 5}`;
}

function refs(container, ids) {
  if (!ids?.length) return;
  const line = node('div', 'refs');
  for (const id of ids) line.append(node('span', 'ref', id));
  container.append(line);
}

function renderList(targetId, items, empty, renderer) {
  const target = $(targetId);
  target.replaceChildren();
  if (!items.length) target.append(node('div', 'empty-layer', empty));
  else for (const item of [...items].reverse()) target.append(renderer(item));
}

function renderTurn(turn) {
  const card = node('div', `memory-item raw-item ${speakerTone(turn.acoustic_id || turn.speaker || turn.id)}`);
  const top = node('div', 'item-top');
  top.append(node('span', 'node-id', turn.id), node('span', 'speaker-name', turn.speaker), node('span', 'item-time', readableTime(turn.timestamp)));
  card.append(top, node('p', 'item-text', turn.text));
  if (turn.acoustic_id) {
    const identity = node('div', 'refs');
    identity.append(node('span', 'speaker-badge', turn.acoustic_id));
    if (turn.speaker_match?.ema_updated) identity.append(node('span', 'ref', 'EMA UPDATED'));
    if (Number.isFinite(turn.speaker_match?.top_cosine)) identity.append(node('span', 'ref', `SIM ${turn.speaker_match.top_cosine.toFixed(2)}`));
    card.append(identity);
  } else {
    card.append(node('div', 'profile-meta', (turn.speaker_source === 'manual' || (turn.speaker && turn.speaker !== 'Unknown speaker')) ? 'Manual name label · no acoustic identity' : 'Speaker identity not established'));
  }
  if (turn.audio_name) {
    const link = node('a', 'audio-link', '▶ Play source audio');
    link.href = `/api/audio/${encodeURIComponent(sid)}/${encodeURIComponent(turn.audio_name)}`;
    link.target = '_blank';
    card.append(link);
  }
  return card;
}

function renderFact(fact) {
  const card = node('div', 'memory-item fact-item');
  const top = node('div', 'item-top');
  top.append(node('span', 'node-id', fact.id));
  if (fact.speaker) top.append(node('span', 'speaker-name', fact.speaker));
  card.append(top, node('p', 'item-text', fact.text));
  refs(card, fact.refer_ids);
  return card;
}

function renderCollection(item) {
  const card = node('div', 'memory-item collection-item');
  const top = node('div', 'item-top');
  top.append(node('span', 'node-id', item.id), node('span', 'speaker-name', item.label));
  card.append(top);
  refs(card, item.refer_ids);
  return card;
}

function renderSpeaker(item) {
  const card = node('div', `memory-item ${speakerTone(item.acoustic || item.name)}`);
  const row = node('div', 'profile-row');
  row.append(node('span', 'profile-avatar', item.name === 'Unknown speaker' ? '?' : item.name.slice(0, 1).toUpperCase()));
  const main = node('div', 'profile-main');
  const top = node('div', 'item-top');
  top.append(node('span', 'speaker-name', item.name), node('span', 'item-time', `${item.count} turn${item.count === 1 ? '' : 's'}`));
  main.append(top);
  main.append(node('div', 'profile-meta', item.acoustic
    ? `${item.acoustic} · acoustic cluster${item.lastMatch?.ema_updated ? ' · EMA updated' : ''}`
    : 'Name label only · voice not verified'));
  if (item.acoustic) {
    const form = node('form', 'speaker-bind');
    const input = node('input');
    input.type = 'text'; input.maxLength = 80; input.placeholder = 'Bind or correct name';
    input.setAttribute('aria-label', `Name for ${item.acoustic}`);
    const save = node('button', '', 'Bind name'); save.type = 'submit';
    form.append(input, save);
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (!input.value.trim()) return;
      save.disabled = true;
      try {
        const result = await postJSON('/api/speaker-label', {sid, acoustic_id: item.acoustic, label: input.value.trim()});
        render(result.state);
        notice(`Bound ${item.acoustic} to ${result.label}. ${result.warning || ''}`);
      } catch (error) { notice(error.message, true); }
      finally { save.disabled = false; }
    });
    main.append(form);
  }
  row.append(main); card.append(row);
  return card;
}

function renderAnswer(question) {
  const target = $('answer-section');
  target.replaceChildren();
  if (!question) {
    const empty = node('div', 'empty-answer');
    empty.append(node('span', 'empty-symbol', '↗'), node('strong', '', 'Ready when you are.'), node('p', '', 'Add a turn, then ask a question. The retrieval trail will appear here.'));
    target.append(empty);
    return;
  }
  const answer = node('section', 'answer-card');
  answer.append(node('div', 'answer-kicker', `ANSWER / ${question.id}`), node('p', 'question-echo', question.question), node('div', 'answer-text', question.answer));
  if (question.asker) answer.append(node('div', 'profile-meta', `Asker: ${question.asker}${question.asker_acoustic_id ? ` · ${question.asker_acoustic_id}` : ' · name label only'}`));
  target.append(answer);
  const plan = node('section', 'trace-card');
  plan.append(node('div', 'trace-title', 'RETRIEVAL PLAN'));
  plan.append(node('div', 'trace-row', `Strategy: ${question.plan?.strategy || 'unknown'} · Query: ${question.plan?.rewritten_query || question.question}`));
  for (const route of question.plan?.routes || []) {
    plan.append(node('span', 'trace-badge', `${route.layer} / ${(route.retrievers || []).join(' + ')}`));
  }
  if (question.iterative) plan.append(node('div', 'trace-row', `Rounds: ${question.iterative.rounds_executed} · Stop: ${question.iterative.stop_reason}`));
  const traces = (question.trace || []).flatMap(entry => entry.events || [entry]);
  for (const entry of traces.slice(0, 16)) {
    if (!entry.channel) continue;
    plan.append(node('div', 'trace-row', `${entry.channel}: ${entry.status || 'ok'} · ${entry.hits ?? entry.n ?? 0} hits`));
  }
  target.append(plan);
  const evidence = node('section', 'trace-card');
  evidence.append(node('div', 'trace-title', `BOTTOM-LEVEL EVIDENCE / ${question.evidence?.length || 0} TURNS`));
  if (!question.evidence?.length) evidence.append(node('div', 'trace-row', 'No matching raw evidence.'));
  for (const row of question.evidence || []) {
    const card = node('div', 'evidence-card');
    card.append(node('strong', '', `${row.mem_id} · ${row.speaker}`), node('p', '', row.text));
    evidence.append(card);
  }
  target.append(evidence);
  if (question.warning) notice(question.warning, true);
}

function render(state) {
  $('session-short').textContent = state.session_id.slice(0, 8).toUpperCase();
  $('turn-count').textContent = state.turns.length;
  $('fact-count').textContent = state.facts.length;
  $('event-count').textContent = state.collections.length;
  const speakerMap = new Map();
  for (const turn of state.turns) {
    const key = turn.acoustic_id || (turn.speaker === 'Unknown speaker' ? turn.id : turn.speaker);
    const item = speakerMap.get(key) || {name: turn.speaker, acoustic: turn.acoustic_id, count: 0, lastMatch: null};
    item.count += 1;
    item.name = state.speaker_labels?.[turn.acoustic_id] || turn.speaker;
    item.lastMatch = turn.speaker_match || item.lastMatch;
    speakerMap.set(key, item);
  }
  const nameOptions = $('speaker-options');
  nameOptions.replaceChildren();
  for (const name of new Set([...speakerMap.values()].map(item => item.name).filter(name => name && name !== 'Unknown speaker' && !name.startsWith('ONLINE_SPK_')))) {
    const option = node('option'); option.value = name; nameOptions.append(option);
  }
  renderList('speakers', [...speakerMap.values()], 'Speaker labels appear after the first turn.', renderSpeaker);
  renderList('turns', state.turns, 'No raw turns yet. Record a voice note to begin.', renderTurn);
  renderList('facts', state.facts, serviceStatus?.model_connected ? 'Facts appear after a grounded extraction.' : 'Connect the LLM to extract contextual facts.', renderFact);
  renderList('collections', state.collections, 'Event groups appear as a conversation develops.', renderCollection);
  renderAnswer(state.questions.at(-1));
}

async function refresh() {
  render(await getJSON(`/api/state?sid=${encodeURIComponent(sid)}`));
}

async function loadStatus() {
  const firstLoad = !serviceStatus;
  serviceStatus = await getJSON('/api/status');
  const llmReady = serviceStatus.model_connected;
  $('mode-pill').textContent = llmReady
    ? (serviceStatus.asr_available ? 'LLM CONNECTED · ASR CONFIGURED' : 'LLM CONNECTED · MANUAL TRANSCRIPT')
    : 'OFFLINE PREVIEW';
  $('mode-pill').classList.toggle('offline', !llmReady);
  $('topk-label').textContent = serviceStatus.top_k;
  $('system-detail').textContent = `ASR: ${serviceStatus.asr_available ? serviceStatus.asr_backend + ' (configured)' : 'not connected'} · speaker: ${serviceStatus.speaker_backend} · ${serviceStatus.retrieval}`;
  const speakerReady = serviceStatus.speaker_ready;
  const speakerConfigured = serviceStatus.speaker_available;
  $('speaker-status').textContent = speakerReady ? 'ECAPA ACTIVE' : speakerConfigured ? 'ECAPA CONFIGURED' : serviceStatus.speaker_backend === 'ecapa' ? 'MODEL DEPENDENCIES MISSING' : 'NOT CONNECTED';
  $('speaker-status').classList.toggle('ready', speakerReady || speakerConfigured);
  $('speaker-help').textContent = speakerReady || speakerConfigured
    ? 'Each one-voice clip is matched to an anonymous cluster; names are optional bindings.'
    : serviceStatus.speaker_error
      ? `ECAPA could not initialize: ${serviceStatus.speaker_error}`
      : 'Automatic voice matching needs the frozen ECAPA model. Manual names are labels, not acoustic verification.';
  $('record-turn').disabled = false;
  $('record-question').disabled = !serviceStatus.asr_available;
  if (!serviceStatus.asr_available && firstLoad) notice('Record audio, then enter its transcript below. Configure ASR in .env for automatic transcription.');
}

async function submitText() {
  const text = $('turn-text').value.trim();
  if (!text) return notice('Enter a transcript first.', true);
  busy(true);
  notice('Writing raw turn and extracting grounded memory…');
  try {
    const result = await postJSON('/api/turn', {sid, text, speaker: $('speaker').value.trim(), audio_name: pendingAudioName});
    $('turn-text').value = '';
    $('speaker').value = '';
    pendingAudioName = null;
    render(result.state);
    await loadStatus();
    notice(result.warning || `Saved ${result.turn.id}. Memory view is current.`, !!result.warning);
  } catch (error) { notice(error.message, true); }
  finally { busy(false); }
}

async function askText() {
  const question = $('question-text').value.trim();
  if (!question) return notice('Enter a question first.', true);
  busy(true);
  notice('Planning retrieval and checking evidence…');
  try {
    const result = await postJSON('/api/ask', {sid, question, asker: $('asker').value.trim()});
    render(result.state);
    notice(result.question.warning || `Answered with ${result.question.evidence.length} source turn(s).`, !!result.question.warning);
  } catch (error) { notice(error.message, true); }
  finally { busy(false); }
}

async function sendAudio(blob, purpose) {
  if (!blob.size) return notice('Recording was empty. Please try again.', true);
  busy(true);
  notice(purpose === 'turn' ? 'Transcribing audio and writing memory…' : 'Transcribing your question and retrieving evidence…');
  try {
    const response = await fetch('/api/audio', {method: 'POST', headers: {
      'Content-Type': blob.type || 'audio/webm', 'X-Session-ID': sid,
      'X-Purpose': purpose, 'X-Speaker': encodeURIComponent($(purpose === 'turn' ? 'speaker' : 'asker').value.trim()),
    }, body: blob});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Audio request failed (${response.status})`);
    if (result.pending_transcript) {
      pendingAudioName = result.audio_name;
      $('turn-text').focus();
      notice(result.warning);
      return;
    }
    render(result.state);
    await loadStatus();
    if (purpose === 'question') $('question-text').value = result.transcript;
    if (purpose === 'turn') $('speaker').value = '';
    notice(result.warning || `Transcribed: “${result.transcript.slice(0, 110)}${result.transcript.length > 110 ? '…' : ''}”`, !!result.warning);
  } catch (error) { notice(error.message, true); }
  finally { busy(false); }
}

async function toggleRecording(purpose) {
  if (recorder) {
    if (purpose === recordingPurpose) recorder.stop();
    return;
  }
  if (working) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
    const options = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus'].find(type => MediaRecorder.isTypeSupported(type));
    recorder = new MediaRecorder(stream, options ? {mimeType: options} : undefined);
    recordingPurpose = purpose;
    const chunks = [];
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    recorder.onstop = () => {
      const blob = new Blob(chunks, {type: recorder.mimeType.split(';')[0]});
      stream.getTracks().forEach(track => track.stop());
      recorder = null; recordingPurpose = null;
      $('wave').classList.remove('active');
      $('record-turn').classList.remove('recording');
      $('record-question').classList.remove('recording');
      $('record-turn').querySelector('span:nth-child(2)').textContent = 'Start recording';
      sendAudio(blob, purpose);
    };
    recorder.start();
    $('wave').classList.add('active');
    (purpose === 'turn' ? $('record-turn') : $('record-question')).classList.add('recording');
    if (purpose === 'turn') $('record-turn').querySelector('span:nth-child(2)').textContent = 'Stop & save recording';
    notice(purpose === 'turn' ? 'Recording a memory turn. Press again to stop.' : 'Recording your question. Press the microphone again to stop.');
  } catch (error) { notice(`Microphone unavailable: ${error.message}`, true); }
}

$('record-turn').addEventListener('click', () => toggleRecording('turn'));
$('record-question').addEventListener('click', () => toggleRecording('question'));
$('audio-upload').addEventListener('change', async event => {
  const file = event.target.files?.[0];
  if (!file) return;
  const type = file.type || ({wav: 'audio/wav', mp3: 'audio/mpeg', m4a: 'audio/mp4', webm: 'audio/webm', ogg: 'audio/ogg'}[file.name.split('.').at(-1).toLowerCase()] || '');
  await sendAudio(new Blob([file], {type}), 'turn');
  event.target.value = '';
});
$('add-text').addEventListener('click', submitText);
$('ask').addEventListener('click', askText);
$('new-session').addEventListener('click', async () => {
  if (!confirm('Start a new local session? The current session stays saved on this machine.')) return;
  sid = crypto.randomUUID();
  pendingAudioName = null;
  $('speaker').value = '';
  $('asker').value = '';
  localStorage.setItem('voxpolymem-demo-session', sid);
  await refresh();
  notice('New session ready.');
});

loadStatus().then(refresh).catch(error => notice(`Demo server unavailable: ${error.message}`, true));
