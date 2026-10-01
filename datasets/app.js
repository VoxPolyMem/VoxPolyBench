const audioRoot = "./assets/audio/family-city-break/";
const status = document.getElementById("audio-status");
const sessionsRoot = document.getElementById("audio-sessions");
const questionsRoot = document.getElementById("audio-questions");
const spokenQuestions = document.getElementById("spoken-questions");

async function loadAudioDemo() {
  try {
    const response = await fetch(`${audioRoot}demo_manifest.json`, { cache: "no-store" });
    if (!response.ok) throw new Error("Audio package unavailable");
    const manifest = await response.json();
    if (manifest.case_id !== "family-city-break" || !Array.isArray(manifest.sessions) || manifest.sessions.length !== 8 || !Array.isArray(manifest.questions) || manifest.questions.length !== 10) {
      throw new Error("Incomplete audio package");
    }
    if (manifest.sessions.some(session => !/^S[1-8]\.mp3$/.test(session.file)) ||
        manifest.questions.some(question => !/^q\d{2}\.mp3$/.test(question.file))) {
      throw new Error("Invalid audio path");
    }
    for (const session of manifest.sessions) {
      const item = document.createElement("div");
      item.className = "audio-session";
      const label = document.createElement("div");
      label.className = "audio-session-label";
      const name = document.createElement("strong");
      name.textContent = `Session ${session.session_id.replace("S", "")}`;
      const count = document.createElement("span");
      count.textContent = `${session.turn_count} turns`;
      label.append(name, count);
      const player = document.createElement("audio");
      player.controls = true;
      player.preload = "none";
      player.setAttribute("aria-label", `Play family-trip ${session.session_id} dialogue`);
      player.src = audioRoot + session.file;
      item.append(label, player);
      sessionsRoot.append(item);
    }
    for (const question of manifest.questions) {
      const item = document.createElement("div");
      item.className = "audio-question";
      const label = document.createElement("p");
      label.textContent = question.question;
      const player = document.createElement("audio");
      player.controls = true;
      player.preload = "none";
      player.setAttribute("aria-label", `Play personalized question: ${question.question}`);
      player.src = audioRoot + question.file;
      item.append(label, player);
      questionsRoot.append(item);
    }
    spokenQuestions.hidden = false;
    status.textContent = "Eight complete dialogue sessions and ten spoken personalized questions.";
  } catch {
    status.textContent = "Audio preview is not published yet. The real questions above remain browsable.";
  }
}

loadAudioDemo();
