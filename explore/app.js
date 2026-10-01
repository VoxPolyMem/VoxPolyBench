const sourceUrl = "./data/family-city-break.json";
const audioRoot = "../datasets/assets/audio/family-city-break/";
const sessionSelect = document.getElementById("session-select");
const contentStatus = document.getElementById("content-status");
const dialogueList = document.getElementById("dialogue-list");
const turnCount = document.getElementById("turn-count");
const sessionAudio = document.getElementById("session-audio");
const qaSearch = document.getElementById("qa-search");
const qaType = document.getElementById("qa-type");
const qaList = document.getElementById("qa-list");
const qaCount = document.getElementById("qa-count");
let documentData;
let audioFiles = new Set();

function renderQuestions() {
  const query = qaSearch.value.trim().toLocaleLowerCase();
  const selectedType = qaType.value;
  const visible = documentData.qa.filter(item =>
    (selectedType === "all" || item.type === selectedType) &&
    `${item.question} ${item.answer}`.toLocaleLowerCase().includes(query)
  );
  qaCount.textContent = `${visible.length} / ${documentData.qa.length}`;
  const nodes = visible.map(item => {
    const details = document.createElement("details");
    details.className = "explore-qa";
    const summary = document.createElement("summary");
    const meta = document.createElement("small");
    meta.textContent = item.type.replaceAll("_", " ");
    const question = document.createElement("span");
    question.textContent = item.question;
    summary.append(meta, question);
    const answer = document.createElement("p");
    answer.textContent = item.answer;
    details.append(summary, answer);
    return details;
  });
  qaList.replaceChildren(...nodes);
  if (!visible.length) qaList.textContent = "No questions match these filters.";
}

function renderSession() {
  const session = documentData.sessions.find(item => item.session_id === sessionSelect.value);
  if (!session) return;
  contentStatus.textContent = `${session.turns.length} canonical turns in ${session.session_id}.`;
  dialogueList.replaceChildren(...session.turns.map(turn => {
    const row = document.createElement("article");
    row.className = "dialogue-turn";
    const header = document.createElement("div");
    header.className = "dialogue-turn-header";
    const name = document.createElement("strong");
    name.textContent = turn.speaker;
    const index = document.createElement("span");
    index.textContent = `TURN ${String(turn.turn_idx + 1).padStart(2, "0")}`;
    header.append(name, index);
    const text = document.createElement("p");
    text.textContent = turn.text;
    row.append(header, text);
    return row;
  }));
  sessionAudio.replaceChildren();
  if (audioFiles.has(`${session.session_id}.mp3`)) {
    const label = document.createElement("p");
    label.textContent = `Listen to ${session.session_id} while reading`;
    const player = document.createElement("audio");
    player.controls = true;
    player.preload = "none";
    player.src = audioRoot + session.session_id + ".mp3";
    player.setAttribute("aria-label", `Play ${session.session_id} dialogue`);
    sessionAudio.append(label, player);
    sessionAudio.hidden = false;
  } else {
    sessionAudio.hidden = true;
  }
}

async function loadAudioManifest() {
  try {
    const response = await fetch(`${audioRoot}demo_manifest.json`);
    if (!response.ok) return;
    const manifest = await response.json();
    if (manifest.case_id !== "family-city-break" || !Array.isArray(manifest.sessions)) return;
    audioFiles = new Set(manifest.sessions.map(item => item.file).filter(file => /^S[1-8]\.mp3$/.test(file)));
    if (documentData.sessions.length) renderSession();
  } catch {
    // The source browser remains useful when audio is not yet local.
  }
}

async function loadCase() {
  try {
    const response = await fetch(sourceUrl, { cache: "no-store" });
    if (!response.ok) throw new Error("Case data unavailable");
    documentData = await response.json();
    if (documentData.case_id !== "family-city-break" || !Array.isArray(documentData.qa) || documentData.qa.length !== 75 || !Array.isArray(documentData.sessions)) {
      throw new Error("Invalid case data");
    }
    const types = [...new Set(documentData.qa.map(item => item.type))].sort();
    for (const type of types) {
      const option = document.createElement("option");
      option.value = type;
      option.textContent = type.replaceAll("_", " ");
      qaType.append(option);
    }
    qaSearch.addEventListener("input", renderQuestions);
    qaType.addEventListener("change", renderQuestions);
    renderQuestions();
    if (documentData.status === "complete" && documentData.sessions.length === 8) {
      turnCount.textContent = "480 / 480 turns";
      sessionSelect.replaceChildren(...documentData.sessions.map(item => {
        const option = document.createElement("option");
        option.value = item.session_id;
        option.textContent = `${item.session_id} · ${item.turns.length} turns`;
        return option;
      }));
      sessionSelect.disabled = false;
      sessionSelect.addEventListener("change", renderSession);
      renderSession();
    } else {
      contentStatus.textContent = "The dialogue is temporarily unavailable. The QA collection on the right remains browsable.";
    }
    loadAudioManifest();
  } catch {
    qaCount.textContent = "Unavailable";
    qaList.textContent = "The QA data could not be loaded.";
    contentStatus.textContent = "The dialogue is temporarily unavailable.";
  }
}

loadCase();
